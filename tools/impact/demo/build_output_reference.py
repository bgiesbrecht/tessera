"""Generate a captured reference of the change-impact tool's output.

The two narrative demos (timeline, overlap) each tell one story. This module
produces a different artifact: a *reference* showing what every check emits and
what each output format looks like, in one place, so someone can see the shape
of the tool's output without running it.

Every block is real output, produced by running the tool against the committed
demo fixtures. Regenerate with:

    ./.venv/bin/python -m tools.impact.demo.build_output_reference

Writes:
    tools/impact/demo/OUTPUT-REFERENCE.md
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from tools.impact import (
    analyze,
    lint,
    render_json,
    render_markdown,
    render_text,
)
from tools.impact.model import Corpus, load_policy_dict
from tools.impact.demo import build_overlap_demo as overlap
from tools.impact.demo import build_timeline_demo as timeline


REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DOC = Path(__file__).resolve().parent / "OUTPUT-REFERENCE.md"


def _corpus(*docs: dict) -> Corpus:
    c = Corpus()
    for d in docs:
        c.add(load_policy_dict(d))
    return c


def _fence(text: str, lang: str = "") -> str:
    return f"```{lang}\n" + text.rstrip("\n") + "\n```"


# ----------------------------------------------------------------------------
# Per-check scenarios, each reusing the committed demo fixtures where possible
# ----------------------------------------------------------------------------


def _c6_widen():
    base = timeline.v1()
    prop = copy.deepcopy(base)
    # Analysts gain a priority level -> exposure increases.
    prop["rules"][1]["condition"]["values"].append("2-HIGH")
    return analyze(_corpus(base), _corpus(prop))


def _c6_narrow_and_c1():
    # Removing the urgent-desk rule: NARROW plus a C1 coverage finding.
    return analyze(_corpus(timeline.v3()), _corpus(timeline.v4()))


def _c6_invert_transform():
    base = overlap.redact_pii()
    prop = copy.deepcopy(base)
    prop["defaultBranch"]["transformation"] = {"type": "Hash", "algorithm": "sha256"}
    return analyze(_corpus(base), _corpus(prop))


def _c2_default_net():
    base = timeline.v1()
    prop = copy.deepcopy(base)
    prop["defaultStrategy"] = "explicit-baseline-group"
    prop["baselineGroup"] = "account users"
    return analyze(_corpus(base), _corpus(prop))


def _c3_shadowing():
    # v2 → v3 introduces the dead analysts rule.
    return analyze(_corpus(timeline.v2()), _corpus(timeline.v3()))


def _c4_overlap():
    before = _corpus(overlap.redact_pii())
    after = _corpus(overlap.redact_pii(), overlap.hash_pii(), overlap.concrete_clerk())
    return analyze(before, after)


def _c5_dangling():
    base = timeline.v1()
    prop = copy.deepcopy(base)
    # Point a condition at a column outside the policy's appliesTo scope.
    prop["rules"][1]["condition"]["operands"] = ["column:other.db.tbl.col"]
    return analyze(_corpus(base), _corpus(prop))


def _l1_dead_rules():
    return lint(_corpus(timeline.v4(), timeline.companion()))


def _l2_overlap():
    return lint(_corpus(overlap.redact_pii(), overlap.hash_pii(), overlap.concrete_clerk()))


def _clean():
    base = timeline.v1()
    return analyze(_corpus(base), _corpus(copy.deepcopy(base)))


def build() -> None:
    OUT_DOC.write_text(_render())
    print(f"wrote {_rel(OUT_DOC)}")


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _render() -> str:
    # One representative report rendered in all three formats.
    fmt_report = _l1_dead_rules()

    return f"""# Change-impact tool: output reference

> **Generated file.** Produced by `tools/impact/demo/build_output_reference.py`.
> Every block below is real tool output, captured by running the checks against
> the committed demo fixtures. Regenerate with
> `./.venv/bin/python -m tools.impact.demo.build_output_reference`.

This is a reference for *what the tool emits*: one example per check, plus each
output format. For the narrative walkthroughs see
[`dead-rule-lint-demo.md`](../../../docs/exercises/dead-rule-lint-demo.md) and
[`cross-policy-overlap-demo.md`](../../../docs/exercises/cross-policy-overlap-demo.md).
For how to use the tool see
[`analyzing-changes.md`](../../../docs/user-guide/analyzing-changes.md).

## Anatomy of a finding

```
[C6]  NARROW  selector group:acme_urgent_desk   PROVEN
     Removed a keep-matching-rows rule (kept ['1-URGENT', '2-HIGH']). ...
     grounding: §4.3 effect polarity
 ^     ^        ^                                ^
 |     |        |                                └─ confidence: PROVEN | CANDIDATE
 |     |        └─ subject: always selector-relative, never a resolved identity
 |     └─ polarity (checks that compute one): WIDEN | NARROW | INVERT | NEUTRAL
 └─ check code
```

Findings are ordered PROVEN before CANDIDATE, then by check code.

---

## Diff checks (`tessera impact`)

### C6 exposure polarity: WIDEN

A condition value-set gains a value on a `keep-matching-rows` rule.

{_fence(render_text(_c6_widen()))}

### C6 exposure polarity: NARROW (with C1)

Removing a rule reduces exposure, and the selector loses its last governing
rule, so C1 reports where those principals now fall through.

{_fence(render_text(_c6_narrow_and_c1()))}

### C6 exposure polarity: INVERT (transformation swap)

`Redact` → `Hash` has no total order (scoping doc §9.4): the tool refuses to
fabricate a direction and routes the substitution to review.

{_fence(render_text(_c6_invert_transform()))}

### C2: default-net change

`defaultStrategy` moves from fail-closed (`none`) to a baseline grant. This edit
also trips C5: it names a `baselineGroup` without adding a rule that targets it,
so the declared default branch is unreachable, a realistic mistake, and a good
illustration of checks composing on one change.

{_fence(render_text(_c2_default_net()))}

### C3: reachability / shadowing

An unconditional grant is inserted above a narrower rule on the same selector,
rendering it unreachable under ordered first-match (ADR-015).

{_fence(render_text(_c3_shadowing()))}

### C4: cross-policy overlap

Two column masks resolve to the same columns with divergent transformations:
the ADR-023 MULTIPLE_MASKS situation. Note the mixed confidence: the two
attribute predicates provably overlap, while the predicate-vs-concrete-column
pair is CANDIDATE with the unknown named.

{_fence(render_text(_c4_overlap()))}

### C5: dangling reference

A condition operand points outside the policy's `appliesTo` scope.

{_fence(render_text(_c5_dangling()))}

### No findings

A change with no exposure-relevant consequence reports nothing rather than
inventing noise.

{_fence(render_text(_clean()))}

---

## Standing lints (`tessera lint`)

### L1: dead rules

Every provably-unreachable rule in the corpus, naming the rule that shadows it.
Healthy policies in the same corpus produce no findings.

{_fence(render_text(_l1_dead_rules()))}

### L2: cross-policy overlap

Every overlap currently present, regardless of when it was introduced.

{_fence(render_text(_l2_overlap()))}

---

## Output formats

The same report (L1, above) in each format. Select with `--format`.

### `--format text` (default)

{_fence(render_text(fmt_report))}

### `--format md`

Renders a table, useful for pasting into a pull-request comment.

{_fence(render_markdown(fmt_report), "markdown")}

### `--format json`

Machine-readable, for CI and tooling. `polarity` and `unknown` are `null` where
they do not apply.

{_fence(render_json(fmt_report), "json")}

---

## Exit codes

The tool is advisory: the exit code is `0` whether or not findings are present.
CI gating is opt-in via `--exit-on <POLARITY>`, which exits `1` if any finding
carries that polarity. See the CI section of
[`analyzing-changes.md`](../../../docs/user-guide/analyzing-changes.md).
"""


if __name__ == "__main__":
    build()
