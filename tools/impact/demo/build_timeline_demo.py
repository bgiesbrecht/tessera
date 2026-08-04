"""Generate the dead-rule timeline demo: fixtures + narrative markdown.

This builds a small, realistic story of one policy evolving across four
versions. A well-intentioned edit silently strands a rule as dead code, and a
later "cleanup" leaves it stranded. The demo contrasts two views of the same
fact:

  * C3 (change-impact) catches the *moment* a rule goes dead — the diff between
    the version that introduced it and the one before.
  * L1 (standing lint) catches the *lingering* deadness — the rule is still
    dead versions later, long after the diff that introduced it has scrolled
    out of anyone's review window.

Everything the markdown asserts about tool output is produced by actually
running the tool here, so the doc cannot drift from the code. Regenerate with:

    ./.venv/bin/python -m tools.impact.demo.build_timeline_demo

The four versions share one @id (policy:orders-access) — they are the SAME
policy evolving — so they cannot co-reside in one corpus directory. Each
version is written to its own subdirectory, alongside the clean companion
policy, so that `tools/impact/demo/timeline/vN/` is a runnable single-corpus
state that `--lint --corpus` accepts directly.

Writes:
    tools/impact/demo/timeline/v{1..4}/orders-access.jsonld    (the evolving policy)
    tools/impact/demo/timeline/v{1..4}/analysts-tiering.jsonld  (clean companion)
    docs/exercises/dead-rule-lint-demo.md                       (the demo doc)
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.impact import analyze, lint, load_corpus_from_paths, render_text
from tools.impact.model import Corpus, load_policy_dict


REPO_ROOT = Path(__file__).resolve().parents[3]
TIMELINE_DIR = Path(__file__).resolve().parent / "timeline"
DEMO_DOC = REPO_ROOT / "docs" / "exercises" / "dead-rule-lint-demo.md"

TABLE = "table:acme.tpch.orders"
PRIORITY_COL = "column:acme.tpch.orders.o_orderpriority"


# ----------------------------------------------------------------------------
# Rule builders
# ----------------------------------------------------------------------------


def _keep(group: str, values: list[str] | None = None) -> dict:
    rule = {
        "principal": {"selector": "byIdentity", "resource": f"group:{group}"},
        "effect": "keep-matching-rows",
    }
    if values is not None:
        rule["condition"] = {"op": "in", "operands": [PRIORITY_COL], "values": values}
    return rule


def _policy(pid: str, version: str, description: str, rules: list[dict]) -> dict:
    return {
        "@context": "https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld",
        "@type": "Policy",
        "@id": f"policy:{pid}",
        "version": version,
        "policyKind": "RowVisibilityConstraint",
        "description": description,
        "appliesTo": {"selector": "byIdentity", "resource": TABLE},
        "action": "Read",
        "defaultStrategy": "none",
        "rules": rules,
    }


# ----------------------------------------------------------------------------
# The four versions of orders-access
# ----------------------------------------------------------------------------

LOW = ["3-MEDIUM", "4-NOT SPECIFIED", "5-LOW"]
HIGH = ["1-URGENT", "2-HIGH"]


def v1() -> dict:
    # Initial policy. Ops see everything; analysts see low-priority rows only.
    return _policy(
        "orders-access", "1.0.0",
        "Ops see all orders; analysts see low-priority orders only.",
        [
            _keep("acme_all_priority_ops"),          # 0: sees all
            _keep("acme_analysts", LOW),             # 1: low-priority only
        ],
    )


def v2() -> dict:
    # Add an urgent desk that sees the high-priority rows. Distinct selector,
    # everything still reachable.
    return _policy(
        "orders-access", "1.1.0",
        "Add an urgent desk that sees high-priority orders.",
        [
            _keep("acme_all_priority_ops"),          # 0: sees all
            _keep("acme_urgent_desk", HIGH),         # 1: high-priority
            _keep("acme_analysts", LOW),             # 2: low-priority
        ],
    )


def v3() -> dict:
    # Incident response: analysts need full visibility *right now*. An admin
    # adds an unconditional analysts keep near the top and — under pressure —
    # leaves the old conditional analysts rule in place below it. That old rule
    # is now shadowed: it can never fire. Dead code introduced.
    return _policy(
        "orders-access", "1.2.0",
        "Incident grant: analysts temporarily see all orders.",
        [
            _keep("acme_all_priority_ops"),          # 0: sees all
            _keep("acme_analysts"),                  # 1: NEW unconditional grant
            _keep("acme_urgent_desk", HIGH),         # 2: high-priority
            _keep("acme_analysts", LOW),             # 3: now DEAD (shadowed by 1)
        ],
    )


def v4() -> dict:
    # Months later: the urgent desk is disbanded, so its rule is removed. The
    # reviewer focuses on that removal and never notices the analysts rule that
    # has been dead since v3. The dead rule persists.
    return _policy(
        "orders-access", "1.3.0",
        "Urgent desk disbanded; its rule removed. (Dead analysts rule lingers.)",
        [
            _keep("acme_all_priority_ops"),          # 0: sees all
            _keep("acme_analysts"),                  # 1: unconditional grant
            _keep("acme_analysts", LOW),             # 2: STILL DEAD (shadowed by 1)
        ],
    )


def companion() -> dict:
    # A second, always-clean policy in the corpus, to show the lint flags only
    # the offending policy and leaves healthy ones silent.
    return _policy(
        "analysts-tiering", "1.0.0",
        "Two distinct analyst tiers — no overlap, no dead rules.",
        [
            _keep("acme_analysts_tier1", HIGH),
            _keep("acme_analysts_tier2", LOW),
        ],
    )


# ----------------------------------------------------------------------------
# Build
# ----------------------------------------------------------------------------


def _corpus(*docs: dict) -> Corpus:
    c = Corpus()
    for d in docs:
        c.add(load_policy_dict(d))
    return c


def _write_fixture(name: str, doc: dict) -> Path:
    path = TIMELINE_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n")
    return path


def _fence(text: str) -> str:
    return "```\n" + text.rstrip("\n") + "\n```"


def build() -> None:
    TIMELINE_DIR.mkdir(parents=True, exist_ok=True)

    # Each version is its own single-corpus directory: the evolving policy plus
    # the clean companion. Same @id across versions means they cannot share a
    # directory, and per-version dirs are what `--lint --corpus` runs against.
    versions = {"v1": v1(), "v2": v2(), "v3": v3(), "v4": v4()}
    for tag, doc in versions.items():
        _write_fixture(f"{tag}/orders-access.jsonld", doc)
        _write_fixture(f"{tag}/analysts-tiering.jsonld", companion())

    # Change-impact diffs between consecutive versions (C3 among others).
    diff_v2_v3 = render_text(analyze(_corpus(v2()), _corpus(v3())),
                             title="tessera impact  (v2 → v3)")
    diff_v3_v4 = render_text(analyze(_corpus(v3()), _corpus(v4())),
                             title="tessera impact  (v3 → v4)")

    # Standing lint at v4, over a two-policy corpus (offender + clean companion).
    lint_v4 = render_text(lint(_corpus(v4(), companion())),
                          title="tessera impact --lint  (corpus at v4)")

    # Lint at v1 (clean) to show the healthy baseline.
    lint_v1 = render_text(lint(_corpus(v1(), companion())),
                          title="tessera impact --lint  (corpus at v1)")

    doc = _render_markdown(diff_v2_v3, diff_v3_v4, lint_v4, lint_v1)
    DEMO_DOC.write_text(doc)
    print(f"wrote {_rel(DEMO_DOC)}")
    print(f"wrote fixtures under {_rel(TIMELINE_DIR)}/")


def _rel(path: Path) -> str:
    """Repo-relative path for status output, tolerant of redirected outputs
    (e.g. a temp dir under test) that lie outside the repo root."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _render_markdown(diff_v2_v3: str, diff_v3_v4: str, lint_v4: str, lint_v1: str) -> str:
    return f"""# Demo — standing dead-rule lint over a policy timeline

> **Generated file.** Produced by `tools/impact/demo/build_timeline_demo.py`.
> Every tool-output block below is real output from `tools/impact`, not
> hand-written. Regenerate with
> `./.venv/bin/python -m tools.impact.demo.build_timeline_demo`.

## What this demonstrates

The change-impact tool has two complementary reachability views:

- **C3 (change-impact)** reports when a rule's reachability *changes* between
  two versions — the moment a rule goes dead, or comes back to life.
- **L1 (standing lint, `--lint`)** reports every provably-dead rule in a single
  corpus state, regardless of *when* it went dead.

The distinction matters because dead rules are usually born in one commit and
discovered — if ever — many commits later. A change-diff shows the problem only
in the review of the commit that introduced it; once that review scrolls past,
the diff never mentions it again. The standing lint keeps surfacing it until
someone fixes it.

Both views share the same reasoning and the same ADR-001 guard: they reason
only about selector *expressions* subsuming one another (ordered first-match,
ADR-015), never about which concrete principals populate a selector. Opaque
selectors (`byDataset`/ACL tables) never subsume, so a dead-rule claim is never
membership-dependent — the tool only ever says "dead" when it can prove it from
the policy text alone.

## The timeline

One policy, `policy:orders-access` on `acme.tpch.orders`, evolving across four
versions. Because all four carry the same `@id` (they are the *same* policy over
time), each version lives in its own directory — `tools/impact/demo/timeline/v1/`
… `v4/` — alongside a clean companion policy, so each is a runnable
single-corpus state.

| Version | Change | Rules (in order) | Health |
|---|---|---|---|
| **v1** | Initial | ops→all; analysts→{{low}} | clean |
| **v2** | Add urgent desk | ops→all; urgent-desk→{{high}}; analysts→{{low}} | clean |
| **v3** | Incident grant | ops→all; **analysts→all**; urgent-desk→{{high}}; analysts→{{low}} | **dead rule introduced** |
| **v4** | Urgent desk disbanded | ops→all; analysts→all; analysts→{{low}} | **dead rule lingers** |

At **v3**, an admin grants analysts full visibility during an incident by
adding an unconditional `group:acme_analysts` keep near the top — but leaves the
old conditional `analysts→{{low}}` rule in place below it. Under ordered
first-match, that old rule can now never fire. It is dead code.

At **v4**, the urgent desk is disbanded and its rule removed. The reviewer
focuses on that removal; nobody notices the analysts rule that has been dead
since v3. It persists.

## View 1 — C3 catches the moment it goes dead (v2 → v3)

Diffing the version that introduced the dead rule against the one before it,
the change-impact run flags the newly-unreachable rule:

{_fence(diff_v2_v3)}

## View 2 — the diff goes quiet once the rule is already dead (v3 → v4)

By v4 the rule was *already* dead in v3, so its reachability did not *change* —
C3 has nothing to say about it. The v3 → v4 diff reports only the urgent-desk
removal. The dead analysts rule is now invisible to change review:

{_fence(diff_v3_v4)}

This is the gap. A reviewer who only ever sees diffs would have exactly one
chance — the v2 → v3 review — to catch the dead rule, and would never be
reminded again.

## View 3 — the standing lint keeps surfacing it (corpus at v4)

Running `--lint` over the whole corpus as it stands at v4 flags the dead rule,
months after the diff that introduced it, and names the earlier rule that
shadows it. The always-clean companion policy (`policy:analysts-tiering`)
produces no findings — the lint flags only the offender:

{_fence(lint_v4)}

For contrast, the same lint over the clean v1 corpus is silent:

{_fence(lint_v1)}

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

Dead rules are a maintenance smell, not an exposure change in themselves — but
they mislead. An operator editing a dead rule believes they are changing policy
behavior when they are not. C3 catches the moment of death for the one review
that sees it; L1 is the standing health check that keeps the corpus honest
afterwards. Both stay strictly on the static side of the ADR-001 line: they
prove deadness from the policy text, and stay silent wherever membership would
be required to know.
"""


if __name__ == "__main__":
    build()
