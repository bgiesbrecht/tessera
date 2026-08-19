"""Oracle emission: IR → Oracle DDL/PL-SQL.

Oracle's governance primitives are different in shape from Unity Catalog's and
Snowflake's, which is exactly why a third platform is a good portability test
(ADR-033). The mapping (cited in the capability profile per ADR-027):

    * Row visibility   → Virtual Private Database (VPD): DBMS_RLS.ADD_POLICY
      attaches a PL/SQL *policy function* that returns a predicate string, which
      Oracle appends to every query's WHERE clause.
        - byIdentity: the function returns a role-gated predicate, testing enabled
          roles via SYS_CONTEXT('SYS_SESSION_ROLES','<ROLE>').
        - byDataset:  the function returns an EXISTS subquery over the ACL tables,
          keyed off SYS_CONTEXT('USERENV','SESSION_USER').
    * Column visibility → Oracle Data Redaction: DBMS_REDACT.ADD_POLICY. A Redact
      with a replacement literal lowers to function_type => DBMS_REDACT.REGEXP
      (FULL cannot carry an arbitrary replacement string); the `expression`
      controls who sees redacted data.
    * Access grants     → GRANT <priv> ON <obj> TO <role>.

Selector kinds / policy kinds without an Oracle mapping (byScope/tag-driven ABAC,
retention) surface a structured diagnostic. The adapter never executes; it returns
statements for the caller to run.

`oracledb` is imported lazily elsewhere (discovery/live scripts); emission needs no
driver.
"""

from __future__ import annotations

from typing import Any

from adapters.contract.types import (
    AdapterConfig,
    Diagnostic,
    DiagnosticSeverity,
    EmissionResult,
)

_ACTION_TO_PRIVILEGE = {
    "Read": "SELECT",
    "Write": "UPDATE",
    "Delete": "DELETE",
    "Execute": "EXECUTE",
}


def emit_policy(policy: dict[str, Any], config: AdapterConfig) -> EmissionResult:
    policy_id = policy.get("@id")
    policy_kind = policy.get("policyKind") or policy.get("@type")
    applies_to = policy.get("appliesTo") or {}
    target = applies_to.get("resource") or applies_to.get("scope") or ""

    if policy_kind == "RowVisibilityConstraint":
        return _emit_row_visibility(policy, config)
    if policy_kind == "ColumnVisibilityConstraint":
        return _emit_column_visibility(policy, config)
    if policy_kind == "AccessGrantConstraint":
        return _emit_access_grant(policy, config)
    if policy_kind == "RetentionConstraint":
        return _emit_retention_expression_only(policy_id)

    return EmissionResult(
        policy_id=policy_id,
        target_artifacts=[_strip_iri(target)] if target else [],
        statements=[],
        diagnostics=[Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="UNIMPLEMENTED_POLICY_KIND",
            message=f"oracle adapter has not implemented emission for policyKind={policy_kind!r}.",
            location="policyKind",
        )],
    )


def _emit_retention_expression_only(policy_id: Any) -> EmissionResult:
    return EmissionResult(
        policy_id=policy_id, target_artifacts=[], statements=[],
        diagnostics=[Diagnostic(
            severity=DiagnosticSeverity.INFO,
            code="RETENTION_EXPRESSION_ONLY",
            message=(
                "RetentionConstraint is expressed and validated but not emitted (ADR-031). "
                "Oracle has no declarative delete-after primitive; enforcement would be a "
                "scheduled job (DBMS_SCHEDULER + DELETE), which Tessera does not emit in v0."
            ),
            location="policyKind",
        )],
    )


# ---------------------------------------------------------------------------
# Row visibility: Virtual Private Database (VPD)
# ---------------------------------------------------------------------------


def _emit_row_visibility(policy: dict[str, Any], config: AdapterConfig) -> EmissionResult:
    policy_id = policy.get("@id")
    applies_to = policy.get("appliesTo") or {}

    if applies_to.get("selector") == "byScope":
        return EmissionResult(
            policy_id=policy_id, target_artifacts=[], statements=[],
            diagnostics=[Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="UNSUPPORTED_ABAC_SCOPING",
                message=(
                    "Oracle has no governed-tag-driven policy attachment (the UC/Snowflake "
                    "byScope mechanism). Oracle Label Security is the nearest primitive and is "
                    "deferred; byScope row visibility is not emitted."
                ),
                location="appliesTo.selector",
            )],
        )

    raw_resource = applies_to.get("resource") or ""
    schema, obj = _oracle_object(raw_resource, config)
    rules = policy.get("rules") or []

    if rules and all(
        (rule.get("principal") or {}).get("selector") == "byDataset" for rule in rules
    ):
        return _emit_row_visibility_by_dataset(policy, config, schema, obj)
    return _emit_row_visibility_by_identity(policy, config, schema, obj)


def _emit_row_visibility_by_identity(
    policy: dict[str, Any], config: AdapterConfig, schema: str, obj: str,
) -> EmissionResult:
    """Role-gated VPD policy function. Each byIdentity rule becomes an IF branch
    testing SYS_CONTEXT('SYS_SESSION_ROLES','<ROLE>'); the returned predicate is
    the rule's row filter. Fail-closed ELSE ('1=0') for principals in no rule.
    That is what explicit-baseline-group intends (the baseline group is an
    explicit rule)."""
    diagnostics: list[Diagnostic] = []
    policy_id = policy.get("@id")
    rules = policy.get("rules") or []

    branches: list[str] = []
    for idx, rule in enumerate(rules):
        principal = rule.get("principal") or {}
        if principal.get("selector") != "byIdentity" or not principal.get("resource"):
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="UNSUPPORTED_PRINCIPAL_SELECTOR",
                message=f"rule {idx}: Oracle byIdentity VPD emits byIdentity principals only.",
                location=f"rules[{idx}].principal",
            ))
            continue
        role = _oracle_role(principal["resource"], config)
        predicate = _row_predicate(rule, obj, idx, diagnostics)
        branch_kw = "IF" if not branches else "ELSIF"
        branches.append(
            f"  {branch_kw} SYS_CONTEXT('SYS_SESSION_ROLES', '{role}') = 'TRUE' THEN\n"
            f"    RETURN '{predicate}';"
        )

    if not branches:
        return EmissionResult(
            policy_id=policy_id, target_artifacts=[f"{schema}.{obj}"], statements=[],
            diagnostics=diagnostics + [Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="EMPTY_POLICY_BODY",
                message="No emittable byIdentity rules; nothing to attach.",
            )],
        )

    fn = _vpd_function_name(policy_id)
    body = "\n".join(branches)
    func = (
        f"CREATE OR REPLACE FUNCTION {schema}.{fn}(\n"
        f"  p_schema IN VARCHAR2, p_object IN VARCHAR2\n"
        f") RETURN VARCHAR2 AS\n"
        f"BEGIN\n"
        f"{body}\n"
        f"  ELSE\n"
        f"    RETURN '1=0';\n"
        f"  END IF;\n"
        f"END;\n/"
    )
    add_policy = _add_vpd_policy(schema, obj, policy_id, fn)
    return EmissionResult(
        policy_id=policy_id,
        target_artifacts=[f"{schema}.{obj}"],
        statements=[func, add_policy],
        diagnostics=diagnostics,
    )


def _emit_row_visibility_by_dataset(
    policy: dict[str, Any], config: AdapterConfig, schema: str, obj: str,
) -> EmissionResult:
    """VPD policy function whose predicate is a non-correlated IN-subquery over the
    ACL tables (the same join the other adapters build), returned as a WHERE
    predicate string. Fail-closed for principals absent from the join: the
    subquery returns no values."""
    diagnostics: list[Diagnostic] = []
    policy_id = policy.get("@id")
    rules = policy.get("rules") or []
    rule = rules[0]

    principal = rule.get("principal") or {}
    dataset = principal.get("dataset") or {}
    if dataset.get("@type") != "PrincipalSetFromTable":
        return EmissionResult(
            policy_id=policy_id, target_artifacts=[f"{schema}.{obj}"], statements=[],
            diagnostics=[Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="UNSUPPORTED_DATASET_TYPE",
                message=f"byDataset requires PrincipalSetFromTable; got {dataset.get('@type')!r}.",
                location="rules[0].principal.dataset.@type",
            )],
        )
    mapping_table = _oracle_table(dataset.get("table") or "", config)
    m_prin = dataset.get("principalColumn") or "username"
    m_res = dataset.get("resourceColumn") or "code_name"

    condition = rule.get("condition") or {}
    operands = condition.get("operands") or []
    if condition.get("op") != "exists-in-dataset" or not operands:
        return EmissionResult(
            policy_id=policy_id, target_artifacts=[f"{schema}.{obj}"], statements=[],
            diagnostics=[Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="UNSUPPORTED_CONDITION_FOR_BYDATASET",
                message="byDataset VPD requires exists-in-dataset with a ResourceSetFromTable operand.",
                location="rules[0].condition",
            )],
        )
    resource_ds = operands[0]
    resource_table = _oracle_table(resource_ds.get("table") or "", config)
    p_prin = resource_ds.get("principalColumn") or "code_name"
    p_res = resource_ds.get("resourceColumn") or "orderpriority"

    # Issue #13: resourceColumn is conflated as both the ACL value column (p.) and
    # the protected-table discriminator (bare, resolved against the outer table by
    # the VPD predicate). The aligned convention is assumed, as in the other adapters.
    diagnostics.append(Diagnostic(
        severity=DiagnosticSeverity.INFO,
        code="RESOURCE_COLUMN_CONFLATION",
        message=(
            f"Using {p_res!r} as both the ACL value column (p.) and the protected-table "
            "discriminator in the VPD predicate, per the aligned convention (issue #13)."
        ),
        location="rules[0].condition.operands[0].resourceColumn",
    ))

    # The predicate is a string returned by the function; single-quotes inside it
    # must be doubled for the PL/SQL literal.
    #
    # A non-correlated IN-subquery, NOT a correlated EXISTS. Live verification
    # caught the trap: in `EXISTS (... AND p.<col> = <col>)` the bare <col>
    # resolves to the inner ACL table p (which also has that column), making the
    # predicate `p.<col> = p.<col>`, always true, so any mapped user saw all rows.
    # The IN form keeps the outer column bare (VPD resolves it to the protected
    # table, correctly, and robustly under table aliasing) while the subquery is
    # self-contained: the set of values the current user is entitled to.
    predicate = (
        f"{p_res} IN (SELECT p.{p_res} FROM {mapping_table} m "
        f"JOIN {resource_table} p ON m.{m_res} = p.{p_prin} "
        f"WHERE lower(trim(m.{m_prin})) = lower(trim(SYS_CONTEXT(''USERENV'',''SESSION_USER''))))"
    )
    fn = _vpd_function_name(policy_id)
    func = (
        f"CREATE OR REPLACE FUNCTION {schema}.{fn}(\n"
        f"  p_schema IN VARCHAR2, p_object IN VARCHAR2\n"
        f") RETURN VARCHAR2 AS\n"
        f"BEGIN\n"
        f"  RETURN '{predicate}';\n"
        f"END;\n/"
    )
    add_policy = _add_vpd_policy(schema, obj, policy_id, fn)
    return EmissionResult(
        policy_id=policy_id,
        target_artifacts=[f"{schema}.{obj}"],
        statements=[func, add_policy],
        diagnostics=diagnostics,
    )


def _row_predicate(rule: dict[str, Any], obj: str, idx: int, diagnostics: list[Diagnostic]) -> str:
    """Build the WHERE-predicate a VPD branch returns. No condition ⇒ '1=1' (all
    rows for that role). An `in` condition ⇒ `<col> IN ('a','b')`. Single quotes
    are doubled because the predicate is itself a PL/SQL string literal."""
    condition = rule.get("condition") or {}
    if not condition:
        return "1=1"
    op = condition.get("op")
    operands = condition.get("operands") or []
    values = condition.get("values") or []
    if op == "in" and operands and values:
        col = _strip_iri(operands[0]).rsplit(".", 1)[-1]
        vals = ", ".join(f"''{v}''" for v in values)  # doubled quotes for PL/SQL literal
        return f"{col} IN ({vals})"
    diagnostics.append(Diagnostic(
        severity=DiagnosticSeverity.WARNING,
        code="UNSUPPORTED_CONDITION",
        message=f"rule {idx}: condition op={op!r} not lowered; branch returns all-rows predicate.",
        location=f"rules[{idx}].condition",
    ))
    return "1=1"


def _add_vpd_policy(schema: str, obj: str, policy_id: Any, fn: str) -> str:
    pname = _vpd_policy_name(policy_id)
    return (
        f"BEGIN\n"
        f"  DBMS_RLS.ADD_POLICY(\n"
        f"    object_schema   => '{schema}',\n"
        f"    object_name     => '{obj}',\n"
        f"    policy_name     => '{pname}',\n"
        f"    function_schema => '{schema}',\n"
        f"    policy_function => '{fn}',\n"
        f"    statement_types => 'SELECT'\n"
        f"  );\nEND;\n/"
    )


# ---------------------------------------------------------------------------
# Column visibility: Oracle Data Redaction
# ---------------------------------------------------------------------------


def _emit_column_visibility(policy: dict[str, Any], config: AdapterConfig) -> EmissionResult:
    diagnostics: list[Diagnostic] = []
    policy_id = policy.get("@id")
    applies_to = policy.get("appliesTo") or {}

    if applies_to.get("selector") == "byScope":
        return EmissionResult(
            policy_id=policy_id, target_artifacts=[], statements=[],
            diagnostics=[Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="UNSUPPORTED_ABAC_SCOPING",
                message=(
                    "Oracle Data Redaction has no tag-driven attachment; byScope column masking "
                    "is not emitted (Oracle Label Security deferred)."
                ),
                location="appliesTo.selector",
            )],
        )

    raw_col = applies_to.get("resource") or ""
    schema, obj, column = _oracle_column(raw_col, config)

    # Determine the allowed principal (sees real data) and the transform.
    rules = policy.get("rules") or []
    allow_roles = [
        _oracle_role((r.get("principal") or {}).get("resource", ""), config)
        for r in rules if r.get("effect") == "allow"
        and (r.get("principal") or {}).get("selector") == "byIdentity"
    ]
    default_branch = policy.get("defaultBranch") or {}
    transformation = default_branch.get("transformation") or {}
    if transformation.get("type") != "Redact":
        # Some policies carry the transform on a rule rather than defaultBranch.
        for r in rules:
            if r.get("effect") == "transform":
                transformation = r.get("transformation") or transformation
    if transformation.get("type") != "Redact":
        return EmissionResult(
            policy_id=policy_id, target_artifacts=[f"{schema}.{obj}"], statements=[],
            diagnostics=[Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="UNSUPPORTED_TRANSFORMATION",
                message=(
                    f"Oracle adapter emits Redact via DBMS_REDACT.REGEXP; got "
                    f"transformation={transformation.get('type')!r}. Mask/Hash queued."
                ),
                location="defaultBranch.transformation.type",
            )],
        )
    replacement = transformation.get("replacement", "REDACTED")

    # Data Redaction applies when `expression` is TRUE. Allowed roles must see real
    # data, so redact when the session has NONE of the allowed roles.
    if allow_roles:
        # Redact when the session holds none of the allowed roles (redact-by-default):
        # reveal only when the role is explicitly 'TRUE'. SYS_SESSION_ROLES returns
        # 'TRUE'/'FALSE' for a role and NULL for one that does not exist. Data Redaction
        # expressions forbid NVL (ORA-28087) but allow `= / IS NULL / OR / AND`, so the
        # robust form is `(SYS_CONTEXT(..) = 'FALSE' OR SYS_CONTEXT(..) IS NULL)`. (Both
        # facts, the NVL ban and that a bare `IS NULL` test never redacts an ungranted
        # role, were caught in live verification.) Inner quotes are doubled for the
        # PL/SQL string literal.
        conds = " AND ".join(
            f"(SYS_CONTEXT(''SYS_SESSION_ROLES'', ''{r}'') = ''FALSE'' "
            f"OR SYS_CONTEXT(''SYS_SESSION_ROLES'', ''{r}'') IS NULL)"
            for r in allow_roles
        )
        expression = conds
    else:
        expression = "1=1"  # redact for everyone
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.INFO,
            code="NO_ALLOW_RULE",
            message="No allow rule; Data Redaction applies to all sessions.",
        ))

    # FULL redaction cannot carry an arbitrary replacement; REGEXP can. Use REGEXP
    # so the Tessera replacement literal is honored.
    diagnostics.append(Diagnostic(
        severity=DiagnosticSeverity.INFO,
        code="REDACT_VIA_REGEXP",
        message=(
            "Redact lowered to DBMS_REDACT.REGEXP (not FULL) so the replacement literal "
            f"{replacement!r} is honored; FULL uses type-default masking values."
        ),
        location="defaultBranch.transformation",
    ))

    pname = _redact_policy_name(policy_id)
    stmt = (
        f"BEGIN\n"
        f"  DBMS_REDACT.ADD_POLICY(\n"
        f"    object_schema        => '{schema}',\n"
        f"    object_name          => '{obj}',\n"
        f"    column_name          => '{column}',\n"
        f"    policy_name          => '{pname}',\n"
        f"    function_type        => DBMS_REDACT.REGEXP,\n"
        f"    regexp_pattern       => '(.*)',\n"
        f"    regexp_replace_string => '{replacement}',\n"
        f"    regexp_position      => 1,\n"
        # occurrence => 1 (first match only): the greedy `(.*)` matches the whole
        # string once; `=> 0` (all) also matches the trailing empty position, which
        # doubled the replacement (live-verified).
        f"    regexp_occurrence    => 1,\n"
        f"    expression           => '{expression}'\n"
        f"  );\nEND;\n/"
    )
    return EmissionResult(
        policy_id=policy_id,
        target_artifacts=[f"{schema}.{obj}.{column}"],
        statements=[stmt],
        diagnostics=diagnostics,
    )


# ---------------------------------------------------------------------------
# Access grants: GRANT
# ---------------------------------------------------------------------------


def _emit_access_grant(policy: dict[str, Any], config: AdapterConfig) -> EmissionResult:
    diagnostics: list[Diagnostic] = []
    policy_id = policy.get("@id")
    applies_to = policy.get("appliesTo") or {}
    action = policy.get("action") or "Read"
    privilege = _ACTION_TO_PRIVILEGE.get(action)
    if privilege is None:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="UNMAPPED_ACTION",
            message=f"action {action!r} has no Oracle privilege mapping; using SELECT.",
            location="action",
        ))
        privilege = "SELECT"

    obj_ref = applies_to.get("resource") or ""
    oracle_obj = _oracle_qualified(obj_ref, config)

    statements: list[str] = []
    for idx, rule in enumerate(policy.get("rules") or []):
        principal = rule.get("principal") or {}
        if rule.get("effect") != "allow" or principal.get("selector") != "byIdentity":
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.INFO,
                code="GRANT_RULE_SKIPPED",
                message=f"rule {idx}: only effect=allow byIdentity grants are emitted.",
                location=f"rules[{idx}]",
            ))
            continue
        role = _oracle_role(principal.get("resource", ""), config)
        statements.append(f"GRANT {privilege} ON {oracle_obj} TO {role};")

    if not statements:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="EMPTY_POLICY_BODY",
            message="No emittable grant rules.",
        ))
    return EmissionResult(
        policy_id=policy_id,
        target_artifacts=[oracle_obj],
        statements=statements,
        diagnostics=diagnostics,
    )


# ---------------------------------------------------------------------------
# Helpers: identifiers & naming
# ---------------------------------------------------------------------------


def _strip_iri(value: str) -> str:
    if ":" in value and not value.startswith("'"):
        return value.split(":", 1)[1]
    return value


def _oracle_object(resource_iri: str, config: AdapterConfig) -> tuple[str, str]:
    """(schema, object) for a table IRI. Honors config.resource_bindings; else maps
    the last two dotted segments of the Tessera name to SCHEMA.OBJECT (uppercased).
    Oracle has no catalog tier, so a 3-part catalog.schema.table drops the catalog."""
    bound = config.bind_resource(resource_iri)
    name = bound if bound else _strip_iri(resource_iri)
    parts = name.split(".")
    if len(parts) >= 2:
        schema, obj = parts[-2], parts[-1]
    else:
        schema, obj = "TESSERA", parts[-1]
    return schema.upper(), obj.upper()


def _oracle_column(resource_iri: str, config: AdapterConfig) -> tuple[str, str, str]:
    """(schema, object, column) for a column IRI (…schema.table.column)."""
    bound = config.bind_resource(resource_iri)
    name = bound if bound else _strip_iri(resource_iri)
    parts = name.split(".")
    if len(parts) >= 3:
        return parts[-3].upper(), parts[-2].upper(), parts[-1].upper()
    if len(parts) == 2:
        return "TESSERA", parts[0].upper(), parts[1].upper()
    return "TESSERA", "UNKNOWN", parts[-1].upper()


def _oracle_table(dotted: str, config: AdapterConfig) -> str:
    """SCHEMA.OBJECT for an ACL table name used inside a predicate."""
    bound = config.bind_resource(f"table:{dotted}")
    name = bound if bound else dotted
    parts = name.split(".")
    if len(parts) >= 2:
        return f"{parts[-2].upper()}.{parts[-1].upper()}"
    return name.upper()


def _oracle_qualified(resource_iri: str, config: AdapterConfig) -> str:
    """SCHEMA.OBJECT for a GRANT target (table: or function:)."""
    schema, obj = _oracle_object(resource_iri, config)
    return f"{schema}.{obj}"


def _oracle_role(principal_ref: str, config: AdapterConfig) -> str:
    """Map a PrincipalRef to an Oracle role name. Honors config.identity_bindings;
    else uppercases and replaces spaces/hyphens with underscores (Oracle role names
    are unquoted identifiers, so 'account users' must be bound or sanitized)."""
    bound = config.bind_principal(principal_ref)
    if bound:
        return bound
    bare = _strip_iri(principal_ref)
    return bare.upper().replace(" ", "_").replace("-", "_")


def _slug(policy_id: Any) -> str:
    return (str(policy_id) or "policy").split(":")[-1].replace("-", "_").upper()


def _vpd_function_name(policy_id: Any) -> str:
    return f"TESSERA_{_slug(policy_id)}_VPD"


def _vpd_policy_name(policy_id: Any) -> str:
    return f"TESSERA_{_slug(policy_id)}"


def _redact_policy_name(policy_id: Any) -> str:
    return f"TESSERA_{_slug(policy_id)}_REDACT"
