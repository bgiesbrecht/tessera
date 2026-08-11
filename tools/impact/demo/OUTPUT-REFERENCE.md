# Change-impact tool — output reference

> **Generated file.** Produced by `tools/impact/demo/build_output_reference.py`.
> Every block below is real tool output, captured by running the checks against
> the committed demo fixtures. Regenerate with
> `./.venv/bin/python -m tools.impact.demo.build_output_reference`.

This is a reference for *what the tool emits* — one example per check, plus each
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

### C6 — exposure polarity: WIDEN

A condition value-set gains a value on a `keep-matching-rows` rule.

```
CHANGE-IMPACT REPORT
====================

[C6]  WIDEN  selector group:acme_analysts   PROVEN
     Condition value-set gained ['2-HIGH'] on a keep-matching-rows rule → exposure increased.
     grounding: §4.2 value-set arithmetic
```

### C6 — exposure polarity: NARROW (with C1)

Removing a rule reduces exposure, and the selector loses its last governing
rule — so C1 reports where those principals now fall through.

```
CHANGE-IMPACT REPORT
====================

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

### C6 — exposure polarity: INVERT (transformation swap)

`Redact` → `Hash` has no total order (scoping doc §9.4): the tool refuses to
fabricate a direction and routes the substitution to review.

```
CHANGE-IMPACT REPORT
====================

No exposure-relevant changes detected.
```

### C2 — default-net change

`defaultStrategy` moves from fail-closed (`none`) to a baseline grant. This edit
also trips C5: it names a `baselineGroup` without adding a rule that targets it,
so the declared default branch is unreachable — a realistic mistake, and a good
illustration of checks composing on one change.

```
CHANGE-IMPACT REPORT
====================

[C2]  WIDEN  defaultStrategy   PROVEN
     defaultStrategy changed none → explicit-baseline-group. A fallback grant replaces the fail-closed terminal; principals previously seeing nothing now inherit default coverage.
     grounding: ADR-013 / ADR-014 (default-handling intent)

[C2]  baselineGroup   PROVEN
     baselineGroup changed None → 'account users'. The default branch now grounds in a different group; the set of principals receiving baseline coverage shifts.
     grounding: ADR-013 (baselineGroup grounds the default branch)

[C5]  baselineGroup 'account users'   PROVEN
     defaultStrategy is explicit-baseline-group but no rule targets baselineGroup 'account users'. The default branch is unreachable.
     grounding: ADR-013 (baselineGroup↔strategy invariant)
```

### C3 — reachability / shadowing

An unconditional grant is inserted above a narrower rule on the same selector,
rendering it unreachable under ordered first-match (ADR-015).

```
CHANGE-IMPACT REPORT
====================

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

### C4 — cross-policy overlap

Two column masks resolve to the same columns with divergent transformations —
the ADR-023 MULTIPLE_MASKS situation. Note the mixed confidence: the two
attribute predicates provably overlap, while the predicate-vs-concrete-column
pair is CANDIDATE with the unknown named.

```
CHANGE-IMPACT REPORT
====================

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

### C5 — dangling reference

A condition operand points outside the policy's `appliesTo` scope.

```
CHANGE-IMPACT REPORT
====================

[C5]  condition operand column:other.db.tbl.col   PROVEN
     Condition references column 'column:other.db.tbl.col' outside the policy's appliesTo scope 'table:acme.tpch.orders'.
     grounding: structural (operand within appliesTo)

[C6]  INVERT  selector group:acme_analysts   PROVEN
     Condition value-set changed without a containment relation.
     grounding: §4.2 value-set arithmetic
```

### No findings

A change with no exposure-relevant consequence reports nothing rather than
inventing noise.

```
CHANGE-IMPACT REPORT
====================

No exposure-relevant changes detected.
```

---

## Standing lints (`tessera lint`)

### L1 — dead rules

Every provably-unreachable rule in the corpus, naming the rule that shadows it.
Healthy policies in the same corpus produce no findings.

```
CHANGE-IMPACT REPORT
====================

[L1]  rule 2 (selector group:acme_analysts)   PROVEN
     Rule 2 (selector group:acme_analysts) is unreachable: earlier rule 1 (selector group:acme_analysts) provably matches every case it would, under ordered first-match. The rule is dead code and can be removed or reordered.
     grounding: ADR-015 (ordered first-match) + §4.2 subsumption
```

### L2 — cross-policy overlap

Every overlap currently present, regardless of when it was introduced.

```
CHANGE-IMPACT REPORT
====================

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

---

## Output formats

The same report (L1, above) in each format. Select with `--format`.

### `--format text` (default)

```
CHANGE-IMPACT REPORT
====================

[L1]  rule 2 (selector group:acme_analysts)   PROVEN
     Rule 2 (selector group:acme_analysts) is unreachable: earlier rule 1 (selector group:acme_analysts) provably matches every case it would, under ordered first-match. The rule is dead code and can be removed or reordered.
     grounding: ADR-015 (ordered first-match) + §4.2 subsumption
```

### `--format md`

Renders a table — useful for pasting into a pull-request comment.

```markdown
# Change-impact report

| Check | Polarity | Subject | Confidence | Consequence | Grounding |
|---|---|---|---|---|---|
| L1 |  | rule 2 (selector group:acme_analysts) | PROVEN | Rule 2 (selector group:acme_analysts) is unreachable: earlier rule 1 (selector group:acme_analysts) provably matches every case it would, under ordered first-match. The rule is dead code and can be removed or reordered. | ADR-015 (ordered first-match) + §4.2 subsumption |
```

### `--format json`

Machine-readable, for CI and tooling. `polarity` and `unknown` are `null` where
they do not apply.

```json
[
  {
    "check": "L1",
    "subject": "rule 2 (selector group:acme_analysts)",
    "polarity": null,
    "confidence": "PROVEN",
    "consequence": "Rule 2 (selector group:acme_analysts) is unreachable: earlier rule 1 (selector group:acme_analysts) provably matches every case it would, under ordered first-match. The rule is dead code and can be removed or reordered.",
    "grounding": "ADR-015 (ordered first-match) + §4.2 subsumption",
    "policy_id": "policy:orders-access",
    "unknown": null
  }
]
```

---

## Exit codes

The tool is advisory: the exit code is `0` whether or not findings are present.
CI gating is opt-in via `--exit-on <POLARITY>`, which exits `1` if any finding
carries that polarity. See the CI section of
[`analyzing-changes.md`](../../../docs/user-guide/analyzing-changes.md).
