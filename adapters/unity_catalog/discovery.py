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

    return DiscoveryResult(artifacts=artifacts, diagnostics=diagnostics)


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
    return ExtractionResult(
        policy=None, confidence=0.0,
        diagnostics=[Diagnostic(
            severity=DiagnosticSeverity.ERROR,
            code="UNKNOWN_ARTIFACT_KIND",
            message=f"Unrecognized artifact kind: {kind!r}.",
        )],
    )


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
