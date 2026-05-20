"""Reconciliation — diff intended IR state against observed platform state.

Platform-neutral comparison logic. Each adapter exposes `discover()` and
`extract()` to produce an "observed IR" snapshot; the caller provides the
"intended IR" corpus (typically a directory of `.tessera.yaml` / `.jsonld`
files validated against schema + SHACL). This module compares the two and
returns a structured `ReconciliationResult`.

Matching is by **policy identity**: `appliesTo.resource` + the action. Two
policies match if they target the same resource for the same action; we then
compare the rules + defaultBranch shape for modifications.

The diff is structural, not semantic-deep-equal — the IR's `@context`,
`@id`, `description`, `provenance` fields are noise for reconciliation
purposes; the rules and the appliesTo resource are signal.
"""

from __future__ import annotations

from typing import Any

from adapters.contract.types import (
    Diagnostic,
    DiagnosticSeverity,
    DiscoveryResult,
    ExtractionResult,
    ReconciliationResult,
)


def reconcile(
    intended: list[dict[str, Any]],
    observed: list[dict[str, Any]],
) -> ReconciliationResult:
    """Compare intended IR policies against observed (extracted) IR policies.

    Args:
        intended: list of IR dicts representing what the corpus says should be deployed.
        observed: list of IR dicts representing what was actually found and extracted.

    Returns ReconciliationResult with:
        - additions: policies in `intended` but not in `observed` (deploy these)
        - removals: policies in `observed` but not in `intended` (drift; either
          adopt into the corpus or drop from the platform)
        - modifications: policies present on both sides whose rules differ
        - diagnostics: extraction or matching issues that prevented a clean compare
    """
    diagnostics: list[Diagnostic] = []

    def key(p: dict[str, Any]) -> tuple[str, str]:
        applies_to = p.get("appliesTo") or {}
        resource = applies_to.get("resource") or applies_to.get("scope") or ""
        action = p.get("action") or ""
        return (resource.casefold(), action.casefold())

    intended_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for p in intended:
        k = key(p)
        if k in intended_by_key:
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="DUPLICATE_INTENDED_KEY",
                message=f"Two intended policies share key {k!r}; ambiguous reconcile target.",
            ))
        intended_by_key[k] = p

    observed_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for p in observed:
        k = key(p)
        observed_by_key[k] = p

    additions: list[dict[str, Any]] = []
    removals: list[dict[str, Any]] = []
    modifications: list[dict[str, Any]] = []

    for k, p in intended_by_key.items():
        if k not in observed_by_key:
            additions.append({"key": k, "intended": p})
        else:
            diff = _structural_diff(p, observed_by_key[k])
            if diff is not None:
                modifications.append({"key": k, "intended": p,
                                       "observed": observed_by_key[k],
                                       "diff": diff})

    for k, p in observed_by_key.items():
        if k not in intended_by_key:
            removals.append({"key": k, "observed": p})

    return ReconciliationResult(
        additions=additions,
        removals=removals,
        modifications=modifications,
        diagnostics=diagnostics,
    )


def _structural_diff(intended: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any] | None:
    """Compare two IR policies on rule structure. Returns None if equivalent.

    Compared fields: policyKind, action, defaultStrategy, rules, defaultBranch.
    Ignored fields: @context, @id, description, version, provenance, capabilityRequirements.
    """
    significant = ("policyKind", "action", "defaultStrategy", "rules", "defaultBranch")
    diffs: dict[str, Any] = {}
    for field in significant:
        i = intended.get(field)
        o = observed.get(field)
        if not _equal(i, o):
            diffs[field] = {"intended": i, "observed": o}
    return diffs or None


def _equal(a: Any, b: Any) -> bool:
    """Recursive equality with case-insensitive string compare on the identifier
    portion of `prefix:id` strings (so `table:Foo` and `table:FOO` are equal).
    """
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        return all(_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, str) and isinstance(b, str):
        # IRI-shaped string with prefix? Compare prefix exactly + identifier case-fold.
        if ":" in a and ":" in b and a.count(":") == b.count(":"):
            ap, ai = a.split(":", 1); bp, bi = b.split(":", 1)
            if ap == bp:
                return ai.casefold() == bi.casefold()
        return a == b
    return a == b
