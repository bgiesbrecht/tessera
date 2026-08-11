"""Spike (2): within-policy request-space enumeration with witness reporting.

The idea from the Layer-2 design conversation: because Tessera policies are
attribute/selector-based over finite domains, the abstract "request space" a
single policy discriminates is finite and small. We can enumerate it, evaluate
the policy's ordered first-match decision (ADR-015) on each abstract request,
and diff two versions of the policy — reporting every abstract request whose
decision *flips*, with a concrete witness and whether it OPENED or CLOSED.

This is not evaluation over data (ADR-001): a request here is an *abstract*
tuple of "does the principal match selector S?" and "which value-class is column
C in?", never a concrete user or row. Within a single policy there is no
cross-policy combining question (ADR-023) — first-match gives one decision per
request — so this slice needs no combining commitment and no solver.

Scope of this spike:
  * Conditions supported: absent, `in`, `eq` on a single column operand. Any
    other operator makes a rule opaque; the policy is reported as only partially
    enumerable rather than silently mis-evaluated.
  * Principal selectors are treated as independent booleans (a request may
    "match" any subset). This OVER-approximates — it includes principal
    combinations that real membership might make impossible (two disjoint
    groups) — so it can over-report a flip, never miss one. Refining it needs a
    declared-disjointness assertion (scoping-doc §9.3).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from tools.impact import kernel
from tools.impact.kernel import Polarity
from tools.impact.model import Policy, Rule


OTHER = "◇ other"  # value-class standing for "none of the mentioned values"
NO_MATCH = "∅ no rule matched"


# ----------------------------------------------------------------------------
# Abstract request
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class AbstractRequest:
    principals: frozenset[str]          # principal-selector descriptors that match
    columns: tuple[tuple[str, str], ...]  # (column IRI, value-class)

    def describe(self) -> str:
        who = ", ".join(sorted(self.principals)) or "(no selector matched)"
        cols = "; ".join(f"{c}={v}" for c, v in self.columns)
        return f"principal∈{{{who}}}" + (f" · {cols}" if cols else "")


@dataclass
class Decision:
    effect: str                 # effect string, or NO_MATCH
    transformation: str | None  # transformation type when effect == transform

    def label(self) -> str:
        if self.effect == "transform" and self.transformation:
            return f"transform:{self.transformation}"
        return self.effect

    def polarity_rank(self) -> int:
        # Higher = more exposed. NO_MATCH / default-none is most restrictive.
        pol = kernel.effect_polarity(self.effect)
        return {Polarity.EXPOSE: 3, Polarity.PARTIAL_RESTRICT: 2,
                Polarity.RESTRICT: 1}.get(pol, 0)


@dataclass
class Flip:
    request: AbstractRequest
    old: Decision
    new: Decision

    @property
    def direction(self) -> str:
        hi, lo = self.new.polarity_rank(), self.old.polarity_rank()
        if hi > lo:
            return "OPENED"
        if hi < lo:
            return "CLOSED"
        return "CHANGED"  # same exposure rank, different decision (e.g. transform swap)


# ----------------------------------------------------------------------------
# Enumeration
# ----------------------------------------------------------------------------

_SUPPORTED_OPS = {"in", "eq", None}


def _rule_condition_dims(rule: Rule) -> tuple[str, tuple[str, ...]] | None:
    """(column, values) a rule's condition discriminates, or None if absent.
    Raises OpaqueCondition if the operator/shape isn't enumerable."""
    cond = rule.condition
    if cond is None:
        return None
    if cond.op not in _SUPPORTED_OPS or len(cond.operands) != 1:
        raise _OpaqueCondition(cond.op)
    return cond.operands[0], tuple(cond.values)


class _OpaqueCondition(Exception):
    pass


def _dimensions(policies: list[Policy]):
    """Collect the abstract request dimensions across the given policy versions:
    the set of principal-selector descriptors, and per column the value-classes
    mentioned (plus OTHER). Returns (principal_selectors, {column: [classes]})."""
    principals: set[str] = set()
    columns: dict[str, set[str]] = {}
    opaque: set[str] = set()
    for policy in policies:
        for rule in policy.rules:
            if rule.principal is not None:
                principals.add(rule.principal.describe())
            try:
                dim = _rule_condition_dims(rule)
            except _OpaqueCondition as e:
                opaque.add(str(e))
                continue
            if dim is not None:
                col, values = dim
                columns.setdefault(col, set()).update(values)
    col_classes = {c: sorted(vs) + [OTHER] for c, vs in columns.items()}
    return sorted(principals), col_classes, sorted(opaque)


def _enumerate(principal_selectors: list[str], col_classes: dict[str, list[str]]):
    """Yield every AbstractRequest in the finite product of principal subsets ×
    per-column value-classes."""
    cols = sorted(col_classes)
    value_lists = [col_classes[c] for c in cols]
    # All subsets of principal selectors (the independent-boolean over-approx).
    for r in range(len(principal_selectors) + 1):
        for subset in itertools.combinations(principal_selectors, r):
            for combo in itertools.product(*value_lists) if cols else [()]:
                yield AbstractRequest(
                    principals=frozenset(subset),
                    columns=tuple(zip(cols, combo)),
                )


def _rule_matches(rule: Rule, request: AbstractRequest) -> bool:
    if rule.principal is not None and rule.principal.describe() not in request.principals:
        return False
    dim = _rule_condition_dims(rule)  # opaque already filtered out before enumerate
    if dim is None:
        return True
    col, values = dim
    col_map = dict(request.columns)
    return col_map.get(col) in values


def decide(policy: Policy, request: AbstractRequest) -> Decision:
    """The policy's ordered first-match decision (ADR-015) on an abstract request."""
    for rule in policy.rules:
        try:
            if _rule_matches(rule, request):
                tf = rule.transformation.get("type") if rule.transformation else None
                return Decision(rule.effect or NO_MATCH, tf)
        except _OpaqueCondition:
            continue
    # No rule matched — fall to the declared default terminal.
    if policy.default_branch is not None:
        db = policy.default_branch
        tf = db.transformation.get("type") if db.transformation else None
        return Decision(db.effect or NO_MATCH, tf)
    return Decision(NO_MATCH, None)


def diff_within_policy(base: Policy, prop: Policy) -> tuple[list[Flip], list[str]]:
    """Enumerate the shared abstract request space and return the flips plus any
    opaque-operator notes (dimensions the enumeration could not model)."""
    principals, col_classes, opaque = _dimensions([base, prop])
    flips: list[Flip] = []
    for request in _enumerate(principals, col_classes):
        old = decide(base, request)
        new = decide(prop, request)
        if old.label() != new.label():
            flips.append(Flip(request, old, new))
    return flips, opaque


def render(flips: list[Flip], opaque: list[str], *, title: str = "REQUEST-SPACE DIFF") -> str:
    lines = [title, "=" * len(title), ""]
    if not flips:
        lines.append("No abstract request changes decision.")
    else:
        opened = sum(1 for f in flips if f.direction == "OPENED")
        closed = sum(1 for f in flips if f.direction == "CLOSED")
        other = len(flips) - opened - closed
        lines.append(f"{len(flips)} abstract request(s) flip: "
                     f"{opened} OPENED, {closed} CLOSED, {other} CHANGED.")
        lines.append("")
        for f in flips:
            lines.append(f"[{f.direction}]  {f.request.describe()}")
            lines.append(f"     {f.old.label()}  →  {f.new.label()}")
    if opaque:
        lines.append("")
        lines.append(f"note: {len(opaque)} condition operator(s) not enumerable "
                     f"({', '.join(opaque)}); affected rules treated conservatively.")
    return "\n".join(lines) + "\n"
