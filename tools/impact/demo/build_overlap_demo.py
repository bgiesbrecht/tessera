"""Generate the cross-policy overlap demo: fixtures + narrative markdown.

Shows C4 / L2 catching the ADR-023 MULTIPLE_MASKS situation: two column-mask
policies that resolve to the same columns with divergent transformations, which
a platform declaring `single-column-mask-per-column` will refuse to emit.

The story: a corpus starts with one PII redaction mask. A second team adds a
hashing mask for the same PII columns (a different downstream consumer's need).
Both are individually valid; together they conflict. C4 catches the moment the
second policy lands; L2 keeps surfacing the standing conflict. A third policy
targets a concrete column that *may* carry the attribute, flagged CANDIDATE,
not PROVEN, because whether that column is tagged is a platform fact the tool
does not read (the ADR-001 line).

As with the timeline demo, every tool-output block is real output. Regenerate:

    ./.venv/bin/python -m tools.impact.demo.build_overlap_demo

Writes:
    tools/impact/demo/overlap/before/*.jsonld   (single redaction mask)
    tools/impact/demo/overlap/after/*.jsonld     (redaction + hashing + concrete)
    docs/exercises/cross-policy-overlap-demo.md   (the demo doc)
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.impact import analyze, lint, load_corpus_from_paths, render_text
from tools.impact.model import Corpus, load_policy_dict


REPO_ROOT = Path(__file__).resolve().parents[3]
OVERLAP_DIR = Path(__file__).resolve().parent / "overlap"
DEMO_DOC = REPO_ROOT / "docs" / "exercises" / "cross-policy-overlap-demo.md"


def _mask(pid: str, *, scope: str | None, resource: str | None,
          sensitivity: str | None, tf_type: str, description: str) -> dict:
    if scope is not None:
        applies = {"selector": "byScope", "scope": scope}
        if sensitivity is not None:
            applies["matching"] = {"attributes": {"sensitivity": sensitivity}}
    else:
        applies = {"selector": "byIdentity", "resource": resource}
    tf = {"type": tf_type}
    if tf_type == "Redact":
        tf["replacement"] = "REDACTED"
    return {
        "@context": "https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld",
        "@type": "Policy",
        "@id": f"policy:{pid}",
        "policyKind": "ColumnVisibilityConstraint",
        "description": description,
        "appliesTo": applies,
        "action": "Read",
        "defaultStrategy": "negated-complement",
        "rules": [{"principal": {"selector": "byIdentity", "resource": "group:acme_stewards"},
                   "effect": "allow"}],
        "defaultBranch": {"effect": "transform", "transformation": tf},
    }


def redact_pii() -> dict:
    return _mask(
        "pii-redact", scope="catalog:acme", resource=None, sensitivity="PII",
        tf_type="Redact",
        description="Redact PII columns across the catalog for non-stewards.")


def hash_pii() -> dict:
    return _mask(
        "pii-hash", scope="schema:acme.tpch", resource=None, sensitivity="PII",
        tf_type="Hash",
        description="Hash PII columns in the tpch schema for the analytics consumer.")


def concrete_clerk() -> dict:
    return _mask(
        "clerk-redact", scope=None, resource="column:acme.tpch.orders.o_clerk",
        sensitivity=None, tf_type="Redact",
        description="Redact the specific o_clerk column.")


def _corpus(*docs: dict) -> Corpus:
    c = Corpus()
    for d in docs:
        c.add(load_policy_dict(d))
    return c


def _write(subdir: str, pid_file: str, doc: dict) -> None:
    path = OVERLAP_DIR / subdir / pid_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n")


def _fence(text: str) -> str:
    return "```\n" + text.rstrip("\n") + "\n```"


def build() -> None:
    # before/: only the redaction mask (clean).
    _write("before", "pii-redact.jsonld", redact_pii())
    # after/: redaction + hashing (PROVEN conflict) + concrete column (CANDIDATE).
    _write("after", "pii-redact.jsonld", redact_pii())
    _write("after", "pii-hash.jsonld", hash_pii())
    _write("after", "clerk-redact.jsonld", concrete_clerk())

    before = _corpus(redact_pii())
    after = _corpus(redact_pii(), hash_pii(), concrete_clerk())

    diff = render_text(analyze(before, after), title="tessera impact  (before → after)")
    lint_after = render_text(lint(after), title="tessera impact --lint  (after)")
    lint_before = render_text(lint(before), title="tessera impact --lint  (before)")

    DEMO_DOC.write_text(_render_markdown(diff, lint_after, lint_before))
    print(f"wrote {_rel(DEMO_DOC)}")
    print(f"wrote fixtures under {_rel(OVERLAP_DIR)}/")


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _render_markdown(diff: str, lint_after: str, lint_before: str) -> str:
    return f"""# Demo: cross-policy overlap detection (ADR-023)

> **Generated file.** Produced by `tools/impact/demo/build_overlap_demo.py`.
> Every tool-output block below is real output from `tools/impact`. Regenerate
> with `./.venv/bin/python -m tools.impact.demo.build_overlap_demo`.

## What this demonstrates

ADR-023 records that Databricks rejects **multiple column masks on the same
column** at query time (`COLUMN_MASKS_FEATURE_NOT_SUPPORTED.MULTIPLE_MASKS`), and
the same shape applies to row filters (**one row filter per table**). These are
*multiplicity* constraints: the platform permits at most one such policy per
target, so two policies resolving to the same target conflict whether their
effects disagree (Redact vs Hash) or are identical (a redundant duplicate). This
demo uses column masks; the row-filter case ("someone added a second filter for
another team on the same table") is the same rule and is flagged the same way.
Under γ-with-refinement, Tessera does not pick a winner; it surfaces the
conflict at analysis time so the author resolves it before deployment.

The change-impact tool detects this statically:

- **C4 (change-impact)** flags an overlap the moment a change introduces it (or
  notes when a change resolves one).
- **L2 (standing lint, `--lint`)** flags every current overlap in the corpus.

Both stay on the static side of the ADR-001 line. Two attribute *predicates*
that provably co-apply (by scope containment + ontology subsumption) are
**PROVEN**. But a predicate versus a *concrete column* is only **CANDIDATE**:
proving that overlap would require knowing whether the column carries the
attribute tag, which is a platform-tagging fact the tool does not read.

## The corpus

`policy:pii-redact` redacts PII columns across `catalog:acme`. A second team
adds `policy:pii-hash`, hashing PII columns in `schema:acme.tpch` for a
different consumer. Both are individually valid; together they resolve two
different masks onto the same PII columns in the tpch schema. A third policy,
`policy:clerk-redact`, targets the concrete column `o_clerk`.

| Policy | Attaches to | Effect |
|---|---|---|
| `pii-redact` | `catalog:acme`, `sensitivity: PII` | Redact |
| `pii-hash` | `schema:acme.tpch`, `sensitivity: PII` | Hash |
| `clerk-redact` | `column:acme.tpch.orders.o_clerk` (concrete) | Redact |

`catalog:acme` ⊇ `schema:acme.tpch`, and `PII ⊇ PII`, so `pii-redact` and
`pii-hash` provably co-apply to the PII columns in tpch, with divergent
transformations. That is the conflict.

## C4: the overlap the change introduced (before → after)

Adding `pii-hash` and `clerk-redact` to the single-policy baseline:

{_fence(diff)}

Three overlaps, and the confidence split is the point:

- **`pii-redact ∩ pii-hash`: PROVEN.** Two attribute predicates on overlapping
  scope (`catalog:acme` ⊇ `schema:acme.tpch`) with the same axis value; the
  overlap follows from the policy text alone. Divergent transforms (Redact vs
  Hash).
- **`clerk-redact ∩ pii-hash`: CANDIDATE.** A concrete column vs. an attribute
  predicate: the tool would have to know `o_clerk` is tagged PII to be sure, and
  that is a platform-tagging fact it does not read, so it flags a possibility
  and names the unknown rather than guessing.
- **`clerk-redact ∩ pii-redact`: CANDIDATE, duplicate coverage.** Same shape,
  but here both policies *redact*. The effects are identical, yet it is still a
  conflict: the platform's `single-column-mask-per-column` rule is about
  multiplicity, not disagreement: at most one mask may resolve to a column,
  even two identical ones. A tool that only flagged *divergent* effects would
  miss this, and miss the analogous "second row filter on the same table" case
  entirely.

## L2: the standing overlap lint (after)

{_fence(lint_after)}

For contrast, the single-policy `before` corpus is silent:

{_fence(lint_before)}

## Try it yourself

```
# Standing overlap lint over the conflicting corpus:
python -m tools.impact --lint --corpus tools/impact/demo/overlap/after

# The clean baseline (silent):
python -m tools.impact --lint --corpus tools/impact/demo/overlap/before
```

## Takeaway

Cross-policy conflicts are invisible in any single policy file; they emerge
only from the corpus as a whole, and on Databricks they surface at query time,
after deployment, as a runtime rejection. C4/L2 pull that discovery forward to
analysis time and name both policies, the platform constraint, and the ADR-023
resolution path. And they hold the line: PROVEN where the policy text settles
it, CANDIDATE (with the unknown named) where a tagging fact would be required.
"""


if __name__ == "__main__":
    build()
