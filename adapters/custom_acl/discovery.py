"""custom-ACL discovery & extraction: ACL-view → Tessera IR.

Extraction is this adapter's highest-value responsibility and the reason ADR-003
exists: a customer with thousands of hand-built ACL views wants to lift them into
Tessera IR so they can be re-emitted to native Unity Catalog / Snowflake and
migrated *selectively*, keeping the ACL pattern operational for the rest.

`extract_artifact` parses a wrapping-view definition (the shape this adapter's
`emit` produces, and the shape the customer hand-writes) back into a byDataset
RowVisibilityConstraint. The regexes are deliberate-not-perfect: they match the
documented ACL-join shape; a production extractor would use a SQL AST parser.
Low-confidence / partial matches surface as diagnostics rather than silent IR.

`discover_schema` inventories candidate ACL-wrapping views. Because the pattern is
engine-neutral, it works two ways: an *offline* list of view artifacts supplied via
`config.extras['acl_views']` (so extraction is testable with no live DB), or a live
DB-API cursor querying INFORMATION_SCHEMA.VIEWS with an EXISTS-pattern heuristic.
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

# The EXISTS-join shape emit produces (and the customer hand-writes). Matched
# piecewise so a partial match degrades to a diagnostic rather than a crash.
_FROM_RE = re.compile(r"FROM\s+([A-Za-z0-9_.]+)\s+(?:AS\s+)?(\w+)", re.IGNORECASE)
_JOIN_RE = re.compile(
    r"JOIN\s+([A-Za-z0-9_.]+)\s+(?:AS\s+)?(\w+)\s+ON\s+(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)",
    re.IGNORECASE,
)
# Principal match, case-insensitive (lower(trim(...))) or exact.
_WHERE_USER_RE = re.compile(
    r"WHERE\s+(?:lower\s*\(\s*trim\s*\(\s*)?(\w+)\.(\w+)\)?\)?\s*=\s*"
    r"(?:lower\s*\(\s*trim\s*\(\s*)?current_user\s*\(\s*\)",
    re.IGNORECASE,
)
# Resource predicate: AND p.<col> = b.<col>  (or = <param>).
_AND_VALUE_RE = re.compile(
    r"AND\s+(\w+)\.(\w+)\s*=\s*(?:(\w+)\.)?(\w+)", re.IGNORECASE,
)
# The wrapped base table: SELECT ... FROM <base> <alias> WHERE EXISTS
_BASE_RE = re.compile(
    r"FROM\s+([A-Za-z0-9_.]+)\s+(?:AS\s+)?(\w+)\s+WHERE\s+EXISTS", re.IGNORECASE,
)


def extract_artifact(artifact: dict[str, Any]) -> ExtractionResult:
    """Lift a discovered ACL view into Tessera IR.

    Expected artifact: {"kind": "acl_view", "fq_name": <view name>,
    "definition": <full CREATE VIEW ... or the SELECT body>,
    optional "protected_table": <base table>}.
    """
    diagnostics: list[Diagnostic] = []
    kind = artifact.get("kind")
    if kind != "acl_view":
        return ExtractionResult(
            policy=None, confidence=0.0,
            diagnostics=[Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="UNKNOWN_ARTIFACT_KIND",
                message=f"custom-acl extract expects kind='acl_view'; got {kind!r}.",
            )],
        )

    definition = artifact.get("definition") or ""
    fq = artifact.get("fq_name") or "unknown_view"

    # Base (protected) table: prefer the explicit hint, else parse the outer FROM.
    protected_table = artifact.get("protected_table")
    if not protected_table:
        base_match = _BASE_RE.search(definition)
        if base_match:
            protected_table = base_match.group(1)

    exists_match = re.search(r"EXISTS\s*\((.*)\)", definition, re.IGNORECASE | re.DOTALL)
    body = exists_match.group(1) if exists_match else definition

    from_match = _FROM_RE.search(body)
    join_match = _JOIN_RE.search(body)
    where_user_match = _WHERE_USER_RE.search(body)
    and_value_match = _AND_VALUE_RE.search(body)

    if not (protected_table and from_match and join_match and where_user_match and and_value_match):
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="ACL_VIEW_PATTERN_PARTIAL_MATCH",
            message=(
                f"ACL view {fq!r} did not match the full ACL-join shape. "
                f"base={bool(protected_table)} from={bool(from_match)} "
                f"join={bool(join_match)} where_user={bool(where_user_match)} "
                f"and_value={bool(and_value_match)}. Not lifting to IR."
            ),
        ))
        return ExtractionResult(policy=None, confidence=0.0, diagnostics=diagnostics)

    map_table = from_match.group(1)
    acl_table = join_match.group(1)
    map_resource_col = join_match.group(4)      # m.<map_resource_col>
    acl_principal_col = join_match.group(6)      # p.<acl_principal_col>
    map_principal_col = where_user_match.group(2)
    acl_resource_col = and_value_match.group(2)  # p.<acl_resource_col>

    slug = fq.rsplit(".", 1)[-1].lower().removesuffix("_secured")
    policy = {
        "@context": CONTEXT_URL,
        "@type": "Policy",
        "@id": f"policy:extracted-{slug}",
        "version": "1.0.0",
        "policyKind": "RowVisibilityConstraint",
        "description": f"Extracted from custom ACL view {fq}.",
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
            "extractedFrom": f"custom-acl:view:{fq}",
            "notes": (
                "Extracted by CustomACLAdapter discover()/extract(). The ACL-view "
                "migration on-ramp (ADR-032). Re-emit through a native adapter to migrate."
            ),
        },
    }
    # Full shape recognized; confidence is high but < native (the regex is a
    # heuristic over hand-written SQL, not an AST parse).
    return ExtractionResult(policy=policy, confidence=0.9, diagnostics=diagnostics)


def discover_schema(
    cursor: Any | None = None,
    database: str | None = None,
    schema: str | None = None,
    *,
    offline_views: list[dict[str, Any]] | None = None,
) -> DiscoveryResult:
    """Inventory candidate ACL-wrapping views.

    Offline: pass `offline_views` (a list of acl_view artifacts) directly, used
    when the caller already has view definitions in hand. Live: pass a DB-API
    `cursor` plus `database`/`schema` to query INFORMATION_SCHEMA.VIEWS and keep
    only definitions that contain an EXISTS ACL-join (a conservative heuristic).
    """
    diagnostics: list[Diagnostic] = []
    artifacts: list[dict[str, Any]] = []

    if offline_views is not None:
        for v in offline_views:
            art = dict(v)
            art.setdefault("kind", "acl_view")
            artifacts.append(art)
        return DiscoveryResult(artifacts=artifacts, diagnostics=diagnostics)

    if cursor is None or not schema:
        return DiscoveryResult(
            artifacts=[],
            diagnostics=[Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="DISCOVER_MISSING_INPUTS",
                message=(
                    "custom-acl discover() needs either offline_views, or a live DB-API "
                    "cursor plus a schema. Pass offline_views=[...] for the offline path, "
                    "or cursor=<dbapi cursor>, schema=<schema> for the live path."
                ),
            )],
        )

    where_schema = f"{database}.{schema}" if database else schema
    try:
        cursor.execute(
            "SELECT TABLE_NAME, VIEW_DEFINITION FROM INFORMATION_SCHEMA.VIEWS "
            f"WHERE TABLE_SCHEMA = '{schema}'"
        )
        rows = cursor.fetchall()
    except Exception as exc:  # noqa: BLE001. Engine-neutral; surface as diagnostic
        return DiscoveryResult(
            artifacts=[],
            diagnostics=[Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="DISCOVER_QUERY_FAILED",
                message=f"INFORMATION_SCHEMA.VIEWS query failed on {where_schema}: {exc}",
            )],
        )

    for name, definition in rows:
        definition = definition or ""
        if "EXISTS" in definition.upper() and "CURRENT_USER" in definition.upper():
            artifacts.append({
                "kind": "acl_view",
                "fq_name": f"{where_schema}.{name}",
                "definition": definition,
            })

    if not artifacts:
        diagnostics.append(Diagnostic(
            severity=DiagnosticSeverity.INFO,
            code="NO_ACL_VIEWS_FOUND",
            message=f"No views matching the ACL-join heuristic found in {where_schema}.",
        ))
    return DiscoveryResult(artifacts=artifacts, diagnostics=diagnostics)
