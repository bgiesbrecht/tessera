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
                "scaffold currently emits row filters only for byIdentity table targets. "
                f"Got selector={applies_to.get('selector')!r}."
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
