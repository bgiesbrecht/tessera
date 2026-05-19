# Diagnostic Report — ACL-Table Row Visibility

**Companion artifacts:**
- `acl-row-visibility-policy.tessera.yaml` / `.jsonld`
- `acl-row-visibility.databricks.sql`

**Inputs:** `docs/exercises/acl-row-visibility-inputs.md`
**Exercise framing:** `docs/worked-example-exercise.md`
**Spec version:** v0, post-ADR-014 / ADR-015.
**Target platform:** Databricks Unity Catalog.

This report is the honest accounting required by §2.4 of the exercise framing: which elements of the policy are fully enforced, which are partially enforced, which are unenforced — plus the v0 IR gaps the exercise surfaces and a per-mechanism timing disclosure per the §5.2 timing-disclosure principle from the technical design.

---

## 1. Summary

The Tessera-derived Policy compiles to a Unity Catalog row filter function that should produce the visibility specified by the policy intent. The SQL emission uses `EXISTS` against a two-table join through `rls_acl_mapping` and `rls_priority_acl`, with case-insensitive whitespace-trimmed matching on the principal column. Three v0 IR gaps surfaced during the derivation, plus one mechanism-specific timing observation. None of the gaps blocks the exercise from completing; all are recorded as v1 candidates (v0 immutability is no longer admissible per ADR-014's closing note).

The pattern exercises `byDataset` / `PrincipalSetFromTable` for the first time in this project's worked examples. The gaps surfaced are properties of the v0 vocabulary's expressiveness, not of the framework's correctness — the SQL emission is correct; the IR carries less of the pattern's structure than would be ideal.

---

## 2. Per-element enforcement

| Policy element | Category | Notes |
|---|---|---|
| Resource binding (`bg_rls_demo.tpch.orders_rls_acl`) | **Fully enforced** | `ALTER TABLE … SET ROW FILTER` attaches the filter to the protected table. |
| Principal selector — single-table portion (`rls_acl_mapping`) | **Fully enforced** | The `byDataset` selector and `PrincipalSetFromTable` carry the principal-to-codename mapping; the SQL emits the corresponding lookup. |
| Principal selector — codename indirection (`rls_priority_acl`) | **Partially enforced** | v0 `PrincipalSetFromTable` models a single ACL table. The second table reference lives in the `existsInDataset` condition operand as a best-effort representation; the adapter must compile the join from this structural shape plus its knowledge of the pattern. SQL emission is correct, IR is under-specified. See §4.1. |
| Case-insensitive, whitespace-trimmed match | **Unenforced at the IR level; enforced by the adapter** | The IR does not declare a normalization modifier on `PrincipalSetFromTable`. The adapter applies `lower(trim(…))` based on convention from the inputs (§3.2). The match correctness is preserved; the policy file does not record the intent. See §4.2. |
| `existsInDataset` condition operator | **Partially enforced** | The operator is in the v0 condition algebra, but its operand shape is under-specified. The adapter compiles a reasonable structural reading of the operand into the EXISTS clause. See §4.3. |
| `defaultStrategy: none` | **Fully enforced** | Single-rule Policy with fail-closed default. A principal with no ACL chain matches no rule and sees no rows. |
| `effect: keep-matching-rows` | **Fully enforced** | The row filter function returns TRUE/FALSE; rows are kept iff the EXISTS clause evaluates true. |
| `action: Read` | **Implicitly enforced** | Unity Catalog row filters apply to read paths. Write/delete paths are out of scope for row visibility; no per-action policy needed. |
| Purpose binding | **Not applicable** | Inputs §4.4 declares none. |
| Obligations (audit log / notify / watermark) | **Not applicable** | Inputs §4.6 declares none. |
| Capability requirements declared | **Declared, not enforced by Tessera at v0** | The policy declares `data-driven-selectors`, `two-table-join-via-codename`, `case-insensitive-principal-match`, `fail-closed-on-acl-absence`. These names are not yet vocabulary; they exist as machine-readable strings the adapter capability profile may match against. The Databricks adapter (when built) will be expected to declare which of these it supports. |

---

## 3. Edge-case coverage (per inputs §5)

| # | Edge case | Coverage | Notes |
|---|---|---|---|
| 5.1 | Duplicate ACL entries | **Fully enforced** | The SQL uses `EXISTS`, which is idempotent on duplicate matches. |
| 5.2 | Stale / expired ACL entries | **N/A** | No expiration columns in either ACL table. |
| 5.3 | Mid-session ACL changes | **Fully enforced; synchronous on next query** | See §5 of this report for the timing disclosure. Contra the group exercise's 2–4 minute account-group propagation, the ACL pattern reads the tables directly on each query. |
| 5.4 | Joins with other tables | **Fully enforced** | Unity Catalog row filters apply to the base table before joins; downstream joins see only the filtered rows. |
| 5.5 | Views over the protected table | **Fully enforced** | Standard Unity Catalog behavior. |
| 5.6 | Service accounts | **Fully enforced** | Service accounts are treated as ordinary principals; the same `current_user()` resolution applies; absence from `rls_acl_mapping` yields zero visibility. |
| 5.7 | ACL table unavailability | **Fully enforced (fail-closed)** | The EXISTS clause cannot evaluate true if either ACL table is unavailable; the row filter returns FALSE for all rows. |
| 5.8 | Empty ACL tables | **Fully enforced** | Empty tables yield no matches; no rows are visible. Consistent with `defaultStrategy: none`. |
| 5.9 | Cross-tenant / cross-region | **N/A** | Out of scope. |
| 5.10 | Silent failure modes | **Surfaced, not enforced** | The diagnostic surfaces these explicitly; the SQL behavior is correct, but the policy text gives no warning when these failure modes activate. |

### 3.1 Note on 5.10 — silent failure modes

Three failure modes are silent in the current pattern:

- **Codename collisions across users.** Two users sharing a codename share the codename's priorities. The pattern allows this by design (codenames are generalized to shared roles).
- **Codenames in `rls_acl_mapping` not present in `rls_priority_acl`.** The join produces no rows for that codename; the user sees nothing from it. No warning.
- **Priorities in the protected table not covered by any codename in `rls_priority_acl`.** No user ever sees rows with that priority. No warning.

These are characteristic of data-driven access patterns. A v1 candidate would be **ACL integrity checks** at policy-load time — comparing the ACL tables' contents against the protected table's column values and surfacing orphaned codenames or unreachable priority values. v0 has no facility for this.

---

## 4. v0 IR gaps surfaced

These are findings the exercise produced. Per the inputs §8 ("On v0 vs v1 candidates"), they are recorded as **v1 candidates**, not v0 corrections — the v0 immutability bar came down with ADR-014.

### 4.1 PrincipalSetFromTable models a single ACL table; two-table joins are under-specified

The v0 `PrincipalSetFromTable` carries `table`, `principalColumn`, `resourceColumn`, `permissionColumn`, `permissionValue` — all fields of a single ACL table. The ACL pattern in this exercise uses two tables joined on a codename column: the principal-to-codename mapping (`rls_acl_mapping`) and the codename-to-priority mapping (`rls_priority_acl`). v0 has no IR primitive for "principal set computed from a join of multiple ACL tables."

The artifact's workaround is to carry the second table in the `existsInDataset` condition operand. This works as a structural hint for the adapter, but it leaves the *join semantics across the principal selector and condition layers* implicit. An adapter that doesn't already know the codename-indirection pattern would not be able to compile correct SQL from the IR alone.

**Candidate v1 shape:**

```yaml
principal:
  selector: byDataset
  dataset:
    "@type": PrincipalSetFromJoinedTables
    tables:
      - { table: rls_acl_mapping,   principalColumn: username,  joinColumn: code_name }
      - { table: rls_priority_acl,  joinColumn: code_name,      resourceColumn: orderpriority }
```

Or, more general: an explicit `join` structure within `PrincipalSetFromTable` that names additional tables and their join columns. The exact shape is design work; the principle is "carry the full join structure in the IR rather than leaving the second leg to adapter convention."

This would also clarify the `existsInDataset` operator's role — it would describe the existence test against the full computed principal set, not against a separate secondary table.

### 4.2 No case-insensitive / whitespace-trim match modifier on PrincipalSetFromTable

The existing implementation normalizes the principal column with `lower(trim(...))`. The v0 IR has no field to declare this. The Tessera-derived SQL applies the normalization based on the conventional Databricks identity model (emails are case-insensitive); the IR doesn't record the intent.

This is a real expressiveness gap: a policy reviewer reading the YAML cannot tell whether matches are case-sensitive or case-insensitive. Two policies with different match semantics could be IR-identical.

**Candidate v1 shape:** a `match` field on `PrincipalSetFromTable` (and `ResourceSetFromTable`) declaring normalization. Initial values: `exact`, `case-insensitive`, `case-insensitive-trim`. Closed set in v1; extensibility per ADR-007.

### 4.3 The `existsInDataset` operator's operand shape is under-specified

The v0 ontology and context define `existsInDataset` as a condition operator paired with `byDataset` selectors. The intended semantics is "exists a row in the referenced dataset matching the join predicate." But:

- The operator's operand shape is not formalized in the v0 ontology or schema. The artifact carries a `ResourceSetFromTable` as the operand with `principalColumn` and `resourceColumn` doing double duty (the former matches a column from the principal selector's set; the latter matches against the protected row's column). This is a reasonable structural choice but it isn't canonical.
- The join binding — *which* column of the principal selector matches *which* column of the operand dataset — is not explicit. The adapter must infer from naming conventions.

**Candidate v1 shape:** a formal `existsInDataset` operand schema declaring `dataset` and `join` (a list of (from-column, to-column) pairs binding the principal selector's columns to the dataset's). The operator becomes structurally complete.

This issue is structural cousin to §4.1: both reflect that v0's expression of multi-table data-driven access is incomplete. A v1 design pass would address them together, likely producing one richer `byDataset` shape rather than separate operand schemas.

---

## 5. Per-mechanism timing disclosure

Per the §5.2 timing-disclosure principle from the technical design (added in the same revision as ADR-014's worked-example commit chain): the adapter's capability profile should declare the timing/consistency characteristics of each mechanism it emits. The ACL pattern's characteristics:

**ACL change propagation: synchronous on next query.** The row filter function reads `rls_acl_mapping` and `rls_priority_acl` directly on each invocation; there is no caching layer analogous to the account-group cache. A change to either ACL table takes effect on the next query against the protected table (subject only to whatever query-result caching is configured at the warehouse layer, which is independent of the row-filter mechanism).

**Contrast with the group-based mechanism.** The group exercise's diagnostic recorded a 2–4 minute propagation window for `is_account_group_member()` membership changes. The ACL mechanism on the same adapter has effectively zero propagation latency for the corresponding change (modifying ACL rows). This is the per-mechanism specificity the §5.2 principle calls out: timing is a property of the mechanism, not the framework.

A future Databricks adapter capability profile would declare these two timing characteristics separately, against the two mechanisms. The exercise contributes a second worked example (after group-based) that grounds the §5.2 principle in concrete observations.

**Note:** this disclosure is structural; behavioral verification (Phase 3) should confirm that ACL changes propagate synchronously rather than via a hidden cache layer. If propagation turns out to have its own latency, the disclosure here is updated with the observed window.

---

## 6. Disqualifying-divergence checklist (per inputs §7.3)

| Requirement | Status |
|---|---|
| Row filter that Unity Catalog accepts via `ALTER TABLE … SET ROW FILTER` | ✓ — `acl-row-visibility.databricks.sql` produces a `CREATE FUNCTION` + `ALTER TABLE` pair structurally identical to the group exercise's accepted form. |
| Reference the two ACL tables verbatim, with verbatim column names | ✓ — `bg_rls_demo.tpch.rls_acl_mapping` and `bg_rls_demo.tpch.rls_priority_acl` named directly; `username`, `code_name`, `orderpriority` named directly. |
| Case-insensitive, whitespace-trimmed match on the principal column | ✓ — `lower(trim(m.username)) = lower(trim(current_user()))` in the EXISTS body. |
| `EXISTS` semantics for the join | ✓ — the SQL uses `EXISTS (SELECT 1 FROM … WHERE …)`. |
| Fail-closed for principals without ACL entries | ✓ — single-rule Policy with `defaultStrategy: none`; principals matching no rule see no rows. The SQL's EXISTS returns FALSE for unmapped users. |

---

## 7. Non-functional observation

The ACL join runs at query time on every read against the protected table. This is a real cost that scales with the size of `rls_acl_mapping` and `rls_priority_acl`. For the demo (a few rows each), the cost is negligible. For production, the cost is a non-trivial operational property of the pattern. Tessera correctly does not try to model this in the IR — performance is mechanism-specific — but a production-grade adapter capability profile should disclose the per-query cost characteristic alongside the timing characteristic in §5.

This observation is out of scope per inputs §0.1 (demo only) but recorded as a known property of the pattern.

---

## 8. What this exercise did not exercise

- **Multi-rule Policy semantics.** This is a single-rule Policy; the combining algebra from ADR-015 doesn't activate.
- **`defaultBranch` field.** `defaultStrategy: none` doesn't use it.
- **Group-based principal selection.** Tested in the prior exercise; not exercised here.
- **Obligations, transformations, purpose binding, classifications.** All declared not applicable in inputs §4.

The exercise's exercised surface is intentionally narrow — it complements the group exercise's coverage rather than duplicating it.

---

## 9. Findings summary (for tracking)

| Finding | Category | Recommended action |
|---|---|---|
| Two-table-join not natively expressible (§4.1) | **v1 candidate** | Open issue referencing this section. Design: `PrincipalSetFromJoinedTables` or richer `PrincipalSetFromTable` shape. |
| No case-insensitive match modifier (§4.2) | **v1 candidate** | Open issue. Design: `match` field on `PrincipalSetFromTable` / `ResourceSetFromTable`. |
| `existsInDataset` operand shape under-specified (§4.3) | **v1 candidate** | Open issue. Likely co-designed with §4.1. |
| Silent failure modes in data-driven patterns (§3.1) | **v1 candidate (lower priority)** | Open issue. Design: integrity-check policy-load semantics. Not blocking; valuable for production hardening. |
| Per-mechanism timing disclosure for ACL pattern (§5) | **Documented; not an issue** | The timing characteristic is captured here. Once a Databricks adapter exists, its capability profile records both this and the group-based mechanism's separately. |

The Phase 3 comparison (when the existing implementation is shared) will produce a parallel set of findings categorized along the same axes. Items here are likely to be confirmed, qualified, or supplemented by that comparison.
