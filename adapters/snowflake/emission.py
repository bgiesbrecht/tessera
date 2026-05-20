"""Snowflake emission — IR → Snowflake DDL/SQL.

Coverage (scaffold):
    * Row visibility — role-driven, single rule, allow-list semantics. Same source
      IR as the Unity Catalog row-visibility path; different platform output.
    * Other policyKinds and selector kinds emit a placeholder statement plus a
      diagnostic flagging the gap.

Mechanism note: where Unity Catalog uses `is_account_group_member(...)`, Snowflake
uses `IS_ROLE_IN_SESSION('ROLE_NAME')` against the currently active session role.
The adapter relies on AdapterConfig.identity_bindings to map IR PrincipalRefs
(typically Databricks-style group names) to the corresponding Snowflake role name.
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

    if policy_kind == "RowVisibilityConstraint":
        return _emit_row_visibility(policy, config)
    if policy_kind == "ColumnVisibilityConstraint":
        return _emit_column_visibility(policy, config)
    if policy_kind == "AccessGrantConstraint":
        return _emit_access_grant(policy, config)

    return EmissionResult(
        policy_id=policy_id,
        target_artifacts=[target_table] if target_table else [],
        statements=[f"-- TODO: emit {policy_kind} for {policy_id}"],
        diagnostics=[Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="UNIMPLEMENTED_POLICY_KIND",
            message=f"snowflake adapter has not implemented emission for policyKind={policy_kind!r}.",
            location="policyKind",
        )],
    )


def _emit_row_visibility(policy: dict[str, Any], config: AdapterConfig) -> EmissionResult:
    diagnostics: list[Diagnostic] = []
    policy_id = policy.get("@id")
    applies_to = policy.get("appliesTo") or {}
    raw_resource = applies_to.get("resource") or ""
    target_table = config.bind_resource(raw_resource) or _strip_iri(raw_resource)
    rules = policy.get("rules") or []

    if applies_to.get("selector") != "byIdentity":
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="UNIMPLEMENTED_SELECTOR_FOR_ROW_VISIBILITY",
            message=(
                "scaffold currently emits row-access policies only for byIdentity table targets. "
                f"Got selector={applies_to.get('selector')!r}."
            ),
            location="appliesTo.selector",
        ))

    # Dispatch on principal selector kind. The byDataset path emits a single-branch
    # row-access policy whose body is a correlated EXISTS subquery joining the ACL
    # mapping tables; the byIdentity path emits per-rule role-based branches as before.
    if rules and all(
        (rule.get("principal") or {}).get("selector") == "byDataset" for rule in rules
    ):
        return _emit_row_visibility_by_dataset(policy, config, target_table)

    branches: list[str] = []
    for idx, rule in enumerate(rules):
        branch, rule_diags = _render_rule_branch(rule, config, idx, target_table)
        diagnostics.extend(rule_diags)
        if branch:
            branches.append(branch)

    column_name, column_diags = _row_policy_column(rules)
    diagnostics.extend(column_diags)
    policy_name = _row_policy_name(policy_id, target_table)
    column_type = "VARCHAR"

    if not branches:
        body = "FALSE"
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="EMPTY_POLICY_BODY",
            message="No emittable rule branches; row-access policy denies all rows by default.",
        ))
    else:
        body = "\n        OR ".join(branches)

    statements = [
        f"CREATE OR REPLACE ROW ACCESS POLICY {policy_name}\n"
        f"AS ({column_name} {column_type}) RETURNS BOOLEAN ->\n"
        f"        {body};",
        f"ALTER TABLE {target_table} ADD ROW ACCESS POLICY {policy_name} ON ({column_name});",
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
    """Emit a Snowflake row-access policy backed by an ACL mapping-table join.

    The IR shape this handles:
        rules[0].principal.selector = "byDataset"
        rules[0].principal.dataset  = PrincipalSetFromTable {table, principalColumn, resourceColumn}
        rules[0].condition.op       = "exists-in-dataset"
        rules[0].condition.operands = [ResourceSetFromTable {table, principalColumn, resourceColumn}]

    Lowered to:
        CREATE OR REPLACE ROW ACCESS POLICY <name>
        AS (<col> VARCHAR) RETURNS BOOLEAN ->
            EXISTS (
                SELECT 1
                FROM <mapping_table> m
                JOIN <resource_acl_table> p ON m.<m_resource_col> = p.<p_principal_col>
                WHERE m.<m_principal_col> = CURRENT_USER()
                  AND p.<p_resource_col> = <col>
            );

    Single-rule, single-branch. defaultStrategy: none ⇒ no fallback clause is emitted.
    """
    diagnostics: list[Diagnostic] = []
    policy_id = policy.get("@id")
    rules = policy.get("rules") or []
    if len(rules) != 1:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="MULTI_RULE_BYDATASET_NOT_SUPPORTED",
            message=(
                f"scaffold byDataset emission expects exactly one rule; got {len(rules)}. "
                "Emitting the first rule only."
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
                f"got {condition.get('op')!r}. Emitting with mapping-table-only EXISTS clause."
            ),
            location="rules[0].condition.op",
        ))
        resource_table = None
        resource_principal_col = None
        resource_resource_col = None
    else:
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
                location="rules[0].condition.operands[0].@type",
            ))
        resource_table_raw = resource_ds.get("table") or ""
        resource_table = config.bind_resource(f"table:{resource_table_raw}") or resource_table_raw
        resource_principal_col = resource_ds.get("principalColumn") or "code_name"
        resource_resource_col = resource_ds.get("resourceColumn") or "orderpriority"

    policy_name = _row_policy_name(policy_id, target_table)
    # The policy parameter name must NOT collide with any column name referenced in the
    # subquery body (otherwise Snowflake resolves the bare identifier to the column and
    # the predicate becomes `col = col`, always true). Use a fixed parameter alias.
    param_name = "POLICY_INPUT_VALUE"
    bound_column = resource_resource_col or "value"
    column_type = "VARCHAR"

    # Build the EXISTS body. If we have both mapping and resource ACL tables, join them.
    # If only the mapping table (degraded condition path), the body is a simple mapping lookup.
    if resource_table:
        body = (
            "EXISTS (\n"
            "            SELECT 1\n"
            f"            FROM {mapping_table} m\n"
            f"            JOIN {resource_table} p\n"
            f"              ON m.{mapping_resource_col} = p.{resource_principal_col}\n"
            f"            WHERE m.{mapping_principal_col} = CURRENT_USER()\n"
            f"              AND p.{resource_resource_col} = {param_name}\n"
            "        )"
        )
    else:
        body = (
            "EXISTS (\n"
            f"            SELECT 1 FROM {mapping_table} m\n"
            f"            WHERE m.{mapping_principal_col} = CURRENT_USER()\n"
            "        )"
        )

    statements = [
        f"CREATE OR REPLACE ROW ACCESS POLICY {policy_name}\n"
        f"AS ({param_name} {column_type}) RETURNS BOOLEAN ->\n"
        f"        {body};",
        f"ALTER TABLE {target_table} ADD ROW ACCESS POLICY {policy_name} ON ({bound_column});",
    ]

    return EmissionResult(
        policy_id=policy_id,
        target_artifacts=[target_table],
        statements=statements,
        diagnostics=diagnostics,
    )


def _emit_column_visibility(policy: dict[str, Any], config: AdapterConfig) -> EmissionResult:
    """Lower a ColumnVisibilityConstraint to a Snowflake masking policy.

    Emission target:
        CREATE OR REPLACE MASKING POLICY <name>
        AS (<col> VARCHAR) RETURNS VARCHAR ->
          CASE
            WHEN IS_ROLE_IN_SESSION('<role>') THEN <col>
            ELSE '<replacement>'
          END;

        ALTER TABLE <table> MODIFY COLUMN <col> SET MASKING POLICY <name>;

    Snowflake role-discrimination semantics per issue #14: the adapter emits
    `IS_ROLE_IN_SESSION` (Intent B — permission-scope semantics, matches
    Snowflake's documented recommendation). If a policy needs primary-role-only
    discrimination (Intent A), that's a deferred design question, not implemented here.

    Coverage scope: byIdentity column targets; rules with effect=allow or
    effect=transform; defaultBranch with effect=transform; Redact transformation.
    Mask and Hash emit NULL placeholders pending future scaffold passes.
    ABAC byScope column masking is a separate emission path, queued.
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
                "scaffold currently emits masking policies only for byIdentity column targets. "
                f"Got selector={applies_to.get('selector')!r}. ABAC byScope column masking is queued."
            ),
            location="appliesTo.selector",
        ))

    if "." not in bound_resource:
        return EmissionResult(
            policy_id=policy_id, target_artifacts=[], statements=[],
            diagnostics=[Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="MALFORMED_COLUMN_REFERENCE",
                message=(
                    "ColumnVisibility appliesTo.resource must resolve (via resource_bindings or "
                    "directly) to a fully-qualified <database>.<schema>.<table>.<column>; "
                    f"got {bound_resource!r}."
                ),
                location="appliesTo.resource",
            )],
        )
    target_table, target_column = bound_resource.rsplit(".", 1)
    schema_qualified = target_table.rsplit(".", 1)[0] if target_table.count(".") >= 1 else target_table

    # Each rule contributes a WHEN clause. The policy body's parameter name must
    # not collide with any column name referenced in the body — see the row-access
    # policy comment in _emit_row_visibility_by_dataset. For masking policies the
    # parameter IS the column being masked, so the name should match (Snowflake
    # binds positionally and uses the parameter name as the column reference
    # inside the CASE). We use the column name verbatim as the parameter; the
    # collision concern in the byDataset row-policy case does not apply here.
    when_clauses: list[str] = []
    for idx, rule in enumerate(rules):
        principal = rule.get("principal") or {}
        effect = rule.get("effect")
        if principal.get("selector") != "byIdentity":
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="UNSUPPORTED_PRINCIPAL_SELECTOR",
                message=f"rule {idx}: scaffold supports only byIdentity principal selectors for masking policies.",
                location=f"rules[{idx}].principal.selector",
            ))
            continue
        principal_ref = principal.get("resource") or ""
        bound = config.bind_principal(principal_ref) or _strip_iri(principal_ref).upper()
        membership = f"IS_ROLE_IN_SESSION('{bound}')"

        if effect == "allow":
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
                    f"rule {idx}: masking-policy emission supports effect=allow or "
                    f"effect=transform; got {effect!r}."
                ),
                location=f"rules[{idx}].effect",
            ))

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
    policy_name = _mask_policy_name(policy_id, schema_qualified)

    statements = [
        f"CREATE OR REPLACE MASKING POLICY {policy_name}\n"
        f"AS ({target_column} VARCHAR) RETURNS VARCHAR ->\n"
        f"  CASE\n"
        f"    {case_body}\n"
        f"  END;",
        f"ALTER TABLE {target_table}\n  MODIFY COLUMN {target_column}\n  SET MASKING POLICY {policy_name};",
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
    """Render a TransformationInstance into a Snowflake SQL expression usable inside a CASE branch."""
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
        quoted = "'" + str(replacement).replace("'", "''") + "'"
        return quoted, diagnostics
    if ttype == "Mask":
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="MASK_TRANSFORMATION_NOT_IMPLEMENTED",
            message="Mask transformation emission queued; emitting NULL placeholder.",
            location=f"transformation@{location_tag}",
        ))
        return "NULL", diagnostics
    if ttype == "Hash":
        algorithm = (transformation.get("algorithm") or "sha256").lower()
        if algorithm in ("sha256", "sha-256"):
            # Snowflake's SHA2 with bit-length 256.
            return f"SHA2({column_name}, 256)", diagnostics
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


def _mask_policy_name(policy_id: str | None, schema_qualified: str) -> str:
    slug = (policy_id or "policy").split(":")[-1].replace("-", "_")
    return f"{schema_qualified}.{slug}_mask"


def _render_rule_branch(
    rule: dict[str, Any], config: AdapterConfig, idx: int, target_table: str,
) -> tuple[str, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    principal = rule.get("principal") or {}
    effect = rule.get("effect")

    if effect not in ("keep-matching-rows", "allow"):
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.INFO,
            code="ROW_POLICY_EFFECT_REINTERPRETED",
            message=f"rule {idx} effect={effect!r} treated as keep-matching-rows for row-access policy emission.",
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

    bound = config.bind_principal(principal_ref)
    if bound is None:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="UNBOUND_PRINCIPAL",
            message=(
                f"rule {idx}: principal {principal_ref!r} has no identity_bindings entry. Snowflake roles "
                "are case-sensitive; without an explicit binding the adapter falls back to the IR slug, "
                "which may not resolve."
            ),
            location=f"rules[{idx}].principal",
        ))
        bound = _strip_iri(principal_ref)
    membership = f"IS_ROLE_IN_SESSION('{bound.upper()}')"

    condition_clause = _render_condition(rule.get("condition") or {}, idx, diagnostics)
    if condition_clause:
        return f"({membership} AND {condition_clause})", diagnostics
    return membership, diagnostics


def _render_condition(condition: dict[str, Any], idx: int, diagnostics: list[Diagnostic]) -> str:
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
    """Lower an AccessGrantConstraint to Snowflake GRANT statements.

    Action map (Snowflake):
        Read    → SELECT
        Write   → INSERT, UPDATE, DELETE  (best-effort; Snowflake fans out)
        Delete  → DELETE
        Execute → USAGE  (Snowflake uses USAGE for function/procedure invocation)
        Share   → SELECT
        Sample  → SELECT
        Aggregate → SELECT

    Snowflake function grants require a signature (`(args)`). The IR doesn't
    carry the signature; emission uses `()` as a placeholder and emits a
    warning. Production migration tooling would resolve the signature from
    the deployed function metadata.
    """
    diagnostics: list[Diagnostic] = []
    policy_id = policy.get("@id")
    applies_to = policy.get("appliesTo") or {}
    selector = applies_to.get("selector")
    action_ir = (policy.get("action") or "Read")
    rules = policy.get("rules") or []

    object_kind: str | None = None
    target_name: str | None = None

    if selector == "byIdentity":
        raw_resource = applies_to.get("resource") or ""
        bound = config.bind_resource(raw_resource) or _strip_iri(raw_resource)
        prefix, _ = (raw_resource.split(":", 1) + [""])[:2]
        prefix = prefix.lower()
        if prefix == "table":
            object_kind = "TABLE"; target_name = bound
        elif prefix == "column":
            object_kind = "TABLE"
            target_name = bound.rsplit(".", 1)[0]
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.INFO,
                code="COLUMN_GRANT_COERCED_TO_TABLE",
                message=(f"column-level grants aren't a Snowflake primitive; "
                         f"grant emitted on parent TABLE {target_name!r}."),
            ))
        elif prefix == "function":
            object_kind = "FUNCTION"
            # If the bound resource already includes a signature (e.g.,
            # `ACME.SCHEMA.fn(NUMBER)`), use it verbatim. Otherwise resolve
            # via the Snowflake cursor if one is available in extras; failing
            # that, emit a `()` placeholder with a warning.
            if "(" in bound:
                target_name = bound
            else:
                sig = _resolve_function_signature(bound, config, diagnostics)
                target_name = f"{bound}{sig}"
                if sig == "()":
                    diagnostics.append(Diagnostic(
                        severity=DiagnosticSeverity.WARNING,
                        code="FUNCTION_SIGNATURE_PLACEHOLDER",
                        message=(f"Could not resolve signature for {bound!r}; emitted "
                                 "with `()` placeholder. Provide the signature via the "
                                 "resource binding (e.g., `fn(NUMBER)`) or supply a "
                                 "Snowflake cursor in config.extras for auto-resolution."),
                    ))
        else:
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="UNSUPPORTED_RESOURCE_PREFIX",
                message=f"Unknown byIdentity resource prefix {prefix!r}; cannot emit grant.",
            ))
    elif selector == "byScope":
        raw_scope = applies_to.get("scope") or ""
        bound = (config.bind_resource(f"scope:{raw_scope}")
                 or config.bind_resource(f"scope:{_strip_iri(raw_scope)}")
                 or _strip_iri(raw_scope))
        prefix, _ = (raw_scope.split(":", 1) + [""])[:2]
        prefix = prefix.lower()
        if prefix == "schema":
            object_kind = "SCHEMA"; target_name = bound
        elif prefix == "catalog":
            # Snowflake's catalog analog is DATABASE.
            object_kind = "DATABASE"; target_name = bound
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

    privileges = _map_action_to_snowflake(action_ir, object_kind, diagnostics)

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
        bound_principal = (config.bind_principal(principal_ref)
                           or _strip_iri(principal_ref).upper())

        keyword = "GRANT" if rule.get("effect") == "allow" else None
        if keyword is None:
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="UNSUPPORTED_EFFECT_FOR_GRANT",
                message=(f"rule {idx}: Snowflake emission supports effect=allow only; "
                         f"got {rule.get('effect')!r}. (Snowflake has no DENY equivalent.)"),
                location=f"rules[{idx}].effect",
            ))
            continue

        # Schema/database grants need USAGE first so the role can resolve the namespace.
        if object_kind == "SCHEMA":
            statements.append(
                f"GRANT USAGE ON SCHEMA {target_name} TO ROLE {bound_principal};"
            )
        elif object_kind == "DATABASE":
            statements.append(
                f"GRANT USAGE ON DATABASE {target_name} TO ROLE {bound_principal};"
            )

        for priv in privileges:
            if object_kind == "SCHEMA" and priv != "USAGE":
                # Snowflake doesn't allow privileges like SELECT directly on a SCHEMA.
                # Schema-level read intent expands to "SELECT on all current + future
                # tables in the schema" — matching Tessera's byScope downward-
                # propagation semantics from ADR-019.
                statements.append(
                    f"{keyword} {priv} ON ALL TABLES IN SCHEMA {target_name} TO ROLE {bound_principal};"
                )
                statements.append(
                    f"{keyword} {priv} ON FUTURE TABLES IN SCHEMA {target_name} TO ROLE {bound_principal};"
                )
            elif object_kind == "DATABASE" and priv != "USAGE":
                statements.append(
                    f"{keyword} {priv} ON ALL TABLES IN DATABASE {target_name} TO ROLE {bound_principal};"
                )
                statements.append(
                    f"{keyword} {priv} ON FUTURE TABLES IN DATABASE {target_name} TO ROLE {bound_principal};"
                )
            else:
                statements.append(
                    f"{keyword} {priv} ON {object_kind} {target_name} TO ROLE {bound_principal};"
                )

    return EmissionResult(
        policy_id=policy_id,
        target_artifacts=[f"{object_kind.lower()}:{target_name}"],
        statements=statements,
        diagnostics=diagnostics,
    )


def _resolve_function_signature(
    fq_function: str, config: AdapterConfig, diagnostics: list[Diagnostic],
) -> str:
    """Query Snowflake for the signature of a function by name. Returns '(...)'.

    Uses INFORMATION_SCHEMA.FUNCTIONS via the cursor in config.extras['snowflake_cursor']
    when available. Falls back to '()' if no cursor or no match.
    """
    cursor = config.extras.get("snowflake_cursor")
    if cursor is None:
        return "()"
    parts = fq_function.split(".")
    if len(parts) != 3:
        return "()"
    db, schema, name = parts
    try:
        cursor.execute(
            "SELECT argument_signature FROM "
            f"  {db}.INFORMATION_SCHEMA.FUNCTIONS "
            f"WHERE function_schema = '{schema}' AND function_name = '{name.upper()}'"
        )
        rows = cursor.fetchall()
        if rows:
            sig = rows[0][0] or "()"
            # argument_signature looks like "(CUSTOMER_KEY NUMBER)"; Snowflake's
            # GRANT USAGE ON FUNCTION needs just the type list, e.g., "(NUMBER)".
            import re
            inner = sig.strip("()")
            if not inner.strip():
                return "()"
            type_list = []
            for arg in inner.split(","):
                tokens = arg.strip().split()
                if len(tokens) >= 2:
                    type_list.append(tokens[-1])
                elif tokens:
                    type_list.append(tokens[-1])
            return "(" + ", ".join(type_list) + ")"
    except Exception as e:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.INFO,
            code="FUNCTION_SIGNATURE_LOOKUP_FAILED",
            message=f"Could not resolve signature for {fq_function}: {str(e).splitlines()[0][:160]}",
        ))
    return "()"


def _map_action_to_snowflake(
    action_ir: str, object_kind: str, diagnostics: list[Diagnostic],
) -> list[str]:
    """Translate a Tessera action to Snowflake privilege keyword(s).

    Returns a list because some actions fan out to multiple Snowflake privileges
    (e.g., Write → INSERT + UPDATE + DELETE on tables).
    """
    action_ir = action_ir.removeprefix("tessera:")
    if object_kind == "FUNCTION":
        # Snowflake function/procedure invocation = USAGE privilege.
        if action_ir in ("Execute",):
            return ["USAGE"]
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="ACTION_NOT_APPLICABLE_TO_FUNCTION",
            message=(f"Action {action_ir!r} doesn't apply to Snowflake functions; "
                     "emitting USAGE as a best-effort fallback."),
        ))
        return ["USAGE"]
    if action_ir == "Read":
        return ["SELECT"]
    if action_ir == "Write":
        return ["INSERT", "UPDATE", "DELETE"]
    if action_ir == "Delete":
        return ["DELETE"]
    if action_ir in ("Share", "Sample", "Aggregate"):
        return ["SELECT"]
    if action_ir == "Execute":
        return ["USAGE"]
    diagnostics.append(Diagnostic(
        severity=DiagnosticSeverity.WARNING,
        code="ACTION_TO_PRIVILEGE_FALLBACK",
        message=f"No Snowflake privilege mapping for action {action_ir!r}; emitting verbatim.",
    ))
    return [action_ir.upper()]


def _strip_iri(value: str) -> str:
    if ":" in value and not value.startswith("'"):
        return value.split(":", 1)[1]
    return value


def _column_only(qualified: str) -> str:
    if "." in qualified:
        return qualified.rsplit(".", 1)[-1]
    return qualified


def _row_policy_name(policy_id: str | None, target_table: str) -> str:
    slug = (policy_id or "policy").split(":")[-1].replace("-", "_")
    schema_qualified = target_table.rsplit(".", 1)[0] if "." in target_table else ""
    name = f"{slug}_rap"
    return f"{schema_qualified}.{name}" if schema_qualified else name


def _row_policy_column(rules: list[dict[str, Any]]) -> tuple[str, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    for rule in rules:
        cond = rule.get("condition") or {}
        operands = cond.get("operands") or []
        if operands:
            return _column_only(_strip_iri(operands[0])), diagnostics
    diagnostics.append(Diagnostic(
        severity=DiagnosticSeverity.INFO,
        code="ROW_POLICY_NO_COLUMN_REF",
        message="No condition operand referenced; defaulting policy column to 'col'.",
    ))
    return "col", diagnostics
