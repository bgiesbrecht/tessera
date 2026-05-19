# Diagnostic Report — ABAC Row-Filter (priority)

**Companion artifacts:**
- `abac-row-filter-priority.tessera.yaml` / `.jsonld`
- `abac-row-filter-priority.databricks.sql`
- `abac-row-filter-priority.comparison.md` (Phase 3 stub)

**Inputs:** `docs/exercises/abac-row-filter-priority-inputs.md`
**Exercise framing:** Canonical three-phase mode, blind derivation. Brice's existing implementation has not been shared during Phase 2.
**Spec version:** v0 with ABAC additions (ADRs 018–021) prefigured; Stage 4 spec changes still pending.
**Target platform:** Databricks Unity Catalog ABAC row filter.

---

## 1. Summary

The Tessera-derived Policy expresses the three-branch row-visibility intent using the post-ABAC vocabulary: `byScope` at catalog scope, `matching` on an attribute axis, three rules under ordered first-match, and a `defaultBranch` for the negated-complement default. The SQL emission compiles all three branches into a single `CASE`-based row-filter UDF (Mechanism B), bound to a `CREATE POLICY ... ROW FILTER` statement at catalog scope.

The exercise's substantive design outputs:

1. **The three-branch case forces Mechanism B.** Databricks ABAC's `TO/EXCEPT` is binary, so three-or-more branches require the principal logic inside the UDF. Tessera's clean multi-rule IR compiles to one UDF; the IR's intent is preserved, the SQL collapses.
2. **Adopter-namespaced axis (`bg:rowDiscriminator`) used because no v0 well-known axis fits.** v0's four axes (`sensitivity`, `dataSubject`, `regulatoryRegime`, `businessDomain`) don't have a slot for "row-classification-key column." Adopter extension is the right escape valve; v1 may absorb this if the pattern proves common.
3. **A condition-operand convention surfaced (`column:$matched`).** Per-rule conditions need to reference the value of the column matched by the policy's `MATCH COLUMNS` predicate, not a hardcoded column name. v0's condition algebra doesn't formalize this. The convention used here is a placeholder pending a v1 design pass.
4. **Cross-policy combination for row filters is a Phase 3 observation.** Deferred to deployment.

---

## 2. Per-element enforcement

| Policy element | Category | Notes |
|---|---|---|
| Scoped attachment (`byScope` at `catalog:bg_rls_demo`) | **Fully enforced** | `CREATE POLICY ... ON CATALOG bg_rls_demo`. The policy auto-applies to any table in the catalog matching the MATCH COLUMNS predicate. |
| Attribute matching (`bg:rowDiscriminator: orderpriority`) | **Fully enforced via taxonomy mapping** | Translates to `has_tag_value('abac_column', 'orderpriority')` per the configured taxonomy. |
| Three-branch principal logic | **Fully enforced via UDF CASE expression** | Mechanism B. UDF body branches on `is_account_group_member` results in the same order as the IR's `rules`. |
| `defaultStrategy: negated-complement` | **Preserved in IR, collapses at SQL emission** | The CASE's `ELSE` clause encodes the default branch. The IR's distinction between `negated-complement` and `explicit-baseline-group` is invisible at the SQL layer for Mechanism B; both compile to the same UDF. |
| `effect: keep-matching-rows` on each rule | **Fully enforced** | UDF returns `BOOLEAN` (TRUE for the principal/row combinations that should be visible); ABAC retains rows where the function returns TRUE. |
| First-match rule ordering (ADR-015) | **Fully enforced via CASE order** | SQL `CASE … WHEN … THEN …` evaluates in order; first match wins; subsequent branches not evaluated. Matches the IR semantics. |
| `MATCH COLUMNS … AS alias` + `USING COLUMNS (alias)` | **Fully enforced** | The policy DDL uses the verified Databricks form. |
| GRANT EXECUTE on UDF | **Emitted defensively** | Same issue #10 finding as prior exercises. |

---

## 3. Edge-case coverage

| # | Edge case | Coverage |
|---|---|---|
| 6.1 | Principal in both restrictive groups | **Fully enforced** via first-match ordering. Most-permissive WHEN branch wins; the `all_priority_ops` branch runs first. |
| 6.2 | Mid-session membership changes | **Fully enforced (with 2–4 min cache lag)**. Same as prior exercises. |
| 6.3 | Multiple row-filter policies on the same table | **Phase 3 observation deferred.** Whether Databricks rejects this analogously to multi-mask is empirically observable. |
| Tag removed from `o_orderpriority` mid-exercise | **Adapter-dependent.** Most likely the policy no longer applies to that table on next evaluation; rows become visible without filtering. |
| Table without an `abac_column=orderpriority` column | **Fully enforced (policy does not apply)**. ABAC's MATCH COLUMNS predicate gates whether the policy attaches to that table. |

---

## 4. v0 spec gaps surfaced by this exercise

### 4.1 Axis-naming for row-discriminator columns

v0's four well-known axes are `sensitivity`, `dataSubject`, `regulatoryRegime`, `businessDomain`. None of them naturally name "this column carries the data that drives row-level access decisions." The Phase 2 artifact uses an adopter-namespaced axis (`bg:rowDiscriminator`) to surface the gap honestly.

Two candidate v1 framings:

- **Add a new well-known axis** (e.g., `rowKey` or `accessKey` or `rowDiscriminator`) to the v0 starter set. Would cleanly capture this pattern; risks proliferation of niche axes.
- **Document the adopter-extensibility pattern more explicitly.** v1's docs would point future authors at "if no v0 axis fits, declare your own under your namespace; if the pattern is common, propose it as a future well-known."

The second is honest, the first is more ergonomic. A v1 design pass picks; this exercise just surfaces the gap.

### 4.2 Condition-operand reference to the matched column

The Tessera policy's per-rule conditions reference column values. In the artifact:

```yaml
condition:
  op: in
  operands:
    - column:$matched
  values: ["1-URGENT", "2-HIGH"]
```

The convention `column:$matched` is a placeholder. The actual semantic the IR needs: "the value of the column that the policy's `MATCH COLUMNS` predicate matched, for the row being evaluated." In SQL emission terms, that's the alias declared in MATCH COLUMNS (here `priority_col`) and threaded into the UDF via USING COLUMNS.

v0's condition algebra has `operands` as a generic list with no formal type system. The convention used here works for the worked example but is not authoritatively defined.

**Candidate v1 design:** formalize a `$matched` (or equivalent) reserved identifier in the condition algebra, plus the binding semantics that says it refers to the MATCH COLUMNS-aliased column. Adapters translate the reserved identifier to the SQL alias at emission. This is small in design surface but worth specifying.

### 4.3 Mechanism A vs B distinction collapses for ABAC row filter

The prior column-mask exercise surfaced two ways to encode the principal split (Mechanism A: TO/EXCEPT in policy header; Mechanism B: branching inside the UDF). For binary cases, A is cleaner. For three-or-more-branch cases — like this one — A cannot express it; B is the only choice.

The implication for Tessera: the IR's clean multi-rule shape compiles to a single Mechanism-B UDF. The IR's `defaultStrategy` distinction (`negated-complement` vs `explicit-baseline-group`) is preserved at the IR layer (for audit, intent, and other-platform emission) but collapses at the Databricks-ABAC-row-filter emission. Both strategies compile to the same `CASE … WHEN … ELSE` UDF.

This is **not a problem** — it's an honest acknowledgment that the IR carries intent that the platform's emission can't always express. The audit value of `defaultStrategy` is at the IR layer; the platform doesn't need to know.

The companion observation: a hypothetical platform that *did* support multi-policy attachment at the row-filter level (each policy with its own TO/EXCEPT) could distinguish `negated-complement` from `explicit-baseline-group` more directly. Databricks doesn't; other platforms might. The IR's expressivity is greater than any single platform's emission shape, which is the right relationship.

### 4.4 Whether `defaultStrategy: explicit-baseline-group` adds value here

Given §4.3, an honest question: does the IR need both `negated-complement` and `explicit-baseline-group` here? On Databricks ABAC row filter, they compile to the same SQL. Could the IR simplify by collapsing them?

Probably not. The IR's audit semantics value the distinction even when the platform doesn't. A future external consumer reading the IR can tell whether the policy author *intended* a baseline-group framing or a negated-complement framing. The choice is meaningful for review, change management, and cross-platform portability, even if Databricks ABAC row filter emission is identical for both.

This exercise uses `negated-complement` (chosen in §4.2 of the inputs) without prejudice. The hypothetical `explicit-baseline-group` variant would be a one-line YAML change and an identical SQL emission.

---

## 5. Per-mechanism timing disclosure

The row-filter mechanism on Databricks ABAC inherits the same account-group cache propagation as the prior exercises: 2–4 minutes for `is_account_group_member` changes. Tag-binding propagation (changes to `abac_column = orderpriority`) is a separate timing characteristic — likely fast since tag lookup goes through the metastore, but a precise measurement is a Phase 3 observation.

---

## 6. Disqualifying-divergence checklist (per inputs §7.3)

| Requirement | Status |
|---|---|
| Use verified ABAC ROW FILTER DDL form | ✓ — `CREATE POLICY ... ON CATALOG ... ROW FILTER fn TO ... FOR TABLES MATCH COLUMNS ... AS alias USING COLUMNS (alias)`. |
| Reference all three groups verbatim | ✓ — `bg_rls_demo_all_priority_ops`, `bg_rls_demo_high_priority_ops`, and `account users` (broad TO). |
| Catalog or narrower scope | ✓ — `ON CATALOG bg_rls_demo` (broader than schema; both valid). |
| `MATCH COLUMNS has_tag_value('abac_column', 'orderpriority')` | ✓ |
| `USING COLUMNS (...)` to pass matched value | ✓ — `USING COLUMNS (priority_col)`. |
| Applies to `bg_rls_demo.tpch.orders_abac` | ✓ (catalog scope; only tagged column in scope). |
| Fail-closed for unmatched principals | ✓ — the UDF's ELSE branch catches "everyone else"; no principal sees nothing. The "fail-closed if UDF errors" case is platform-handled (Databricks returns no rows). |

---

## 7. Findings summary

| Finding | Category | Recommended action |
|---|---|---|
| Axis-naming gap for row-discriminator columns (§4.1) | **v1 candidate** | Open issue. Decision: new well-known axis vs. document adopter-extensibility convention. |
| Condition-operand reference convention (§4.2) | **v1 candidate** | Open issue. Small design — formalize `$matched` reserved identifier or equivalent. |
| Mechanism A vs B collapses for multi-branch row filter (§4.3) | **Observation, not a gap** | Document in the technical design's adapter contract section. No spec change needed; the IR's richer expressivity than platform emission is the right relationship. |
| Cross-policy combination for row filters (§3 / inputs §6.3) | **Phase 3 observation pending** | Deploy this row filter alongside another (or test by attaching a second row filter targeting the same column) to observe Databricks' behavior. |

---

## 8. What this exercise is not

- **Not a multi-policy combination test for row filters.** The Phase 1 inputs designed this as a single-policy exercise that surfaces the three-branch / Mechanism B shape. The multi-policy question for row filters (analogous to the column-mask exercise's α/β/γ) is a deferred observation, not the primary design point here.
- **Not a hierarchical-axis subsumption test.** The `bg:rowDiscriminator` axis is flat (no subsumption); the values are independent. Hierarchical-axis behavior is a separate exercise.
- **Not an attempt to validate every ABAC syntax variant.** WHEN clauses (table-level conditions), USING COLUMNS with multiple args, and other ABAC features the worked example doesn't exercise remain unvalidated.

These are intentional scope choices.

---

## 9. Postscript — adapter coverage 2026-05-19

The Unity Catalog adapter now emits this policy. `_emit_row_visibility_by_scope` in `adapters/unity_catalog/emission.py` produces the three-piece DDL: `CREATE OR REPLACE FUNCTION` with the Mechanism B CASE body, `GRANT EXECUTE` (scaffolding per ADR-025), and `CREATE OR REPLACE POLICY ... ON CATALOG bg_rls_demo ROW FILTER ... FOR TABLES MATCH COLUMNS has_tag_value('abac_column', 'orderpriority') AS orderpriority USING COLUMNS (orderpriority)`.

`AdapterConfig.tag_taxonomy` carries the Tessera-to-Databricks tag translation:

```python
tag_taxonomy = {
    ('bg:rowDiscriminator', 'orderpriority'): ('abac_column', 'orderpriority'),
}
```

The IR's `column:$matched` reference in rule conditions substitutes the function parameter name at emit time — the IR's per-policy abstraction over the matched column.

**Differences from the hand-derived target** (`abac-row-filter-priority.databricks.sql`):

| Aspect | Hand-derived | Adapter | Why divergent |
|---|---|---|---|
| Function parameter name | `priority` | `orderpriority` | Adapter derives from the tag value; arbitrary either way |
| Policy `MATCH COLUMNS` alias | `priority_col` | `orderpriority` | Same — adapter derives from the tag value |
| `COMMENT 'Tessera ABAC row filter — ...'` clause | present | absent | Adapter doesn't emit COMMENT clauses yet (cosmetic; queued as a small refinement) |
| Whitespace alignment | manually aligned for readability | standard formatting | Cosmetic |

Substantively equivalent. Live-applied via `CREATE OR REPLACE POLICY` (the prior hand-derived policy with the same name was overwritten cleanly). Caller (not in either custom group; `account users` only) saw `4,499,708` rows in priorities `3-MEDIUM`, `4-NOT SPECIFIED`, `5-LOW` — exactly the ELSE branch, consistent with the prior exercise's verification.

Capability profile entry `Capability.ATTRIBUTE_BASED_SCOPING` updated to reflect that ABAC row visibility is now implemented (PARTIAL overall; ABAC column masking via byScope is the remaining stub).
