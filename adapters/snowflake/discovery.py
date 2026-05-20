"""Snowflake adapter — discovery and extraction.

Discovery inventories deployed policies on a target schema. Extraction lifts
one of those discovered artifacts back into Tessera IR.

The implementation handles the policy shapes the project's worked exercises
have actually deployed:

    1. **Role-based row access policy.** Multi-branch CASE-like predicate
       gating on `IS_ROLE_IN_SESSION(...)` with optional `col IN (...)`
       filters per branch. Lifts to a `RowVisibilityConstraint` with
       byIdentity principals; one rule per role.

    2. **byDataset / mapping-table row access policy.** Body of the form
       `EXISTS (SELECT 1 FROM <map> m JOIN <acl> p ON m.<col> = p.<col>
       WHERE m.<user_col> = CURRENT_USER() AND p.<resource_col> = <param>)`.
       Lifts to a `RowVisibilityConstraint` with byDataset principal selector
       and exists-in-dataset condition. (The IR shape the exercise validated.)

    3. **Role-based column mask.** `CASE WHEN IS_ROLE_IN_SESSION(...) THEN col
       ELSE 'literal' END`. Lifts to a `ColumnVisibilityConstraint` with one
       byIdentity rule (effect: allow) and a defaultBranch Redact transformation.

The extractor is intentionally pattern-driven over the policy body text. Real
migration tooling would parse a Snowflake AST; for the exercise's purpose the
pattern matchers are sufficient for the deployed shapes and produce diagnostics
when they can't recognize a body.
"""

from __future__ import annotations

import re
from typing import Any

from adapters.contract.types import (
    AdapterConfig,
    Diagnostic,
    DiagnosticSeverity,
    DiscoveryResult,
    ExtractionResult,
)


# ----------------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------------


def discover_schema(cursor, database: str, schema: str) -> DiscoveryResult:
    """Inventory row-access policies, masking policies, and explicit grants
    on a Snowflake schema.

    Caller passes an open Snowflake connector cursor and the fully-qualified
    schema (database + schema name). Returns a DiscoveryResult whose
    `artifacts` list carries one entry per policy or grant, each enriched with
    its body / attachments / metadata.
    """
    diagnostics: list[Diagnostic] = []
    artifacts: list[dict[str, Any]] = []

    artifacts.extend(_inventory_policies(
        cursor, database, schema,
        list_sql=f"SHOW ROW ACCESS POLICIES IN SCHEMA {database}.{schema}",
        describe_kind="ROW ACCESS POLICY",
        artifact_kind="row_access_policy",
        diagnostics=diagnostics,
    ))
    artifacts.extend(_inventory_policies(
        cursor, database, schema,
        list_sql=f"SHOW MASKING POLICIES IN SCHEMA {database}.{schema}",
        describe_kind="MASKING POLICY",
        artifact_kind="masking_policy",
        diagnostics=diagnostics,
    ))

    # Schema-level grants.
    artifacts.extend(_discover_snowflake_grants(
        cursor, "SCHEMA", f"{database}.{schema}", diagnostics,
    ))

    # Per-table grants.
    try:
        cursor.execute(f"SHOW TABLES IN SCHEMA {database}.{schema}")
        rows = cursor.fetchall()
        desc = [d.name for d in cursor.description]
        for row in rows:
            meta = dict(zip(desc, row))
            tname = meta.get("name")
            if tname:
                fq = f"{database}.{schema}.{tname}"
                artifacts.extend(_discover_snowflake_grants(
                    cursor, "TABLE", fq, diagnostics,
                ))
    except Exception as e:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="SHOW_TABLES_FAILED",
            message=f"could not enumerate tables in {database}.{schema}: {str(e).splitlines()[0][:200]}",
        ))

    # Per-function grants.
    try:
        cursor.execute(f"SHOW USER FUNCTIONS IN SCHEMA {database}.{schema}")
        rows = cursor.fetchall()
        desc = [d.name for d in cursor.description]
        for row in rows:
            meta = dict(zip(desc, row))
            fname = meta.get("name")
            args = meta.get("arguments") or ""
            # arguments is typically "NAME(SIG) RETURN RET_TYPE" — extract the
            # (SIG) portion (between the first '(' and its matching ')').
            sig = ""
            paren_open = args.find("(")
            paren_close = args.find(")")
            if paren_open != -1 and paren_close > paren_open:
                sig = args[paren_open:paren_close + 1]
            if fname:
                fq = f"{database}.{schema}.{fname}{sig}"
                artifacts.extend(_discover_snowflake_grants(
                    cursor, "FUNCTION", fq, diagnostics,
                ))
    except Exception as e:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.INFO,
            code="SHOW_FUNCTIONS_FAILED",
            message=f"could not enumerate functions in {database}.{schema}: {str(e).splitlines()[0][:200]}",
        ))

    return DiscoveryResult(artifacts=artifacts, diagnostics=diagnostics)


# Snowflake-side filtering parallel to UC: skip ownership and implicit grants.
_SNOWFLAKE_PRIVILEGES_SKIP = {"OWNERSHIP", "ALL", "ALL PRIVILEGES"}


def _discover_snowflake_grants(
    cursor, object_kind: str, fq_object: str,
    diagnostics: list[Diagnostic],
) -> list[dict[str, Any]]:
    """Walk SHOW GRANTS ON <kind> <object>; produce one artifact per explicit grant."""
    out: list[dict[str, Any]] = []
    try:
        cursor.execute(f"SHOW GRANTS ON {object_kind} {fq_object}")
        rows = cursor.fetchall()
        desc = [d.name for d in cursor.description]
    except Exception as e:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.INFO,
            code="SHOW_GRANTS_FAILED",
            message=f"could not SHOW GRANTS ON {object_kind} {fq_object}: {str(e).splitlines()[0][:160]}",
        ))
        return out

    # Snowflake SHOW GRANTS columns include: created_on, privilege, granted_on,
    # name (the object), granted_to, grantee_name, grant_option, granted_by.
    for row in rows:
        meta = dict(zip(desc, row))
        privilege = (meta.get("privilege") or "").strip().upper()
        granted_on = (meta.get("granted_on") or "").strip().upper()
        granted_to = (meta.get("granted_to") or "").strip().upper()
        grantee = (meta.get("grantee_name") or "").strip()
        if not (privilege and grantee):
            continue
        if privilege in _SNOWFLAKE_PRIVILEGES_SKIP:
            continue
        out.append({
            "kind": "access_grant",
            "fq_name": f"{object_kind.lower()}:{fq_object}::{privilege}::{grantee}",
            "name": f"{grantee} {privilege} {object_kind} {fq_object}",
            "principal": grantee,
            "grantee_type": granted_to,    # ROLE / USER / etc.
            "privilege": privilege,
            "object_kind": object_kind,
            "object_name": fq_object,
            "source_kind": granted_on,
            "source_object": meta.get("name", ""),
            "attachments": [{
                "REF_ENTITY_NAME": fq_object,
                "REF_OBJECT_KIND": object_kind,
            }],
        })
    return out


def _inventory_policies(
    cursor, database: str, schema: str, *,
    list_sql: str, describe_kind: str, artifact_kind: str,
    diagnostics: list[Diagnostic],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cursor.execute(list_sql)
    rows = cursor.fetchall()
    desc = [d.name for d in cursor.description]
    for row in rows:
        meta = dict(zip(desc, row))
        name = meta["name"]
        fq = f"{database}.{schema}.{name}"

        # Body and signature
        cursor.execute(f"DESCRIBE {describe_kind} {fq}")
        ddesc = [d.name for d in cursor.description]
        body_meta: dict[str, Any] = {}
        for rr in cursor.fetchall():
            body_meta = dict(zip(ddesc, rr))
            break

        # Attachments
        attachments: list[dict[str, Any]] = []
        try:
            cursor.execute(
                "SELECT * FROM TABLE("
                f"  {database}.INFORMATION_SCHEMA.POLICY_REFERENCES("
                f"    POLICY_NAME => '{fq}'))"
            )
            attach_desc = [d.name for d in cursor.description]
            for arow in cursor.fetchall():
                a = {k: v for k, v in zip(attach_desc, arow) if v not in (None, "")}
                attachments.append(a)
        except Exception as e:
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="POLICY_REFERENCES_QUERY_FAILED",
                message=f"could not enumerate attachments for {fq}: {str(e).splitlines()[0][:160]}",
            ))

        out.append({
            "kind": artifact_kind,
            "fq_name": fq,
            "database": database,
            "schema": schema,
            "name": name,
            "signature": body_meta.get("signature", ""),
            "return_type": body_meta.get("return_type", ""),
            "body": body_meta.get("body", ""),
            "attachments": attachments,
        })
    return out


# ----------------------------------------------------------------------------
# Extraction
# ----------------------------------------------------------------------------


def extract_artifact(artifact: dict[str, Any]) -> ExtractionResult:
    """Lift a discovered Snowflake artifact into Tessera IR.

    Recognized shapes (see module docstring). Returns ExtractionResult with the
    parsed IR dict + a confidence score (1.0 = full shape recognized; <1.0 =
    partial). Diagnostics report any pieces that couldn't be lifted cleanly.
    """
    kind = artifact.get("kind")
    if kind == "row_access_policy":
        return _extract_row_access_policy(artifact)
    if kind == "masking_policy":
        return _extract_masking_policy(artifact)
    if kind == "access_grant":
        return _extract_snowflake_access_grant(artifact)
    return ExtractionResult(
        policy=None, confidence=0.0,
        diagnostics=[Diagnostic(
            severity=DiagnosticSeverity.ERROR,
            code="UNKNOWN_ARTIFACT_KIND",
            message=f"Unrecognized artifact kind: {kind!r}.",
        )],
    )


_SNOWFLAKE_PRIVILEGE_TO_ACTION = {
    "SELECT": "Read",
    "INSERT": "Write",
    "UPDATE": "Write",
    "DELETE": "Delete",
    "TRUNCATE": "Delete",
    "USAGE": None,    # context-dependent: scaffolding for schema/db; Execute for function
    "REFERENCES": "Read",
}


def _extract_snowflake_access_grant(artifact: dict[str, Any]) -> ExtractionResult:
    """Lift a Snowflake SHOW GRANTS row into a Tessera AccessGrantConstraint policy."""
    diagnostics: list[Diagnostic] = []
    principal = artifact["principal"]
    privilege = artifact["privilege"]
    object_kind = artifact["object_kind"]
    object_name = artifact["object_name"]

    # USAGE on a function = invoke (Execute); USAGE on schema/database = scaffolding.
    if privilege == "USAGE":
        if object_kind == "FUNCTION":
            action = "Execute"
        else:
            return ExtractionResult(policy=None, confidence=0.0, diagnostics=[
                Diagnostic(
                    severity=DiagnosticSeverity.INFO,
                    code="SCAFFOLDING_GRANT_SKIPPED",
                    message=(f"USAGE on {object_kind} {object_name!r} treated as adapter "
                             "scaffolding (not policy intent); skipped."),
                )
            ])
    else:
        action = _SNOWFLAKE_PRIVILEGE_TO_ACTION.get(privilege)

    if action is None:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="UNMAPPED_PRIVILEGE",
            message=(f"Snowflake privilege {privilege!r} has no Tessera action mapping; "
                     "lifting under verbatim action name."),
        ))
        action = privilege.title()

    kind_to_prefix = {
        "TABLE": ("byIdentity", "resource", "table"),
        "VIEW":  ("byIdentity", "resource", "table"),
        "FUNCTION": ("byIdentity", "resource", "function"),
        "SCHEMA": ("byScope", "scope", "schema"),
        "DATABASE": ("byScope", "scope", "catalog"),
    }
    selector_info = kind_to_prefix.get(object_kind)
    if selector_info is None:
        return ExtractionResult(
            policy=None, confidence=0.0,
            diagnostics=[Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="UNSUPPORTED_OBJECT_KIND",
                message=f"Cannot map Snowflake object kind {object_kind!r} to a Tessera selector.",
            )],
        )
    selector, key, prefix = selector_info

    # Strip Snowflake function signature when constructing the IR resource ref —
    # the IR carries the function name; the signature is a Snowflake artifact.
    bare_object = object_name.split("(", 1)[0] if object_kind == "FUNCTION" else object_name

    applies_to = {"selector": selector, key: f"{prefix}:{bare_object}"}

    slug = (f"{object_kind.lower()}_{bare_object.replace('.', '_').replace(' ', '_')}_"
            f"{principal.replace(' ', '_').replace('@', '_at_').lower()}_"
            f"{action.lower()}")
    policy = {
        "@context": "https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld",
        "@type": "Policy",
        "@id": f"policy:extracted-grant-{slug}",
        "version": "1.0.0",
        "policyKind": "AccessGrantConstraint",
        "description": (f"Extracted from Snowflake grant: {principal} {privilege} on "
                        f"{object_kind} {object_name}."),
        "appliesTo": applies_to,
        "action": action,
        "rules": [{
            "principal": {"selector": "byIdentity", "resource": f"group:{principal}"},
            "effect": "allow",
        }],
        "provenance": {
            "extractedFrom": f"snowflake:grant:{object_kind}:{object_name}",
            "notes": f"Extracted by SnowflakeAdapter discover()/extract(). Raw privilege: {privilege}.",
        },
    }
    return ExtractionResult(policy=policy, confidence=0.95, diagnostics=diagnostics)


def _extract_row_access_policy(artifact: dict[str, Any]) -> ExtractionResult:
    diagnostics: list[Diagnostic] = []
    body = artifact.get("body", "") or ""
    fq = artifact["fq_name"]
    attachments = artifact.get("attachments", [])

    # The byDataset pattern: an EXISTS clause that joins a mapping table and
    # an ACL table and gates on CURRENT_USER(). The shape was deployed by
    # the snowflake-byDataset-row-visibility exercise.
    if "EXISTS" in body and "CURRENT_USER()" in body:
        return _extract_bydataset_row_access(artifact, diagnostics)

    # The byIdentity (role-based) pattern: one or more IS_ROLE_IN_SESSION(...)
    # branches OR'd together, optionally with column-IN-list constraints.
    if "IS_ROLE_IN_SESSION" in body:
        return _extract_byidentity_row_access(artifact, diagnostics)

    diagnostics.append(Diagnostic(
        severity=DiagnosticSeverity.WARNING,
        code="UNRECOGNIZED_ROW_POLICY_BODY",
        message=(
            f"Snowflake row-access policy {fq!r} did not match any known body shape "
            "(IS_ROLE_IN_SESSION branches or byDataset EXISTS join). Lift skipped."
        ),
    ))
    return ExtractionResult(policy=None, confidence=0.0, diagnostics=diagnostics)


def _extract_bydataset_row_access(
    artifact: dict[str, Any], diagnostics: list[Diagnostic],
) -> ExtractionResult:
    """Lift the byDataset EXISTS shape into Tessera IR.

    Recognized body:
        EXISTS (
            SELECT 1
            FROM <map_table> m
            JOIN <acl_table> p ON m.<map_resource_col> = p.<acl_principal_col>
            WHERE m.<map_principal_col> = CURRENT_USER()
              AND p.<acl_resource_col> = <param>
        )

    Lifts to a RowVisibilityConstraint with byDataset principal selector and an
    exists-in-dataset condition.
    """
    body = artifact["body"]
    fq = artifact["fq_name"]
    attachments = artifact.get("attachments", [])

    # Identify the protected table from attachments. Snowflake row-access policies
    # can be attached to multiple tables but for the exercise we expect one.
    if not attachments:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="NO_ATTACHMENTS",
            message=f"Row-access policy {fq!r} has no attachments; cannot determine protected table.",
        ))
        return ExtractionResult(policy=None, confidence=0.0, diagnostics=diagnostics)
    attach = attachments[0]
    protected_table = f"{attach['REF_DATABASE_NAME']}.{attach['REF_SCHEMA_NAME']}.{attach['REF_ENTITY_NAME']}"

    # Parse the FROM/JOIN/WHERE clauses. Patterns are deliberate-not-perfect;
    # they match the body the exercise deployed. A production extractor would
    # use a SQL AST parser.
    from_match = re.search(
        r"FROM\s+([A-Za-z0-9_.]+)\s+(?:AS\s+)?(\w+)", body, re.IGNORECASE,
    )
    join_match = re.search(
        r"JOIN\s+([A-Za-z0-9_.]+)\s+(?:AS\s+)?(\w+)\s+ON\s+(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)",
        body, re.IGNORECASE,
    )
    where_user_match = re.search(
        r"WHERE\s+(\w+)\.(\w+)\s*=\s*CURRENT_USER\(\)", body, re.IGNORECASE,
    )
    where_value_match = re.search(
        r"AND\s+(\w+)\.(\w+)\s*=\s*(\w+)\s*\)?\s*$", body, re.IGNORECASE | re.DOTALL,
    )

    if not (from_match and join_match and where_user_match and where_value_match):
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="BYDATASET_PATTERN_PARTIAL_MATCH",
            message=(
                "byDataset row-access body did not match the full expected pattern. "
                f"from={bool(from_match)} join={bool(join_match)} "
                f"where_user={bool(where_user_match)} where_value={bool(where_value_match)}"
            ),
        ))
        return ExtractionResult(policy=None, confidence=0.0, diagnostics=diagnostics)

    map_table = from_match.group(1)
    acl_table = join_match.group(1)
    map_principal_col = where_user_match.group(2)
    map_resource_col = join_match.group(4)  # m.<map_resource_col>
    acl_principal_col = join_match.group(6)  # p.<acl_principal_col>
    acl_resource_col = where_value_match.group(2)

    slug = (fq.rsplit(".", 1)[-1]).lower().removesuffix("_rap")
    policy = {
        "@context": "https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld",
        "@type": "Policy",
        "@id": f"policy:extracted-{slug}",
        "version": "1.0.0",
        "policyKind": "RowVisibilityConstraint",
        "description": f"Extracted from Snowflake row-access policy {fq}.",
        "appliesTo": {
            "selector": "byIdentity",
            "resource": f"table:{protected_table}",
        },
        "action": "Read",
        "defaultStrategy": "none",
        "rules": [
            {
                "principal": {
                    "selector": "byDataset",
                    "dataset": {
                        "@type": "PrincipalSetFromTable",
                        "table": map_table,
                        "principalColumn": map_principal_col,
                        "resourceColumn": map_resource_col,
                    },
                },
                "condition": {
                    "op": "exists-in-dataset",
                    "operands": [
                        {
                            "@type": "ResourceSetFromTable",
                            "table": acl_table,
                            "principalColumn": acl_principal_col,
                            "resourceColumn": acl_resource_col,
                        }
                    ],
                },
                "effect": "keep-matching-rows",
            }
        ],
        "provenance": {
            "extractedFrom": f"snowflake:{fq}",
            "notes": "Extracted by SnowflakeAdapter discover()/extract().",
        },
    }
    return ExtractionResult(policy=policy, confidence=0.95, diagnostics=diagnostics)


def _extract_byidentity_row_access(
    artifact: dict[str, Any], diagnostics: list[Diagnostic],
) -> ExtractionResult:
    """Lift an IS_ROLE_IN_SESSION-branched row-access policy to RowVisibilityConstraint.

    Recognized body pattern (per Snowflake-emitted shape):
        IS_ROLE_IN_SESSION('A')
        OR (IS_ROLE_IN_SESSION('B') AND <col> IN ('v1', 'v2'))
        OR (IS_ROLE_IN_SESSION('C') AND <col> IN (...))
    """
    body = artifact["body"]
    fq = artifact["fq_name"]
    attachments = artifact.get("attachments", [])
    if not attachments:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING, code="NO_ATTACHMENTS",
            message=f"Row-access policy {fq!r} has no attachments.",
        ))
        return ExtractionResult(policy=None, confidence=0.0, diagnostics=diagnostics)
    attach = attachments[0]
    protected_table = f"{attach['REF_DATABASE_NAME']}.{attach['REF_SCHEMA_NAME']}.{attach['REF_ENTITY_NAME']}"
    # The matched column is the policy's argument (REF_ARG_COLUMN_NAMES).
    arg_cols_raw = attach.get("REF_ARG_COLUMN_NAMES", "")
    bound_column = re.findall(r'"([^"]+)"', arg_cols_raw)
    bound_column = bound_column[0] if bound_column else None

    # Split on top-level OR to find each branch. The body comes back with
    # parentheses around the AND-bearing branches; the first branch is
    # un-parenthesized.
    branches = _split_top_level_or(body)

    rules: list[dict[str, Any]] = []
    column_qual = f"column:{protected_table}.{bound_column.lower()}" if bound_column else "column:$matched"
    for branch in branches:
        m_role = re.search(r"IS_ROLE_IN_SESSION\s*\(\s*'([^']+)'\s*\)", branch, re.IGNORECASE)
        if not m_role:
            continue
        role = m_role.group(1)
        principal = {
            "selector": "byIdentity",
            "resource": f"group:{role.lower()}",
        }
        rule: dict[str, Any] = {"principal": principal, "effect": "keep-matching-rows"}

        m_in = re.search(r"\bIN\s*\(([^)]+)\)", branch, re.IGNORECASE)
        if m_in:
            values = [v.strip().strip("'") for v in m_in.group(1).split(",")]
            rule["condition"] = {
                "op": "in",
                "operands": [column_qual],
                "values": values,
            }
        rules.append(rule)

    if not rules:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="BYIDENTITY_ROW_NO_BRANCHES",
            message=f"Could not extract any IS_ROLE_IN_SESSION branches from {fq!r}.",
        ))
        return ExtractionResult(policy=None, confidence=0.0, diagnostics=diagnostics)

    slug = (fq.rsplit(".", 1)[-1]).lower().removesuffix("_rap")
    policy = {
        "@context": "https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld",
        "@type": "Policy",
        "@id": f"policy:extracted-{slug}",
        "version": "1.0.0",
        "policyKind": "RowVisibilityConstraint",
        "description": f"Extracted from Snowflake row-access policy {fq}.",
        "appliesTo": {"selector": "byIdentity", "resource": f"table:{protected_table}"},
        "action": "Read",
        "rules": rules,
        "provenance": {
            "extractedFrom": f"snowflake:{fq}",
            "notes": "Extracted by SnowflakeAdapter discover()/extract().",
        },
    }
    # Confidence: high if every branch parsed; slight haircut for unrecognized fragments.
    confidence = 0.9 if len(rules) == len(branches) else 0.7
    return ExtractionResult(policy=policy, confidence=confidence, diagnostics=diagnostics)


def _extract_masking_policy(
    artifact: dict[str, Any],
) -> ExtractionResult:
    """Lift a CASE-WHEN-IS_ROLE_IN_SESSION masking policy to ColumnVisibilityConstraint."""
    diagnostics: list[Diagnostic] = []
    body = artifact["body"]
    fq = artifact["fq_name"]
    attachments = artifact.get("attachments", [])
    if not attachments:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING, code="NO_ATTACHMENTS",
            message=f"Masking policy {fq!r} has no attachments.",
        ))
        return ExtractionResult(policy=None, confidence=0.0, diagnostics=diagnostics)
    attach = attachments[0]
    protected_column = (
        f"{attach['REF_DATABASE_NAME']}.{attach['REF_SCHEMA_NAME']}."
        f"{attach['REF_ENTITY_NAME']}.{attach['REF_COLUMN_NAME'].lower()}"
    )

    # Recognize CASE WHEN IS_ROLE_IN_SESSION('R') THEN col ELSE 'literal' END.
    m_role = re.search(
        r"WHEN\s+IS_ROLE_IN_SESSION\s*\(\s*'([^']+)'\s*\)\s+THEN\s+(\w+)",
        body, re.IGNORECASE,
    )
    m_else = re.search(r"ELSE\s+'([^']+)'\s*END", body, re.IGNORECASE)
    if not (m_role and m_else):
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="MASKING_PATTERN_PARTIAL_MATCH",
            message=f"Masking policy {fq!r} did not match WHEN-IS_ROLE_IN_SESSION/ELSE-literal pattern.",
        ))
        return ExtractionResult(policy=None, confidence=0.5, diagnostics=diagnostics)

    role = m_role.group(1)
    replacement = m_else.group(1)
    slug = (fq.rsplit(".", 1)[-1]).lower().removesuffix("_mask")

    policy = {
        "@context": "https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld",
        "@type": "Policy",
        "@id": f"policy:extracted-{slug}",
        "version": "1.0.0",
        "policyKind": "ColumnVisibilityConstraint",
        "description": f"Extracted from Snowflake masking policy {fq}.",
        "appliesTo": {"selector": "byIdentity", "resource": f"column:{protected_column}"},
        "action": "Read",
        "defaultStrategy": "negated-complement",
        "rules": [
            {
                "principal": {"selector": "byIdentity", "resource": f"group:{role.lower()}"},
                "effect": "allow",
            }
        ],
        "defaultBranch": {
            "effect": "transform",
            "transformation": {"type": "Redact", "replacement": replacement},
        },
        "provenance": {
            "extractedFrom": f"snowflake:{fq}",
            "notes": "Extracted by SnowflakeAdapter discover()/extract().",
        },
    }
    return ExtractionResult(policy=policy, confidence=0.95, diagnostics=diagnostics)


def _split_top_level_or(body: str) -> list[str]:
    """Split a SQL body on top-level OR operators (ignoring OR inside parens)."""
    branches: list[str] = []
    depth = 0
    current: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "(":
            depth += 1
            current.append(ch); i += 1; continue
        if ch == ")":
            depth -= 1
            current.append(ch); i += 1; continue
        if depth == 0 and body[i:i + 4].upper() == " OR " and i + 4 < len(body):
            branches.append("".join(current).strip())
            current = []
            i += 4
            continue
        current.append(ch); i += 1
    branches.append("".join(current).strip())
    return branches
