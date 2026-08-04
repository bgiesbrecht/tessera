"""Tests for the standing whole-corpus dead-rule lint (L1) and its CLI mode.

L1 shares C3's reachability mechanism but audits a single corpus state rather
than diffing two versions. These pin: it flags every dead rule, names the
shadowing rule, stays silent on clean policies, and holds the ADR-001 guard
(opaque selectors never yield a dead-rule claim).
"""

from __future__ import annotations

from pathlib import Path

from tools.impact import lint
from tools.impact.findings import Confidence
from tools.impact.model import Corpus, load_policy_dict


REPO_ROOT = Path(__file__).resolve().parents[3]
TIMELINE = REPO_ROOT / "tools" / "impact" / "demo" / "timeline"


def _pol(pid: str, rules: list[dict]) -> dict:
    return {
        "@context": "x",
        "@type": "Policy",
        "@id": f"policy:{pid}",
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


def _corpus(*docs: dict) -> Corpus:
    c = Corpus()
    for d in docs:
        c.add(load_policy_dict(d))
    return c


def _l1(report):
    return [f for f in report.findings if f.check == "L1"]


def test_lint_flags_dead_rule_and_names_shadower():
    broad = _rule("group:g", "keep-matching-rows")
    dead = _rule("group:g", "drop-matching-rows", values=["1"])
    report = lint(_corpus(_pol("p", [broad, dead])))
    l1 = _l1(report)
    assert len(l1) == 1
    assert l1[0].confidence == Confidence.PROVEN
    assert "rule 1" in l1[0].subject
    assert "earlier rule 0" in l1[0].consequence


def test_lint_silent_on_clean_corpus():
    clean = _pol("clean", [
        _rule("group:a", "keep-matching-rows", values=["1"]),
        _rule("group:b", "keep-matching-rows", values=["2"]),
    ])
    assert _l1(lint(_corpus(clean))) == []


def test_lint_flags_only_offending_policy():
    dead = _pol("dead", [
        _rule("group:g", "keep-matching-rows"),
        _rule("group:g", "drop-matching-rows", values=["1"]),
    ])
    clean = _pol("clean", [_rule("group:h", "keep-matching-rows")])
    l1 = _l1(lint(_corpus(dead, clean)))
    assert len(l1) == 1
    assert l1[0].policy_id == "policy:dead"


def test_lint_opaque_selector_never_dead_adr001_guard():
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
    assert _l1(lint(_corpus(_pol("p", [opaque, later])))) == []


def test_lint_multiple_dead_rules_all_reported():
    broad = _rule("group:g", "keep-matching-rows")
    dead1 = _rule("group:g", "drop-matching-rows", values=["1"])
    dead2 = _rule("group:g", "keep-matching-rows", values=["2"])
    l1 = _l1(lint(_corpus(_pol("p", [broad, dead1, dead2]))))
    assert len(l1) == 2
    assert {"rule 1 (selector group:g)", "rule 2 (selector group:g)"} == {f.subject for f in l1}


# -- demo fixture regression -------------------------------------------------


def test_demo_v4_fixture_has_the_expected_dead_rule():
    # The committed v4 fixture must still exhibit the dead analysts rule the
    # demo narrative describes; guards against fixture drift.
    import json
    v4 = json.loads((TIMELINE / "v4" / "orders-access.jsonld").read_text())
    l1 = _l1(lint(_corpus(v4)))
    assert len(l1) == 1
    assert "group:acme_analysts" in l1[0].subject
