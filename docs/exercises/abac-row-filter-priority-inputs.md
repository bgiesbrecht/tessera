# Phase 1 Inputs — ABAC Row-Filter Exercise (orders_abac.o_orderpriority)

**For:** Claude Code.
**Companion documents:** `docs/worked-example-exercise.md`, `CLAUDE.md`, `DECISIONS.md`, `docs/v1-candidates/abac-and-attribute-axes.md`, and the prior worked examples (especially `abac-column-mask-*` for the ABAC mechanism precedent and `group-row-visibility-*` for the three-branch row-visibility precedent).
**Status:** Canonical three-phase mode. Blind derivation preserved: Brice has set up an existing row-filter ABAC policy in the workspace but has deliberately not shared its DDL with Claude Code. Phase 3 comparison happens after Phase 2 commits.
**Effective spec version:** v0, with ABAC additions (ADRs 018–021) prefigured (Stage 4 spec changes still pending). The companion ABAC column-mask exercise's findings inform the framing here.

---

## 0. Framing

**0.1 — Demo or production scope?**

Demo. Same `bg_rls_demo` environment, same target table (`bg_rls_demo.tpch.orders_abac` on the Azure workspace `adb-984752964297111`) as the ABAC column-mask exercise.

**0.2 — Target platform**

Databricks Unity Catalog, ABAC mechanism — specifically `CREATE POLICY ... ROW FILTER ... MATCH COLUMNS ... USING COLUMNS (...)` form. This is the row-filter sibling of the column-mask mechanism the prior exercise exercised. Public-docs syntax reference: `ROW FILTER function_name TO ... [EXCEPT ...] FOR TABLES [WHEN ...] [MATCH COLUMNS ... [AS alias]] [USING COLUMNS (...)]`; UDF returns `BOOLEAN`.

**0.3 — Scope of this exercise**

A **three-branch row-visibility policy** driven by ABAC tag-matching rather than per-table row-filter attachment. The three branches are the same shape as the original group row-visibility exercise — but the mechanism is ABAC, not the legacy `ALTER TABLE … SET ROW FILTER`.

This exercise's design output, in order of expected substance:

1. **Mechanism A vs Mechanism B forced into Mechanism B.** The prior ABAC column-mask exercise surfaced two ways to encode the principal split (TO/EXCEPT in policy header vs. `is_account_group_member` inside the UDF). For binary exempt/not-exempt cases, A is cleaner. For *three-branch* cases, A cannot express it — Databricks ABAC's principal binding is binary (`TO ... EXCEPT ...`). Tessera's three-rule IR must compile to a single UDF with CASE branches (Mechanism B). The exercise validates that the IR's clean multi-rule shape compiles correctly to the single-UDF emission.
2. **An axis-naming gap.** The `abac_column=orderpriority` tag doesn't fit any of the four well-known v0 axes (`sensitivity`, `dataSubject`, `regulatoryRegime`, `businessDomain`). The exercise surfaces what axis a "row-classification-key column" belongs to. Likely a v1-candidate finding.
3. **A condition-operand reference gap.** Per-rule conditions in the IR reference column values (`column:bg_rls_demo.tpch.orders.o_orderpriority`). For ABAC row filters, the column is identified by `MATCH COLUMNS` and aliased; the rule's `condition.operands` should reference the alias, not a hardcoded column name. v0's condition algebra doesn't have a clean syntax for "the matched-attribute column's value." Likely another v1-candidate finding.
4. **Cross-policy combination for row filters.** Does Databricks ABAC reject multiple row filters on the same table (analogous to the multi-mask error from the column-mask exercise)? Empirical observation deferred to Phase 3 deployment.

---

## 1. The protected resource

**1.1 — Protected table**

`bg_rls_demo.tpch.orders_abac` on workspace `adb-984752964297111`. Same table as the column-mask exercise; the row filter and column mask compose at evaluation time on Unity Catalog.

**1.2 — Discriminator column**

`o_orderpriority` (STRING). Five possible values:

- `1-URGENT`
- `2-HIGH`
- `3-MEDIUM`
- `4-NOT SPECIFIED`
- `5-LOW`

The column is tagged `abac_column = orderpriority` (set up during the column-mask exercise's Phase 1, intentionally pre-tagged for this follow-on).

**1.3 — Other columns**

Unaffected. The row filter narrows which rows are visible; the column mask on `o_clerk` (still attached from the prior exercise) continues to apply to whichever rows the row filter admits.

---

## 2. The attribute axis and tag taxonomy

**2.1 — Tessera axis for the row-discriminator column**

This is a real design choice. The tag `abac_column=orderpriority` doesn't fit the v0 well-known axes (`sensitivity`, `dataSubject`, `regulatoryRegime`, `businessDomain`) cleanly. The column carries data that *drives row-level access decisions*, but it's neither a sensitivity classifier per se nor a data-subject identifier.

**Interpretive choice for this exercise:** declare an **adopter-namespaced axis** to make the gap visible. Specifically:

- Adopter namespace: `bg` (placeholder for Brice's deployment).
- New axis: `bg:rowDiscriminator`.
- Value for `o_orderpriority`: `bg:rowDiscriminator: orderpriority`.

The intent: "this column is the row-classification key for ABAC row-filter policies." Adopters who model the same pattern under their own namespace declare their own values. v1 may absorb this into a well-known axis (e.g., a new `rowKey` or `accessKey` axis) if the pattern proves common; the exercise surfaces the need.

**Tag taxonomy mapping (per ADR-021):**

```yaml
tagTaxonomy:
  - axis: bg:rowDiscriminator
    axisValue: orderpriority
    tagKey: abac_column
    tagValue: orderpriority
```

**2.2 — Why not use a v0 well-known axis?**

Considered and rejected:

- `sensitivity`: stretchy. One could argue priority IS a sensitivity classification, but the policy isn't about sensitivity-graded access; it's about category-graded access. The semantic mismatch would bury the actual pattern under a misleading label.
- `businessDomain`: even more stretchy. `businessDomain: orderpriority` reads like "the orderpriority business domain," which isn't what's being said.
- `dataSubject` / `regulatoryRegime`: not applicable.

Declaring an adopter-namespaced axis is the honest framing. The diagnostic records the finding.

---

## 3. The principal model

**3.1 — Principal identification**

Standard Databricks: `is_account_group_member('group_name')` evaluated at session time.

**3.2 — Three groups**

- `bg_rls_demo_all_priority_ops` — privileged group, sees all rows.
- `bg_rls_demo_high_priority_ops` — restricted group, sees `1-URGENT` and `2-HIGH` rows only.
- (Implicit default) — everyone else (including all `account users` not in either restrictive group), sees `3-MEDIUM`, `4-NOT SPECIFIED`, `5-LOW` rows.

All three groups already exist (the first two from the original group row-visibility exercise; the implicit default is "everyone else in `account users`").

---

## 4. The policy intent

**4.1 — In plain English**

A row in `orders_abac` is visible to a principal if and only if:

- The principal is in `bg_rls_demo_all_priority_ops`, OR
- The principal is in `bg_rls_demo_high_priority_ops` AND the row's `o_orderpriority` is `1-URGENT` or `2-HIGH`, OR
- The principal is in neither restrictive group AND the row's `o_orderpriority` is `3-MEDIUM`, `4-NOT SPECIFIED`, or `5-LOW`.

(Per the input requirements, every principal is in at least one of these three brackets — the default catches everyone not in either restrictive group, regardless of any other group membership.)

**4.2 — Default-handling strategy**

Three branches with a clear default for "everyone else" maps cleanly to either:

- **Explicit-baseline-group** with `account users` as the baseline — the "everyone else" rule is the baseline rule.
- **Negated-complement** — the third branch is the `defaultBranch` for principals matching neither restrictive rule.

The original group exercise produced both forms (Policy A and Policy B). For this ABAC exercise, I'll produce **negated-complement only** to match the simpler shape and because the ABAC mechanism doesn't naturally distinguish between the two (both compile to the same UDF — see §5 below).

**4.3 — Purpose binding / Time / Jurisdiction**

None.

**4.4 — Obligations**

None.

---

## 5. Mechanism choice (Mechanism A vs Mechanism B)

This is the central design point this exercise validates.

**Mechanism A** (TO/EXCEPT in policy header, unconditional UDF body) **cannot express three branches**. Databricks ABAC's principal binding supports `TO principal_set EXCEPT principal_set` — a binary split, not a three-way one. With three branches, the policy must encode the principal logic somewhere other than `TO/EXCEPT`.

**Mechanism B** (broad `TO`, conditional UDF body) is the natural fit. The UDF body becomes a `CASE` over `is_account_group_member` results, returning `BOOLEAN` per row. The Tessera adapter compiles all three IR rules into a single UDF.

**Implications:**

- Tessera's three-rule IR (clean multi-branch shape per ADR-014/015) compiles to a single SQL UDF for Databricks ABAC row filter.
- The IR's `defaultStrategy: negated-complement` vs `explicit-baseline-group` distinction is **lost** at the SQL emission layer in Mechanism B — both produce the same UDF (a CASE expression with the same branches). The distinction is preserved in the IR for audit and intent purposes; the emission is the same.
- This is a real design observation worth recording: ABAC row filter is structurally Mechanism-B-only for multi-branch policies. The prior column-mask exercise's Mechanism A vs B distinction collapses here.

---

## 6. Edge cases

**6.1 — Principal in both restrictive groups**

By the first-match semantics of Tessera's ordered rules (ADR-015) and the implicit ordering of `is_account_group_member` checks in the emitted UDF: the first matching `WHEN` branch wins. The natural ordering — most-permissive first (`all_priority_ops` → `high_priority_ops` → default) — gives a member of both `all_priority_ops` and `high_priority_ops` the all-rows behavior. Matches the original group exercise's behavior.

**6.2 — Mid-session group membership changes**

Subject to the same 2–4 minute account-group cache propagation observed in prior exercises. No new mechanism-specific timing.

**6.3 — Multiple row-filter policies on the same table (deferred to Phase 3)**

The column-mask exercise surfaced that Databricks rejects multi-mask evaluation when two column masks resolve to the same column. Whether the analogous constraint holds for row filters is a Phase 3 observation:

- If the same `MULTIPLE_*` error appears for row filters, the cross-policy combination resolution from the column-mask exercise (γ-with-refinement) applies symmetrically.
- If row filters compose (e.g., logical AND of all matching filters' return values), Tessera's model would need a different framing.

Phase 3 deploys both this exercise's row filter and (optionally) a second row filter to test.

---

## 7. What success looks like

**7.1 — Behavioral verification criteria**

Three scenarios against `bg_rls_demo.tpch.orders_abac`, mirroring the original group exercise but via ABAC mechanism:

| Scenario | Brice's membership | Expected priorities visible |
|---|---|---|
| 1 | Member of `bg_rls_demo_all_priority_ops` | All five |
| 2 | Member of `bg_rls_demo_high_priority_ops` only | `1-URGENT`, `2-HIGH` |
| 3 | Neither restrictive group | `3-MEDIUM`, `4-NOT SPECIFIED`, `5-LOW` |

Brice's current state at Phase 1 commit (per discovery 2026-05-19): not in either restrictive group. Scenario 3 is the immediately-testable state; Scenarios 1 and 2 require Brice to add himself to one of the groups (with the standard 2–4 minute cache lag).

**7.2 — Acceptable divergences**

Function names, SQL formatting, header comments. Choice of `CASE`/`WHEN`/`ELSE` versus equivalent constructs as long as semantically equivalent.

**7.3 — Disqualifying divergences**

The Tessera derivation must:

- Use the verified ABAC ROW FILTER DDL form per Databricks docs.
- Reference all three groups verbatim.
- Apply at scope `catalog:bg_rls_demo` (or narrower; schema scope is also valid).
- Use `MATCH COLUMNS has_tag_value('abac_column', 'orderpriority')` for column selection.
- Use `USING COLUMNS (...)` to pass the matched column's value into the UDF.
- Apply to `bg_rls_demo.tpch.orders_abac` (and any other tables in scope with the same tag, though none currently exist).
- Be fail-closed for principals matching no rule — though under the three-branch design, "everyone else" catches the default, so fail-closed only applies if the UDF errors.

---

## 8. Anticipated findings

**8.1 — Axis-naming gap (§2.1).** v0's four well-known axes don't have a slot for "row-discriminator column." Adopter-namespaced workaround used; v1 candidate.

**8.2 — Condition-operand reference (§4).** Rule conditions need to reference the value of the MATCH COLUMNS-aliased column. v0's condition algebra hardcodes column references; an ABAC-aware reference convention (e.g., `$.matched`, or `column:$alias`) is needed.

**8.3 — Mechanism A vs B forced to B (§5).** Three-branch row filters cannot use Mechanism A on Databricks ABAC; Tessera's clean three-rule IR compiles to one CASE-based UDF. The `defaultStrategy` distinction is preserved at the IR layer but collapses at the SQL emission layer.

**8.4 — Multi-row-filter constraint (§6.3).** Phase 3 observation pending.

**8.5 — Other possible findings.** Phase 3 deployment may surface things not anticipated here; that's the exercise's purpose.

---

## 9. Phase 2 deliverables

After this inputs commit, Phase 2 produces (all under `spec/v0/examples/`):

- `abac-row-filter-priority.tessera.yaml` — Single Policy, three rules + defaultBranch, RowVisibilityConstraint kind, byScope + matching on `bg:rowDiscriminator: orderpriority`.
- `abac-row-filter-priority.jsonld` — canonical form.
- `abac-row-filter-priority.databricks.sql` — `CREATE FUNCTION` (returns BOOLEAN, CASE over `is_account_group_member`) + `CREATE POLICY … ROW FILTER` with MATCH COLUMNS and USING COLUMNS.
- `abac-row-filter-priority.diagnostic.md` — per-element enforcement, surfaces the three anticipated findings explicitly.
- `abac-row-filter-priority.comparison.md` — Phase 3 stub for the deployment observation and (later) the comparison against Brice's existing implementation.

Phase 3 deployment runs against the Azure workspace once Phase 2 lands.
