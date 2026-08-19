"""Spike (1): the corpus as an RDF graph, queried for the interaction surface.

The Layer-1 question: does loading the policy corpus into a graph and querying
it with SPARQL buy us more than the Python-side checks. In particular, can we
get attribute subsumption (PII ⊇ PHI) "for free" from the ontology via property
paths, and express the cross-policy interaction surface declaratively?

This spike answers empirically. It builds one rdflib graph from the ontology
plus a set of policy JSON-LD documents, and runs SPARQL to (a) extract each
policy's attachment target and attribute matches, and (b) attempt an
ontology-subsumption query. It also probes whether attribute values in the
corpus actually resolve to vocabulary IRIs, which turns out to be the crux.

Finding (see the companion spike report): the graph's one genuine advantage,
ontology subsumption via property paths, was originally *blocked* because the
`sensitivity` term was `"@type": "@id"` and the context had no `@vocab`, so bare
attribute values expanded to document-base junk instead of `vocab#` IRIs.
**ADR-028 (2026-08-05) resolved this**: `sensitivity` is now `"@type": "@vocab"`
and the context declares a top-level `@vocab`, so bare values resolve to the
Tessera namespace (`PII` ⇒ `tessera:PII`) and the `subClassOf*` property path
reaches the ontology hierarchy. Scope containment remains string logic either
way; the subsumption win is now real for Tessera-namespace values, while
adopter-prefixed values (`acme:PIIClerk`) are correctly outside it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from rdflib import Graph


REPO_ROOT = Path(__file__).resolve().parents[3]
ONTOLOGY = REPO_ROOT / "spec" / "v0" / "ontology.ttl"
CONTEXT = REPO_ROOT / "spec" / "v0" / "context.jsonld"
VOCAB = "https://bgiesbrecht.github.io/tessera/spec/v0/vocab#"


def build_graph(policy_paths: list[str | Path], *, with_ontology: bool = True) -> Graph:
    """Load the ontology (optional) plus the given policy JSON-LD files into one
    RDF graph. The real context object is inlined so term mappings apply."""
    g = Graph()
    if with_ontology:
        g.parse(str(ONTOLOGY), format="turtle")
    ctx = json.load(open(CONTEXT))
    ctx_obj = ctx.get("@context", ctx)
    for p in policy_paths:
        doc = json.loads(Path(p).read_text())
        doc["@context"] = ctx_obj
        g.parse(data=json.dumps(doc), format="json-ld")
    return g


# SPARQL: each policy's kind + attachment target (scope or resource).
_Q_TARGETS = """
PREFIX t: <https://bgiesbrecht.github.io/tessera/spec/v0/vocab#>
SELECT ?policy ?kind ?target WHERE {
  ?policy t:policyKind ?kind ;
          t:appliesTo ?sel .
  { ?sel t:scope ?target } UNION { ?sel t:resource ?target }
}
"""

# SPARQL: attribute matches (axis + value) declared by any policy's selector.
_Q_ATTRS = """
PREFIX t: <https://bgiesbrecht.github.io/tessera/spec/v0/vocab#>
SELECT ?policy ?value WHERE {
  ?policy t:appliesTo ?sel .
  ?sel t:matching ?m .
  ?m t:attributesMap ?am .
  ?am t:sensitivity ?value .
}
"""


@dataclass
class InteractionPair:
    a: str
    b: str
    kind: str
    relation: str  # e.g. "scope acme ⊇ acme.tpch.orders"


def _local(iri: str) -> str:
    s = str(iri)
    return s.split("#")[-1].split("/")[-1] if s.startswith("http") else s


def _target_str(t) -> str:
    """Normalize an attachment target to its CURIE/string form for containment."""
    return str(t)


def _path_parts(target: str) -> tuple[str, list[str]]:
    if ":" not in target:
        return "", target.split(".")
    kind, rest = target.split(":", 1)
    return kind, rest.split(".") if rest else []


def _contains(outer: str, inner: str) -> bool:
    _, o = _path_parts(outer)
    _, i = _path_parts(inner)
    return len(o) <= len(i) and i[: len(o)] == o


def scope_interaction_surface(g: Graph) -> list[InteractionPair]:
    """Policy pairs of the same kind whose attachment targets nest (one scope
    contains the other). Extraction is via SPARQL; containment is the same
    dotted-path logic the Python kernel uses (the graph does not do this for us)."""
    rows = [(str(p), _local(k), _target_str(tg)) for p, k, tg in g.query(_Q_TARGETS)]
    pairs: list[InteractionPair] = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            (p1, k1, t1), (p2, k2, t2) = rows[i], rows[j]
            if k1 != k2:
                continue
            if _contains(t1, t2):
                pairs.append(InteractionPair(p1, p2, k1, f"{t1} ⊇ {t2}"))
            elif _contains(t2, t1):
                pairs.append(InteractionPair(p2, p1, k1, f"{t2} ⊇ {t1}"))
    return pairs


def attribute_iri_probe(g: Graph) -> dict:
    """Do attribute values in the corpus resolve to vocabulary IRIs (so ontology
    subsumption via rdfs:subClassOf* could reach them)? This is the crux of
    whether the graph buys us attribute reasoning."""
    values = [str(v) for _, v in g.query(_Q_ATTRS)]
    vocab_iris = [v for v in values if v.startswith(VOCAB)]
    return {
        "attribute_values_seen": values,
        "resolved_to_vocab_iri": vocab_iris,
        "unresolved": [v for v in values if not v.startswith(VOCAB)],
        "subsumption_reachable": bool(vocab_iris),
    }


def subsumption_pairs(g: Graph) -> list[tuple[str, str]]:
    """Policy pairs whose sensitivity values are related by the ontology
    hierarchy (one subsumes the other), via a SPARQL property path. Returns
    empty on the current corpus because values are not vocab IRIs, the finding."""
    q = """
    PREFIX t: <https://bgiesbrecht.github.io/tessera/spec/v0/vocab#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT DISTINCT ?p1 ?p2 WHERE {
      ?p1 t:appliesTo/t:matching/t:attributesMap/t:sensitivity ?v1 .
      ?p2 t:appliesTo/t:matching/t:attributesMap/t:sensitivity ?v2 .
      ?v2 rdfs:subClassOf* ?v1 .
      FILTER(?p1 != ?p2)
    }
    """
    return [(str(a), str(b)) for a, b in g.query(q)]
