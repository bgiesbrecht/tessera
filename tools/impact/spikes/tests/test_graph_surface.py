"""Tests for spike (1): the corpus-as-graph interaction surface.

These pin the empirical findings: SPARQL extraction + scope containment works,
attribute subsumption is BLOCKED on bare-term values, and authoring values as
CURIEs unlocks genuine ontology subsumption via a property path.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from tools.impact.spikes.graph_surface import (
    build_graph, scope_interaction_surface, attribute_iri_probe, subsumption_pairs,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
EXAMPLES = REPO_ROOT / "spec" / "v0" / "examples"


def _mask(pid: str, scope: str, sensitivity: str, tf: str) -> dict:
    return {
        "@context": "https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld",
        "@type": "Policy", "@id": f"policy:{pid}",
        "policyKind": "ColumnVisibilityConstraint",
        "appliesTo": {"selector": "byScope", "scope": scope,
                      "matching": {"attributes": {"sensitivity": sensitivity}}},
        "action": "Read", "defaultStrategy": "negated-complement",
        "rules": [{"principal": {"selector": "byIdentity", "resource": "group:ok"},
                   "effect": "allow"}],
        "defaultBranch": {"effect": "transform", "transformation": {"type": tf}},
    }


def _write(tmp: Path, name: str, doc: dict) -> Path:
    p = tmp / name
    p.write_text(json.dumps(doc))
    return p


def test_scope_surface_finds_nesting_pair(tmp_path):
    a = _write(tmp_path, "a.jsonld", _mask("a", "catalog:acme", "tessera:PII", "Redact"))
    b = _write(tmp_path, "b.jsonld", _mask("b", "table:acme.tpch.orders", "tessera:PII", "Hash"))
    g = build_graph([a, b])
    pairs = scope_interaction_surface(g)
    assert len(pairs) == 1
    assert "acme" in pairs[0].relation


def test_bare_terms_resolve_to_vocab_after_adr028(tmp_path):
    # Post-ADR-028: with @vocab + sensitivity as @type:@vocab, a bare attribute
    # value resolves to a vocab# IRI (the spike's original blocked finding is
    # resolved). A declared bare value (PII) reaches the ontology; an undeclared
    # bare value (Typo) is still a well-formed vocab IRI, not document-base junk.
    a = _write(tmp_path, "a.jsonld", _mask("a", "catalog:acme", "PII", "Redact"))
    b = _write(tmp_path, "b.jsonld", _mask("b", "catalog:acme", "Typo", "Redact"))
    probe = attribute_iri_probe(build_graph([a, b]))
    assert probe["subsumption_reachable"] is True
    assert probe["unresolved"] == []  # no more file:// junk


def test_curie_values_unlock_ontology_subsumption(tmp_path):
    # PHI ⊂ PII in the ontology; with CURIE values the property path finds that
    # the PII policy covers the PHI policy (and not the reverse).
    a = _write(tmp_path, "a.jsonld", _mask("broad-pii", "catalog:acme", "tessera:PII", "Redact"))
    b = _write(tmp_path, "b.jsonld", _mask("narrow-phi", "catalog:acme", "tessera:PHI", "Redact"))
    g = build_graph([a, b])
    assert attribute_iri_probe(g)["subsumption_reachable"] is True
    pairs = {(x.split("/")[-1], y.split("/")[-1]) for x, y in subsumption_pairs(g)}
    # PII covers PHI (reflexive self-pairs are also returned; assert the real edge).
    assert ("policy:broad-pii", "policy:narrow-phi") in pairs
    assert ("policy:narrow-phi", "policy:broad-pii") not in pairs
