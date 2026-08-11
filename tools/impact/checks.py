"""Change-impact checks (scoping doc §5).

Shipped:
    C1  fall-through coverage — a selector loses its last governing rule
    C2  default-net removal   — the fallback itself weakens
    C3  reachability          — a rule shadowed / un-shadowed under first-match
    C5  dangling reference    — referential integrity, seeded by the change
    C6  exposure polarity     — WIDEN / NARROW / INVERT / NEUTRAL per change

Each check is a thin composition over the kernel (§4). Checks take a baseline
corpus and a proposed corpus and emit selector-relative, confidence-tagged
findings. Later stages add C4 (cross-policy overlap).
"""

from __future__ import annotations

from tools.impact import kernel
from tools.impact.findings import Confidence, Finding, Polarity
from tools.impact.kernel import Polarity as EffPolarity
from tools.impact.model import Corpus, Policy, Rule


# ============================================================================
# C6 — Exposure polarity (the headline check)
# ============================================================================


def check_c6_exposure_polarity(baseline: Corpus, proposed: Corpus) -> list[Finding]:
    """Classify each policy-level change by its net effect on exposure (§5-C6).

    Works per-policy (matched by @id). For each policy present in both corpora,
    compare rule lists position-wise plus set membership, and classify:

      WIDEN   — the change exposes strictly more
      NARROW  — the change exposes strictly less
      INVERT  — an effect flips polarity, or a transform is swapped
      NEUTRAL — provably no exposure change

    Added / removed whole policies are also classified (a new expose-bearing
    policy is WIDEN for its selector; a removed one NARROW, subject to §4.4).
    """
    findings: list[Finding] = []

    # Policies added or removed wholesale. Sorted for deterministic report order.
    for pid in sorted(proposed.ids() - baseline.ids()):
        findings.extend(_whole_policy_findings(proposed.get(pid), added=True))
    for pid in sorted(baseline.ids() - proposed.ids()):
        findings.extend(_whole_policy_findings(baseline.get(pid), added=False))

    # Policies present in both: diff their rules and default branch.
    for pid in sorted(baseline.ids() & proposed.ids()):
        findings.extend(_diff_policy_c6(baseline.get(pid), proposed.get(pid)))

    return findings


def _whole_policy_findings(policy: Policy | None, *, added: bool) -> list[Finding]:
    if policy is None:
        return []
    # A policy that exposes anywhere widens exposure when added, narrows when
    # removed. A purely-restrictive policy is the mirror.
    exposes = any(
        kernel.effect_polarity(r.effect) == EffPolarity.EXPOSE for r in policy.rules
    )
    restricts = any(
        kernel.effect_polarity(r.effect) in (EffPolarity.RESTRICT, EffPolarity.PARTIAL_RESTRICT)
        for r in _rules_and_default(policy)
    )
    subj = policy.applies_to.describe() if policy.applies_to else policy.id
    if added:
        pol = Polarity.WIDEN if exposes and not restricts else (
            Polarity.NARROW if restricts and not exposes else Polarity.INVERT
        )
        verb = "adds"
    else:
        pol = Polarity.NARROW if exposes and not restricts else (
            Polarity.WIDEN if restricts and not exposes else Polarity.INVERT
        )
        verb = "removes"
    return [
        Finding(
            check="C6",
            subject=f"scope {subj}",
            polarity=pol,
            consequence=(
                f"Change {verb} policy {policy.id}. Net exposure for the "
                f"attached scope shifts accordingly."
            ),
            confidence=Confidence.PROVEN,
            grounding="§4.3 effect polarity",
            policy_id=policy.id,
        )
    ]


def _rules_and_default(policy: Policy) -> list[Rule]:
    rules = list(policy.rules)
    if policy.default_branch is not None:
        rules.append(policy.default_branch)
    return rules


def _diff_policy_c6(base: Policy, prop: Policy) -> list[Finding]:
    findings: list[Finding] = []

    # Match rules across versions by principal selector (the stable key). A
    # rule whose selector exists in both is compared; selectors only in one
    # side are added/removed rules.
    base_by_sel = _index_by_selector(base.rules)
    prop_by_sel = _index_by_selector(prop.rules)

    base_keys = set(base_by_sel)
    prop_keys = set(prop_by_sel)

    # Iterate in source declaration order (dicts preserve insertion order, which
    # is rule order from _index_by_selector) so report output is deterministic.

    # Removed rules — in baseline order.
    for key in base_by_sel:
        if key not in prop_keys:
            findings.append(_removed_rule_finding(prop.id, base_by_sel[key]))

    # Added rules — in proposed order.
    for key in prop_by_sel:
        if key not in base_keys:
            findings.append(_added_rule_finding(prop.id, prop_by_sel[key]))

    # Rules present in both — in proposed order.
    for key in prop_by_sel:
        if key in base_keys:
            f = _changed_rule_finding(prop.id, base_by_sel[key], prop_by_sel[key])
            if f is not None:
                findings.append(f)

    return findings


def _index_by_selector(rules: list[Rule]) -> dict[str, Rule]:
    """Index rules by a stable selector key. Rules whose principal cannot be
    described distinctly fall back to positional keys to avoid collisions."""
    out: dict[str, Rule] = {}
    for i, r in enumerate(rules):
        key = r.principal.describe() if r.principal else f"<pos:{i}>"
        # Guard against two rules with the same selector: disambiguate.
        if key in out:
            key = f"{key}#{i}"
        out[key] = r
    return out


def _rule_subject(policy_id: str, rule: Rule) -> str:
    sel = rule.principal.describe() if rule.principal else "<no-principal>"
    return f"selector {sel}"


def _removed_rule_finding(policy_id: str, rule: Rule) -> Finding:
    pol = kernel.effect_polarity(rule.effect)
    # Removing an expose rule narrows; removing a restrict rule widens.
    if pol == EffPolarity.EXPOSE:
        polarity, word = Polarity.NARROW, "reduced"
    elif pol in (EffPolarity.RESTRICT, EffPolarity.PARTIAL_RESTRICT):
        polarity, word = Polarity.WIDEN, "increased"
    else:
        polarity, word = Polarity.INVERT, "changed"
    cond = _describe_condition(rule)
    return Finding(
        check="C6",
        subject=_rule_subject(policy_id, rule),
        polarity=polarity,
        consequence=(
            f"Removed a {rule.effect} rule{cond}. Net exposure for the "
            f"affected selector is strictly {word}."
        ),
        confidence=Confidence.PROVEN,
        grounding="§4.3 effect polarity",
        policy_id=policy_id,
    )


def _added_rule_finding(policy_id: str, rule: Rule) -> Finding:
    pol = kernel.effect_polarity(rule.effect)
    if pol == EffPolarity.EXPOSE:
        polarity, word = Polarity.WIDEN, "increased"
    elif pol in (EffPolarity.RESTRICT, EffPolarity.PARTIAL_RESTRICT):
        polarity, word = Polarity.NARROW, "reduced"
    else:
        polarity, word = Polarity.INVERT, "changed"
    cond = _describe_condition(rule)
    return Finding(
        check="C6",
        subject=_rule_subject(policy_id, rule),
        polarity=polarity,
        consequence=(
            f"Added a {rule.effect} rule{cond}. Net exposure for the "
            f"affected selector is strictly {word}."
        ),
        confidence=Confidence.PROVEN,
        grounding="§4.3 effect polarity",
        policy_id=policy_id,
    )


def _changed_rule_finding(policy_id: str, base: Rule, prop: Rule) -> Finding | None:
    # Effect changed?
    if base.effect != prop.effect:
        base_pol = kernel.effect_polarity(base.effect)
        prop_pol = kernel.effect_polarity(prop.effect)
        # Classification rule (scoping-doc §5-C6):
        #   * A full polarity flip between EXPOSE and RESTRICT (allow↔deny,
        #     keep↔drop) is INVERT — the doc reserves INVERT for exactly this.
        #   * A change involving PARTIAL_RESTRICT (transform) on one side is
        #     directional on the exposure ordering EXPOSE > PARTIAL > RESTRICT:
        #     more exposure → WIDEN, less → NARROW (a transform relaxed to
        #     allow widens; an allow tightened to transform narrows).
        #   * Anything the kernel can't rank falls back to INVERT ("changed;
        #     review it") rather than a fabricated direction.
        rank = {EffPolarity.EXPOSE: 2, EffPolarity.PARTIAL_RESTRICT: 1, EffPolarity.RESTRICT: 0}
        full = {EffPolarity.EXPOSE, EffPolarity.RESTRICT}
        if base_pol in full and prop_pol in full and base_pol != prop_pol:
            polarity = Polarity.INVERT
        elif base_pol in rank and prop_pol in rank:
            polarity = Polarity.WIDEN if rank[prop_pol] > rank[base_pol] else Polarity.NARROW
        else:
            polarity = Polarity.INVERT
        return Finding(
            check="C6",
            subject=_rule_subject(policy_id, prop),
            polarity=polarity,
            consequence=f"Rule effect changed {base.effect} → {prop.effect}.",
            confidence=Confidence.PROVEN,
            grounding="§4.3 effect polarity",
            policy_id=policy_id,
        )

    # Effect unchanged: did the condition value-set change?
    b_cond, p_cond = base.condition, prop.condition
    if b_cond == p_cond:
        # Transformation swap on a transform rule -> INVERT (scoping-doc §9.4).
        # There is no total order between two transformations — whether Hash is
        # "more exposed" than Redact depends on the threat model, which the tool
        # cannot read from the policy text. Rather than fabricate a WIDEN/NARROW
        # direction, C6 flags the swap as INVERT ("changed; review it"). This is
        # exactly the case the tool exists for: a new change silently altering
        # how an existing policy transforms data.
        if base.effect == "transform" and base.transformation != prop.transformation:
            return Finding(
                check="C6",
                subject=_rule_subject(policy_id, prop),
                polarity=Polarity.INVERT,
                consequence=(
                    f"Transformation changed "
                    f"{_tf(base.transformation)} → {_tf(prop.transformation)}. "
                    f"No total order between transforms; review the substitution."
                ),
                confidence=Confidence.PROVEN,
                grounding="ADR-016 (transformation parameterization) + §9.4",
                policy_id=policy_id,
            )
        return None  # genuinely no exposure-relevant change

    # Condition changed on a same-effect rule. Determine widen/narrow via
    # value-set containment, scoped to the rule's exposure polarity.
    pol = kernel.effect_polarity(base.effect)
    if not (kernel.condition_comparable(b_cond) and kernel.condition_comparable(p_cond)):
        return Finding(
            check="C6",
            subject=_rule_subject(policy_id, prop),
            polarity=Polarity.INVERT,
            consequence="Condition changed on an operator static analysis cannot compare.",
            confidence=Confidence.CANDIDATE,
            grounding="§4.4 unknown boundary",
            policy_id=policy_id,
            unknown="condition operator is opaque (e.g. exists-in-dataset)",
        )

    prop_superset = kernel.condition_value_superset(p_cond, b_cond)
    base_superset = kernel.condition_value_superset(b_cond, p_cond)

    # For an EXPOSE rule: a larger matched value-set exposes MORE.
    # For a RESTRICT/PARTIAL rule: a larger matched value-set restricts MORE.
    if prop_superset and not base_superset:
        larger = "prop"
    elif base_superset and not prop_superset:
        larger = "base"
    else:
        # incomparable columns or equal sets already handled -> flag as change
        return Finding(
            check="C6",
            subject=_rule_subject(policy_id, prop),
            polarity=Polarity.INVERT,
            consequence="Condition value-set changed without a containment relation.",
            confidence=Confidence.PROVEN,
            grounding="§4.2 value-set arithmetic",
            policy_id=policy_id,
        )

    grew = larger == "prop"
    if pol == EffPolarity.EXPOSE:
        polarity = Polarity.WIDEN if grew else Polarity.NARROW
    else:
        polarity = Polarity.NARROW if grew else Polarity.WIDEN

    direction = "increased" if polarity == Polarity.WIDEN else "decreased"
    change = _describe_condition_change(b_cond, p_cond, grew)
    return Finding(
        check="C6",
        subject=_rule_subject(policy_id, prop),
        polarity=polarity,
        consequence=f"{change} on a {base.effect} rule → exposure {direction}.",
        confidence=Confidence.PROVEN,
        grounding="§4.2 value-set arithmetic",
        policy_id=policy_id,
    )


def _describe_condition_change(b_cond, p_cond, grew: bool) -> str:
    """Phrase the condition change, handling the whole-condition add/remove
    cases (a rule becoming unconditional, or gaining a first condition) that a
    bare value-set diff would render as a confusing empty set."""
    if p_cond is None:
        return "Condition removed (rule is now unconditional)"
    if b_cond is None:
        return f"Condition added (matching {sorted(p_cond.values)})"
    delta = sorted(set(p_cond.values) ^ set(b_cond.values))
    return f"Condition value-set {'gained' if grew else 'lost'} {delta}"


def _describe_condition(rule: Rule) -> str:
    if rule.condition is None or not rule.condition.values:
        return ""
    return f" (kept {sorted(rule.condition.values)})"


def _tf(tf: dict | None) -> str:
    if not tf:
        return "none"
    return str(tf.get("type", tf))


# ============================================================================
# C5 — Dangling reference
# ============================================================================


def check_c5_dangling_reference(baseline: Corpus, proposed: Corpus) -> list[Finding]:
    """Referential-integrity check, seeded by the change (§5-C5).

    The check examines only policies the change *touched* — those added in the
    proposed corpus, or present in both but with differing content. Pre-existing
    issues in unchanged files are out of scope: this is change-impact analysis,
    not a whole-corpus linter (that is the Priority-5 linter's job).

    For each changed policy it flags references left dangling by the edit:
      * baselineGroup naming a group no rule targets;
      * a condition operand column outside the (possibly narrowed) appliesTo;
      * an unprefixed attribute axis key not declared in the ontology (adopter-
        namespaced axes, carrying a `prefix:` per ADR-018, are legitimate
        extensions and are not flagged).
    Cross-file dataset references (tableRef) are structural but their contents
    are opaque (§4.4); only the reference's presence is checked.
    """
    findings: list[Finding] = []
    for pid, policy in proposed.policies.items():
        base = baseline.get(pid)
        if base is not None and base.raw == policy.raw:
            continue  # unchanged policy — not part of this change
        findings.extend(_c5_policy(policy))
    return findings


def _c5_policy(policy: Policy) -> list[Finding]:
    findings: list[Finding] = []

    # baselineGroup must be targeted by some rule under explicit-baseline-group.
    if policy.default_strategy == "explicit-baseline-group" and policy.baseline_group:
        bg = policy.baseline_group
        # A rule targets it if some principal resource IRI's last segment
        # matches the baseline group (accounting for the IRI-safety convention
        # noted in the group-row-visibility example, where "account users"
        # is carried as group:account-users).
        targeted = any(
            _principal_matches_group(r.principal, bg) for r in policy.rules
        )
        if not targeted:
            findings.append(
                Finding(
                    check="C5",
                    subject=f"baselineGroup '{bg}'",
                    consequence=(
                        f"defaultStrategy is explicit-baseline-group but no rule "
                        f"targets baselineGroup '{bg}'. The default branch is "
                        f"unreachable."
                    ),
                    confidence=Confidence.PROVEN,
                    grounding="ADR-013 (baselineGroup↔strategy invariant)",
                    policy_id=policy.id,
                )
            )

    # Condition operand columns must sit within the appliesTo scope/resource.
    scope_iri = None
    if policy.applies_to:
        scope_iri = policy.applies_to.resource or policy.applies_to.scope
    if scope_iri:
        for r in _rules_and_default(policy):
            if r.condition is None:
                continue
            for operand in r.condition.operands:
                if not _operand_within_scope(operand, scope_iri):
                    findings.append(
                        Finding(
                            check="C5",
                            subject=f"condition operand {operand}",
                            consequence=(
                                f"Condition references column '{operand}' outside the "
                                f"policy's appliesTo scope '{scope_iri}'."
                            ),
                            confidence=Confidence.PROVEN,
                            grounding="structural (operand within appliesTo)",
                            policy_id=policy.id,
                        )
                    )

    # Attribute axis keys in byScope matching must be known axes.
    for sel in _all_selectors(policy):
        for axis_key, _val in sel.attributes:
            if not _is_known_axis(axis_key):
                findings.append(
                    Finding(
                        check="C5",
                        subject=f"attribute axis '{axis_key}'",
                        consequence=(
                            f"Selector references attribute axis '{axis_key}' not "
                            f"declared in the ontology."
                        ),
                        confidence=Confidence.PROVEN,
                        grounding="ADR-018 (declared axes)",
                        policy_id=policy.id,
                    )
                )

    return findings


def _principal_matches_group(principal, group: str) -> bool:
    if principal is None or not principal.resource:
        return False
    res = principal.resource
    tail = res.split(":", 1)[1] if ":" in res else res
    # Compare against the group name and its IRI-safe slug (spaces -> hyphens).
    slug = group.replace(" ", "-")
    return tail in (group, slug)


# ABAC sentinel operands that resolve to the matched column/scope at emission
# time rather than naming a fixed path. They are never "outside" any scope.
_SENTINEL_OPERANDS = {"column:$matched", "$matched"}


def _operand_within_scope(operand: str, scope_iri: str) -> bool:
    # ABAC sentinels (`column:$matched`) are placeholders the adapter binds to
    # the matched column at emission; they carry no fixed path to check.
    if operand in _SENTINEL_OPERANDS:
        return True
    # A column operand `column:a.b.c.col` is within `table:a.b.c` /
    # `catalog:a` / `schema:a.b` when the scope's path is a prefix.
    return kernel.scope_contains(scope_iri, operand)


def _all_selectors(policy: Policy):
    if policy.applies_to:
        yield policy.applies_to
    for r in _rules_and_default(policy):
        if r.principal:
            yield r.principal


def _is_known_axis(axis_key: str) -> bool:
    # Adopter-namespaced axes (carrying a `prefix:`) are legitimate extensions
    # per ADR-018; static analysis cannot know the adopter's ontology, so it
    # does not flag them. Only unprefixed keys are checked against v0's axes.
    if ":" in axis_key:
        return True
    _supers, axis_types = kernel._ontology_relations()
    return f"{axis_key}Axis" in axis_types


# ============================================================================
# C1 — Fall-through coverage
# ============================================================================


# Plain-language description of what each strategy's terminal does when a
# principal matches no rule. Read straight from the declared intent (ADR-013);
# no evaluation of who those principals are.
_STRATEGY_TERMINAL = {
    "none": "fail-closed terminal (no rows / full restriction)",
    "explicit-baseline-group": "the baselineGroup rule's grant (if a baseline member)",
    "negated-complement": "the defaultBranch effect",
    None: "an unspecified fallback (no defaultStrategy declared)",
}


def check_c1_fallthrough_coverage(baseline: Corpus, proposed: Corpus) -> list[Finding]:
    """Detect selectors that lose their last governing rule (§5-C1).

    Per policy matched by @id, count the governing rules for each principal
    selector before and after. A selector dropping to zero rules changes
    coverage class for the principals matching it; the consequence is read from
    the policy's declared defaultStrategy (ADR-013) — no population is resolved.

    PROVEN: the selector's rule count dropped to zero.
    CANDIDATE: the downstream fate under explicit-baseline-group depends on
    baseline-group membership, which static analysis cannot see (§4.4).
    """
    findings: list[Finding] = []
    for pid in sorted(baseline.ids() & proposed.ids()):
        base, prop = baseline.get(pid), proposed.get(pid)
        base_sels = _selector_rule_counts(base)
        prop_sels = _selector_rule_counts(prop)
        for sel_key, count in base_sels.items():
            if count > 0 and prop_sels.get(sel_key, 0) == 0:
                findings.append(_c1_finding(prop, sel_key))
    return findings


def _selector_rule_counts(policy: Policy) -> dict[str, int]:
    """Count governing rules per principal-selector key. The defaultBranch is
    not counted — it has no principal (it applies to whoever matched no rule),
    so it is not a governing rule *for* any selector."""
    counts: dict[str, int] = {}
    for r in policy.rules:
        if r.principal is None:
            continue
        key = r.principal.describe()
        counts[key] = counts.get(key, 0) + 1
    return counts


def _c1_finding(policy: Policy, sel_key: str) -> Finding:
    strategy = policy.default_strategy
    terminal = _STRATEGY_TERMINAL.get(strategy, "the declared fallback")
    # The downstream fate is a CANDIDATE only under explicit-baseline-group,
    # where it hinges on unseen baseline membership. Under none/negated-
    # complement the terminal is fully determined by the declared policy.
    if strategy == "explicit-baseline-group":
        confidence = Confidence.CANDIDATE
        unknown = "baseline-group membership is not visible to static analysis"
    else:
        confidence = Confidence.PROVEN
        unknown = None
    return Finding(
        check="C1",
        subject=f"selector {sel_key}",
        consequence=(
            f"Lost its last governing rule. defaultStrategy = "
            f"{strategy or '(none declared)'}. Principals matching this "
            f"selector now fall through to {terminal}."
        ),
        confidence=confidence,
        grounding="ADR-013 (declared default-handling intent)",
        policy_id=policy.id,
        unknown=unknown,
    )


# ============================================================================
# C2 — Default-net removal or weakening
# ============================================================================

# Ordering of default strategies by how much of a safety net they provide when
# a principal matches no rule. `none` is fail-closed (strongest restriction,
# weakest net); a baseline/complement branch grants *something* to the
# unmatched set (weaker restriction, stronger net). Moving toward `none`
# removes net; moving away adds it. This is a declared-intent ordering
# (ADR-013/014), not a runtime measurement.
_NET_STRENGTH = {
    "none": 0,
    "explicit-baseline-group": 1,
    "negated-complement": 1,
}


def check_c2_default_net(baseline: Corpus, proposed: Corpus) -> list[Finding]:
    """Detect changes to the fallback itself (§5-C2).

    Flags: defaultStrategy changing; the baselineGroup value changing; the
    defaultBranch being added or removed. All are direct comparisons of
    policy-level default-handling fields against the ADR-013/014 invariants —
    PROVEN, since they are structural properties of the declared policy.
    """
    findings: list[Finding] = []
    for pid in sorted(baseline.ids() & proposed.ids()):
        base, prop = baseline.get(pid), proposed.get(pid)

        if base.default_strategy != prop.default_strategy:
            findings.append(_c2_strategy_finding(base, prop))

        if base.baseline_group != prop.baseline_group:
            findings.append(
                Finding(
                    check="C2",
                    subject=f"baselineGroup",
                    consequence=(
                        f"baselineGroup changed "
                        f"{base.baseline_group!r} → {prop.baseline_group!r}. The "
                        f"default branch now grounds in a different group; the set "
                        f"of principals receiving baseline coverage shifts."
                    ),
                    confidence=Confidence.PROVEN,
                    grounding="ADR-013 (baselineGroup grounds the default branch)",
                    policy_id=prop.id,
                )
            )

        base_has_branch = base.default_branch is not None
        prop_has_branch = prop.default_branch is not None
        if base_has_branch and not prop_has_branch:
            findings.append(
                Finding(
                    check="C2",
                    subject="defaultBranch",
                    polarity=Polarity.NARROW,
                    consequence=(
                        "defaultBranch removed. Principals matching no rule lose "
                        "their explicit fallback effect."
                    ),
                    confidence=Confidence.PROVEN,
                    grounding="ADR-014 (defaultBranch under negated-complement)",
                    policy_id=prop.id,
                )
            )
        elif prop_has_branch and not base_has_branch:
            findings.append(
                Finding(
                    check="C2",
                    subject="defaultBranch",
                    consequence=(
                        "defaultBranch added. Principals matching no rule now "
                        "receive an explicit fallback effect."
                    ),
                    confidence=Confidence.PROVEN,
                    grounding="ADR-014 (defaultBranch under negated-complement)",
                    policy_id=prop.id,
                )
            )

    return findings


def _c2_strategy_finding(base: Policy, prop: Policy) -> Finding:
    b_net = _NET_STRENGTH.get(base.default_strategy)
    p_net = _NET_STRENGTH.get(prop.default_strategy)
    polarity = None
    net_note = ""
    if b_net is not None and p_net is not None and b_net != p_net:
        if p_net < b_net:
            # Toward `none`: the fail-closed terminal replaces a grant. For the
            # unmatched principals this is a NARROW (they now see less).
            polarity = Polarity.NARROW
            net_note = (
                " Fail-closed terminal replaces a fallback grant; principals "
                "previously covered by the default net now match nothing."
            )
        else:
            polarity = Polarity.WIDEN
            net_note = (
                " A fallback grant replaces the fail-closed terminal; principals "
                "previously seeing nothing now inherit default coverage."
            )
    return Finding(
        check="C2",
        subject="defaultStrategy",
        polarity=polarity,
        consequence=(
            f"defaultStrategy changed "
            f"{base.default_strategy or '(none)'} → "
            f"{prop.default_strategy or '(none)'}.{net_note}"
        ),
        confidence=Confidence.PROVEN,
        grounding="ADR-013 / ADR-014 (default-handling intent)",
        policy_id=prop.id,
        # The *magnitude* for a byDataset/ACL policy depends on ACL contents we
        # do not read; note it where the policy's rules are opaque.
        unknown=(
            "row/principal magnitude depends on data not read by static analysis"
            if _policy_has_opaque_selector(prop)
            else None
        ),
    )


def _policy_has_opaque_selector(policy: Policy) -> bool:
    for sel in _all_selectors(policy):
        if kernel.selector_opaque(sel):
            return True
    return False


# ============================================================================
# C3 — Reachability / shadowing
# ============================================================================
#
# Under ordered first-match (ADR-015), a rule is unreachable ("shadowed") when
# some earlier rule provably matches every principal-and-condition case the
# later rule would. C3 reports two change deltas:
#
#   * a rule NEWLY shadowed by the change — dead policy introduced;
#   * a rule NEWLY un-shadowed by the change — dormant policy silently
#     activated (the scoping doc flags this as the more dangerous direction).
#
# This is the check nearest the ADR-001 line. It reasons ONLY about selector
# *expressions* subsuming one another (kernel.selector_subsumes) and condition
# value-set containment (kernel.condition_value_superset) — never about which
# concrete principals populate a selector. Shadowing that would depend on group
# membership or a group-subset relation is unknowable and is deliberately not
# claimed: opaque selectors never subsume (kernel), so a pair involving one
# simply does not produce a shadowing finding.


def check_c3_reachability(baseline: Corpus, proposed: Corpus) -> list[Finding]:
    """Report rules whose reachability changed under first-match (§5-C3).

    For each policy in both corpora, compute the provably-shadowed rule set
    before and after the change, and emit a finding for each rule that crossed
    the reachability boundary. Every finding is PROVEN: it is only emitted when
    an earlier rule's selector AND condition provably subsume the later rule's
    (opaque selectors never subsume, so membership-dependent shadowing is never
    guessed).
    """
    findings: list[Finding] = []
    for pid in sorted(baseline.ids() & proposed.ids()):
        base, prop = baseline.get(pid), proposed.get(pid)

        base_shadowed = _shadowed_rules(base)
        prop_shadowed = _shadowed_rules(prop)

        # Key shadowed rules by their selector description so we compare the
        # *same* rule across versions rather than by list index (which shifts
        # when rules are added/removed).
        base_keys = {_rule_key(base, i): i for i in base_shadowed}
        prop_keys = {_rule_key(prop, i): i for i in prop_shadowed}

        # Newly shadowed: shadowed in proposed, and either absent from baseline
        # or not shadowed there.
        for key, idx in prop_keys.items():
            if key not in base_keys:
                by_idx = prop_shadowed[idx]
                findings.append(_c3_shadowed_finding(prop, idx, by_idx, key))

        # Newly un-shadowed: was shadowed in baseline, now reachable (present in
        # proposed but no longer shadowed).
        prop_rule_keys = {_rule_key(prop, i) for i in range(len(prop.rules))}
        for key, idx in base_keys.items():
            if key in prop_rule_keys and key not in prop_keys:
                findings.append(_c3_unshadowed_finding(prop, key))

    return findings


def _rule_key(policy: Policy, index: int) -> str:
    """A stable per-rule key: principal selector + condition signature. Two
    rules with an identical selector are disambiguated by their condition, and
    finally by index, so distinct rules never collide."""
    rule = policy.rules[index]
    sel = rule.principal.describe() if rule.principal else "<no-principal>"
    cond = rule.condition
    if cond is None:
        cond_sig = "∅"
    else:
        cond_sig = f"{cond.op}:{','.join(cond.operands)}={','.join(sorted(cond.values))}"
    return f"{sel}||{cond_sig}"


def _shadowed_rules(policy: Policy) -> dict[int, int]:
    """Map each provably-unreachable rule index to the index of an earlier rule
    that shadows it (§5-C3 mechanism).

    Rule j is shadowed by an earlier rule i (i < j) when i provably matches
    every case j would: i.selector ⊇ j.selector AND i's condition is a superset
    of j's (an unconditional earlier rule is a superset of any condition). Only
    provable subsumptions count; opaque selectors never subsume, so a rule
    behind an opaque earlier rule is not claimed shadowed.
    """
    shadowed: dict[int, int] = {}
    rules = policy.rules
    for j in range(len(rules)):
        for i in range(j):
            if i in shadowed:
                # An already-dead rule cannot do the shadowing (it never fires).
                continue
            if _rule_shadows(rules[i], rules[j]):
                shadowed[j] = i
                break
    return shadowed


def _rule_shadows(earlier: Rule, later: Rule) -> bool:
    """True if `earlier` provably fires in every case `later` would (§4.2)."""
    if not kernel.selector_subsumes(earlier.principal, later.principal):
        return False
    # earlier's condition must be a superset of later's matched set. A None
    # (unconditional) earlier condition subsumes any later condition.
    return kernel.condition_value_superset(earlier.condition, later.condition)


def _c3_shadowed_finding(policy: Policy, idx: int, by_idx: int, key: str) -> Finding:
    later_sel = policy.rules[idx].principal.describe() if policy.rules[idx].principal else "?"
    earlier_sel = policy.rules[by_idx].principal.describe() if policy.rules[by_idx].principal else "?"
    return Finding(
        check="C3",
        subject=f"selector {later_sel}",
        consequence=(
            f"Rule {idx} (selector {later_sel}) is now unreachable: earlier rule "
            f"{by_idx} (selector {earlier_sel}) provably matches every case it "
            f"would, under ordered first-match. The rule is dead code."
        ),
        confidence=Confidence.PROVEN,
        grounding="ADR-015 (ordered first-match) + §4.2 subsumption",
        policy_id=policy.id,
    )


def _c3_unshadowed_finding(policy: Policy, key: str) -> Finding:
    sel = key.split("||", 1)[0]
    return Finding(
        check="C3",
        subject=f"selector {sel}",
        consequence=(
            f"A previously-unreachable rule (selector {sel}) is now reachable "
            f"under ordered first-match. Dormant policy has been activated — "
            f"verify the newly-live effect is intended."
        ),
        confidence=Confidence.PROVEN,
        grounding="ADR-015 (ordered first-match) + §4.2 subsumption",
        policy_id=policy.id,
    )


# ============================================================================
# L1 — Dead-rule lint (whole-corpus, not change-seeded)
# ============================================================================
#
# C3 reports reachability *changes* between two corpus versions. L1 is the
# standing lint counterpart: it reports every provably-dead rule in a single
# corpus state, regardless of when it went dead. Same reachability mechanism
# and the same ADR-001 guard (opaque selectors never subsume, so a dead-rule
# claim is never membership-dependent); different framing — a health check on
# the corpus as it stands, not a diff. This is what powers the "lint my whole
# corpus for dead rules" mode.


def lint_dead_rules(corpus: Corpus) -> list[Finding]:
    """Report every provably-unreachable rule across a whole corpus (L1).

    For each policy, compute its shadowed-rule set and emit one PROVEN finding
    per dead rule, naming the earlier rule that shadows it. Unlike C3 this does
    not diff versions — it audits the corpus as it currently stands.
    """
    findings: list[Finding] = []
    for pid in sorted(corpus.ids()):
        policy = corpus.get(pid)
        shadowed = _shadowed_rules(policy)
        for idx in sorted(shadowed):
            by_idx = shadowed[idx]
            findings.append(_l1_dead_rule_finding(policy, idx, by_idx))
    return findings


def _l1_dead_rule_finding(policy: Policy, idx: int, by_idx: int) -> Finding:
    later_sel = policy.rules[idx].principal.describe() if policy.rules[idx].principal else "?"
    earlier_sel = policy.rules[by_idx].principal.describe() if policy.rules[by_idx].principal else "?"
    return Finding(
        check="L1",
        subject=f"rule {idx} (selector {later_sel})",
        consequence=(
            f"Rule {idx} (selector {later_sel}) is unreachable: earlier rule "
            f"{by_idx} (selector {earlier_sel}) provably matches every case it "
            f"would, under ordered first-match. The rule is dead code and can be "
            f"removed or reordered."
        ),
        confidence=Confidence.PROVEN,
        grounding="ADR-015 (ordered first-match) + §4.2 subsumption",
        policy_id=policy.id,
    )


# ============================================================================
# C4 — Cross-policy overlap / conflict  (and L2, its standing counterpart)
# ============================================================================
#
# Two policies of the same policyKind whose attachment scopes provably overlap
# AND whose attribute-matches provably overlap, but whose effects diverge, are
# the MULTIPLE_MASKS situation that drove ADR-023. On a platform declaring
# `single-column-mask-per-column` / `single-row-filter-per-table`, the adapter
# will refuse to emit the pair; Tessera surfaces the conflict at analysis time.
#
# C4 stays strictly static (the ADR-001 line): it proves scope-IRI containment
# and attribute-axis subsumption from the policy text, and reports the overlap
# plus the ADR-023 resolution rule. It does NOT compute which policy "wins" at
# runtime — γ-with-refinement leaves that to the author, guided by the finding.
#
# Only these policyKinds are subject to the platform single-policy-per-target
# constraint; RowVisibility filters compose (AND) rather than conflict, so
# overlapping row-visibility policies are not flagged as conflicts here.
_CONFLICTING_KINDS = {
    "ColumnVisibilityConstraint": "single-column-mask-per-column",
    "RowVisibilityConstraint": "single-row-filter-per-table",
}


def check_c4_cross_policy_overlap(baseline: Corpus, proposed: Corpus) -> list[Finding]:
    """Report cross-policy overlaps the change introduces or resolves (§5-C4).

    Computes the provable-overlap pair set in each corpus and reports the
    delta: pairs that are newly overlapping in the proposed corpus (a conflict
    introduced) and pairs no longer overlapping (a conflict resolved). This is
    the diff view, run alongside the other change-impact checks.
    """
    findings: list[Finding] = []
    base_pairs = _overlap_pairs(baseline)
    prop_pairs = _overlap_pairs(proposed)

    base_keys = {p[0] for p in base_pairs}
    prop_map = {p[0]: p for p in prop_pairs}
    prop_keys = set(prop_map)

    for key in sorted(prop_keys - base_keys):
        findings.append(_c4_overlap_finding(prop_map[key], introduced=True))
    base_map = {p[0]: p for p in base_pairs}
    for key in sorted(base_keys - prop_keys):
        findings.append(_c4_overlap_finding(base_map[key], introduced=False))

    return findings


def _unpack_pair(pair):
    key, pid_a, pid_b, kind, constraint, confidence, unknown, divergent = pair
    return key, pid_a, pid_b, kind, constraint, confidence, unknown, divergent


def lint_cross_policy_overlap(corpus: Corpus) -> list[Finding]:
    """Report every current cross-policy overlap in a corpus (L2).

    The standing counterpart to C4: audits the corpus as it stands, flagging
    all same-kind scope+attribute overlaps subject to a single-policy platform
    constraint, regardless of when they were introduced.
    """
    return [_c4_overlap_finding(pair, introduced=None) for pair in _overlap_pairs(corpus)]


def _overlap_pairs(corpus: Corpus):
    """Return the sorted list of overlapping policy pairs.

    Each entry is (key, pid_a, pid_b, kind, constraint, confidence, unknown,
    divergent), where key is a stable sorted-id string. A pair is included when
    two same-policyKind policies (of a kind subject to a single-policy platform
    constraint) resolve to an overlapping target — because ADR-023's
    `single-column-mask-per-column` / `single-row-filter-per-table` constraints
    are about MULTIPLICITY: the platform permits at most one such policy per
    target, so two overlapping ones conflict whether or not their effects
    differ. `divergent` records whether the effects differ, for the message
    (divergent masks vs. a duplicate), not as a gate. Confidence is PROVEN when
    the overlap follows from the policy text alone, CANDIDATE when it would
    require assuming a concrete resource carries an attribute tag (§4.4).
    """
    pairs = []
    ids = sorted(corpus.ids())
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = corpus.get(ids[i]), corpus.get(ids[j])
            result = _policies_conflict(a, b)
            if result is not None:
                constraint, confidence, unknown = result
                key = "||".join(sorted((a.id, b.id)))
                lo, hi = sorted((a.id, b.id))
                pairs.append((key, lo, hi, a.policy_kind, constraint, confidence,
                              unknown, _effects_diverge(a, b)))
    pairs.sort(key=lambda p: p[0])
    return pairs


def _policies_conflict(a: Policy, b: Policy):
    """Return (constraint, confidence, unknown) if a and b conflict, else None.

    Conflict requires: same conflict-prone policyKind, overlapping scope, and
    overlapping attribute-match (§4.2 + ADR-023). Effect divergence is NOT a
    requirement — the platform constraints are about multiplicity (at most one
    mask per column / one row filter per table), so two overlapping same-kind
    policies conflict even with identical effects. Divergence is reported as
    information by the finding, not used to gate here.

    Confidence discipline (the ADR-001 line): overlap between two attribute
    *predicates* (both byScope) or between two *concrete* resources (both
    byIdentity paths) is PROVEN — it follows from scope containment and ontology
    subsumption alone. But overlap between an attribute-constrained predicate
    and a concrete resource is only CANDIDATE: proving it would require knowing
    whether that specific resource carries the attribute tag, which is a
    platform-tagging fact static analysis does not read.
    """
    if a.policy_kind != b.policy_kind:
        return None
    constraint = _CONFLICTING_KINDS.get(a.policy_kind or "")
    if constraint is None:
        return None
    if not _scopes_overlap(a.applies_to, b.applies_to):
        return None
    if not _attributes_overlap(a.applies_to, b.applies_to):
        return None

    confidence, unknown = _overlap_confidence(a.applies_to, b.applies_to)
    return constraint, confidence, unknown


def _overlap_confidence(a: Selector | None, b: Selector | None):
    """Classify an overlap as PROVEN or CANDIDATE (§4.4 boundary).

    CANDIDATE exactly when one side constrains attributes and the other names a
    concrete resource whose membership in that attribute set is unknown."""
    a_attr = bool(a and a.attributes)
    b_attr = bool(b and b.attributes)
    a_concrete = _is_concrete_resource(a)
    b_concrete = _is_concrete_resource(b)
    if (a_attr and b_concrete) or (b_attr and a_concrete):
        constrained = a if a_attr else b
        concrete = b if a_attr else a
        axis_desc = ", ".join(f"{k}:{v}" for k, v in (constrained.attributes if constrained else ()))
        return Confidence.CANDIDATE, (
            f"whether resource '{concrete.resource}' carries attribute(s) "
            f"[{axis_desc}] is a platform-tagging fact not visible to static analysis"
        )
    return Confidence.PROVEN, None


def _is_concrete_resource(sel: Selector | None) -> bool:
    """True if the selector names a concrete resource IRI with no attribute
    predicate (byIdentity resource:…), as opposed to a byScope predicate."""
    return bool(sel and sel.resource and not sel.attributes)


def _scopes_overlap(a: Selector | None, b: Selector | None) -> bool:
    """True if two appliesTo selectors provably target a common resource.

    Handles both the byScope form (scope IRI containment either direction) and
    the byIdentity/resource form (equal resource IRIs, or one containing the
    other as a scope path)."""
    if a is None or b is None:
        return False
    a_iri = a.scope or a.resource
    b_iri = b.scope or b.resource
    if not a_iri or not b_iri:
        return False
    return kernel.scope_contains(a_iri, b_iri) or kernel.scope_contains(b_iri, a_iri)


def _attributes_overlap(a: Selector | None, b: Selector | None) -> bool:
    """True if two selectors' attribute-matches provably intersect.

    Two attribute sets intersect when, for every axis they share, one value
    subsumes the other (§4.2 #4). An axis constrained by only one side does not
    block intersection (the other side is unconstrained on that axis, i.e.
    matches any value). If neither side constrains any attribute, the whole
    scope is matched and they trivially overlap."""
    a_attrs = dict(a.attributes) if a else {}
    b_attrs = dict(b.attributes) if b else {}
    shared = set(a_attrs) & set(b_attrs)
    for axis in shared:
        av, bv = a_attrs[axis], b_attrs[axis]
        if not (kernel.attribute_value_subsumes(axis, av, bv)
                or kernel.attribute_value_subsumes(axis, bv, av)):
            return False
    return True


def _effects_diverge(a: Policy, b: Policy) -> bool:
    """True if the two policies would impose different transformations/effects
    on the overlapping target. A conservative signature comparison: same effect
    AND same transformation means no conflict; any difference diverges.

    For column masks the transformation is the discriminator (Redact vs Hash on
    the same column is the MULTIPLE_MASKS case). We compare the effective
    (rule-level) transformation signatures across each policy."""
    return _policy_effect_signature(a) != _policy_effect_signature(b)


def _policy_effect_signature(policy: Policy):
    """A hashable signature of what a policy does to its target: the sorted set
    of (effect, transformation-type) pairs across its rules and default branch."""
    sig = set()
    for rule in _rules_and_default(policy):
        tf_type = None
        if rule.transformation:
            tf_type = rule.transformation.get("type")
        sig.add((rule.effect, tf_type))
    return frozenset(sig)


def _c4_overlap_finding(pair, *, introduced: bool | None) -> Finding:
    _key, pid_a, pid_b, kind, constraint, confidence, unknown, divergent = _unpack_pair(pair)
    overlap_word = "provably overlap" if confidence is Confidence.PROVEN else "may overlap"
    # Divergence is not required for the conflict (multiplicity is), but it
    # tells the reader whether they are looking at two different masks/filters
    # or a redundant duplicate — both of which the platform still rejects.
    effect_note = "with divergent effects" if divergent else "with the same effect (duplicate coverage)"
    if introduced is True:
        lead = "Change introduces a cross-policy overlap:"
        tail = ("On a platform declaring this constraint the adapter will refuse to "
                "emit the pair; resolve before deployment (ADR-023 γ-with-refinement).")
    elif introduced is False:
        lead = "Change resolves a previously-overlapping pair:"
        tail = "The conflicting overlap is no longer present."
    else:
        lead = "Cross-policy overlap:"
        tail = ("On a platform declaring this constraint the adapter will refuse to "
                "emit the pair; resolve before deployment (ADR-023 γ-with-refinement).")
    check = "C4" if introduced is not None else "L2"
    return Finding(
        check=check,
        subject=f"{pid_a} ∩ {pid_b}",
        consequence=(
            f"{lead} {pid_a} and {pid_b} are both {kind} policies whose scopes and "
            f"attribute-matches {overlap_word}, {effect_note} — the "
            f"platform '{constraint}' constraint. {tail}"
        ),
        confidence=confidence,
        grounding="ADR-023 (γ-with-refinement) + §4.2 overlap",
        policy_id=pid_a,
        unknown=unknown,
    )
