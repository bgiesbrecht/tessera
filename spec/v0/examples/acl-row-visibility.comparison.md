# Phase 3 Comparison — ACL-Table Row Visibility

**Companion artifacts:**
- `acl-row-visibility-policy.tessera.yaml` / `.jsonld`
- `acl-row-visibility.databricks.sql`
- `acl-row-visibility.diagnostic.md`

**Inputs:** `docs/exercises/acl-row-visibility-inputs.md`
**Exercise framing:** `docs/worked-example-exercise.md`
**Existing implementation reference:** `RLS Demo (3).ipynb` (Databricks notebook), cells 11–15 — the "Mapping-table RLS (managed ACL table)" section. Shared 2026-05-18.

**Status:** Behavioral verification (§2) and structural comparison (§3) both complete.

---

## 1. Summary

The Tessera-derived single-rule Policy compiles to a Unity Catalog row filter function that is **substantively equivalent** to the existing notebook implementation (§3). Function-body logic, join shape, normalization, and EXISTS semantics all match. Cosmetic divergences (function name, parameter name, JOIN ON column order) are accepted per inputs §7.2. One structural finding emerged from the comparison that the Tessera derivation did not anticipate: the existing implementation includes a `GRANT EXECUTE ON FUNCTION` statement (§3.2 below) that Tessera does not emit and the v0 IR does not declare. This is a real operational gap, not a behavioral one.

Three v0 IR gaps were surfaced by the derivation (diagnostic §4); none affected the SQL emission's correctness, but each carried structural information that the IR could not express natively.

---

## 2. Behavioral equivalence (§3.1 of the exercise framing)

### 2.1 Test scenarios per inputs §7.1

Behavioral equivalence verified by deploying the Tessera-derived row filter (`acme.tpch.tessera__acl_row_visibility__row_filter`) to `acme.tpch.orders_rls_acl` and running `SELECT DISTINCT o_orderpriority` under three ACL membership states.

| Scenario | Setup | Expected (Brice) | Observed (Tessera Policy B) | Match |
|---|---|---|---|---|
| 1 | Seed data as-is (Brice → urgent_priority_ops + high_priority_ops) | `1-URGENT`, `2-HIGH` | Same | ✓ |
| 2 | Add (Brice, standard_ops) to `rls_acl_mapping` | `1-URGENT`, `2-HIGH`, `3-MEDIUM`, `4-NOT SPECIFIED`, `5-LOW` | Same | ✓ |
| 3 | Delete all Brice rows from `rls_acl_mapping` | zero priorities, zero rows | Same (0 rows, 0 distinct priorities) | ✓ |

Verification mechanics: an SDK-driven script created the protected table (`orders_rls_acl`) as a CTAS from `samples.tpch.orders` (the unfiltered TPC-H source), created and seeded both ACL tables, deployed the row filter, then executed the three scenarios with ACL-table modifications between them. Final state restored to the §2.8 seed values from the inputs.

### 2.2 Behavioral categorization (per §3.1's four-category framework)

All three scenarios fall into the "both implementations agree" category for the Tessera-derived filter against the inputs' expectations. The §3.1 four-category analysis (Tessera-wrong / existing-wrong / spec-wrong / intent-ambiguous) requires the existing implementation; it will be filled in when Brice shares it.

### 2.3 Operational observation — ACL change propagation

The ACL mechanism showed **synchronous propagation** of membership changes: each scenario's query ran immediately after its `INSERT`/`DELETE` against the ACL tables, and the row-filter's `EXISTS` clause reflected the change on the very next query. There was no cache lag.

This is a notable contrast with the group exercise's account-group cache, which exhibited a 2–4 minute propagation window. The diagnostic's §5 timing disclosure called this out as the expected behavior; this verification confirms it.

Per the §5.2 timing-disclosure principle from the technical design, a Databricks adapter capability profile should declare both characteristics:

- **Group-based mechanism (`is_account_group_member`):** ~2–4 minute propagation window via account-group cache (worked example: group-row-visibility exercise).
- **ACL-table mechanism (direct `EXISTS` over ACL tables):** synchronous on next query; no caching layer (worked example: this exercise).

Two mechanisms, same adapter, materially different timing characteristics. Recording it cleanly here so the next adapter design pass has both data points.

### 2.4 Setup gotcha worth recording

A setup mistake during initial deployment is worth noting because it could trip a future contributor: the protected table was first created as a CTAS from `acme.tpch.orders`, which already had the *group* exercise's row filter attached. Because the operator's group membership at the time was "in neither restrictive group" (left over from the group exercise's Scenario 3), the CTAS source was filtered to only show priorities 3, 4, 5 — the new ACL table inherited that filtered set and was missing the 1-URGENT and 2-HIGH rows the ACL was supposed to grant to Brice.

The fix was straightforward: rebuild the table from `samples.tpch.orders` (the unfiltered TPC-H source).

**Lesson for future worked examples:** when creating a protected test table by CTAS, the source must be either (a) unfiltered, or (b) verified to contain the full range of values the policy under test will exercise. Filtered sources silently truncate the test corpus.

---

## 3. Structural comparison (§3.2 of the exercise framing)

### 3.1 SQL row-filter function — line-by-line

Both implementations produce a Unity Catalog row filter function with substantively identical logic: a `RETURN EXISTS (SELECT 1 FROM rls_acl_mapping JOIN rls_priority_acl ON code_name WHERE lower(trim(username)) = lower(trim(current_user())) AND p.orderpriority = $parameter)`.

| Dimension | Existing implementation | Tessera-derived | Category |
|---|---|---|---|
| Function name | `acme.tpch.rls_orders_by_priority` | `acme.tpch.tessera__acl_row_visibility__row_filter` | **Accepted divergence** per inputs §7.2; Tessera's form is deterministic and traces back to the policy ID. |
| Function parameter name | `p_priority` | `o_orderpriority` | **Accepted divergence**. Both work — parameter names are local to the function body; Databricks binds the function to the table column via the `ON (…)` clause in `ALTER TABLE`. |
| `RETURNS BOOLEAN` clause | Implicit (Databricks infers from the EXISTS expression) | Explicit | **Accepted divergence**. Behaviorally identical. |
| JOIN ON column order | `ON p.code_name = m.code_name` | `ON m.code_name = p.code_name` | **Match** (semantically). Equivalent join predicate. |
| Principal normalization | `lower(trim(m.username)) = lower(trim(current_user()))` | Same | **Match** verbatim. |
| Priority match | `p.orderpriority = p_priority` | `p.orderpriority = o_orderpriority` | **Match** modulo parameter name. |
| EXISTS form | `RETURN EXISTS (SELECT 1 FROM …)` | Same | **Match**. |
| ALTER TABLE attachment | `ON (o_orderpriority)` | Same | **Match**. |
| `GRANT EXECUTE ON FUNCTION … TO 'account users'` | **Present** | **Absent** | **Real divergence with operational implications.** See §3.2 below. |
| Header / provenance comments | None | Multi-line header tracing back to `policy:acl-row-visibility` and companion artifacts | **Tessera adds.** Audit-trail value. |

### 3.2 The GRANT EXECUTE finding

The existing implementation includes:

```sql
GRANT EXECUTE ON FUNCTION acme.tpch.rls_orders_by_priority TO `account users`;
```

This is operationally meaningful: without it, callers other than the function owner may hit `PERMISSION_DENIED` when their query triggers the row filter. The notebook's own prerequisite cell (cell 0) hints at this with "EXECUTE on functions" as a precondition.

The Tessera-derived form does not emit this grant. The v0 IR does not have a place to declare "the function this policy compiles to must be executable by these principals" — grants are typically considered separate from policy semantics. But for a deployable artifact, the grant is part of what makes the policy actually work for users.

This is a real finding the exercise produced:

**Category:** v1 candidate (lower priority than the principal-set / case-insensitive / existsInDataset gaps, but real).

**Candidate v1 shape:** an optional `executeGrants` field on Policy that names the principals (or principal selectors) authorized to be subject to the policy. The adapter compiles this into platform-specific grants alongside the row filter function. Default value: `account users` on Databricks (matching the existing convention); explicitly overridable.

**Alternative framing:** treat grants as out-of-band operational concern, document in the adapter contract that emitting policies requires a separate grant step, and leave it to deployment tooling. Defensible but loses the "v0 artifact is complete" property — a customer who copy-pastes Tessera-emitted SQL into their environment would need to remember the grant manually.

I lean toward making this an explicit IR concern in v1 (the first framing), because the grant is structurally part of "this policy is deployable" and the alternative is silent operational footgun. But it's a real design question that needs working through.

### 3.3 What Tessera adds (confirmed by §3.1 and §3.2)

| Element | Tessera form | Existing implementation |
|---|---|---|
| Canonical IR form | `.tessera.yaml` + `.jsonld` files | None |
| Declared `defaultStrategy: none` | Explicit fail-closed declaration | Implicit (no `ELSE` branch in SQL; EXISTS returns false for unmapped users) |
| Capability-requirement declarations | `data-driven-selectors`, `two-table-join-via-codename`, `case-insensitive-principal-match`, `fail-closed-on-acl-absence` named explicitly | None |
| Provenance / traceability | Header comments link the SQL function back to its policy `@id` | None |
| Diagnostic report | Per-element enforcement table; v0 IR gap surfacing | None |
| Timing disclosure | Per-mechanism (§2.3; ties to technical design §5.2) | None |
| Comparison record | This document | None |

### 3.4 What the existing implementation has that Tessera does not capture

| Element | Existing form | Tessera capture |
|---|---|---|
| `GRANT EXECUTE` on the row filter function | Inline cell after the function definition | Not captured. See §3.2 — this is the substantive finding. |
| Verification queries (cell 15) | Inline `select o_orderpriority, count(o_orderpriority) ... group by` after attachment | Tessera has parallel scaffolding in `verify_scenario.py` (covers the group exercise's scenarios; ACL verification was scripted ad-hoc, not committed). |
| Catalog/schema/table creation cells (cells 1–4) | Inline setup | Tessera does not try to express this — it is deployment, not policy. (Same call as the group exercise's §3.3.) |
| Seed-data INSERTs (cells 11–12) | Inline | Same — data, not policy. |

The notebook's setup, seeding, and verification cells are correctly **out of scope** for the IR — they are deployment and demonstration, not policy meaning. The only structural finding from §3.4 is the `GRANT EXECUTE`, which the inputs §7.3 disqualifying checklist did not capture but which the existing implementation actually requires for non-owner usage.

---

## 4. Lessons for v0 (§3.3 of the exercise framing)

### 4.1 v0 bug fixes

None anticipated. The diagnostic-flagged gaps (§4 of the diagnostic) are limitations, not bugs.

### 4.2 v0 corrections in non-immutable artifacts

The diagnostic surfaced one gap — IRI-safety convention from the group exercise — that has been resolved by issues #4–#6 from the prior exercise. No new doc-correction items are anticipated from this exercise, pending §3.

The setup-gotcha in §2.4 may warrant a one-paragraph addition to `docs/worked-example-exercise.md` about validating the source corpus when creating a protected test table. Low priority.

### 4.3 v1 candidates

Three gaps in the diagnostic (§4):

- **Two-table-join not natively expressible in `PrincipalSetFromTable`** (diagnostic §4.1).
- **No case-insensitive / trim match modifier on `PrincipalSetFromTable`** (diagnostic §4.2).
- **`existsInDataset` operator's operand shape under-specified** (diagnostic §4.3).

A fourth gap from this comparison's §3:

- **Function `GRANT EXECUTE` not expressible in the IR** (comparison §3.2). The existing implementation emits a `GRANT EXECUTE ON FUNCTION … TO 'account users'` alongside the row filter function definition. The Tessera-derived form does not. Adding an `executeGrants` field (or equivalent) to Policy is the candidate; the alternative is documenting grants as adapter-operational concern. Either is defensible; this is a real design question for v1.

All four should be opened as v1-candidate GitHub issues. The first and third are structurally related and likely to be co-designed in v1; the fourth is standalone.

A fifth, lower-priority candidate is recorded for tracking: **ACL integrity checks** (diagnostic §3.1) — surfacing the three silent failure modes characteristic of data-driven access patterns (codename collisions across users, codenames without priority mappings, priorities without codename coverage).

### 4.4 Out-of-scope confirmations

- **Operational interoperability**, **runtime interoperability**, **group-based row visibility** — all out of scope per ADR-001, ADR-002, and inputs §0.3 respectively. Correctly not addressed.
- **Purpose binding, obligations, classifications, transformations** — declared not applicable per inputs §4. Correctly not invented.

---

## 5. Recommended actions

1. ✓ **Behavioral verification of the three scenarios** — done (§2).
2. ✓ **Existing-implementation comparison** — done (§3, against `RLS Demo (3).ipynb` cells 11–15).
3. **Open four v1-candidate issues** (with `v1-candidate` label):
   - `principal-set-from-joined-tables` — multi-table support in `PrincipalSetFromTable` (diagnostic §4.1).
   - `principal-set-match-modifiers` — case-insensitive / trim match flag on `PrincipalSetFromTable` (diagnostic §4.2).
   - `exists-in-dataset-operand-formalization` — formal operand shape for the `existsInDataset` operator (diagnostic §4.3).
   - `policy-execute-grants` — Policy-level declaration of function-execute grants the adapter compiles in (comparison §3.2).
4. **Open one lower-priority v1-candidate issue**:
   - `acl-integrity-checks` — surface silent failure modes characteristic of data-driven access patterns (diagnostic §3.1).

The first three were anticipated by Phase 2; the fourth emerged from the §3 comparison and was not predicted by the Phase 2 diagnostic.

---

## 6. What this comparison did not do (so far)

- **§3 structural comparison** is unpopulated pending the existing implementation share.
- **JSON-LD validation against the context and ontology.** Manual reading suggests no obvious problems; the formal validation belongs to the (not-yet-built) linter.
- **Performance benchmarking.** Out of scope per inputs §0.1.
- **Reasoning** (subclass propagation, contradiction detection). No classification or competing-policy structure in this policy.

---

## 7. Closing observation

The ACL exercise complements the group exercise: same target platform, parallel structure, different parts of the v0 IR exercised. Where the group exercise surfaced gaps around multi-branch policy expression (resolved by ADR-014/015), this exercise surfaces gaps around multi-table data-driven principal selection and operational grant emission — gaps which the v0 IR is honest enough to expose but not rich enough to resolve in-place. They become v1 candidates.

The two exercises together also produce the first two worked examples that ground the §5.2 timing-disclosure principle in concrete, measured observations on a real adapter. The group exercise documented ~2–4 minute account-group cache propagation; this exercise documented synchronous ACL propagation. Two mechanisms on the same adapter, materially different timing — the principle's central claim, now grounded.

The §3 comparison confirmed substantive equivalence between Tessera-derived and existing implementations on the EXISTS+join logic, with one operational finding (the missing `GRANT EXECUTE` emission) that the Phase 2 diagnostic did not predict. This is exactly the kind of "comparison surfaces what Phase 2 misses" outcome the exercise framework anticipates — Phase 2 found three v1 candidates; Phase 3 found a fourth.
