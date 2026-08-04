"""Check tests, including the scoping-doc §6 worked exercises as acceptance tests.

Each exercise takes a committed corpus artifact, applies a concrete change, and
asserts the expected report. They double as regression tests for C5 + C6.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from tools.impact import analyze
from tools.impact.findings import Confidence, Polarity
from tools.impact.model import Corpus, load_policy_dict


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "spec" / "v0" / "examples"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text())


def _corpus(*docs: dict) -> Corpus:
    c = Corpus()
    for d in docs:
        c.add(load_policy_dict(d))
    return c


def _by_check(findings, code):
    return [f for f in findings if f.check == code]


def _c6(findings):
    return _by_check(findings, "C6")


def _c5(findings):
    return _by_check(findings, "C5")


def _c1(findings):
    return _by_check(findings, "C1")


def _c2(findings):
    return _by_check(findings, "C2")


def _c3(findings):
    return _by_check(findings, "C3")


def _pol(rules: list[dict]) -> dict:
    """A minimal synthetic Policy for reachability tests."""
    return {
        "@context": "x",
        "@type": "Policy",
        "@id": "policy:synthetic",
        "policyKind": "RowVisibilityConstraint",
        "appliesTo": {"selector": "byIdentity", "resource": "table:a.b.c"},
        "action": "Read",
        "defaultStrategy": "none",
        "rules": rules,
    }


def _rule(resource, effect, values=None):
    r = {"principal": {"selector": "byIdentity", "resource": resource}, "effect": effect}
    if values is not None:
        r["condition"] = {"op": "in", "operands": ["column:a.b.c.col"], "values": values}
    return r


# ============================================================================
# Exercise 1 — remove Rule A2 from group-row-visibility-policy-a
# ============================================================================


def test_exercise1_remove_rule_a2_is_narrow():
    base = _load("group-row-visibility-policy-a.jsonld")
    prop = copy.deepcopy(base)
    prop["rules"] = [
        r for r in prop["rules"]
        if r["principal"].get("resource") != "group:acme_high_priority_ops"
    ]
    report = analyze(_corpus(base), _corpus(prop))
    c6 = _c6(report.findings)
    assert len(c6) == 1
    f = c6[0]
    assert f.polarity == Polarity.NARROW
    assert f.confidence == Confidence.PROVEN
    assert "acme_high_priority_ops" in f.subject


def test_exercise1_remove_rule_a2_reports_c1_coverage_candidate():
    # The full §6 Exercise 1 report also carries a C1 coverage finding: the
    # selector lost its last rule, and its fate under explicit-baseline-group
    # depends on unseen membership -> CANDIDATE.
    base = _load("group-row-visibility-policy-a.jsonld")
    prop = copy.deepcopy(base)
    prop["rules"] = [
        r for r in prop["rules"]
        if r["principal"].get("resource") != "group:acme_high_priority_ops"
    ]
    c1 = _c1(analyze(_corpus(base), _corpus(prop)).findings)
    assert len(c1) == 1
    assert c1[0].confidence == Confidence.CANDIDATE
    assert "acme_high_priority_ops" in c1[0].subject
    assert c1[0].unknown  # names the membership unknown


def test_exercise1_contrast_add_value_is_widen():
    base = _load("group-row-visibility-policy-a.jsonld")
    prop = copy.deepcopy(base)
    prop["rules"][1]["condition"]["values"].append("3-MEDIUM")
    report = analyze(_corpus(base), _corpus(prop))
    c6 = _c6(report.findings)
    assert len(c6) == 1
    assert c6[0].polarity == Polarity.WIDEN
    assert "3-MEDIUM" in c6[0].consequence


# ============================================================================
# Effect-change polarity classification
# ============================================================================


def test_effect_flip_keep_to_drop_is_invert():
    base = _load("group-row-visibility-policy-a.jsonld")
    prop = copy.deepcopy(base)
    prop["rules"][0]["effect"] = "drop-matching-rows"
    c6 = _c6(analyze(_corpus(base), _corpus(prop)).findings)
    assert len(c6) == 1
    assert c6[0].polarity == Polarity.INVERT


def test_allow_to_transform_is_narrow():
    base = _load("group-row-visibility-policy-a.jsonld")
    prop = copy.deepcopy(base)
    prop["rules"][0]["effect"] = "transform"
    prop["rules"][0]["transformation"] = {"type": "Redact", "replacement": "X"}
    c6 = _c6(analyze(_corpus(base), _corpus(prop)).findings)
    assert len(c6) == 1
    assert c6[0].polarity == Polarity.NARROW


def test_transform_swap_is_invert_not_a_fabricated_direction():
    # Redact → Hash has no total order (§9.4): the tool must flag INVERT and
    # route to review, never invent a WIDEN/NARROW ranking.
    base = _load("group-row-visibility-policy-a.jsonld")
    base = copy.deepcopy(base)
    base["rules"][0]["effect"] = "transform"
    base["rules"][0]["transformation"] = {"type": "Redact", "replacement": "X"}
    prop = copy.deepcopy(base)
    prop["rules"][0]["transformation"] = {"type": "Hash", "algorithm": "sha256"}
    c6 = _c6(analyze(_corpus(base), _corpus(prop)).findings)
    assert len(c6) == 1
    assert c6[0].polarity == Polarity.INVERT
    assert "review the substitution" in c6[0].consequence
    assert "ADR-016" in c6[0].grounding


# ============================================================================
# Whole-policy add / remove
# ============================================================================


def test_add_expose_only_policy_is_widen():
    added = _load("group-row-visibility-policy-b.jsonld")
    # policy-b is all keep-matching-rows -> expose-only -> adding widens.
    report = analyze(Corpus(), _corpus(added))
    c6 = _c6(report.findings)
    assert len(c6) == 1
    assert c6[0].polarity == Polarity.WIDEN


# ============================================================================
# C5 — dangling reference (seeded by the change)
# ============================================================================


def test_c5_removing_baseline_rule_flags_dangling_baseline_group():
    base = _load("group-row-visibility-policy-a.jsonld")
    prop = copy.deepcopy(base)
    prop["rules"] = [
        r for r in prop["rules"]
        if r["principal"].get("resource") != "group:account-users"
    ]
    c5 = _c5(analyze(_corpus(base), _corpus(prop)).findings)
    assert any("baselineGroup" in f.subject for f in c5)


def test_c5_operand_outside_scope_flagged():
    base = _load("group-row-visibility-policy-a.jsonld")
    prop = copy.deepcopy(base)
    prop["rules"][1]["condition"]["operands"] = ["column:other.db.tbl.col"]
    c5 = _c5(analyze(_corpus(base), _corpus(prop)).findings)
    assert any("outside" in f.consequence for f in c5)


def test_c5_ignores_unchanged_policies():
    # An unchanged policy in both corpora must produce no C5 findings, even if
    # it would independently (this guards the change-seeded scoping of C5).
    base = _load("abac-row-filter-priority.jsonld")
    report = analyze(_corpus(base), _corpus(copy.deepcopy(base)))
    assert _c5(report.findings) == []


def test_c5_adopter_namespaced_axis_not_flagged():
    # acme:rowDiscriminator is an adopter-namespaced axis (ADR-018); adding the
    # policy should not flag it as an unknown axis.
    added = _load("abac-row-filter-priority.jsonld")
    c5 = _c5(analyze(Corpus(), _corpus(added)).findings)
    assert not any("rowDiscriminator" in f.subject for f in c5)


# ============================================================================
# No-op change
# ============================================================================


def test_identical_corpus_no_findings():
    base = _load("group-row-visibility-policy-a.jsonld")
    report = analyze(_corpus(base), _corpus(copy.deepcopy(base)))
    assert report.is_empty()


# ============================================================================
# C1 — fall-through coverage
# ============================================================================


def test_c1_none_strategy_fallthrough_is_proven():
    # Under defaultStrategy: none, losing a selector's last rule is a fully
    # determined fail-closed outcome -> PROVEN (no membership dependency).
    from tools.converter import yaml_to_jsonld
    base = yaml_to_jsonld(EXAMPLES / "snowflake-byDataset-row-visibility-policy.tessera.yaml")
    # This policy has one rule with a byDataset principal; removing it drops
    # that selector to zero. Its selector key is the byDataset(...) label.
    prop = copy.deepcopy(base)
    prop["rules"] = []
    prop["defaultStrategy"] = "none"
    c1 = _c1(analyze(_corpus(base), _corpus(prop)).findings)
    assert len(c1) == 1
    assert c1[0].confidence == Confidence.PROVEN
    assert "fail-closed" in c1[0].consequence


def test_c1_not_fired_when_rule_still_present():
    base = _load("group-row-visibility-policy-a.jsonld")
    prop = copy.deepcopy(base)
    # Change a condition value but keep every selector's rule -> no C1.
    prop["rules"][1]["condition"]["values"].append("3-MEDIUM")
    assert _c1(analyze(_corpus(base), _corpus(prop)).findings) == []


# ============================================================================
# C2 — default-net removal / weakening (Exercise 3)
# ============================================================================


def test_exercise3_weaken_snowflake_default_is_widen():
    from tools.converter import yaml_to_jsonld
    base = yaml_to_jsonld(EXAMPLES / "snowflake-byDataset-row-visibility-policy.tessera.yaml")
    prop = copy.deepcopy(base)
    prop["defaultStrategy"] = "explicit-baseline-group"
    prop["baselineGroup"] = "PUBLIC"
    c2 = _c2(analyze(_corpus(base), _corpus(prop)).findings)
    strat = [f for f in c2 if f.subject == "defaultStrategy"]
    assert len(strat) == 1
    assert strat[0].polarity == Polarity.WIDEN
    # honest limit: magnitude depends on ACL contents not read.
    assert strat[0].unknown


def test_c2_strengthen_to_none_is_narrow():
    base = _load("group-row-visibility-policy-a.jsonld")
    prop = copy.deepcopy(base)
    prop["defaultStrategy"] = "none"
    del prop["baselineGroup"]
    c2 = _c2(analyze(_corpus(base), _corpus(prop)).findings)
    strat = [f for f in c2 if f.subject == "defaultStrategy"]
    assert len(strat) == 1
    assert strat[0].polarity == Polarity.NARROW


def test_c2_default_branch_removal_flagged_narrow():
    base = _load("abac-column-mask-policy-a.jsonld")
    assert base.get("defaultBranch") is not None  # sanity: this policy has one
    prop = copy.deepcopy(base)
    del prop["defaultBranch"]
    c2 = _c2(analyze(_corpus(base), _corpus(prop)).findings)
    branch = [f for f in c2 if f.subject == "defaultBranch"]
    assert len(branch) == 1
    assert branch[0].polarity == Polarity.NARROW


# ============================================================================
# C3 — reachability / shadowing
# ============================================================================


def test_c3_reorder_makes_narrow_rule_dead():
    # An unconditional broad keep placed before a narrower rule on the same
    # selector renders the narrower rule unreachable under first-match.
    broad = _rule("group:g", "keep-matching-rows")
    narrow = _rule("group:g", "drop-matching-rows", values=["1"])
    base = _pol([narrow, broad])   # narrow reachable
    prop = _pol([broad, narrow])   # narrow now shadowed
    c3 = _c3(analyze(_corpus(base), _corpus(prop)).findings)
    assert len(c3) == 1
    assert c3[0].confidence == Confidence.PROVEN
    assert "unreachable" in c3[0].consequence


def test_c3_unshadow_activates_dormant_rule():
    # The dangerous direction: reordering makes a previously-dead rule live.
    broad = _rule("group:g", "keep-matching-rows")
    narrow = _rule("group:g", "drop-matching-rows", values=["1"])
    base = _pol([broad, narrow])   # narrow dead
    prop = _pol([narrow, broad])   # narrow now live
    c3 = _c3(analyze(_corpus(base), _corpus(prop)).findings)
    assert len(c3) == 1
    assert "Dormant policy has been activated" in c3[0].consequence


def test_c3_unshadow_via_removal_of_shadowing_rule():
    broad = _rule("group:g", "keep-matching-rows")
    narrow = _rule("group:g", "drop-matching-rows", values=["1"])
    base = _pol([broad, narrow])   # narrow dead
    prop = _pol([narrow])          # shadowing rule removed -> narrow live
    c3 = _c3(analyze(_corpus(base), _corpus(prop)).findings)
    assert len(c3) == 1
    assert "now reachable" in c3[0].consequence


def test_c3_distinct_selectors_never_shadow():
    # Two genuinely different identity selectors never subsume -> no shadowing,
    # regardless of order.
    g1 = _rule("group:g1", "keep-matching-rows")
    g2 = _rule("group:g2", "keep-matching-rows")
    base = _pol([g1, g2])
    prop = _pol([g2, g1])
    assert _c3(analyze(_corpus(base), _corpus(prop)).findings) == []


def test_c3_opaque_selector_never_shadows_adr001_guard():
    # The ADR-001 bright line: an opaque byDataset earlier rule cannot be
    # claimed to shadow, because its population is unknowable. Even with an
    # unconditional opaque rule first, no shadowing finding is produced.
    opaque = {
        "principal": {"selector": "byDataset",
                      "dataset": {"type": "PrincipalSetFromTable", "table": "acme.acl"}},
        "effect": "keep-matching-rows",
    }
    later = {
        "principal": {"selector": "byDataset",
                      "dataset": {"type": "PrincipalSetFromTable", "table": "acme.acl"}},
        "effect": "drop-matching-rows",
    }
    base = _pol([later, opaque])
    prop = _pol([opaque, later])
    assert _c3(analyze(_corpus(base), _corpus(prop)).findings) == []


def test_c3_scope_subsumption_shadows_column_rule():
    # Scope-IRI containment also drives shadowing: an earlier byScope rule at
    # catalog scope subsumes a later one at a contained table scope.
    broad = {"principal": {"selector": "byScope", "scope": "catalog:acme"},
             "effect": "allow"}
    narrow = {"principal": {"selector": "byScope", "scope": "table:acme.tpch.orders"},
              "effect": "deny"}
    base = _pol([narrow, broad])
    prop = _pol([broad, narrow])
    c3 = _c3(analyze(_corpus(base), _corpus(prop)).findings)
    assert len(c3) == 1
    assert "unreachable" in c3[0].consequence


def test_c3_no_change_no_findings():
    broad = _rule("group:g", "keep-matching-rows")
    narrow = _rule("group:g", "drop-matching-rows", values=["1"])
    base = _pol([broad, narrow])
    # Identical corpus -> the shadowing exists in both, so it is not *newly*
    # introduced and produces no finding.
    assert _c3(analyze(_corpus(base), _corpus(copy.deepcopy(base))).findings) == []
