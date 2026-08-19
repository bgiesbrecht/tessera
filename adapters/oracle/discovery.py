"""Oracle discovery & extraction: deployed VPD / Redaction / grants → Tessera IR.

`discover_schema` inventories the policy-bearing artifacts on an Oracle schema from
the data-dictionary views:
    * VPD policies: ALL_POLICIES (+ the policy function body from ALL_SOURCE)
    * Redaction policies: REDACTION_POLICIES / REDACTION_COLUMNS
    * Grants: DBA_TAB_PRIVS / ALL_TAB_PRIVS
Each is normalized to an artifact dict; `extract_artifact` lifts one artifact to IR.

The extractors operate on the normalized artifact dicts (not on a live cursor), so
they are unit-testable offline; `discover_schema` holds the live SQL. `oracledb` is
imported lazily by the caller/live scripts, never here.
"""

from __future__ import annotations

import re
from typing import Any

from adapters.contract.types import (
    Diagnostic,
    DiagnosticSeverity,
    DiscoveryResult,
    ExtractionResult,
)

CONTEXT_URL = "https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld"

_PRIV_TO_ACTION = {
    "SELECT": "Read",
    "UPDATE": "Write",
    "INSERT": "Write",
    "DELETE": "Delete",
    "EXECUTE": "Execute",
}

# EXISTS predicate inside a byDataset VPD function body.
_JOIN_RE = re.compile(
    r"FROM\s+([A-Za-z0-9_.]+)\s+(\w+)\s+JOIN\s+([A-Za-z0-9_.]+)\s+(\w+)\s+ON\s+"
    r"(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)",
    re.IGNORECASE,
)
_USER_RE = re.compile(r"trim\(\s*(\w+)\.(\w+)\s*\)\s*\)?\s*=\s*lower\(\s*trim\(\s*SYS_CONTEXT",
                      re.IGNORECASE)
# Role-gated branch: SYS_CONTEXT('SYS_SESSION_ROLES','<ROLE>') = 'TRUE' THEN RETURN '<pred>'
_ROLE_BRANCH_RE = re.compile(
    r"SYS_CONTEXT\(\s*'SYS_SESSION_ROLES'\s*,\s*'([^']+)'\s*\)\s*=\s*'TRUE'\s*THEN\s*"
    r"RETURN\s*'([^']*(?:''[^']*)*)'",
    re.IGNORECASE,
)


def extract_artifact(artifact: dict[str, Any]) -> ExtractionResult:
    kind = artifact.get("kind")
    if kind == "vpd_policy":
        return _extract_vpd(artifact)
    if kind == "redaction_policy":
        return _extract_redaction(artifact)
    if kind == "grant":
        return _extract_grant(artifact)
    return ExtractionResult(
        policy=None, confidence=0.0,
        diagnostics=[Diagnostic(
            severity=DiagnosticSeverity.ERROR,
            code="UNKNOWN_ARTIFACT_KIND",
            message=f"oracle extract expects vpd_policy / redaction_policy / grant; got {kind!r}.",
        )],
    )


def _extract_grant(artifact: dict[str, Any]) -> ExtractionResult:
    """Lift an ALL_TAB_PRIVS row → AccessGrantConstraint."""
    grantee = artifact["grantee"]
    privilege = artifact["privilege"]
    schema = artifact["owner"]
    obj = artifact["table_name"]
    action = _PRIV_TO_ACTION.get(privilege.upper())
    diagnostics: list[Diagnostic] = []
    if action is None:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="UNMAPPED_PRIVILEGE",
            message=f"Oracle privilege {privilege!r} has no Tessera action mapping.",
        ))
        action = privilege.title()
    prefix = "function" if action == "Execute" else "table"
    slug = f"{obj}_{grantee}_{action}".lower().replace(".", "_")
    policy = {
        "@context": CONTEXT_URL,
        "@type": "Policy",
        "@id": f"policy:extracted-oracle-grant-{slug}",
        "version": "1.0.0",
        "policyKind": "AccessGrantConstraint",
        "description": f"Extracted from Oracle grant: {grantee} {privilege} on {schema}.{obj}.",
        "appliesTo": {"selector": "byIdentity", "resource": f"{prefix}:{schema}.{obj}".lower()},
        "action": action,
        "rules": [{
            "principal": {"selector": "byIdentity", "resource": f"group:{grantee}"},
            "effect": "allow",
        }],
        "provenance": {
            "extractedFrom": f"oracle:grant:{schema}.{obj}",
            "notes": "Extracted by OracleAdapter discover()/extract().",
        },
    }
    return ExtractionResult(policy=policy, confidence=0.95, diagnostics=diagnostics)


def _extract_redaction(artifact: dict[str, Any]) -> ExtractionResult:
    """Lift a REDACTION_COLUMNS row → ColumnVisibilityConstraint (Redact)."""
    schema = artifact["object_owner"]
    obj = artifact["object_name"]
    column = artifact["column_name"]
    replacement = artifact.get("regexp_replace_string") or "REDACTED"
    expression = artifact.get("expression") or ""
    diagnostics: list[Diagnostic] = []

    # Recover allowed roles: any role named in the redaction expression via
    # SYS_CONTEXT('SYS_SESSION_ROLES','<ROLE>') is an allowed (real-data) role.
    allow_roles = list(dict.fromkeys(re.findall(
        r"SYS_CONTEXT\(\s*'SYS_SESSION_ROLES'\s*,\s*'([^']+)'\s*\)",
        expression, re.IGNORECASE,
    )))
    rules = [
        {"principal": {"selector": "byIdentity", "resource": f"group:{r}"}, "effect": "allow"}
        for r in allow_roles
    ]
    slug = f"{obj}_{column}".lower().replace(".", "_")
    policy = {
        "@context": CONTEXT_URL,
        "@type": "Policy",
        "@id": f"policy:extracted-oracle-redact-{slug}",
        "version": "1.0.0",
        "policyKind": "ColumnVisibilityConstraint",
        "description": f"Extracted from Oracle Data Redaction on {schema}.{obj}.{column}.",
        "appliesTo": {
            "selector": "byIdentity",
            "resource": f"column:{schema}.{obj}.{column}".lower(),
        },
        "action": "Read",
        "defaultStrategy": "negated-complement",
        "rules": rules,
        "defaultBranch": {
            "effect": "transform",
            "transformation": {"type": "Redact", "replacement": replacement},
        },
        "provenance": {
            "extractedFrom": f"oracle:redaction:{schema}.{obj}.{column}",
            "notes": "Extracted by OracleAdapter discover()/extract().",
        },
    }
    conf = 0.9 if allow_roles else 0.75
    if not allow_roles:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.INFO,
            code="NO_ALLOW_ROLE_RECOVERED",
            message="Redaction expression did not name allow-roles; extracted default-only.",
        ))
    return ExtractionResult(policy=policy, confidence=conf, diagnostics=diagnostics)


def _extract_vpd(artifact: dict[str, Any]) -> ExtractionResult:
    """Lift a VPD policy (function body in artifact['function_body']) → RowVisibilityConstraint.
    Recognizes the byDataset EXISTS shape and the role-gated byIdentity shape."""
    diagnostics: list[Diagnostic] = []
    schema = artifact["object_owner"]
    obj = artifact["object_name"]
    body = artifact.get("function_body") or ""
    resource = f"table:{schema}.{obj}".lower()

    join = _JOIN_RE.search(body)
    in_m = re.search(r"(\w+)\s+IN\s*\(\s*SELECT\s+\w+\.(\w+)", body, re.IGNORECASE)
    if join and in_m:
        map_table = join.group(1)
        acl_table = join.group(3)
        m_res = join.group(6)
        p_prin = join.group(8)
        user_m = _USER_RE.search(body)
        map_prin = user_m.group(2) if user_m else "username"
        # The IN form: `<protected_col> IN (SELECT p.<acl_res> FROM ...)`. Both are
        # the same column under the aligned convention (issue #13); take the ACL one.
        acl_res = in_m.group(2)
        policy = {
            "@context": CONTEXT_URL, "@type": "Policy",
            "@id": f"policy:extracted-oracle-vpd-{obj}".lower(),
            "version": "1.0.0", "policyKind": "RowVisibilityConstraint",
            "description": f"Extracted from Oracle VPD policy on {schema}.{obj}.",
            "appliesTo": {"selector": "byIdentity", "resource": resource},
            "action": "Read", "defaultStrategy": "none",
            "rules": [{
                "principal": {"selector": "byDataset", "dataset": {
                    "@type": "PrincipalSetFromTable", "table": map_table.lower(),
                    "principalColumn": map_prin, "resourceColumn": m_res,
                }},
                "condition": {"op": "exists-in-dataset", "operands": [{
                    "@type": "ResourceSetFromTable", "table": acl_table.lower(),
                    "principalColumn": p_prin, "resourceColumn": acl_res,
                }]},
                "effect": "keep-matching-rows",
            }],
            "provenance": {"extractedFrom": f"oracle:vpd:{schema}.{obj}",
                           "notes": "Extracted by OracleAdapter (byDataset VPD)."},
        }
        return ExtractionResult(policy=policy, confidence=0.9, diagnostics=diagnostics)

    branches = _ROLE_BRANCH_RE.findall(body)
    if branches:
        rules = []
        for role, pred in branches:
            pred = pred.replace("''", "'")  # un-double the PL/SQL literal quotes
            rule: dict[str, Any] = {
                "principal": {"selector": "byIdentity", "resource": f"group:{role}"},
                "effect": "keep-matching-rows",
            }
            in_m = re.search(r"(\w+)\s+IN\s*\(([^)]*)\)", pred, re.IGNORECASE)
            if in_m:
                col = in_m.group(1)
                values = [v.strip().strip("'") for v in in_m.group(2).split(",")]
                rule["condition"] = {
                    "op": "in",
                    "operands": [f"column:{schema}.{obj}.{col}".lower()],
                    "values": values,
                }
            rules.append(rule)
        policy = {
            "@context": CONTEXT_URL, "@type": "Policy",
            "@id": f"policy:extracted-oracle-vpd-{obj}".lower(),
            "version": "1.0.0", "policyKind": "RowVisibilityConstraint",
            "description": f"Extracted from Oracle VPD policy on {schema}.{obj}.",
            "appliesTo": {"selector": "byIdentity", "resource": resource},
            "action": "Read", "defaultStrategy": "none",
            "rules": rules,
            "provenance": {"extractedFrom": f"oracle:vpd:{schema}.{obj}",
                           "notes": "Extracted by OracleAdapter (byIdentity VPD)."},
        }
        return ExtractionResult(policy=policy, confidence=0.85, diagnostics=diagnostics)

    diagnostics.append(Diagnostic(
        severity=DiagnosticSeverity.WARNING,
        code="VPD_PATTERN_UNRECOGNIZED",
        message=f"VPD function body on {schema}.{obj} matched neither byDataset nor role-gated shape.",
    ))
    return ExtractionResult(policy=None, confidence=0.0, diagnostics=diagnostics)


def discover_schema(cursor: Any, schema: str) -> DiscoveryResult:
    """Inventory VPD policies, Data Redaction policies, and grants for an Oracle
    schema (uppercased owner). Requires a live oracledb cursor."""
    diagnostics: list[Diagnostic] = []
    artifacts: list[dict[str, Any]] = []
    owner = schema.upper()

    def _q(sql: str, code: str):
        try:
            cursor.execute(sql)
            return cursor.fetchall()
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.WARNING, code=code,
                message=f"query failed: {exc}",
            ))
            return []

    # VPD policies + their function bodies.
    for obj_owner, obj_name, pol, pf_owner, pf in _q(
        "SELECT OBJECT_OWNER, OBJECT_NAME, POLICY_NAME, PACKAGE, FUNCTION "
        f"FROM ALL_POLICIES WHERE OBJECT_OWNER = '{owner}'",
        "DISCOVER_VPD_FAILED",
    ):
        body_rows = _q(
            f"SELECT TEXT FROM ALL_SOURCE WHERE OWNER = '{pf_owner or owner}' "
            f"AND NAME = '{pf}' ORDER BY LINE",
            "DISCOVER_VPD_BODY_FAILED",
        )
        body = "".join(r[0] for r in body_rows)
        artifacts.append({
            "kind": "vpd_policy", "object_owner": obj_owner, "object_name": obj_name,
            "policy_name": pol, "function_body": body,
        })

    # Data Redaction columns.
    for o_owner, o_name, col, pol, rep, expr in _q(
        "SELECT c.OBJECT_OWNER, c.OBJECT_NAME, c.COLUMN_NAME, c.POLICY_NAME, "
        "c.REGEXP_REPLACE_STRING, p.EXPRESSION "
        "FROM REDACTION_COLUMNS c JOIN REDACTION_POLICIES p "
        "ON c.OBJECT_OWNER = p.OBJECT_OWNER AND c.OBJECT_NAME = p.OBJECT_NAME "
        f"AND c.POLICY_NAME = p.POLICY_NAME WHERE c.OBJECT_OWNER = '{owner}'",
        "DISCOVER_REDACTION_FAILED",
    ):
        artifacts.append({
            "kind": "redaction_policy", "object_owner": o_owner, "object_name": o_name,
            "column_name": col, "policy_name": pol, "regexp_replace_string": rep,
            "expression": expr,
        })

    # Object grants.
    for grantee, owner_, tab, priv in _q(
        "SELECT GRANTEE, OWNER, TABLE_NAME, PRIVILEGE FROM ALL_TAB_PRIVS "
        f"WHERE OWNER = '{owner}'",
        "DISCOVER_GRANTS_FAILED",
    ):
        artifacts.append({
            "kind": "grant", "grantee": grantee, "owner": owner_,
            "table_name": tab, "privilege": priv,
        })

    if not artifacts and not diagnostics:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.INFO, code="NO_ARTIFACTS_FOUND",
            message=f"No VPD/redaction/grant artifacts found for schema {owner}.",
        ))
    return DiscoveryResult(artifacts=artifacts, diagnostics=diagnostics)
