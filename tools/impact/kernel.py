"""The reasoning kernel for change-impact analysis (scoping doc §4).

Four primitives, each decidable from the corpus or explicitly unknown:

    §4.1 selector normalization    — canonical comparable form
    §4.2 the subsumption lattice   — the only PROVEN relations
    §4.3 effect polarity           — expose / restrict / partial-restrict
    §4.4 the unknown boundary      — what forces CANDIDATE, never a claim

The bright line (scoping doc §2): every relation here is computed over selector
*expressions* — literals, IRIs, typed values — never over the populations those
selectors denote. Nothing in this module resolves group membership or reads an
ACL table. Doing so would be policy evaluation (ADR-001).

Ontology-driven attribute subsumption (§4.2 #4) reads the actual subClassOf
hierarchy and per-axis axisType from spec/v0/ontology.ttl, so the one place the
vocabulary does inferential work stays grounded in the published ontology
rather than a hand-copied table.
"""

from __future__ import annotations

import enum
from functools import lru_cache
from pathlib import Path

from tools.impact.model import Condition, Selector


REPO_ROOT = Path(__file__).resolve().parents[2]
ONTOLOGY_PATH = REPO_ROOT / "spec" / "v0" / "ontology.ttl"
VOCAB = "https://bgiesbrecht.github.io/tessera/spec/v0/vocab#"


# ----------------------------------------------------------------------------
# §4.3 Effect polarity
# ----------------------------------------------------------------------------


class Polarity(enum.Enum):
    EXPOSE = "expose"
    RESTRICT = "restrict"
    PARTIAL_RESTRICT = "partial-restrict"
    UNKNOWN = "unknown"


_EFFECT_POLARITY = {
    "allow": Polarity.EXPOSE,
    "keep-matching-rows": Polarity.EXPOSE,
    "deny": Polarity.RESTRICT,
    "drop-matching-rows": Polarity.RESTRICT,
    "transform": Polarity.PARTIAL_RESTRICT,
}


def effect_polarity(effect: str | None) -> Polarity:
    """Classify a rule effect on the exposure axis (§4.3)."""
    return _EFFECT_POLARITY.get(effect or "", Polarity.UNKNOWN)


# ----------------------------------------------------------------------------
# §4.2 #4 Attribute-axis subsumption, grounded in the ontology
# ----------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _ontology_relations() -> tuple[dict[str, set[str]], dict[str, str]]:
    """Return (superclasses, axis_types) read from the ontology.

    superclasses[local_name] = set of ancestor local-names (reflexive-free).
    axis_types[axis_local_name] = "hierarchical" | "flat".

    Uses rdflib when available and the ontology file is present; otherwise
    falls back to a minimal built-in table covering the v0 well-known values,
    so the kernel degrades gracefully rather than failing where rdflib is
    absent. The fallback mirrors the published ontology's sensitivity subtree.
    """
    try:
        import rdflib  # type: ignore

        g = rdflib.Graph()
        g.parse(str(ONTOLOGY_PATH), format="turtle")
        rdfs_sub = rdflib.RDFS.subClassOf
        supers: dict[str, set[str]] = {}
        for s, _, o in g.triples((None, rdfs_sub, None)):
            if isinstance(s, rdflib.URIRef) and isinstance(o, rdflib.URIRef):
                if str(s).startswith(VOCAB) and str(o).startswith(VOCAB):
                    child = str(s)[len(VOCAB):]
                    parent = str(o)[len(VOCAB):]
                    supers.setdefault(child, set()).add(parent)
        # Transitively close.
        supers = _transitive_close(supers)

        axis_type_prop = rdflib.URIRef(VOCAB + "axisType")
        axis_types: dict[str, str] = {}
        for s, _, o in g.triples((None, axis_type_prop, None)):
            if isinstance(s, rdflib.URIRef) and isinstance(o, rdflib.URIRef):
                axis = str(s)[len(VOCAB):]
                atype = str(o)[len(VOCAB):]
                axis_types[axis] = atype
        return supers, axis_types
    except Exception:
        return _FALLBACK_SUPERS, _FALLBACK_AXIS_TYPES


def _transitive_close(supers: dict[str, set[str]]) -> dict[str, set[str]]:
    closed: dict[str, set[str]] = {k: set(v) for k, v in supers.items()}
    changed = True
    while changed:
        changed = False
        for child, parents in closed.items():
            add: set[str] = set()
            for p in parents:
                add |= closed.get(p, set())
            if not add <= parents:
                parents |= add
                changed = True
    return closed


# Minimal fallback mirroring ontology.ttl's sensitivity subtree + axis types.
_FALLBACK_SUPERS: dict[str, set[str]] = {
    "PersonalData": {"Classification"},
    "PII": {"PersonalData", "Classification"},
    "PHI": {"PII", "PersonalData", "Classification"},
    "SensitivePersonalData": {"PersonalData", "Classification"},
    "Financial": {"Classification"},
    "Public": {"Classification"},
    "Confidential": {"Classification"},
    "Restricted": {"Confidential", "Classification"},
}
_FALLBACK_AXIS_TYPES: dict[str, str] = {
    "sensitivityAxis": "hierarchical",
    "dataSubjectAxis": "flat",
    "regulatoryRegimeAxis": "flat",
    "businessDomainAxis": "flat",
}

# Which axis a policy attribute key maps to, for axisType lookup. The matching
# attribute keys used in policies (`sensitivity`, `dataSubject`, ...) name the
# property; the axis individual is `<key>Axis`.
def _axis_type_for_key(axis_key: str) -> str:
    supers, axis_types = _ontology_relations()
    return axis_types.get(f"{axis_key}Axis", "flat")


def _strip_prefix(value: str) -> str:
    """Drop a leading CURIE prefix (`tessera:PII` -> `PII`)."""
    return value.split(":", 1)[1] if ":" in value else value


def attribute_value_subsumes(axis_key: str, a: str, b: str) -> bool:
    """True if value `a` subsumes (is an ancestor of, or equals) value `b` on
    the given axis. On flat axes only equality subsumes (§4.2 #4)."""
    a_local, b_local = _strip_prefix(a), _strip_prefix(b)
    if a_local == b_local:
        return True
    if _axis_type_for_key(axis_key) != "hierarchical":
        return False
    supers, _ = _ontology_relations()
    return a_local in supers.get(b_local, set())


# ----------------------------------------------------------------------------
# §4.2 #2 Scope-IRI containment
# ----------------------------------------------------------------------------


def _scope_parts(iri: str) -> tuple[str, list[str]]:
    """Split a scope/resource IRI into (kind, dotted-path components).

    `catalog:acme` -> ("catalog", ["acme"])
    `table:acme.tpch.orders` -> ("table", ["acme", "tpch", "orders"])
    `column:acme.tpch.orders.o_clerk` -> ("column", ["acme", ...])
    """
    if ":" not in iri:
        return "", iri.split(".")
    kind, rest = iri.split(":", 1)
    return kind, rest.split(".") if rest else []


def scope_contains(outer: str, inner: str) -> bool:
    """True if `outer` scope-IRI contains (or equals) `inner` (§4.2 #2).

    Containment is a dotted-path prefix relation on the identifier path,
    regardless of the `kind:` prefix — `catalog:acme` contains
    `table:acme.tpch.orders` because ["acme"] is a prefix of
    ["acme","tpch","orders"]. Equal IRIs contain each other.
    """
    _, outer_parts = _scope_parts(outer)
    _, inner_parts = _scope_parts(inner)
    if len(outer_parts) > len(inner_parts):
        return False
    return inner_parts[: len(outer_parts)] == outer_parts


# ----------------------------------------------------------------------------
# §4.2 #3 Condition value-set containment
# ----------------------------------------------------------------------------

# Operators the kernel can compare via set/interval containment. Operators that
# reach into external data (exists-in-dataset) are opaque -> force CANDIDATE.
_COMPARABLE_SET_OPS = {"in", "eq"}


def condition_comparable(cond: Condition | None) -> bool:
    """True if the condition is one the kernel can reason about statically."""
    if cond is None:
        return True  # absence of a condition is fully comparable (unconditional)
    return cond.op in _COMPARABLE_SET_OPS


def condition_value_superset(outer: Condition | None, inner: Condition | None) -> bool:
    """True if `outer`'s matched value-set contains `inner`'s, on a shared
    operand column with a comparable operator (§4.2 #3).

    An absent (None) condition is unconditional and therefore a superset of any
    condition. Two conditions on different operand columns are not comparable
    and return False (the caller treats non-comparability as "not proven").
    """
    if outer is None:
        return True
    if inner is None:
        # A conditional rule cannot be a superset of an unconditional one.
        return False
    if not (condition_comparable(outer) and condition_comparable(inner)):
        return False
    if outer.operands != inner.operands:
        return False
    return set(inner.values) <= set(outer.values)


# ----------------------------------------------------------------------------
# §4.1 Selector normalization + equality/subsumption
# ----------------------------------------------------------------------------


def selectors_equal(a: Selector | None, b: Selector | None) -> bool:
    """Syntactic equality after normalization (§4.1)."""
    if a is None or b is None:
        return a is b
    return (
        a.kind == b.kind
        and a.resource == b.resource
        and a.scope == b.scope
        and a.attributes == b.attributes
        and a.dataset_table == b.dataset_table
    )


def selector_opaque(sel: Selector | None) -> bool:
    """True if the selector's population depends on data the kernel must not
    read (§4.4): byDataset table contents, or an unrecognized selector kind."""
    if sel is None:
        return True
    if sel.dataset_table is not None or sel.kind in ("byDataset", "byComposition"):
        return True
    return False


def selector_subsumes(outer: Selector | None, inner: Selector | None) -> bool:
    """True if `outer` provably matches every resource/principal `inner` does
    (§4.2). Provable only for identity equality, scope-IRI containment, and
    attribute-axis subsumption. Opaque selectors (§4.4) are never subsumed —
    that would require reading the population.
    """
    if outer is None or inner is None:
        return False
    if selector_opaque(outer) or selector_opaque(inner):
        return False

    # Identity equality (§4.2 #1).
    if outer.resource and inner.resource:
        return outer.resource == inner.resource

    # Scope containment + attribute subsumption (§4.2 #2, #4).
    if outer.scope and inner.scope:
        if not scope_contains(outer.scope, inner.scope):
            return False
        # outer must match at least as broadly on attributes: every attribute
        # outer constrains must subsume inner's value on that axis. If outer
        # constrains an axis inner doesn't mention, outer is narrower -> not a
        # superset.
        outer_attrs = dict(outer.attributes)
        inner_attrs = dict(inner.attributes)
        for axis, outer_val in outer_attrs.items():
            inner_val = inner_attrs.get(axis)
            if inner_val is None:
                return False
            if not attribute_value_subsumes(axis, outer_val, inner_val):
                return False
        return True

    return False


def selectors_overlap(a: Selector | None, b: Selector | None) -> bool:
    """True if the two selectors provably co-apply to some common resource
    (used by cross-policy overlap, C4). Conservative: only returns True when a
    subsumption relation holds in either direction. Distinct opaque identity
    selectors are NOT claimed to overlap (§4.4)."""
    if selectors_equal(a, b):
        return True
    return selector_subsumes(a, b) or selector_subsumes(b, a)
