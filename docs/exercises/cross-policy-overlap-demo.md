# Demo — cross-policy overlap detection (ADR-023)

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
demo uses column masks; the row-filter case — "someone added a second filter for
another team on the same table" — is the same rule and is flagged the same way.
Under γ-with-refinement, Tessera does not pick a winner — it surfaces the
conflict at analysis time so the author resolves it before deployment.

The change-impact tool detects this statically:

- **C4 (change-impact)** flags an overlap the moment a change introduces it (or
  notes when a change resolves one).
- **L2 (standing lint, `--lint`)** flags every current overlap in the corpus.

Both stay on the static side of the ADR-001 line. Two attribute *predicates*
that provably co-apply (by scope containment + ontology subsumption) are
**PROVEN**. But a predicate versus a *concrete column* is only **CANDIDATE** —
proving that overlap would require knowing whether the column carries the
attribute tag, which is a platform-tagging fact the tool does not read.

## The corpus

`policy:pii-redact` redacts PII columns across `catalog:acme`. A second team
adds `policy:pii-hash` — hashing PII columns in `schema:acme.tpch` for a
different consumer. Both are individually valid; together they resolve two
different masks onto the same PII columns in the tpch schema. A third policy,
`policy:clerk-redact`, targets the concrete column `o_clerk`.

| Policy | Attaches to | Effect |
|---|---|---|
| `pii-redact` | `catalog:acme`, `sensitivity: PII` | Redact |
| `pii-hash` | `schema:acme.tpch`, `sensitivity: PII` | Hash |
| `clerk-redact` | `column:acme.tpch.orders.o_clerk` (concrete) | Redact |

`catalog:acme` ⊇ `schema:acme.tpch`, and `PII ⊇ PII`, so `pii-redact` and
`pii-hash` provably co-apply to the PII columns in tpch — with divergent
transformations. That is the conflict.

## C4 — the overlap the change introduced (before → after)

Adding `pii-hash` and `clerk-redact` to the single-policy baseline:

```
tessera impact  (before → after)
================================

[C4]  policy:pii-hash ∩ policy:pii-redact   PROVEN
     Change introduces a cross-policy overlap: policy:pii-hash and policy:pii-redact are both ColumnVisibilityConstraint policies whose scopes and attribute-matches provably overlap, with divergent effects — the platform 'single-column-mask-per-column' constraint. On a platform declaring this constraint the adapter will refuse to emit the pair; resolve before deployment (ADR-023 γ-with-refinement).
     grounding: ADR-023 (γ-with-refinement) + §4.2 overlap

[C6]  INVERT  scope column:acme.tpch.orders.o_clerk   PROVEN
     Change adds policy policy:clerk-redact. Net exposure for the attached scope shifts accordingly.
     grounding: §4.3 effect polarity

[C6]  INVERT  scope schema:acme.tpch [sensitivity=PII]   PROVEN
     Change adds policy policy:pii-hash. Net exposure for the attached scope shifts accordingly.
     grounding: §4.3 effect polarity

[C4]  policy:clerk-redact ∩ policy:pii-hash   CANDIDATE
     Change introduces a cross-policy overlap: policy:clerk-redact and policy:pii-hash are both ColumnVisibilityConstraint policies whose scopes and attribute-matches may overlap, with divergent effects — the platform 'single-column-mask-per-column' constraint. On a platform declaring this constraint the adapter will refuse to emit the pair; resolve before deployment (ADR-023 γ-with-refinement).
     unknown: whether resource 'column:acme.tpch.orders.o_clerk' carries attribute(s) [sensitivity:PII] is a platform-tagging fact not visible to static analysis
     grounding: ADR-023 (γ-with-refinement) + §4.2 overlap

[C4]  policy:clerk-redact ∩ policy:pii-redact   CANDIDATE
     Change introduces a cross-policy overlap: policy:clerk-redact and policy:pii-redact are both ColumnVisibilityConstraint policies whose scopes and attribute-matches may overlap, with the same effect (duplicate coverage) — the platform 'single-column-mask-per-column' constraint. On a platform declaring this constraint the adapter will refuse to emit the pair; resolve before deployment (ADR-023 γ-with-refinement).
     unknown: whether resource 'column:acme.tpch.orders.o_clerk' carries attribute(s) [sensitivity:PII] is a platform-tagging fact not visible to static analysis
     grounding: ADR-023 (γ-with-refinement) + §4.2 overlap
```

Three overlaps, and the confidence split is the point:

- **`pii-redact ∩ pii-hash` — PROVEN.** Two attribute predicates on overlapping
  scope (`catalog:acme` ⊇ `schema:acme.tpch`) with the same axis value; the
  overlap follows from the policy text alone. Divergent transforms (Redact vs
  Hash).
- **`clerk-redact ∩ pii-hash` — CANDIDATE.** A concrete column vs. an attribute
  predicate: the tool would have to know `o_clerk` is tagged PII to be sure, and
  that is a platform-tagging fact it does not read — so it flags a possibility
  and names the unknown rather than guessing.
- **`clerk-redact ∩ pii-redact` — CANDIDATE, duplicate coverage.** Same shape,
  but here both policies *redact*. The effects are identical, yet it is still a
  conflict: the platform's `single-column-mask-per-column` rule is about
  multiplicity, not disagreement — at most one mask may resolve to a column,
  even two identical ones. A tool that only flagged *divergent* effects would
  miss this, and miss the analogous "second row filter on the same table" case
  entirely.

## L2 — the standing overlap lint (after)

```
tessera impact --lint  (after)
==============================

[L2]  policy:pii-hash ∩ policy:pii-redact   PROVEN
     Cross-policy overlap: policy:pii-hash and policy:pii-redact are both ColumnVisibilityConstraint policies whose scopes and attribute-matches provably overlap, with divergent effects — the platform 'single-column-mask-per-column' constraint. On a platform declaring this constraint the adapter will refuse to emit the pair; resolve before deployment (ADR-023 γ-with-refinement).
     grounding: ADR-023 (γ-with-refinement) + §4.2 overlap

[L2]  policy:clerk-redact ∩ policy:pii-hash   CANDIDATE
     Cross-policy overlap: policy:clerk-redact and policy:pii-hash are both ColumnVisibilityConstraint policies whose scopes and attribute-matches may overlap, with divergent effects — the platform 'single-column-mask-per-column' constraint. On a platform declaring this constraint the adapter will refuse to emit the pair; resolve before deployment (ADR-023 γ-with-refinement).
     unknown: whether resource 'column:acme.tpch.orders.o_clerk' carries attribute(s) [sensitivity:PII] is a platform-tagging fact not visible to static analysis
     grounding: ADR-023 (γ-with-refinement) + §4.2 overlap

[L2]  policy:clerk-redact ∩ policy:pii-redact   CANDIDATE
     Cross-policy overlap: policy:clerk-redact and policy:pii-redact are both ColumnVisibilityConstraint policies whose scopes and attribute-matches may overlap, with the same effect (duplicate coverage) — the platform 'single-column-mask-per-column' constraint. On a platform declaring this constraint the adapter will refuse to emit the pair; resolve before deployment (ADR-023 γ-with-refinement).
     unknown: whether resource 'column:acme.tpch.orders.o_clerk' carries attribute(s) [sensitivity:PII] is a platform-tagging fact not visible to static analysis
     grounding: ADR-023 (γ-with-refinement) + §4.2 overlap
```

For contrast, the single-policy `before` corpus is silent:

```
tessera impact --lint  (before)
===============================

No exposure-relevant changes detected.
```

## Try it yourself

```
# Standing overlap lint over the conflicting corpus:
python -m tools.impact --lint --corpus tools/impact/demo/overlap/after

# The clean baseline (silent):
python -m tools.impact --lint --corpus tools/impact/demo/overlap/before
```

## Takeaway

Cross-policy conflicts are invisible in any single policy file — they emerge
only from the corpus as a whole, and on Databricks they surface at query time,
after deployment, as a runtime rejection. C4/L2 pull that discovery forward to
analysis time and name both policies, the platform constraint, and the ADR-023
resolution path. And they hold the line: PROVEN where the policy text settles
it, CANDIDATE (with the unknown named) where a tagging fact would be required.
