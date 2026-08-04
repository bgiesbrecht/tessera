"""Tests for C4 (cross-policy overlap, diff) and L2 (standing overlap lint).

These pin the ADR-023 MULTIPLE_MASKS detection and — critically — the ADR-001
confidence boundary: two attribute predicates that provably co-apply are PROVEN,
but a predicate vs. a concrete resource is only CANDIDATE, because proving it
would require knowing whether that resource carries the attribute tag.
"""

from __future__ import annotations

from pathlib import Path

from tools.impact import analyze, lint
from tools.impact.findings import Confidence
from tools.impact.model import Corpus, load_corpus_from_paths, load_policy_dict


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "spec" / "v0" / "examples"


def _mask(pid: str, *, scope: str | None = None, resource: str | None = None,
          sensitivity: str | None = None, tf_type: str = "Redact") -> dict:
    """A ColumnVisibilityConstraint: byScope+attribute if scope given, else a
    concrete byIdentity column."""
    if scope is not None:
        applies = {"selector": "byScope", "scope": scope}
        if sensitivity is not None:
            applies["matching"] = {"attributes": {"sensitivity": sensitivity}}
    else:
        applies = {"selector": "byIdentity", "resource": resource}
    tf = {"type": tf_type}
    if tf_type == "Redact":
        tf["replacement"] = "X"
    return {
        "@context": "x",
        "@type": "Policy",
        "@id": f"policy:{pid}",
        "policyKind": "ColumnVisibilityConstraint",
        "appliesTo": applies,
        "action": "Read",
        "defaultStrategy": "negated-complement",
        "rules": [{"principal": {"selector": "byIdentity", "resource": "group:ok"},
                   "effect": "allow"}],
        "defaultBranch": {"effect": "transform", "transformation": tf},
    }


def _corpus(*docs: dict) -> Corpus:
    c = Corpus()
    for d in docs:
        c.add(load_policy_dict(d))
    return c


def _l2(report):
    return [f for f in report.findings if f.check == "L2"]


def _c4(report):
    return [f for f in report.findings if f.check == "C4"]


# -- L2 standing lint --------------------------------------------------------


def test_two_scope_predicates_same_attribute_is_proven_overlap():
    a = _mask("redact", scope="catalog:acme", sensitivity="PII", tf_type="Redact")
    b = _mask("hash", scope="table:acme.tpch.orders", sensitivity="PII", tf_type="Hash")
    l2 = _l2(lint(_corpus(a, b)))
    assert len(l2) == 1
    assert l2[0].confidence == Confidence.PROVEN


def test_predicate_vs_concrete_resource_is_candidate():
    # The ADR-001 boundary: proving this overlap needs the tagging fact.
    pred = _mask("hash", scope="catalog:acme", sensitivity="PIIClerk", tf_type="Hash")
    concrete = _mask("redact", resource="column:acme.tpch.orders.o_clerk", tf_type="Redact")
    l2 = _l2(lint(_corpus(pred, concrete)))
    assert len(l2) == 1
    assert l2[0].confidence == Confidence.CANDIDATE
    assert l2[0].unknown and "tagging fact" in l2[0].unknown


def test_same_transformation_no_conflict():
    a = _mask("a", scope="catalog:acme", sensitivity="PII", tf_type="Redact")
    b = _mask("b", scope="table:acme.tpch.orders", sensitivity="PII", tf_type="Redact")
    assert _l2(lint(_corpus(a, b))) == []


def test_disjoint_scopes_no_overlap():
    a = _mask("a", scope="table:acme.sales.x", sensitivity="PII", tf_type="Redact")
    b = _mask("b", scope="table:acme.tpch.orders", sensitivity="PII", tf_type="Hash")
    assert _l2(lint(_corpus(a, b))) == []


def test_disjoint_flat_axis_no_overlap():
    def regime_mask(pid, regime, tf):
        return {
            "@context": "x", "@type": "Policy", "@id": f"policy:{pid}",
            "policyKind": "ColumnVisibilityConstraint",
            "appliesTo": {"selector": "byScope", "scope": "catalog:acme",
                          "matching": {"attributes": {"regulatoryRegime": regime}}},
            "action": "Read", "defaultStrategy": "negated-complement",
            "rules": [{"principal": {"selector": "byIdentity", "resource": "group:ok"},
                       "effect": "allow"}],
            "defaultBranch": {"effect": "transform", "transformation": {"type": tf}},
        }
    # GDPR and HIPAA are siblings on a flat axis — no subsumption, no overlap.
    a = regime_mask("a", "GDPR", "Redact")
    b = regime_mask("b", "HIPAA", "Hash")
    assert _l2(lint(_corpus(a, b))) == []


def test_different_policy_kind_not_compared():
    mask = _mask("m", scope="catalog:acme", sensitivity="PII", tf_type="Redact")
    rowp = {
        "@context": "x", "@type": "Policy", "@id": "policy:r",
        "policyKind": "RowVisibilityConstraint",
        "appliesTo": {"selector": "byScope", "scope": "catalog:acme",
                      "matching": {"attributes": {"sensitivity": "PII"}}},
        "action": "Read", "defaultStrategy": "none",
        "rules": [{"principal": {"selector": "byIdentity", "resource": "group:g"},
                   "effect": "keep-matching-rows"}],
    }
    assert _l2(lint(_corpus(mask, rowp))) == []


# -- C4 diff view ------------------------------------------------------------


def test_c4_reports_overlap_introduced_by_adding_policy():
    a = _mask("redact", scope="catalog:acme", sensitivity="PII", tf_type="Redact")
    b = _mask("hash", scope="table:acme.tpch.orders", sensitivity="PII", tf_type="Hash")
    base = _corpus(a)
    prop = _corpus(a, b)
    c4 = _c4(analyze(base, prop))
    assert len(c4) == 1
    assert "introduces" in c4[0].consequence


def test_c4_reports_overlap_resolved_by_removing_policy():
    a = _mask("redact", scope="catalog:acme", sensitivity="PII", tf_type="Redact")
    b = _mask("hash", scope="table:acme.tpch.orders", sensitivity="PII", tf_type="Hash")
    base = _corpus(a, b)
    prop = _corpus(a)
    c4 = _c4(analyze(base, prop))
    assert len(c4) == 1
    assert "resolves" in c4[0].consequence


# -- real corpus regression --------------------------------------------------


def test_committed_abac_clerk_masks_flagged_proven():
    # The two ABAC clerk masks (byScope PIIClerk, Redact vs Hash) are the
    # ADR-023 MULTIPLE_MASKS case; the standing lint must flag them PROVEN.
    redact = load_corpus_from_paths([EXAMPLES / "abac-column-mask-policy-a.jsonld"])
    both = load_corpus_from_paths([
        EXAMPLES / "abac-column-mask-policy-a.jsonld",
        EXAMPLES / "abac-column-mask-policy-b.jsonld",
    ])
    l2 = _l2(lint(both))
    proven = [f for f in l2 if f.confidence == Confidence.PROVEN]
    assert any("clerk-hash" in f.subject and "clerk-redact" in f.subject for f in proven)
