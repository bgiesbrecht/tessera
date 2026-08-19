"""custom-ACL emission: IR → a wrapping secure view.

The custom-ACL adapter (ADR-032) is a *pattern* adapter, not a platform adapter.
Its enforcement target is the customer's own convention: an ACL-table join
exposed through a wrapping view that is granted to consumers instead of the base
table. It predates and sits alongside native RLS (ADR-003). There is no
platform primitive here: the VIEW *is* the enforcement mechanism.

Coverage (v0):
    * RowVisibilityConstraint with a byDataset principal + exists-in-dataset
      condition: the two-table ACL-join shape. Lowered to CREATE OR REPLACE VIEW
      wrapping the base table with the same EXISTS join the native adapters build
      inside their row-filter/row-access primitives.
    * Other policyKinds / selector kinds emit a structured diagnostic (not an
      error) flagging the gap. byIdentity group binding and column masking (a CASE
      in the view's SELECT list) are queued follow-ups.

The emitted SQL is intentionally engine-neutral ANSI-ish DDL: `current_user()`,
`lower(trim(...))`, a correlated EXISTS. The customer runs it on whichever engine
hosts the ACL pattern; the adapter does not execute it.
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
    policy_kind = policy.get("policyKind") or policy.get("@type")
    applies_to = policy.get("appliesTo") or {}
    target_table = applies_to.get("resource") or applies_to.get("scope") or ""

    if policy_kind == "RowVisibilityConstraint":
        return _emit_row_visibility(policy, config)

    return EmissionResult(
        policy_id=policy_id,
        target_artifacts=[_strip_iri(target_table)] if target_table else [],
        statements=[],
        diagnostics=[Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="UNIMPLEMENTED_POLICY_KIND",
            message=(
                f"custom-acl adapter implements the ACL-join view pattern for "
                f"RowVisibilityConstraint only; got policyKind={policy_kind!r}. "
                "Column masking (a CASE in the view SELECT list) and access grants "
                "are queued follow-ups."
            ),
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

    # The custom-ACL pattern is fundamentally data-driven: visibility comes from
    # the ACL-table join, not from a native group/role binding. byDataset is the
    # pattern's whole reason for being.
    if not (rules and all(
        (rule.get("principal") or {}).get("selector") == "byDataset" for rule in rules
    )):
        selectors = [str((r.get("principal") or {}).get("selector")) for r in rules]
        return EmissionResult(
            policy_id=policy_id,
            target_artifacts=[target_table] if target_table else [],
            statements=[],
            diagnostics=[Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="UNIMPLEMENTED_SELECTOR_FOR_ROW_VISIBILITY",
                message=(
                    "custom-acl emits the ACL-join view for byDataset principal selectors "
                    f"(the ACL-table pattern). Got selectors={selectors!r}. byIdentity "
                    "group gating in the view is a queued follow-up."
                ),
                location="rules[].principal.selector",
            )],
        )

    return _emit_acl_view(policy, config, target_table, diagnostics)


def _emit_acl_view(
    policy: dict[str, Any], config: AdapterConfig, target_table: str,
    diagnostics: list[Diagnostic],
) -> EmissionResult:
    """Emit a wrapping secure view backed by a two-table ACL join.

    The IR shape this handles (identical to the native adapters' byDataset path):
        rules[0].principal.selector = "byDataset"
        rules[0].principal.dataset  = PrincipalSetFromTable {table, principalColumn, resourceColumn}
        rules[0].condition.op       = "exists-in-dataset"
        rules[0].condition.operands = [ResourceSetFromTable {table, principalColumn, resourceColumn}]

    Lowered to:
        CREATE OR REPLACE VIEW <schema>.<base>_secured AS
        SELECT * FROM <base> b
        WHERE EXISTS (
            SELECT 1
            FROM <mapping> m
            JOIN <resource_acl> p ON m.<m_resource_col> = p.<p_principal_col>
            WHERE lower(trim(m.<m_principal_col>)) = lower(trim(current_user()))
              AND p.<p_resource_col> = b.<p_resource_col>
        );

    The consumer is granted SELECT on the view instead of the base table; the
    EXISTS clause is the enforcement. defaultStrategy: none ⇒ principals absent
    from the ACL join see no rows (fail-closed), which the EXISTS gives for free.
    """
    policy_id = policy.get("@id")
    rules = policy.get("rules") or []
    if len(rules) != 1:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="MULTI_RULE_BYDATASET_NOT_SUPPORTED",
            message=(
                f"custom-acl byDataset emission expects exactly one rule; got {len(rules)}. "
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
                    "byDataset principal requires dataset @type PrincipalSetFromTable; "
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
        return EmissionResult(
            policy_id=policy_id, target_artifacts=[target_table], statements=[],
            diagnostics=[Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="UNSUPPORTED_CONDITION_FOR_BYDATASET",
                message=(
                    "custom-acl byDataset view requires condition.op = exists-in-dataset; "
                    f"got {condition.get('op')!r}."
                ),
                location="rules[0].condition.op",
            )],
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
                "exists-in-dataset operand expected to be ResourceSetFromTable; "
                f"got {resource_ds.get('@type')!r}."
            ),
            location="rules[0].condition.operands[0].@type",
        ))
    resource_table_raw = resource_ds.get("table") or ""
    resource_table = config.bind_resource(f"table:{resource_table_raw}") or resource_table_raw
    resource_principal_col = resource_ds.get("principalColumn") or "code_name"
    resource_resource_col = resource_ds.get("resourceColumn") or "orderpriority"

    # Issue #13: ResourceSetFromTable.resourceColumn is conflated as both the ACL
    # table's value column and the protected table's discriminator column. The
    # native adapters resolve this by aligning the two; the view does the same:
    # `p.<col> = b.<col>`. Recorded, not silently swallowed.
    diagnostics.append(Diagnostic(
        severity=DiagnosticSeverity.INFO,
        code="RESOURCE_COLUMN_CONFLATION",
        message=(
            f"Using {resource_resource_col!r} as both the ACL value column (p.) and the "
            "protected-table discriminator (b.), per the aligned convention (issue #13)."
        ),
        location="rules[0].condition.operands[0].resourceColumn",
    ))

    view_name = _view_name(target_table, config)
    body = (
        "SELECT * FROM {base} b\n"
        "WHERE EXISTS (\n"
        "  SELECT 1\n"
        "  FROM {mapping} m\n"
        "  JOIN {resource} p ON m.{m_res} = p.{p_prin}\n"
        "  WHERE lower(trim(m.{m_prin})) = lower(trim(current_user()))\n"
        "    AND p.{p_res} = b.{p_res}\n"
        ")"
    ).format(
        base=target_table,
        mapping=mapping_table,
        resource=resource_table,
        m_res=mapping_resource_col,
        p_prin=resource_principal_col,
        m_prin=mapping_principal_col,
        p_res=resource_resource_col,
    )

    statements = [
        f"CREATE OR REPLACE VIEW {view_name} AS\n{body};",
    ]

    return EmissionResult(
        policy_id=policy_id,
        target_artifacts=[view_name],
        statements=statements,
        diagnostics=diagnostics,
    )


def _view_name(target_table: str, config: AdapterConfig) -> str:
    """Name the wrapping view. Full override via config.extras['view_name'];
    otherwise <base>_<suffix> in the base table's schema (default suffix
    'secured')."""
    override = config.extras.get("view_name")
    if override:
        return override
    suffix = config.extras.get("view_suffix", "secured")
    return f"{target_table}_{suffix}"


def _strip_iri(value: str) -> str:
    if ":" in value and not value.startswith("'"):
        return value.split(":", 1)[1]
    return value
