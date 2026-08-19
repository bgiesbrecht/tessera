# Demo: standing dead-rule lint over a policy timeline

> **Generated file.** Produced by `tools/impact/demo/build_timeline_demo.py`.
> Every tool-output block below is real output from `tools/impact`, not
> hand-written. Regenerate with
> `./.venv/bin/python -m tools.impact.demo.build_timeline_demo`.

## What this demonstrates

The change-impact tool has two complementary reachability views:

- **C3 (change-impact)** reports when a rule's reachability *changes* between
  two versions: the moment a rule goes dead, or comes back to life.
- **L1 (standing lint, `--lint`)** reports every provably-dead rule in a single
  corpus state, regardless of *when* it went dead.

The distinction matters because dead rules are usually born in one commit and
discovered, if ever, many commits later. A change-diff shows the problem only
in the review of the commit that introduced it; once that review scrolls past,
the diff never mentions it again. The standing lint keeps surfacing it until
someone fixes it.

Both views share the same reasoning and the same ADR-001 guard: they reason
only about selector *expressions* subsuming one another (ordered first-match,
ADR-015), never about which concrete principals populate a selector. Opaque
selectors (`byDataset`/ACL tables) never subsume, so a dead-rule claim is never
membership-dependent: the tool only ever says "dead" when it can prove it from
the policy text alone.

## The timeline

One policy, `policy:orders-access` on `acme.tpch.orders`, evolving across four
versions. Because all four carry the same `@id` (they are the *same* policy over
time), each version lives in its own directory, `tools/impact/demo/timeline/v1/`
… `v4/`, alongside a clean companion policy, so each is a runnable
single-corpus state.

| Version | Change | Rules (in order) | Health |
|---|---|---|---|
| **v1** | Initial | ops→all; analysts→{low} | clean |
| **v2** | Add urgent desk | ops→all; urgent-desk→{high}; analysts→{low} | clean |
| **v3** | Incident grant | ops→all; **analysts→all**; urgent-desk→{high}; analysts→{low} | **dead rule introduced** |
| **v4** | Urgent desk disbanded | ops→all; analysts→all; analysts→{low} | **dead rule lingers** |

At **v3**, an admin grants analysts full visibility during an incident by
adding an unconditional `group:acme_analysts` keep near the top, but leaves the
old conditional `analysts→{low}` rule in place below it. Under ordered
first-match, that old rule can now never fire. It is dead code.

At **v4**, the urgent desk is disbanded and its rule removed. The reviewer
focuses on that removal; nobody notices the analysts rule that has been dead
since v3. It persists.

## View 1: C3 catches the moment it goes dead (v2 → v3)

Diffing the version that introduced the dead rule against the one before it,
the change-impact run flags the newly-unreachable rule:

```
tessera impact  (v2 → v3)
=========================

[C3]  selector group:acme_analysts   PROVEN
     Rule 3 (selector group:acme_analysts) is now unreachable: earlier rule 1 (selector group:acme_analysts) provably matches every case it would, under ordered first-match. The rule is dead code.
     grounding: ADR-015 (ordered first-match) + §4.2 subsumption

[C6]  WIDEN  selector group:acme_analysts   PROVEN
     Added a keep-matching-rows rule (kept ['3-MEDIUM', '4-NOT SPECIFIED', '5-LOW']). Net exposure for the affected selector is strictly increased.
     grounding: §4.3 effect polarity

[C6]  WIDEN  selector group:acme_analysts   PROVEN
     Condition removed (rule is now unconditional) on a keep-matching-rows rule → exposure increased.
     grounding: §4.2 value-set arithmetic
```

## View 2: the diff goes quiet once the rule is already dead (v3 → v4)

By v4 the rule was *already* dead in v3, so its reachability did not *change*:
C3 has nothing to say about it. The v3 → v4 diff reports only the urgent-desk
removal. The dead analysts rule is now invisible to change review:

```
tessera impact  (v3 → v4)
=========================

[C1]  selector group:acme_urgent_desk   PROVEN
     Lost its last governing rule. defaultStrategy = none. Principals matching this selector now fall through to fail-closed terminal (no rows / full restriction).
     grounding: ADR-013 (declared default-handling intent)

[C6]  NARROW  selector group:acme_urgent_desk   PROVEN
     Removed a keep-matching-rows rule (kept ['1-URGENT', '2-HIGH']). Net exposure for the affected selector is strictly reduced.
     grounding: §4.3 effect polarity

[C6]  NARROW  selector group:acme_analysts   PROVEN
     Removed a keep-matching-rows rule (kept ['3-MEDIUM', '4-NOT SPECIFIED', '5-LOW']). Net exposure for the affected selector is strictly reduced.
     grounding: §4.3 effect polarity

[C6]  WIDEN  selector group:acme_analysts   PROVEN
     Added a keep-matching-rows rule (kept ['3-MEDIUM', '4-NOT SPECIFIED', '5-LOW']). Net exposure for the affected selector is strictly increased.
     grounding: §4.3 effect polarity
```

This is the gap. A reviewer who only ever sees diffs would have exactly one
chance (the v2 → v3 review) to catch the dead rule, and would never be
reminded again.

## View 3: the standing lint keeps surfacing it (corpus at v4)

Running `--lint` over the whole corpus as it stands at v4 flags the dead rule,
months after the diff that introduced it, and names the earlier rule that
shadows it. The always-clean companion policy (`policy:analysts-tiering`)
produces no findings; the lint flags only the offender:

```
tessera impact --lint  (corpus at v4)
=====================================

[L1]  rule 2 (selector group:acme_analysts)   PROVEN
     Rule 2 (selector group:acme_analysts) is unreachable: earlier rule 1 (selector group:acme_analysts) provably matches every case it would, under ordered first-match. The rule is dead code and can be removed or reordered.
     grounding: ADR-015 (ordered first-match) + §4.2 subsumption
```

For contrast, the same lint over the clean v1 corpus is silent:

```
tessera impact --lint  (corpus at v1)
=====================================

No exposure-relevant changes detected.
```

## Try it yourself

```
# Lint the v4 corpus directly (the dead rule this demo is about):
python -m tools.impact --lint --corpus tools/impact/demo/timeline/v4

# Lint the clean v1 corpus (silent):
python -m tools.impact --lint --corpus tools/impact/demo/timeline/v1

# Standing lint over your own git-tracked corpus (working tree):
python -m tools.impact --lint

# Lint a specific historical commit:
python -m tools.impact --lint --at <ref>

# Change-impact diff between two refs (the C3 view):
python -m tools.impact --git <base-ref> <prop-ref>
```

## Takeaway

Dead rules are a maintenance smell, not an exposure change in themselves, but
they mislead. An operator editing a dead rule believes they are changing policy
behavior when they are not. C3 catches the moment of death for the one review
that sees it; L1 is the standing health check that keeps the corpus honest
afterwards. Both stay strictly on the static side of the ADR-001 line: they
prove deadness from the policy text, and stay silent wherever membership would
be required to know.
