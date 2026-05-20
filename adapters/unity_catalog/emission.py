"""Unity Catalog emission — IR → Databricks DDL/SQL.

Coverage (scaffold):
    * Row visibility — group-driven, single rule, allow-list semantics (the
      group-row-visibility-policy-a worked-example shape).
    * Other policyKinds and selector kinds emit a placeholder statement plus a
      diagnostic flagging the gap. The contract is exercised end-to-end; the
      adapter is honest about what it has not yet implemented.

The handler dispatch is deliberately verbose — flattened rather than abstracted
behind a registry — to keep the emission paths auditable while the contract
shape settles.
"""

from __future__ import annotations

from typing import Any

from adapters.contract.types import (
    AdapterConfig,
    Diagnostic,
    DiagnosticSeverity,
    EmissionResult,
)


def emit_policy(policy: dict[str, Any], config: AdapterConfig) -> EmissionResult:
    policy_id = policy.get("@id")
    policy_kind = policy.get("policyKind")
    applies_to = policy.get("appliesTo") or {}
    target_table = applies_to.get("resource") or applies_to.get("scope") or ""

    diagnostics: list[Diagnostic] = []
    statements: list[str] = []

    if policy_kind == "RowVisibilityConstraint":
        return _emit_row_visibility(policy, config)
    if policy_kind == "ColumnVisibilityConstraint":
        return _emit_column_visibility(policy, config)
    if policy_kind == "AccessGrantConstraint":
        return _emit_access_grant(policy, config)

    diagnostics.append(Diagnostic(
        severity=DiagnosticSeverity.WARNING,
        code="UNIMPLEMENTED_POLICY_KIND",
        message=f"unity-catalog adapter has not implemented emission for policyKind={policy_kind!r}.",
        location="policyKind",
    ))
    statements.append(f"-- TODO: emit {policy_kind} for {policy_id}")

    return EmissionResult(
        policy_id=policy_id,
        target_artifacts=[target_table] if target_table else [],
        statements=statements,
        diagnostics=diagnostics,
    )


def _emit_row_visibility(policy: dict[str, Any], config: AdapterConfig) -> EmissionResult:
    applies_to = policy.get("appliesTo") or {}
    selector = applies_to.get("selector")

    # byScope dispatches to the ABAC row-filter emission path: CREATE POLICY ...
    # ROW FILTER ... MATCH COLUMNS has_tag_value(...) AS alias USING COLUMNS (alias).
    # See _emit_row_visibility_by_scope.
    if selector == "byScope":
        return _emit_row_visibility_by_scope(policy, config)

    diagnostics: list[Diagnostic] = []
    policy_id = policy.get("@id")
    raw_resource = applies_to.get("resource") or ""
    target_table = config.bind_resource(raw_resource) or _strip_iri(raw_resource)
    rules = policy.get("rules") or []

    # byDataset principals — the ACL-mapping-table pattern. Dispatch to a
    # separate helper that emits a row-filter UDF with an EXISTS body joining
    # the IR's mapping tables on current_user().
    if rules and all(
        (rule.get("principal") or {}).get("selector") == "byDataset" for rule in rules
    ):
        return _emit_row_visibility_by_dataset(policy, config, target_table)

    if selector != "byIdentity":
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="UNIMPLEMENTED_SELECTOR_FOR_ROW_VISIBILITY",
            message=(
                "scaffold currently emits row filters only for byIdentity table targets. "
                f"Got selector={selector!r}."
            ),
            location="appliesTo.selector",
        ))

    # Each rule contributes one OR branch in the filter body. The default branch (if any)
    # is rendered as the final clause; if absent the function denies non-matching rows.
    branches: list[str] = []
    for idx, rule in enumerate(rules):
        branch, rule_diags = _render_rule_branch(rule, config, idx, target_table)
        diagnostics.extend(rule_diags)
        if branch:
            branches.append(branch)

    function_name = _row_filter_function_name(policy_id, target_table)
    column_arg, column_diags = _row_filter_column_arg(rules, target_table)
    diagnostics.extend(column_diags)

    if not branches:
        body = "false"
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="EMPTY_FILTER_BODY",
            message="No emittable rule branches; row filter denies all rows by default.",
        ))
    else:
        body = "\n        OR ".join(branches)

    statements = [
        f"CREATE OR REPLACE FUNCTION {function_name}({column_arg})\n"
        f"RETURNS BOOLEAN\n"
        f"RETURN\n"
        f"        {body};",
        f"ALTER TABLE {target_table} SET ROW FILTER {function_name} ON ({column_arg.split()[0] if column_arg else ''});",
    ]

    return EmissionResult(
        policy_id=policy_id,
        target_artifacts=[target_table],
        statements=statements,
        diagnostics=diagnostics,
    )


def _emit_row_visibility_by_dataset(
    policy: dict[str, Any], config: AdapterConfig, target_table: str,
) -> EmissionResult:
    """Lower a byDataset RowVisibilityConstraint to a Databricks row-filter UDF.

    Emission target (matches the hand-derived
    spec/v0/examples/acl-row-visibility.databricks.sql):

        CREATE OR REPLACE FUNCTION <fn>(<col> STRING) RETURNS BOOLEAN
        RETURN EXISTS (
          SELECT 1
          FROM <mapping_table> m
          JOIN <resource_acl_table> p
            ON m.<m_resource_col> = p.<p_principal_col>
          WHERE m.<m_principal_col> = current_user()
            AND p.<p_resource_col> = <col>
        );

        ALTER TABLE <target_table> SET ROW FILTER <fn> ON (<col>);

    Single-rule, single-branch. defaultStrategy: none ⇒ no fallback clause.
    The Databricks counterpart of the Snowflake byDataset emission; the parameter
    name *is* the column name (positional bind), so no collision-avoidance trick
    is needed here.
    """
    diagnostics: list[Diagnostic] = []
    policy_id = policy.get("@id")
    rules = policy.get("rules") or []
    if len(rules) != 1:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="MULTI_RULE_BYDATASET_NOT_SUPPORTED",
            message=(
                f"UC byDataset emission expects exactly one rule; got {len(rules)}. "
                "Emitting the first only."
            ),
        ))
    rule = rules[0]

    principal = rule.get("principal") or {}
    dataset = principal.get("dataset") or {}
    if dataset.get("@type") != "PrincipalSetFromTable":
        return EmissionResult(
            policy_id=policy_id, target_artifacts=[target_table], statements=[],
            diagnostics=[Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="UNSUPPORTED_DATASET_TYPE",
                message=(
                    f"byDataset principal requires dataset @type PrincipalSetFromTable; "
                    f"got {dataset.get('@type')!r}."
                ),
                location="rules[0].principal.dataset.@type",
            )],
        )
    mapping_table_raw = dataset.get("table") or ""
    # Apply resource_bindings to the data-table reference too. The IR carries
    # the source platform's table name; production migration usually needs to
    # remap that to a target-platform table name (or migrate the data and use
    # the new identifier). We look up `table:<raw>` to support this without
    # changing the IR shape.
    mapping_table = config.bind_resource(f"table:{mapping_table_raw}") or mapping_table_raw
    mapping_principal_col = dataset.get("principalColumn") or "username"
    mapping_resource_col = dataset.get("resourceColumn") or "code_name"

    condition = rule.get("condition") or {}
    if condition.get("op") != "exists-in-dataset":
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="UNSUPPORTED_CONDITION_FOR_BYDATASET",
            message=(
                "byDataset row visibility expects condition.op = exists-in-dataset; "
                f"got {condition.get('op')!r}."
            ),
        ))
        return EmissionResult(
            policy_id=policy_id, target_artifacts=[target_table], statements=[],
            diagnostics=diagnostics,
        )

    operands = condition.get("operands") or []
    if not operands or not isinstance(operands[0], dict):
        return EmissionResult(
            policy_id=policy_id, target_artifacts=[target_table], statements=[],
            diagnostics=[Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="MISSING_RESOURCE_DATASET",
                message="exists-in-dataset condition must carry a ResourceSetFromTable operand.",
                location="rules[0].condition.operands[0]",
            )],
        )
    resource_ds = operands[0]
    if resource_ds.get("@type") != "ResourceSetFromTable":
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="UNSUPPORTED_OPERAND_TYPE",
            message=(
                f"exists-in-dataset operand expected to be ResourceSetFromTable; "
                f"got {resource_ds.get('@type')!r}."
            ),
        ))
    resource_table_raw = resource_ds.get("table") or ""
    resource_table = config.bind_resource(f"table:{resource_table_raw}") or resource_table_raw
    resource_principal_col = resource_ds.get("principalColumn") or "code_name"
    resource_resource_col = resource_ds.get("resourceColumn") or "value"

    slug = (policy_id or "policy").split(":")[-1].replace("-", "_")
    schema_qualified = target_table.rsplit(".", 1)[0] if target_table.count(".") >= 1 else target_table
    function_name = f"{schema_qualified}.tessera__{slug}__row_filter"
    # The function parameter MUST NOT collide with any column name referenced
    # inside the EXISTS subquery. SQL is case-insensitive on identifiers, so
    # naming the parameter after the column makes `p.<col> = <col>` ambiguous:
    # Databricks resolves the bare identifier to the column ref, the predicate
    # degenerates to `col = col` (always TRUE), and the filter passes all rows.
    # Pin a fixed alias instead; the column-to-parameter bind happens at
    # ALTER TABLE ... SET ROW FILTER ... ON (col) by position.
    param_name = "policy_input_value"
    bound_column = resource_resource_col

    body = (
        "EXISTS (\n"
        "  SELECT 1\n"
        f"  FROM {mapping_table} m\n"
        f"  JOIN {resource_table} p\n"
        f"    ON m.{mapping_resource_col} = p.{resource_principal_col}\n"
        f"  WHERE m.{mapping_principal_col} = current_user()\n"
        f"    AND p.{resource_resource_col} = {param_name}\n"
        ")"
    )

    statements = [
        f"CREATE OR REPLACE FUNCTION {function_name}({param_name} STRING)\n"
        f"RETURNS BOOLEAN\n"
        f"RETURN {body};",
        f"ALTER TABLE {target_table} SET ROW FILTER {function_name} ON ({bound_column});",
    ]

    return EmissionResult(
        policy_id=policy_id,
        target_artifacts=[target_table],
        statements=statements,
        diagnostics=diagnostics,
    )


def _emit_row_visibility_by_scope(policy: dict[str, Any], config: AdapterConfig) -> EmissionResult:
    """Lower a byScope+matching RowVisibilityConstraint to Databricks ABAC DDL.

    Emission target (Mechanism B — CASE inside the UDF, the only natural choice
    when there are more than two branches):

        CREATE OR REPLACE FUNCTION <fn>(<param> STRING) RETURNS BOOLEAN
        RETURN
          CASE
            WHEN is_account_group_member('A') THEN TRUE
            WHEN is_account_group_member('B') THEN <param> IN (...)
            ELSE <param> IN (...)
          END;

        GRANT EXECUTE ON FUNCTION <fn> TO `account users`;

        CREATE OR REPLACE POLICY <policy>
          ON <CATALOG|SCHEMA|TABLE> <id>
          ROW FILTER <fn>
            TO `account users`
            FOR TABLES
            MATCH COLUMNS has_tag_value('<tag_key>', '<tag_value>') AS <alias>
            USING COLUMNS (<alias>);

    The Tessera->platform tag translation comes from config.tag_taxonomy (ADR-021).
    `column:$matched` in IR rule conditions substitutes the function parameter
    name at emit time — the IR's per-policy abstraction over the matched column.
    """
    diagnostics: list[Diagnostic] = []
    policy_id = policy.get("@id")
    applies_to = policy.get("appliesTo") or {}
    raw_scope = applies_to.get("scope") or ""
    scope_kind, scope_id = _split_scope_iri(raw_scope)
    if not scope_kind or not scope_id:
        return EmissionResult(
            policy_id=policy_id, target_artifacts=[], statements=[],
            diagnostics=[Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="MALFORMED_SCOPE",
                message=(
                    f"byScope appliesTo.scope must be of the form <kind>:<id> "
                    f"(catalog: / schema: / table: / column:); got {raw_scope!r}."
                ),
                location="appliesTo.scope",
            )],
        )

    # Resolve the matching predicate to a Databricks tag.
    matching = applies_to.get("matching") or {}
    tag_clauses, tag_value_for_alias, tag_diags = _render_match_columns(matching, config)
    diagnostics.extend(tag_diags)

    # Use the tag-value-derived alias as the function parameter name. This is
    # arbitrary but consistent (the hand-derived target uses the value verbatim).
    alias = tag_value_for_alias or "matched_col"
    param_name = alias

    # Build the CASE body. Rules + defaultBranch combine in IR-declared order.
    case_lines: list[str] = []
    rules = policy.get("rules") or []
    for idx, rule in enumerate(rules):
        line, rule_diags = _render_abac_case_branch(rule, config, idx, param_name)
        diagnostics.extend(rule_diags)
        if line:
            case_lines.append(line)

    default_branch = policy.get("defaultBranch") or {}
    if default_branch:
        else_predicate = _render_abac_condition_predicate(
            default_branch.get("condition") or {}, param_name, "default", diagnostics,
        )
        if else_predicate:
            case_lines.append(f"ELSE {else_predicate}")
        else:
            # Effect alone determines outcome when no condition.
            case_lines.append("ELSE TRUE" if default_branch.get("effect") in ("keep-matching-rows", "allow") else "ELSE FALSE")
    else:
        case_lines.append("ELSE FALSE")

    case_body = "\n    ".join(case_lines)

    # Function emitted into the bg_rls_demo.tpch schema by convention; the
    # adapter cannot know which schema to use without per-policy config. The
    # `extras["abac_function_schema"]` setting overrides; default uses the
    # scope catalog plus a conventional `tpch` schema. A real deployment
    # should pin this explicitly.
    function_schema = config.extras.get("abac_function_schema")
    if not function_schema:
        if scope_kind == "CATALOG":
            function_schema = f"{scope_id}.tpch"
        elif scope_kind == "SCHEMA":
            function_schema = scope_id
        else:
            function_schema = scope_id.rsplit(".", 1)[0] if "." in scope_id else scope_id
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.INFO,
            code="ABAC_FUNCTION_SCHEMA_INFERRED",
            message=(
                f"Function schema inferred as {function_schema!r}; override via "
                "config.extras['abac_function_schema'] for production deployments."
            ),
        ))

    slug = (policy_id or "policy").split(":")[-1].replace("-", "_")
    function_name = f"{function_schema}.tessera__{slug}__filter"
    policy_name = f"tessera__{slug}"
    grantee = config.extras.get("row_filter_grantee", "account users")

    statements = [
        f"CREATE OR REPLACE FUNCTION {function_name}({param_name} STRING)\n"
        f"RETURNS BOOLEAN\n"
        f"RETURN\n"
        f"  CASE\n"
        f"    {case_body}\n"
        f"  END;",
        f"GRANT EXECUTE ON FUNCTION {function_name} TO `{grantee}`;",
        f"CREATE OR REPLACE POLICY {policy_name}\n"
        f"  ON {scope_kind} {scope_id}\n"
        f"  ROW FILTER {function_name}\n"
        f"    TO `{grantee}`\n"
        f"    FOR TABLES\n"
        f"    {tag_clauses} AS {alias}\n"
        f"    USING COLUMNS ({alias});",
    ]

    return EmissionResult(
        policy_id=policy_id,
        target_artifacts=[f"{scope_kind.lower()}:{scope_id}"],
        statements=statements,
        diagnostics=diagnostics,
    )


def _split_scope_iri(scope_iri: str) -> tuple[str | None, str | None]:
    """Convert 'catalog:foo' / 'schema:foo.bar' / 'table:a.b.c' into (KIND, identifier)."""
    if ":" not in scope_iri:
        return None, None
    prefix, ident = scope_iri.split(":", 1)
    mapping = {
        "catalog": "CATALOG", "schema": "SCHEMA",
        "table": "TABLE", "column": "COLUMN",
    }
    return mapping.get(prefix.lower()), ident


def _render_match_columns(
    matching: dict[str, Any], config: AdapterConfig,
) -> tuple[str, str | None, list[Diagnostic]]:
    """Build the MATCH COLUMNS clause body from the IR's matching predicate.

    Returns (clause_string, alias_hint, diagnostics).
    """
    diagnostics: list[Diagnostic] = []
    attributes = matching.get("attributes") or {}
    if not attributes:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="EMPTY_MATCHING",
            message="byScope without matching attributes attaches the policy to every resource in scope; "
                    "MATCH COLUMNS clause omitted.",
        ))
        return "MATCH COLUMNS TRUE", None, diagnostics

    predicates: list[str] = []
    last_value: str | None = None
    for axis, value in attributes.items():
        # ADR-021 tag-taxonomy lookup: (axis, value) → (tag_key, tag_value).
        binding = config.tag_taxonomy.get((axis, str(value)))
        if binding:
            tag_key, tag_value = binding
        else:
            # Fallback: use the IR's axis IRI suffix as the tag key, value verbatim.
            # Surface as a warning so operators know to declare the binding.
            tag_key = axis.split(":")[-1] if ":" in axis else axis
            tag_value = str(value)
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="UNBOUND_TAG_ATTRIBUTE",
                message=(
                    f"matching attribute ({axis!r}, {value!r}) has no tag_taxonomy entry; "
                    f"falling back to has_tag_value({tag_key!r}, {tag_value!r}). Configure "
                    "config.tag_taxonomy for production."
                ),
            ))
        predicates.append(f"has_tag_value('{tag_key}', '{tag_value}')")
        last_value = tag_value

    # When the IR has multiple matching attributes, the simplest combinator on
    # Databricks is AND. The IR's canonical form supports OR via the `match`
    # property; the sugar form is implicit AND.
    body = " AND ".join(predicates)
    return f"MATCH COLUMNS {body}", last_value, diagnostics


def _render_abac_case_branch(
    rule: dict[str, Any], config: AdapterConfig, idx: int, param_name: str,
) -> tuple[str, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    principal = rule.get("principal") or {}
    effect = rule.get("effect")
    if principal.get("selector") != "byIdentity":
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="UNSUPPORTED_PRINCIPAL_SELECTOR",
            message=f"rule {idx}: ABAC row-filter scaffold supports only byIdentity principal selectors.",
            location=f"rules[{idx}].principal.selector",
        ))
        return "", diagnostics

    principal_ref = principal.get("resource") or ""
    bound = config.bind_principal(principal_ref) or _strip_iri(principal_ref)
    membership = f"is_account_group_member('{bound}')"

    predicate = _render_abac_condition_predicate(
        rule.get("condition") or {}, param_name, idx, diagnostics,
    )
    if effect in ("keep-matching-rows", "allow"):
        then_expr = predicate or "TRUE"
    elif effect in ("drop-matching-rows", "deny"):
        then_expr = f"NOT ({predicate})" if predicate else "FALSE"
    else:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="UNSUPPORTED_EFFECT_FOR_ABAC_ROW_FILTER",
            message=f"rule {idx}: effect {effect!r} unsupported by ABAC row-filter emission.",
            location=f"rules[{idx}].effect",
        ))
        return "", diagnostics

    return f"WHEN {membership} THEN {then_expr}", diagnostics


def _render_abac_condition_predicate(
    condition: dict[str, Any], param_name: str, idx: Any, diagnostics: list[Diagnostic],
) -> str:
    """Render a condition's predicate body using `param_name` for any column:$matched reference."""
    if not condition:
        return ""
    op = condition.get("op")
    if op != "in":
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="UNIMPLEMENTED_CONDITION_OP",
            message=f"rule {idx}: ABAC row-filter emission currently supports op=in; got {op!r}.",
            location=f"rules[{idx}].condition.op",
        ))
        return ""
    operands = condition.get("operands") or []
    values = condition.get("values") or []
    if len(operands) != 1:
        return ""
    operand = operands[0] if isinstance(operands[0], str) else ""
    # column:$matched is the per-policy abstraction for the matched column; the
    # adapter substitutes the function parameter name at emit time.
    if operand in ("column:$matched", "$matched") or operand.endswith(":$matched"):
        col_ref = param_name
    else:
        col_ref = _column_only(_strip_iri(operand))
    rendered_values = ", ".join(f"'{str(v)}'" for v in values)
    return f"{col_ref} IN ({rendered_values})"


def _emit_column_visibility(policy: dict[str, Any], config: AdapterConfig) -> EmissionResult:
    """Lower a ColumnVisibilityConstraint to a CREATE FUNCTION mask + ALTER COLUMN SET MASK.

    Supports:
        * `appliesTo: byIdentity` with `resource: column:<catalog>.<schema>.<table>.<col>`.
        * Multiple rules; each rule with `effect: allow` contributes a `WHEN ... THEN <col>` branch.
        * `defaultBranch` with `effect: transform` + `transformation` produces the ELSE clause.
        * Redact transformation (literal replacement). Mask/Hash emit a TODO diagnostic
          for now (parameter shapes exist in v0 but the SQL templates are out of scope
          for this scaffold pass; queued).

    Adapter scaffolding (per ADR-025 boundary): the GRANT EXECUTE statement on the
    emitted UDF is emission-time scaffolding, not policy intent. The default grantee
    is `account users` (everyone); override via `config.extras["column_mask_grantee"]`.
    """
    diagnostics: list[Diagnostic] = []
    policy_id = policy.get("@id")
    applies_to = policy.get("appliesTo") or {}
    raw_resource = applies_to.get("resource") or ""
    bound_resource = config.bind_resource(raw_resource) or _strip_iri(raw_resource)
    rules = policy.get("rules") or []
    default_branch = policy.get("defaultBranch") or {}

    if applies_to.get("selector") != "byIdentity":
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="UNIMPLEMENTED_SELECTOR_FOR_COLUMN_VISIBILITY",
            message=(
                "scaffold currently emits column masks only for byIdentity column targets. "
                f"Got selector={applies_to.get('selector')!r}. ABAC byScope column masking is queued."
            ),
            location="appliesTo.selector",
        ))

    # Resource shape: column:<catalog>.<schema>.<table>.<col>. The protected column
    # is the last segment; the table is everything before it.
    qualified = bound_resource
    if "." not in qualified:
        return EmissionResult(
            policy_id=policy_id, target_artifacts=[], statements=[],
            diagnostics=[Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="MALFORMED_COLUMN_REFERENCE",
                message=(
                    f"ColumnVisibility appliesTo.resource must be fully-qualified "
                    f"(catalog.schema.table.column). Got {qualified!r}."
                ),
                location="appliesTo.resource",
            )],
        )
    target_table, target_column = qualified.rsplit(".", 1)
    schema_qualified = target_table.rsplit(".", 1)[0] if target_table.count(".") >= 1 else target_table

    # Build per-rule WHEN clauses.
    when_clauses: list[str] = []
    for idx, rule in enumerate(rules):
        principal = rule.get("principal") or {}
        effect = rule.get("effect")
        if principal.get("selector") != "byIdentity":
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="UNSUPPORTED_PRINCIPAL_SELECTOR",
                message=f"rule {idx}: scaffold supports only byIdentity principal selectors for column masks.",
                location=f"rules[{idx}].principal.selector",
            ))
            continue
        principal_ref = principal.get("resource") or ""
        bound = config.bind_principal(principal_ref) or _strip_iri(principal_ref)
        membership = f"is_account_group_member('{bound}')"

        if effect == "allow":
            # Show the real value.
            when_clauses.append(f"WHEN {membership} THEN {target_column}")
        elif effect == "transform":
            transform_expr, t_diags = _render_transformation_expression(
                rule.get("transformation") or {}, target_column, idx,
            )
            diagnostics.extend(t_diags)
            if transform_expr:
                when_clauses.append(f"WHEN {membership} THEN {transform_expr}")
        else:
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="COLUMN_MASK_EFFECT_UNSUPPORTED",
                message=(
                    f"rule {idx}: column-mask emission supports effect=allow or "
                    f"effect=transform; got {effect!r}."
                ),
                location=f"rules[{idx}].effect",
            ))

    # Default branch (ELSE clause). Required by defaultStrategy=negated-complement
    # (the JSON Schema enforces this), but other strategies may produce a column
    # mask without an explicit default; in that case the ELSE returns the real value.
    if default_branch.get("effect") == "transform":
        else_expr, db_diags = _render_transformation_expression(
            default_branch.get("transformation") or {}, target_column, "default",
        )
        diagnostics.extend(db_diags)
    elif default_branch.get("effect") == "allow":
        else_expr = target_column
    else:
        else_expr = target_column  # no default branch ⇒ pass-through

    case_body = "\n    ".join(when_clauses + [f"ELSE {else_expr}"])
    function_name = _mask_function_name(policy_id, schema_qualified)
    grantee = config.extras.get("column_mask_grantee", "account users")

    statements = [
        f"CREATE OR REPLACE FUNCTION {function_name}({target_column} STRING)\n"
        f"RETURNS STRING\n"
        f"RETURN\n"
        f"  CASE\n"
        f"    {case_body}\n"
        f"  END;",
        # Per ADR-025: GRANT EXECUTE here is adapter scaffolding (UDF as policy
        # enforcement vehicle), not policy intent.
        f"GRANT EXECUTE ON FUNCTION {function_name} TO `{grantee}`;",
        f"ALTER TABLE {target_table}\n  ALTER COLUMN {target_column}\n  SET MASK {function_name};",
    ]

    return EmissionResult(
        policy_id=policy_id,
        target_artifacts=[target_table],
        statements=statements,
        diagnostics=diagnostics,
    )


def _render_transformation_expression(
    transformation: dict[str, Any], column_name: str, location_tag: Any,
) -> tuple[str | None, list[Diagnostic]]:
    """Render a TransformationInstance into a SQL expression usable inside a CASE branch."""
    diagnostics: list[Diagnostic] = []
    ttype = transformation.get("type") or transformation.get("@type")
    if ttype == "Redact":
        replacement = transformation.get("replacement")
        if replacement is None:
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="REDACT_MISSING_REPLACEMENT",
                message="Redact transformation requires a `replacement` value (ADR-016).",
                location=f"transformation@{location_tag}",
            ))
            return None, diagnostics
        # SQL-quote the replacement literal. The IR carries a string; we render
        # it as a SQL string literal with single quotes escaped.
        quoted = "'" + str(replacement).replace("'", "''") + "'"
        return quoted, diagnostics
    if ttype == "Mask":
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="MASK_TRANSFORMATION_NOT_IMPLEMENTED",
            message="Mask transformation emission queued; emitting NULL placeholder for now.",
            location=f"transformation@{location_tag}",
        ))
        return "NULL", diagnostics
    if ttype == "Hash":
        algorithm = (transformation.get("algorithm") or "sha256").lower()
        # Databricks SQL: sha2(<expr>, 256) for SHA-256.
        if algorithm in ("sha256", "sha-256"):
            return f"sha2(cast({column_name} AS STRING), 256)", diagnostics
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="HASH_ALGORITHM_NOT_IMPLEMENTED",
            message=f"Hash algorithm {algorithm!r} emission queued; emitting NULL placeholder.",
            location=f"transformation@{location_tag}",
        ))
        return "NULL", diagnostics
    diagnostics.append(Diagnostic(
        severity=DiagnosticSeverity.WARNING,
        code="UNKNOWN_TRANSFORMATION_TYPE",
        message=f"Unknown transformation type {ttype!r}; emitting NULL placeholder.",
        location=f"transformation@{location_tag}",
    ))
    return "NULL", diagnostics


def _mask_function_name(policy_id: str | None, schema_qualified: str) -> str:
    slug = (policy_id or "policy").split(":")[-1].replace("-", "_")
    return f"{schema_qualified}.tessera__{slug}__mask"


def _render_rule_branch(
    rule: dict[str, Any], config: AdapterConfig, idx: int, target_table: str,
) -> tuple[str, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    principal = rule.get("principal") or {}
    effect = rule.get("effect")
    condition = rule.get("condition") or {}

    if effect != "keep-matching-rows" and effect != "allow":
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.INFO,
            code="ROW_FILTER_EFFECT_REINTERPRETED",
            message=f"rule {idx} effect={effect!r} treated as keep-matching-rows for row-filter emission.",
            location=f"rules[{idx}].effect",
        ))

    principal_ref = principal.get("resource") if principal.get("selector") == "byIdentity" else None
    if not principal_ref:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="UNSUPPORTED_PRINCIPAL_SELECTOR",
            message=f"rule {idx}: only byIdentity principal selectors are emitted in the scaffold.",
            location=f"rules[{idx}].principal",
        ))
        return "", diagnostics

    bound = config.bind_principal(principal_ref) or _strip_iri(principal_ref)
    membership = f"is_account_group_member('{bound}')"

    # Condition rendering: support `in` over a single column reference.
    condition_clause = _render_condition(condition, target_table, idx, diagnostics)

    if condition_clause:
        return f"({membership} AND {condition_clause})", diagnostics
    return membership, diagnostics


def _render_condition(
    condition: dict[str, Any], target_table: str, idx: int, diagnostics: list[Diagnostic],
) -> str:
    if not condition:
        return ""
    op = condition.get("op")
    if op != "in":
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="UNIMPLEMENTED_CONDITION_OP",
            message=f"rule {idx}: scaffold currently emits only op=in; got {op!r}.",
            location=f"rules[{idx}].condition.op",
        ))
        return ""
    operands = condition.get("operands") or []
    values = condition.get("values") or []
    if len(operands) != 1:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="UNIMPLEMENTED_CONDITION_SHAPE",
            message=f"rule {idx}: only single-operand `in` is supported.",
            location=f"rules[{idx}].condition",
        ))
        return ""
    column = _column_only(_strip_iri(operands[0]))
    rendered_values = ", ".join(f"'{str(v)}'" for v in values)
    return f"{column} IN ({rendered_values})"


def _emit_access_grant(policy: dict[str, Any], config: AdapterConfig) -> EmissionResult:
    """Lower an AccessGrantConstraint to Databricks GRANT statements.

    The IR carries:
        appliesTo.selector: byIdentity | byScope
        appliesTo.resource: table:... | column:... | function:...  (byIdentity)
        appliesTo.scope:    schema:... | catalog:...                (byScope)
        action:             Read | Write | Execute | Delete | Share | …
        rules[*].principal: byIdentity with resource: group:...
        rules[*].effect:    allow | deny

    Action map (Databricks):
        Read    → SELECT
        Write   → MODIFY        (Databricks aggregates INSERT/UPDATE/DELETE under MODIFY for tables)
        Delete  → MODIFY
        Execute → EXECUTE       (functions only)
        Share   → SELECT        (best-effort; Databricks sharing is a separate mechanism)
        Sample  → SELECT
        Aggregate → SELECT

    For byScope schema-/catalog-level grants, USE SCHEMA / USE CATALOG is
    emitted as adapter scaffolding so the grantee can resolve the namespace
    (per the table-grants exercise's diagnostic on `USE SCHEMA`).
    """
    diagnostics: list[Diagnostic] = []
    policy_id = policy.get("@id")
    applies_to = policy.get("appliesTo") or {}
    selector = applies_to.get("selector")
    action_ir = (policy.get("action") or "Read")
    rules = policy.get("rules") or []

    # Resolve the target object — kind + qualified name — and apply resource_bindings.
    object_kind: str | None = None
    target_name: str | None = None
    needs_usage_scaffold: str | None = None    # what level of USE-* to emit

    if selector == "byIdentity":
        raw_resource = applies_to.get("resource") or ""
        bound = config.bind_resource(raw_resource) or _strip_iri(raw_resource)
        prefix, _ = (raw_resource.split(":", 1) + [""])[:2]
        prefix = prefix.lower()
        if prefix == "table":
            object_kind = "TABLE"; target_name = bound
        elif prefix == "column":
            # Column-level grants aren't a thing in UC; coerce to TABLE on the parent.
            object_kind = "TABLE"
            target_name = bound.rsplit(".", 1)[0]
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.INFO,
                code="COLUMN_GRANT_COERCED_TO_TABLE",
                message=("column-level grants are not a UC primitive; "
                         f"grant emitted on parent TABLE {target_name!r}."),
            ))
        elif prefix == "function":
            object_kind = "FUNCTION"; target_name = bound
        else:
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="UNSUPPORTED_RESOURCE_PREFIX",
                message=f"Unknown byIdentity resource prefix {prefix!r}; cannot emit grant.",
            ))
    elif selector == "byScope":
        raw_scope = applies_to.get("scope") or ""
        # Look up `scope:<raw>` first (preserves the inner prefix for binding clarity);
        # fall back to just the stripped identifier if the inner-prefixed key isn't bound.
        bound = (config.bind_resource(f"scope:{raw_scope}")
                 or config.bind_resource(f"scope:{_strip_iri(raw_scope)}")
                 or _strip_iri(raw_scope))
        prefix, _ = (raw_scope.split(":", 1) + [""])[:2]
        prefix = prefix.lower()
        if prefix == "schema":
            object_kind = "SCHEMA"; target_name = bound; needs_usage_scaffold = "SCHEMA"
        elif prefix == "catalog":
            object_kind = "CATALOG"; target_name = bound; needs_usage_scaffold = "CATALOG"
        else:
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="UNSUPPORTED_SCOPE_PREFIX",
                message=f"Unknown byScope prefix {prefix!r}; cannot emit grant.",
            ))
    else:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="UNSUPPORTED_SELECTOR_FOR_ACCESS_GRANT",
            message=(f"AccessGrantConstraint scaffold supports byIdentity / byScope selectors; "
                     f"got {selector!r}."),
        ))

    if not object_kind or not target_name:
        return EmissionResult(
            policy_id=policy_id, target_artifacts=[], statements=[],
            diagnostics=diagnostics,
        )

    db_action = _map_action_to_databricks(action_ir, object_kind, diagnostics)

    statements: list[str] = []
    for idx, rule in enumerate(rules):
        principal = rule.get("principal") or {}
        if principal.get("selector") != "byIdentity":
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="UNSUPPORTED_PRINCIPAL_SELECTOR_FOR_GRANT",
                message=(f"rule {idx}: AccessGrantConstraint scaffold supports byIdentity principals; "
                         f"got {principal.get('selector')!r}."),
                location=f"rules[{idx}].principal.selector",
            ))
            continue
        principal_ref = principal.get("resource") or ""
        bound_principal = config.bind_principal(principal_ref) or _strip_iri(principal_ref)

        keyword = "GRANT" if rule.get("effect") == "allow" else (
            "DENY" if rule.get("effect") == "deny" else None
        )
        if keyword is None:
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="UNSUPPORTED_EFFECT_FOR_GRANT",
                message=(f"rule {idx}: AccessGrantConstraint supports effect=allow or "
                         f"effect=deny; got {rule.get('effect')!r}."),
                location=f"rules[{idx}].effect",
            ))
            continue

        if needs_usage_scaffold == "SCHEMA":
            statements.append(
                f"GRANT USE SCHEMA ON SCHEMA {target_name} TO `{bound_principal}`;"
            )
        elif needs_usage_scaffold == "CATALOG":
            statements.append(
                f"GRANT USE CATALOG ON CATALOG {target_name} TO `{bound_principal}`;"
            )

        statements.append(
            f"{keyword} {db_action} ON {object_kind} {target_name} "
            f"{'TO' if keyword == 'GRANT' else 'FROM'} `{bound_principal}`;"
        )

    return EmissionResult(
        policy_id=policy_id,
        target_artifacts=[f"{object_kind.lower()}:{target_name}"],
        statements=statements,
        diagnostics=diagnostics,
    )


def _map_action_to_databricks(
    action_ir: str, object_kind: str, diagnostics: list[Diagnostic],
) -> str:
    """Translate a Tessera action to a Databricks privilege keyword."""
    action_ir = action_ir.removeprefix("tessera:")
    mapping = {
        "Read":      "SELECT",
        "Sample":    "SELECT",
        "Aggregate": "SELECT",
        "Share":     "SELECT",
        "Write":     "MODIFY",
        "Delete":    "MODIFY",
        "Execute":   "EXECUTE",
    }
    privilege = mapping.get(action_ir)
    if privilege is None:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="ACTION_TO_PRIVILEGE_FALLBACK",
            message=f"No mapping for Tessera action {action_ir!r}; emitting verbatim.",
        ))
        privilege = action_ir.upper()
    if object_kind == "FUNCTION" and privilege == "SELECT":
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="READ_ON_FUNCTION",
            message=("Action 'Read' on a function maps to SELECT on a TABLE in Databricks. "
                     "For function invocation, the Tessera action should be 'Execute'."),
        ))
    return privilege


def _strip_iri(value: str) -> str:
    if ":" in value and not value.startswith("'"):
        return value.split(":", 1)[1]
    return value


def _column_only(qualified: str) -> str:
    if "." in qualified:
        return qualified.rsplit(".", 1)[-1]
    return qualified


def _row_filter_function_name(policy_id: str | None, target_table: str) -> str:
    slug = (policy_id or "policy").split(":")[-1].replace("-", "_")
    return f"{target_table}__{slug}_filter"


def _row_filter_column_arg(rules: list[dict[str, Any]], target_table: str) -> tuple[str, list[Diagnostic]]:
    """Derive the function's column argument from the first condition operand we find.

    A real adapter would type-check the column against the table schema; the scaffold
    settles for the first column referenced by an `in` condition and assumes STRING.
    """
    diagnostics: list[Diagnostic] = []
    for rule in rules:
        cond = rule.get("condition") or {}
        operands = cond.get("operands") or []
        if operands:
            column = _column_only(_strip_iri(operands[0]))
            return f"{column} STRING", diagnostics
    diagnostics.append(Diagnostic(
        severity=DiagnosticSeverity.INFO,
        code="ROW_FILTER_NO_COLUMN_ARG",
        message="No condition operand referenced; emitting filter without column argument.",
    ))
    return "", diagnostics
