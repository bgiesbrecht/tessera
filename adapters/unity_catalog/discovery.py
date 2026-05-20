"""Unity Catalog adapter — discovery and extraction.

Parallel to `adapters/snowflake/discovery.py`. Inventory row-filter UDFs and
column-mask UDFs attached to tables in a target schema; lift them back into
Tessera IR.

Recognized Databricks UC body shapes (matching what the UC adapter emits):

    1. **byDataset row filter** — `EXISTS (SELECT 1 FROM <map> m JOIN <acl> p
       ON ... WHERE m.<user_col> = current_user() AND p.<resource_col> = <param>)`.
       Lifts to `RowVisibilityConstraint` with `byDataset` principal selector
       and `exists-in-dataset` condition.

    2. **byIdentity multi-rule row filter** — OR-joined branches:
       `is_account_group_member('A') OR (is_account_group_member('B') AND col IN (...))`.
       Lifts to `RowVisibilityConstraint` with multiple `byIdentity` rules.

    3. **byIdentity column mask** — `CASE WHEN is_account_group_member('A')
       THEN <col> ELSE 'literal' END`. Lifts to `ColumnVisibilityConstraint`
       with one allow-rule and a Redact defaultBranch.

ABAC byScope shapes (those that emit `CREATE POLICY ... ON CATALOG`) are not
yet covered here — extraction for those would query the catalog's policy
metadata surface rather than per-table `DESCRIBE` output, which is a separate
implementation path.
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


def discover_schema(run_sql, catalog: str, schema: str) -> DiscoveryResult:
    """Inventory row filters and column masks on every table in the schema.

    `run_sql(sql) -> list[list]` executes a Databricks SQL statement and
    returns its result rows. The caller wires it to a WorkspaceClient +
    warehouse; this module stays SDK-agnostic.
    """
    diagnostics: list[Diagnostic] = []
    artifacts: list[dict[str, Any]] = []

    try:
        tables = run_sql(f"SHOW TABLES IN {catalog}.{schema}") or []
    except Exception as e:
        return DiscoveryResult(
            artifacts=[],
            diagnostics=[Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="SHOW_TABLES_FAILED",
                message=f"Could not list tables in {catalog}.{schema}: {str(e).splitlines()[0][:200]}",
            )],
        )

    for row in tables:
        # SHOW TABLES returns (database, tableName, isTemporary).
        table_name = row[1] if len(row) >= 2 else None
        if not table_name:
            continue
        fq_table = f"{catalog}.{schema}.{table_name}"
        try:
            described = run_sql(f"DESCRIBE TABLE EXTENDED {fq_table}") or []
        except Exception as e:
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="DESCRIBE_TABLE_FAILED",
                message=f"could not describe {fq_table}: {str(e).splitlines()[0][:200]}",
            ))
            continue
        for art in _parse_described_table(described, fq_table, run_sql, diagnostics):
            artifacts.append(art)
        # Walk SHOW GRANTS on the table.
        for art in _discover_grants(run_sql, "TABLE", fq_table, diagnostics):
            artifacts.append(art)

    # Walk SHOW GRANTS on the schema itself.
    for art in _discover_grants(run_sql, "SCHEMA", f"{catalog}.{schema}", diagnostics):
        artifacts.append(art)

    # Walk functions via INFORMATION_SCHEMA.ROUTINES + SHOW GRANTS on each.
    # SHOW USER FUNCTIONS doesn't accept a fully-qualified IN clause without
    # the current catalog being set; the API doesn't carry session state, so
    # information_schema is the reliable surface.
    try:
        functions = run_sql(
            f"SELECT routine_name FROM {catalog}.information_schema.routines "
            f"WHERE routine_schema = '{schema}'"
        ) or []
        for frow in functions:
            fn = frow[0] if frow else None
            if not fn:
                continue
            fq_fn = f"{catalog}.{schema}.{fn}"
            for art in _discover_grants(run_sql, "FUNCTION", fq_fn, diagnostics):
                artifacts.append(art)
    except Exception as e:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="LIST_FUNCTIONS_FAILED",
            message=f"could not enumerate functions in {catalog}.{schema}: {str(e).splitlines()[0][:200]}",
        ))

    return DiscoveryResult(artifacts=artifacts, diagnostics=diagnostics)


# Privileges to skip during grant discovery — platform-mechanism / ownership /
# implicit grants that aren't policy intent.
_GRANT_PRIVILEGES_SKIP = {"OWN", "ALL PRIVILEGES", "ALL_PRIVILEGES", "MANAGE", "APPLY_TAG"}
# Pseudo-principals that are platform built-ins (kept for visibility but
# extraction marks them so the operator can decide).
_GRANT_PSEUDO_PRINCIPALS = {"account users", "users"}


def _discover_grants(
    run_sql, object_kind: str, fq_object: str,
    diagnostics: list[Diagnostic],
) -> list[dict[str, Any]]:
    """Walk SHOW GRANTS ON <kind> <name>; produce one artifact per explicit grant."""
    out: list[dict[str, Any]] = []
    try:
        rows = run_sql(f"SHOW GRANTS ON {object_kind} {fq_object}") or []
    except Exception as e:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.INFO,
            code="SHOW_GRANTS_FAILED",
            message=f"could not SHOW GRANTS ON {object_kind} {fq_object}: {str(e).splitlines()[0][:160]}",
        ))
        return out
    # Databricks SHOW GRANTS returns rows like [principal, privilege, object_type, object].
    # Sometimes the object_type/object are inherited-source values (e.g., row's object_type =
    # 'SCHEMA' on a table grant means the grant was inherited from the parent schema). We
    # surface those but mark them in the artifact so the extractor can decide.
    for row in rows:
        if not row or len(row) < 4:
            continue
        principal = (row[0] or "").strip()
        privilege = (row[1] or "").strip().upper()
        source_kind = (row[2] or "").strip().upper()
        source_object = (row[3] or "").strip()
        if not (principal and privilege):
            continue
        if privilege in _GRANT_PRIVILEGES_SKIP:
            continue
        out.append({
            "kind": "access_grant",
            "fq_name": f"{object_kind.lower()}:{fq_object}::{privilege}::{principal}",
            "name": f"{principal} {privilege} {object_kind} {fq_object}",
            "principal": principal,
            "privilege": privilege,
            "object_kind": object_kind,
            "object_name": fq_object,
            "source_kind": source_kind,
            "source_object": source_object,
            "attachments": [{
                "REF_ENTITY_NAME": fq_object,
                "REF_OBJECT_KIND": object_kind,
            }],
        })
    return out


def _parse_described_table(
    described: list[list[Any]], fq_table: str, run_sql,
    diagnostics: list[Diagnostic],
) -> list[dict[str, Any]]:
    """Walk DESCRIBE TABLE EXTENDED rows; collect row filter + column mask artifacts."""
    out: list[dict[str, Any]] = []
    in_column_masks = False
    for row in described:
        if not row or len(row) < 2:
            continue
        col0 = row[0] if row[0] is not None else ""
        col1 = row[1] if row[1] is not None else ""
        if col0 == "Row Filter":
            # Format: `<schema>`.`<fn>` ON (col)  (the schema part has multiple backtick segments)
            m = re.search(r"`([^`]+)`\.`([^`]+)`\.`([^`]+)`\s+ON\s+\(([^)]+)\)", col1)
            if m:
                fn_fq = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
                bound_col = m.group(4).strip()
                body, fn_diags = _fetch_function_body(run_sql, fn_fq)
                diagnostics.extend(fn_diags)
                out.append({
                    "kind": "row_filter",
                    "fq_name": fn_fq,
                    "name": m.group(3),
                    "body": body,
                    "attachments": [{
                        "REF_ENTITY_NAME": fq_table,
                        "REF_COLUMN_NAME": bound_col,
                    }],
                })
        elif col0 == "# Column Masks":
            in_column_masks = True
        elif in_column_masks:
            if col0 and col1 and col1.startswith("`"):
                m = re.search(r"`([^`]+)`\.`([^`]+)`\.`([^`]+)`", col1)
                if m:
                    fn_fq = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
                    body, fn_diags = _fetch_function_body(run_sql, fn_fq)
                    diagnostics.extend(fn_diags)
                    out.append({
                        "kind": "column_mask",
                        "fq_name": fn_fq,
                        "name": m.group(3),
                        "body": body,
                        "attachments": [{
                            "REF_ENTITY_NAME": fq_table,
                            "REF_COLUMN_NAME": col0,
                        }],
                    })
            elif col0 == "":
                in_column_masks = False
    return out


def _fetch_function_body(run_sql, fn_fq: str) -> tuple[str, list[Diagnostic]]:
    """Return the function body as a string + diagnostics if anything went wrong."""
    diagnostics: list[Diagnostic] = []
    try:
        rows = run_sql(f"DESCRIBE FUNCTION EXTENDED {fn_fq}") or []
    except Exception as e:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="DESCRIBE_FUNCTION_FAILED",
            message=f"could not describe {fn_fq}: {str(e).splitlines()[0][:200]}",
        ))
        return "", diagnostics
    body_lines: list[str] = []
    capturing = False
    for row in rows:
        if not row:
            continue
        text = row[0] if row[0] is not None else ""
        if text.startswith("Body:"):
            capturing = True
            body_lines.append(text[len("Body:"):].strip())
            continue
        if capturing:
            if text.startswith("Comment:") or text.startswith("Owner:"):
                break
            body_lines.append(text)
    return "\n".join(body_lines).strip(), diagnostics


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def extract_artifact(artifact: dict[str, Any]) -> ExtractionResult:
    """Lift a discovered UC artifact into Tessera IR."""
    kind = artifact.get("kind")
    if kind == "row_filter":
        return _extract_row_filter(artifact)
    if kind == "column_mask":
        return _extract_column_mask(artifact)
    if kind == "access_grant":
        return _extract_access_grant(artifact)
    return ExtractionResult(
        policy=None, confidence=0.0,
        diagnostics=[Diagnostic(
            severity=DiagnosticSeverity.ERROR,
            code="UNKNOWN_ARTIFACT_KIND",
            message=f"Unrecognized artifact kind: {kind!r}.",
        )],
    )


# Inverse of the emission mapping. Some Databricks privileges fan out to more
# than one IR action; the extractor picks the canonical Tessera action and
# records the original via provenance.
_DATABRICKS_PRIVILEGE_TO_ACTION = {
    "SELECT": "Read",
    "MODIFY": "Write",
    "EXECUTE": "Execute",
    "INSERT": "Write",
    "UPDATE": "Write",
    "DELETE": "Delete",
    "USE SCHEMA": None,    # Adapter scaffolding; not a policy-intent action.
    "USE CATALOG": None,
    "USAGE": None,
    "CREATE": "Write",
    "CREATE TABLE": "Write",
    "CREATE FUNCTION": "Write",
}


def _extract_access_grant(artifact: dict[str, Any]) -> ExtractionResult:
    """Lift a single SHOW GRANTS row into a Tessera AccessGrantConstraint policy.

    Filters:
        * USE SCHEMA / USE CATALOG / USAGE → skipped (scaffolding, not policy intent).
        * inherited grants (source_kind != object_kind) → skipped; the parent's
          grant is its own discovered artifact and will produce its own IR.
        * pseudo-principals 'users' / 'account users' → lifted with a note.
    """
    diagnostics: list[Diagnostic] = []
    principal = artifact["principal"]
    privilege = artifact["privilege"]
    object_kind = artifact["object_kind"]
    object_name = artifact["object_name"]
    source_kind = artifact.get("source_kind") or object_kind
    source_object = artifact.get("source_object") or object_name

    # Skip inherited grants — the source object's grant will produce its own
    # IR. This avoids N copies of the same logical schema-level grant showing
    # up once per child table.
    if source_kind and source_kind.upper() != object_kind.upper():
        return ExtractionResult(policy=None, confidence=0.0, diagnostics=[
            Diagnostic(
                severity=DiagnosticSeverity.INFO,
                code="INHERITED_GRANT_SKIPPED",
                message=(f"Grant {principal!r} {privilege!r} on {object_kind} {object_name!r} "
                         f"is inherited from {source_kind} {source_object!r}; skipping "
                         "(the inherited-from object produces its own IR)."),
            )
        ])

    action = _DATABRICKS_PRIVILEGE_TO_ACTION.get(privilege)
    if action is None:
        if privilege in ("USE SCHEMA", "USE CATALOG", "USAGE"):
            return ExtractionResult(policy=None, confidence=0.0, diagnostics=[
                Diagnostic(
                    severity=DiagnosticSeverity.INFO,
                    code="SCAFFOLDING_GRANT_SKIPPED",
                    message=(f"{privilege} grant on {object_kind} {object_name!r} treated as "
                             "adapter scaffolding (not policy intent); skipped."),
                )
            ])
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="UNMAPPED_PRIVILEGE",
            message=(f"Databricks privilege {privilege!r} has no Tessera action mapping; "
                     "lifting under verbatim action name."),
        ))
        action = privilege.title()

    if principal.lower() in _GRANT_PSEUDO_PRINCIPALS:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.INFO,
            code="PSEUDO_PRINCIPAL",
            message=(f"Grantee {principal!r} is a Databricks pseudo-principal "
                     "(workspace-wide). Lifted; operator decides whether to "
                     "preserve in the corpus."),
        ))

    # Resource IRI shape depends on object kind.
    kind_to_prefix = {
        "TABLE": ("byIdentity", "resource", "table"),
        "VIEW":  ("byIdentity", "resource", "table"),
        "FUNCTION": ("byIdentity", "resource", "function"),
        "SCHEMA": ("byScope", "scope", "schema"),
        "CATALOG": ("byScope", "scope", "catalog"),
    }
    selector_info = kind_to_prefix.get(object_kind)
    if selector_info is None:
        return ExtractionResult(
            policy=None, confidence=0.0,
            diagnostics=[Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="UNSUPPORTED_OBJECT_KIND",
                message=f"Cannot map object kind {object_kind!r} to a Tessera selector.",
            )],
        )
    selector, key, prefix = selector_info
    applies_to = {"selector": selector, key: f"{prefix}:{object_name}"}

    slug = (f"{object_kind.lower()}_{object_name.replace('.', '_').replace(' ', '_')}_"
            f"{principal.replace(' ', '_').replace('@', '_at_').lower()}_"
            f"{action.lower()}")
    policy = {
        "@context": "https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld",
        "@type": "Policy",
        "@id": f"policy:extracted-grant-{slug}",
        "version": "1.0.0",
        "policyKind": "AccessGrantConstraint",
        "description": (f"Extracted from Databricks grant: {principal} {privilege} on "
                        f"{object_kind} {object_name}."),
        "appliesTo": applies_to,
        "action": action,
        "rules": [{
            "principal": {"selector": "byIdentity", "resource": f"group:{principal}"},
            "effect": "allow",
        }],
        "provenance": {
            "extractedFrom": f"unity-catalog:grant:{object_kind}:{object_name}",
            "notes": f"Extracted by UnityCatalogAdapter discover()/extract(). Raw privilege: {privilege}.",
        },
    }
    return ExtractionResult(policy=policy, confidence=0.95, diagnostics=diagnostics)


def _extract_row_filter(artifact: dict[str, Any]) -> ExtractionResult:
    body = artifact.get("body", "") or ""
    body_norm = re.sub(r"^\s*RETURN\s+", "", body, flags=re.IGNORECASE).rstrip(";").strip()
    if "EXISTS" in body_norm.upper() and "current_user()" in body_norm:
        return _extract_bydataset_row_filter(artifact, body_norm)
    if "is_account_group_member" in body_norm:
        return _extract_byidentity_row_filter(artifact, body_norm)
    return ExtractionResult(
        policy=None, confidence=0.0,
        diagnostics=[Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="UNRECOGNIZED_ROW_FILTER_BODY",
            message=f"Row filter {artifact['fq_name']!r} did not match any known body shape.",
        )],
    )


def _extract_bydataset_row_filter(
    artifact: dict[str, Any], body: str,
) -> ExtractionResult:
    diagnostics: list[Diagnostic] = []
    attach = artifact["attachments"][0]
    protected_table = attach["REF_ENTITY_NAME"]
    fq = artifact["fq_name"]

    from_match = re.search(r"FROM\s+([A-Za-z0-9_.]+)\s+(?:AS\s+)?(\w+)", body, re.IGNORECASE)
    join_match = re.search(
        r"JOIN\s+([A-Za-z0-9_.]+)\s+(?:AS\s+)?(\w+)\s+ON\s+(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)",
        body, re.IGNORECASE,
    )
    where_user_match = re.search(
        r"WHERE\s+(\w+)\.(\w+)\s*=\s*current_user\(\)", body, re.IGNORECASE,
    )
    where_value_match = re.search(
        r"AND\s+(\w+)\.(\w+)\s*=\s*(\w+)\s*\)?\s*$", body, re.IGNORECASE | re.DOTALL,
    )

    if not (from_match and join_match and where_user_match and where_value_match):
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="BYDATASET_PATTERN_PARTIAL_MATCH",
            message=(
                "UC byDataset row filter body did not match the full expected pattern. "
                f"from={bool(from_match)} join={bool(join_match)} "
                f"where_user={bool(where_user_match)} where_value={bool(where_value_match)}"
            ),
        ))
        return ExtractionResult(policy=None, confidence=0.0, diagnostics=diagnostics)

    map_table = from_match.group(1)
    acl_table = join_match.group(1)
    map_principal_col = where_user_match.group(2)
    map_resource_col = join_match.group(4)
    acl_principal_col = join_match.group(6)
    acl_resource_col = where_value_match.group(2)

    slug = (fq.rsplit(".", 1)[-1]).lower().removesuffix("_filter")
    policy = {
        "@context": "https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld",
        "@type": "Policy",
        "@id": f"policy:extracted-{slug}",
        "version": "1.0.0",
        "policyKind": "RowVisibilityConstraint",
        "description": f"Extracted from Databricks row filter {fq}.",
        "appliesTo": {"selector": "byIdentity", "resource": f"table:{protected_table}"},
        "action": "Read",
        "defaultStrategy": "none",
        "rules": [{
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
                "operands": [{
                    "@type": "ResourceSetFromTable",
                    "table": acl_table,
                    "principalColumn": acl_principal_col,
                    "resourceColumn": acl_resource_col,
                }],
            },
            "effect": "keep-matching-rows",
        }],
        "provenance": {
            "extractedFrom": f"unity-catalog:{fq}",
            "notes": "Extracted by UnityCatalogAdapter discover()/extract().",
        },
    }
    return ExtractionResult(policy=policy, confidence=0.95, diagnostics=diagnostics)


def _extract_byidentity_row_filter(
    artifact: dict[str, Any], body: str,
) -> ExtractionResult:
    """Multi-OR branches: is_account_group_member('A') OR (is_account_group_member('B') AND col IN (...))."""
    diagnostics: list[Diagnostic] = []
    attach = artifact["attachments"][0]
    protected_table = attach["REF_ENTITY_NAME"]
    bound_col = attach.get("REF_COLUMN_NAME", "").strip()
    fq = artifact["fq_name"]

    branches = _split_top_level_or(body)
    rules: list[dict[str, Any]] = []
    column_qual = f"column:{protected_table}.{bound_col}" if bound_col else "column:$matched"

    for branch in branches:
        m_group = re.search(r"is_account_group_member\s*\(\s*'([^']+)'\s*\)", branch, re.IGNORECASE)
        if not m_group:
            continue
        group_name = m_group.group(1)
        principal = {"selector": "byIdentity", "resource": f"group:{group_name}"}
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
            message=f"Could not extract any is_account_group_member branches from {fq!r}.",
        ))
        return ExtractionResult(policy=None, confidence=0.0, diagnostics=diagnostics)

    slug = (fq.rsplit(".", 1)[-1]).lower().removesuffix("_filter")
    policy = {
        "@context": "https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld",
        "@type": "Policy",
        "@id": f"policy:extracted-{slug}",
        "version": "1.0.0",
        "policyKind": "RowVisibilityConstraint",
        "description": f"Extracted from Databricks row filter {fq}.",
        "appliesTo": {"selector": "byIdentity", "resource": f"table:{protected_table}"},
        "action": "Read",
        "rules": rules,
        "provenance": {
            "extractedFrom": f"unity-catalog:{fq}",
            "notes": "Extracted by UnityCatalogAdapter discover()/extract().",
        },
    }
    confidence = 0.9 if len(rules) == len(branches) else 0.7
    return ExtractionResult(policy=policy, confidence=confidence, diagnostics=diagnostics)


def _extract_column_mask(artifact: dict[str, Any]) -> ExtractionResult:
    """CASE WHEN is_account_group_member(...) THEN col ELSE 'literal' END."""
    diagnostics: list[Diagnostic] = []
    body = artifact.get("body", "") or ""
    body_norm = re.sub(r"^\s*RETURN\s+", "", body, flags=re.IGNORECASE).rstrip(";").strip()
    fq = artifact["fq_name"]
    attach = artifact["attachments"][0]
    protected_table = attach["REF_ENTITY_NAME"]
    protected_column = attach.get("REF_COLUMN_NAME", "").strip()

    m_role = re.search(
        r"WHEN\s+is_account_group_member\s*\(\s*'([^']+)'\s*\)\s+THEN\s+(\w+)",
        body_norm, re.IGNORECASE,
    )
    m_else = re.search(r"ELSE\s+'([^']+)'\s*END", body_norm, re.IGNORECASE)
    if not (m_role and m_else):
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="MASKING_PATTERN_PARTIAL_MATCH",
            message=f"Column mask {fq!r} did not match WHEN-is_account_group_member/ELSE-literal pattern.",
        ))
        return ExtractionResult(policy=None, confidence=0.5, diagnostics=diagnostics)

    group_name = m_role.group(1)
    replacement = m_else.group(1)
    slug = (fq.rsplit(".", 1)[-1]).lower().removesuffix("__mask").removeprefix("tessera__")
    policy = {
        "@context": "https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld",
        "@type": "Policy",
        "@id": f"policy:extracted-{slug}",
        "version": "1.0.0",
        "policyKind": "ColumnVisibilityConstraint",
        "description": f"Extracted from Databricks column mask {fq}.",
        "appliesTo": {
            "selector": "byIdentity",
            "resource": f"column:{protected_table}.{protected_column}",
        },
        "action": "Read",
        "defaultStrategy": "negated-complement",
        "rules": [{
            "principal": {"selector": "byIdentity", "resource": f"group:{group_name}"},
            "effect": "allow",
        }],
        "defaultBranch": {
            "effect": "transform",
            "transformation": {"type": "Redact", "replacement": replacement},
        },
        "provenance": {
            "extractedFrom": f"unity-catalog:{fq}",
            "notes": "Extracted by UnityCatalogAdapter discover()/extract().",
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
            depth += 1; current.append(ch); i += 1; continue
        if ch == ")":
            depth -= 1; current.append(ch); i += 1; continue
        if depth == 0 and body[i:i + 4].upper() == " OR " and i + 4 < len(body):
            branches.append("".join(current).strip()); current = []; i += 4; continue
        current.append(ch); i += 1
    branches.append("".join(current).strip())
    return branches
