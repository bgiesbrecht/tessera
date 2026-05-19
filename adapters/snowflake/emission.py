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

    mapping_table = dataset.get("table") or ""
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
        resource_table = resource_ds.get("table") or ""
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
