"""Tests for spike (2): within-policy request-space enumeration."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from tools.impact.model import load_policy_dict
from tools.impact.spikes.request_enum import diff_within_policy


REPO_ROOT = Path(__file__).resolve().parents[4]
EXAMPLES = REPO_ROOT / "spec" / "v0" / "examples"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text())


def test_removing_rule_closes_specific_requests():
    base = _load("group-row-visibility-policy-a.jsonld")
    prop = copy.deepcopy(base)
    prop["rules"] = [r for r in prop["rules"]
                     if r["principal"].get("resource") != "group:acme_high_priority_ops"]
    flips, opaque = diff_within_policy(load_policy_dict(base), load_policy_dict(prop))
    assert flips, "removing the high-ops rule must flip some requests"
    # Every flip is a CLOSED (access removed), and all name the high-ops selector.
    assert all(f.direction == "CLOSED" for f in flips)
    assert all("acme_high_priority_ops" in " ".join(f.request.principals) for f in flips)
    # The witnesses are exactly the high-priority values the removed rule kept.
    values = {v for f in flips for _, v in f.request.columns}
    assert {"1-URGENT", "2-HIGH"} <= values


def test_widening_a_condition_opens_one_request():
    base = _load("group-row-visibility-policy-a.jsonld")
    prop = copy.deepcopy(base)
    prop["rules"][1]["condition"]["values"].append("3-MEDIUM")
    flips, _ = diff_within_policy(load_policy_dict(base), load_policy_dict(prop))
    opened = [f for f in flips if f.direction == "OPENED"]
    assert len(opened) == 1
    assert ("column:acme.tpch.orders.o_orderpriority", "3-MEDIUM") in opened[0].request.columns


def test_semantically_inert_reorder_produces_no_flips():
    # Swapping two rules with disjoint principals AND disjoint conditions cannot
    # change any decision under first-match — the enumeration proves it.
    base = _load("group-row-visibility-policy-a.jsonld")
    prop = copy.deepcopy(base)
    prop["rules"][1], prop["rules"][2] = prop["rules"][2], prop["rules"][1]
    flips, _ = diff_within_policy(load_policy_dict(base), load_policy_dict(prop))
    assert flips == []


def test_opaque_operator_is_reported_not_silently_dropped():
    # A condition the enumeration can't model (exists-in-dataset) is surfaced as
    # an opaque note rather than mis-evaluated.
    base = {
        "@context": "x", "@type": "Policy", "@id": "policy:acl",
        "policyKind": "RowVisibilityConstraint",
        "appliesTo": {"selector": "byIdentity", "resource": "table:a.b.c"},
        "action": "Read", "defaultStrategy": "none",
        "rules": [{
            "principal": {"selector": "byIdentity", "resource": "group:g"},
            "effect": "keep-matching-rows",
            "condition": {"op": "exists-in-dataset", "operands": [], "values": []},
        }],
    }
    _flips, opaque = diff_within_policy(load_policy_dict(base), load_policy_dict(copy.deepcopy(base)))
    assert "exists-in-dataset" in opaque
