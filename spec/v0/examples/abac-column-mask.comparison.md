# Phase 3 Comparison — ABAC Column Mask (stub)

**Companion artifacts:**
- `abac-column-mask-policy-a.tessera.yaml` / `.jsonld` (Redact)
- `abac-column-mask-policy-b.tessera.yaml` / `.jsonld` (Hash)
- `abac-column-mask.databricks.sql`
- `abac-column-mask.diagnostic.md`

**Inputs:** `docs/exercises/abac-column-mask-inputs.md`
**Exercise framing:** `docs/worked-example-exercise.md` — canonical three-phase mode. The blind-derivation property is preserved; this comparison is intentionally a **stub** at Phase 2 commit time. Phase 3 sections populate after deployment and after Brice shares the existing implementation.

**Status:** Phase 2 artifacts committed. Phase 3 deployment + observation **completed 2026-05-19**. Existing-implementation structural comparison still pending Brice's share.

---

## 1. Summary

The Phase 2 artifacts express the two-policy ABAC column-mask design using the post-ABAC vocabulary. The Tessera-derived SQL uses the verified Databricks ABAC DDL form. Both policies attached successfully at catalog scope. **The substantive Phase 3 observation: Databricks ABAC rejects multi-mask evaluation when two column-mask policies resolve to the same column.** This is the γ-path resolution from ADR-019's three candidates — the platform does not silently pick a winner or blend the masks; it surfaces a structured error and asks the operator to resolve the policy definitions. The full error text and the implications for ADR-019 are recorded in §2 below.

The existing-implementation structural comparison (§3) is still pending Brice's share. The blind-derivation property held through Phase 2; the Phase 3 observation here is independent of any existing implementation.

---

## 2. Behavioral observation (Phase 3)

### 2.1 Test scenarios — results

Verified 2026-05-19 against `bg_rls_demo.tpch.orders_abac` on `adb-984752964297111.azuredatabricks.net` (Azure). Brice was **not** in `bg_rls_demo_all_priority_ops` during all runs — i.e., we ran Scenario 2 (the load-bearing one) directly without needing Scenario 1 first.

| Scenario | Setup | Observed |
|---|---|---|
| 2a — Policy A only | Brice not in privileged group; only Policy A (Redact) attached at catalog scope | `o_clerk` returned `'CLERK-REDACTED'`. Single-policy redaction works. ✓ |
| 2b — Both policies attached | Brice not in privileged group; both Policy A and Policy B attached at catalog scope | Both policies attached successfully (`SHOW POLICIES ON CATALOG bg_rls_demo` listed both). **`SELECT o_clerk` failed with `COLUMN_MASKS_FEATURE_NOT_SUPPORTED.MULTIPLE_MASKS`.** Databricks ABAC rejects the multi-mask evaluation. |

The verbatim error from Scenario 2b:

```
[COLUMN_MASKS_FEATURE_NOT_SUPPORTED.MULTIPLE_MASKS]
Column mask policies for `bg_rls_demo`.`tpch`.`orders_abac` are not supported:
Table `bg_rls_demo`.`tpch`.`orders_abac` has access control policies resulting in
multiple column masks
  `ColumnMask(o_clerk, List(bg_rls_demo, tpch, tessera__abac_column_mask_clerk_redact__mask), Vector())`,
  `ColumnMask(o_clerk, List(bg_rls_demo, tpch, tessera__abac_column_mask_clerk_hash__mask), Vector())`
applying to the same column(s) `o_clerk`. Please contact the table owner or policy
definer to resolve the issue by updating policies such that at most one mask appl[ies]
```

Three structurally significant observations from the error:

1. **Both policies attached without error.** The rejection is at *query evaluation time*, not at *policy creation time*. Tessera adapters cannot reliably detect the conflict by inspecting one policy's creation in isolation; the constraint emerges when two policies happen to overlap.
2. **The error names both policies explicitly** and the column they both target. Databricks' error message is machine-readable enough that an adapter could parse it and surface a structured diagnostic.
3. **The error is recoverable.** Dropping Policy B (or Policy A) returns the table to a queryable state. The conflict is detectable and resolvable; it is not a permanent failure.

### 2.2 ADR-019's α/β/γ — answered: γ

The Phase 1 design (and ADR-019) listed three candidate resolutions for cross-policy combination on the same column. The observation answers:

- **Not α** — Databricks does not deterministically pick one of the masks by some platform convention (creation order, alphabetical name, declared priority). It refuses to evaluate.
- **Not β** — Databricks does not chain or blend the masks (e.g., `sha2('CLERK-REDACTED', 256)`). No combination algorithm is applied.
- **γ confirmed, with a refinement** — Databricks' position is *not* "adapter-configurable" in the sense ADR-019 contemplated. Databricks declares the constraint explicitly: at most one column mask per column. Tessera's right response is not to pick a combining algorithm in the IR, but to *declare the platform's constraint* in the Databricks adapter's capability profile and *surface the conflict* in the emission diagnostic when two ColumnVis policies would resolve to the same column on the same platform.

The right framing in Tessera terms: the IR remains expressive enough to declare both policies (an author may legitimately want to express "redact for confidentiality" and "hash for analytics" as two different policies at design time), but the **Databricks adapter's capability profile declares `single-column-mask-per-column`** as a constraint, and the **emission diagnostic** for that adapter flags any pair of ColumnVis policies whose effective column sets overlap. The author resolves the conflict before deployment; the platform never sees an ambiguous configuration.

### 2.3 Test methodology

Performed in a single SDK script that:

1. Pre-checked Brice's group membership via `is_account_group_member('bg_rls_demo_all_priority_ops')` — returned `false`, i.e., Scenario 2 state.
2. Deployed both UDFs and granted `EXECUTE` to `account users`.
3. Attached Policy A (Redact) at catalog scope. Queried `o_clerk` → returned `'CLERK-REDACTED'`. Single-policy result confirmed.
4. Attached Policy B (Hash) at catalog scope. Queried `o_clerk` → `MULTIPLE_MASKS` error.
5. Verified both policies attached via `SHOW POLICIES ON CATALOG bg_rls_demo`.
6. Dropped Policy B. Re-queried `o_clerk` → returned `'CLERK-REDACTED'` again. Recovery confirmed.

A reverse-order test (Policy B first, then Policy A) is not needed — the rejection is symmetric and order-independent because both policies are equally "in conflict" once both are attached.

Scenario 1 (Brice in privileged group) was not separately verified; the EXCEPT clause behavior is established by Databricks ABAC documentation and identical between the two policies. Future verification would confirm pass-through observationally but doesn't add evidence to the cross-policy combination question.

---

## 3. Structural comparison against the existing implementation

Existing implementation shared by Brice on 2026-05-19 (after Phase 2 commit; blind-derivation property held). It provides **two** ABAC patterns plus a design commentary on when to use each:

- **Mechanism A — `orders_clerk_mask`** — UDF returns the literal unconditionally; the policy header's `TO ... EXCEPT` handles the privileged-group exemption. Brice's primary recommendation for binary exemption cases.
- **Mechanism B — `orders_clerk_mask_by_group`** — UDF carries an `is_account_group_member` CASE expression; the policy header's `TO account users` is broad. Brice's alternate for cases that need multi-branch behavior beyond a binary exempt/not-exempt split.

Brice's note: *"TO and EXCEPT define **who** the policy applies to, while the UDF defines **what** masking happens. … Using `TO account users EXCEPT group` is the cleaner ABAC pattern for this kind of all-users-except-one-group rule. If you want multiple in-policy behaviors rather than a simple exempt/not-exempt split, then put identity checks such as `is_account_group_member()` inside the UDF instead."*

The Tessera derivation chose Mechanism A. The match against Brice's primary recommendation is structural; the alternate Mechanism B surfaces a finding the Phase 1 inputs didn't predict.

### 3.1 Line-by-line comparison: Tessera vs. existing Mechanism A

| Dimension | Existing (Mechanism A) | Tessera-derived | Category |
|---|---|---|---|
| Tag definition | `CREATE GOVERNED TAG abac_column VALUES ('clerk')` (account-level) | Out of IR scope (adapter-configuration / workspace setup) | **Out of scope for the IR**; correctly not modeled. |
| Catalog/schema/table setup | Inline `CREATE CATALOG ... CREATE SCHEMA ... CREATE TABLE` | Out of IR scope | **Out of scope**; deployment, not policy. |
| `GRANT SELECT ON TABLE ... TO 'account users'` | **Present** | **Absent** | **Real divergence with operational implications.** See §3.3. |
| Column tag application | `ALTER TABLE … ALTER COLUMN o_clerk SET TAGS ('abac_column' = 'clerk')` | Same | **Match** (both done as workspace setup, not in the Tessera IR). |
| UDF name | `mask_order_clerk_abac` | `tessera__abac_column_mask_clerk_redact__mask` | **Accepted divergence** (Tessera form is deterministic + traceable). |
| UDF parameter | `clerk STRING` | `val STRING` | **Accepted divergence**. Local to function body. |
| UDF body | `RETURN 'CLERK-REDACTED'` (unconditional literal) | Same | **Match.** Both Mechanism-A-flavored: the principal logic lives in the policy header, not the UDF. |
| `RETURNS STRING` declaration | Explicit | Explicit | **Match.** |
| Policy name | `orders_clerk_mask` | `tessera__abac_column_mask_clerk_redact` | **Accepted divergence.** |
| Policy attachment scope | `ON SCHEMA bg_rls_demo.tpch` | `ON CATALOG bg_rls_demo` | **Real divergence.** See §3.4. |
| `COMMENT` | Yes (`'ABAC column mask for TPCH orders clerk'`) | Yes (`'Tessera ABAC column mask — policy:abac-column-mask-clerk-redact'`) | **Match on form**, content differs (Tessera form encodes policy ID). |
| `COLUMN MASK function_name` | Same | Same | **Match.** |
| `TO account users` | Same | Same | **Match.** |
| `EXCEPT bg_rls_demo_all_priority_ops` | Same | Same | **Match.** |
| `FOR TABLES` | Same | Same | **Match.** |
| `MATCH COLUMNS has_tag_value('abac_column', 'clerk') AS alias` | Same (`AS clerk_col`) | Same (`AS pii_clerk_col`) | **Match** on form; alias name differs (Tessera form encodes the semantic axis). |
| `ON COLUMN alias` | Same | Same | **Match.** |
| `GRANT EXECUTE ON FUNCTION` | **Absent** | **Present** | **Real divergence** in the opposite direction from prior exercises. See §3.5. |

The substantive structural match for Mechanism A is **very tight**. The Tessera derivation reached the same shape as Brice's primary recommendation independently, validating the blind-derivation property of the worked-example framework.

### 3.2 Mechanism A vs Mechanism B — a real design distinction

Brice's two implementations are observationally equivalent but structurally distinct on a dimension the Phase 1 inputs did not anticipate:

| Dimension | Mechanism A | Mechanism B |
|---|---|---|
| Where principal logic lives | Policy header (`TO ... EXCEPT`) | UDF body (`CASE WHEN is_account_group_member(...) THEN ... ELSE ... END`) |
| UDF body shape | Unconditional literal/transform | Conditional CASE |
| Policy `TO` clause | Narrow (`EXCEPT group`) | Broad (just `account users`) |
| Extensibility for multi-branch | Limited — multiple EXCEPT clauses get unwieldy | Natural — additional WHEN branches inside the UDF |
| Audit semantics | Clean — the policy DDL declares who is exempt | Opaque — the exemption is buried in UDF logic |

This is structurally analogous to **ADR-013's distinction between explicit-baseline-group and negated-complement**: same observable behavior, different intent about where the principal logic is *declared*. The two ABAC mechanisms encode the same kind of intent distinction at a different layer (column mask emission vs. row visibility default-handling).

**The Tessera v0 IR essentially mandates Mechanism A.** Here's why:

- Tessera's `rules` array under a Policy carries `principal` selectors + effects. A privileged-group rule with `effect: allow` plus a `defaultBranch` with `effect: transform` is exactly Mechanism A's shape: principal logic is in the rule structure, transformation logic is unconditional.
- To express Mechanism B in Tessera v0, the IR would need *either* (a) a single rule with no principal restriction and a transformation that internally branches by group membership, *or* (b) a "Custom" transformation type that takes arbitrary SQL.
- (a) is not expressible in v0 because the transformation vocabulary is closed (`Redact`, `Mask`, `Hash`, `Tokenize`, `Bucketize`) — none of them carry conditional logic.
- (b) was explicitly deferred in ADR-016 (Tokenize and Bucketize's parameter shapes are deferred; a `Custom` type is not in v0 at all).

**Finding:** Tessera v0's design is opinionated toward Mechanism A. This is probably *right* (Mechanism A's audit semantics are cleaner; the principal-where-clause separation is structurally cleaner), but it's an opinion the project should record. A follow-on ADR (or a clarifying paragraph in the technical design) should document that v0's IR shape expects Mechanism-A-style emission for ABAC column masks.

If a future exercise surfaces a case where Mechanism B is necessary (e.g., a four-branch policy that doesn't reduce cleanly to "one exempt group + everyone else"), the design question reopens. Until then, Tessera-Mechanism-A is the canonical pattern.

### 3.3 `GRANT SELECT` on the protected table (corrected via Glean)

Brice's existing impl includes:

```sql
GRANT SELECT ON TABLE bg_rls_demo.tpch.orders_abac TO `account users`;
```

with the comment *"ABAC restricts or masks data; it does not grant base access."*

An initial draft of this section read this as a substantive Tessera IR gap parallel to issue #10 (`policy-execute-grants`). On checking against Databricks' actual access-control semantics, that framing is wrong. The corrected reading:

- **`TO account users` in the ABAC policy is about *policy scope*, not data access.** It names who the column mask *applies to* among principals who can already read the table; it does not grant anyone access.
- **`GRANT SELECT ON TABLE ... TO account users` is base table access, separate from any policy.** It is required because the table was just created in the script and ownership doesn't propagate to other groups; absent the grant, members of `account users` (other than the owner) would see "permission denied" *regardless of whether the ABAC policy was attached*.
- For **existing tables** where readers already have access (via schema/catalog inheritance, prior grants, or table ownership), attaching an ABAC mask does **not** require any additional grant. The mask transforms what they see; it does not change *whether* they can access the table at all.

So this `GRANT SELECT` is **table-creation deployment scaffolding**, not a policy concern. Tessera's IR correctly does not model it — it's no more a policy concern than the `CREATE TABLE` or `CREATE GOVERNED TAG` statements that also appear in the script.

The `GRANT EXECUTE ON FUNCTION` finding (issue #10) is similar in shape — both grants are about base permissions, not the policy itself — but EXECUTE on a UDF has tighter default semantics on Databricks than SELECT on a table, so the `GRANT EXECUTE` omission is more likely to bite in practice. Issue #10's framing remains valid; this section does **not** open a parallel `policy-table-access-grants` candidate.

**Acknowledgment of the prior framing.** The initial draft of this section claimed the missing `GRANT SELECT` would "silently break the policy" — that overstated the operational impact. The grant is needed for the *deployment* (specifically, ensuring non-owner principals can read the table at all), not for the *policy* (which does its masking work the same way regardless). The distinction was clarified via internal Databricks documentation; the corrected version stands.

### 3.4 Scope choice: schema vs. catalog

Brice attached at `ON SCHEMA bg_rls_demo.tpch`. The Tessera derivation attached at `ON CATALOG bg_rls_demo`. Both work because the only tagged column in the catalog right now is `o_clerk` on `orders_abac` (which lives in the `tpch` schema); whichever scope is narrower than or equal to the resource's actual location is correct.

**The choice reflects intent:**

- Schema scope (Brice's choice): "This policy is for the TPCH demo data; not intended to leak into other schemas if they're added later."
- Catalog scope (Tessera's choice): "This policy applies to anywhere in `bg_rls_demo` where columns are tagged `abac_column=clerk`."

Both are legitimate readings of the inputs §3 framing. The Phase 1 inputs §0.3 and §4.1 specified catalog scope ("`scope: catalog:bg_rls_demo`") — the Tessera derivation followed the spec. Brice's existing impl chose schema scope, perhaps reflecting a tighter intent than the inputs captured.

**Finding (mild):** ADR-019's `byScope` framing supports all of `catalog:`, `schema:`, `table:`, `column:`. The Phase 1 inputs picked one without justifying the choice. A real Tessera policy author would presumably pick the narrowest scope that captures the intent; the inputs document should probably guide that choice in the inputs template for future exercises. Not a v0 spec finding; just a documentation-quality note.

### 3.5 `GRANT EXECUTE` on the UDF — direction inverted vs prior exercises

Brice's existing impl does **not** issue `GRANT EXECUTE ON FUNCTION`. The Tessera derivation does (defensively, mirroring the prior exercises' patterns).

This is the **third occurrence** of grant-emission asymmetry between Tessera derivation and existing implementations across the worked-example series. The previous pattern from issue #10 `policy-execute-grants`: existing notebook implementations emitted GRANT EXECUTE; Tessera derivations omitted it. Here it's inverted — existing impl omits; Tessera emits.

This inverse pattern *reinforces* the same finding: **the IR is not the source of truth for grant emission; whichever side decides to emit is making an implementation choice the IR doesn't authorize**. The right v1 fix per issue #10 is to make grant emission an IR-level concern (declared by the policy author) rather than an adapter-default.

### 3.6 What Tessera adds (confirmed by the comparison)

The pattern from prior exercises holds:

| Element | Tessera form | Existing implementation |
|---|---|---|
| Canonical IR form | `.tessera.yaml` + `.jsonld` | None |
| Declared `defaultStrategy: negated-complement` | Explicit | Implicit (the `EXCEPT` clause encodes the structure; nothing names it) |
| `policyKind: ColumnVisibilityConstraint` | Explicit | Implicit (`COLUMN MASK` carries it) |
| Capability-requirement declarations | `scoped-policy-attachment`, `attribute-axis-matching`, `tag-taxonomy-mapping` | None |
| Tag-taxonomy mapping (per ADR-021) | Explicit per-environment adapter configuration | Implicit (tag key/value hardcoded in the SQL) |
| Provenance | Header comments link the SQL back to the policy ID | None |
| Diagnostic report (per-element enforcement) | Present | None |
| Comparison report | This document | None |

The diagnostic-and-comparison surface continues to be where Tessera's value-add concentrates. The SQL emission is structurally equivalent; the IR + supporting documents are what's new.

### 3.7 What the existing implementation has that Tessera does not capture

- **The Mechanism-A-vs-B design distinction itself** (§3.2). The existing impl documents both forms and the choice between them in a comment. Tessera's IR makes the choice implicit by structurally favoring Mechanism A; there is no comment or declaration in the IR that names the design choice. A documentation addition in the technical design (§4 or §5) would close this gap.
- **Deployment scaffolding** (`CREATE CATALOG`, `CREATE TABLE AS SELECT`, `CREATE GOVERNED TAG`, `ALTER TABLE … SET TAGS`, `GRANT SELECT ON TABLE`). Correctly out of scope for the policy IR; recorded for completeness. The `GRANT SELECT` belongs to this category per §3.3 — it is table-creation-time access scaffolding, not a policy concern.
- **The alternate Mechanism B example** (`orders_clerk_mask_by_group`). Tessera v0 cannot express this naturally; see §3.2. This is a v1 candidate worth tracking separately if Mechanism B becomes a real need.

---

## 4. Lessons for v0 (per exercise framing §3.3)

Three categories will populate after Phase 3 observation.

### 4.1 v0 spec changes for Stage 4 — proceed as planned

Phase 3 did not surface design problems with the ABAC additions themselves. The four ADRs (018–021) hold up: `byScope` attached cleanly; `matching.attributes` with the implicit-AND shortcut emitted correctly; the tag-taxonomy mapping (sensitivity:PIIClerk ↔ abac_column=clerk) worked as designed; the structured `TransformationInstance` carried the Redact and Hash parameters correctly. Stage 4 can proceed with the scoping doc's design.

### 4.2 Cross-policy combination — resolved as γ, with refinement

ADR-019 deliberately deferred the cross-policy combining choice. Phase 3 produced the discriminating observation: **Databricks ABAC rejects multi-mask evaluation** with a structured `COLUMN_MASKS_FEATURE_NOT_SUPPORTED.MULTIPLE_MASKS` error.

The Tessera response (proposed for a follow-on ADR — call it ADR-023 for now):

1. **The IR remains expressive.** Authors may legitimately declare multiple ColumnVis policies whose matchers overlap. The IR does not preemptively reject this.
2. **The Databricks adapter capability profile declares `single-column-mask-per-column`** as a platform constraint.
3. **The Databricks adapter's emission diagnostic** detects when two ColumnVis policies' effective column-sets overlap and surfaces the conflict at emit time. The diagnostic names both policies and the affected column, mirroring Databricks' own error.
4. **The author resolves the conflict before deployment** — by merging the policies, narrowing one matcher, scoping one to a subset, etc. Tessera does not pick a winner in the IR or pick a combining algorithm.

This is γ with the refinement that Tessera *names* the platform's constraint rather than declaring an algorithm. Other platforms (Snowflake, future) may have different constraints; their adapters declare them in their own capability profiles. The IR's neutrality is preserved.

A follow-on ADR records the choice and the corresponding capability-profile vocabulary additions.

### 4.3 New v1 candidates

Two v1 candidates surfaced across the deployment observation and the structural comparison:

- **`column-mask-conflict-detection`** — adapter capability profile vocabulary for declaring constraints like `single-column-mask-per-column`, and the emission-diagnostic shape that surfaces detected conflicts. Surfaced by §2 cross-policy observation. Lower priority than the structural ABAC additions; can wait for the actual Databricks adapter to be built before being formalized.

- **`column-mask-mechanism-a-canonical`** — documentation/technical-design note recording that v0's IR shape favors Mechanism A (principal logic in policy header, transformation unconditional) for ABAC column masks, and that Mechanism B (CASE inside the UDF) is currently not naturally expressible in v0. Surfaced by §3.2. A future ADR might either (a) document v0's opinion as final or (b) introduce a "Custom" transformation type to enable Mechanism B if real cases demand it.

An earlier draft of this section listed `policy-table-access-grants` as a third v1 candidate. That candidate is withdrawn after the §3.3 correction: `GRANT SELECT` is deployment scaffolding, not a policy concern. Issue #10 (`policy-execute-grants`) remains the open question on grants; it covers `GRANT EXECUTE ON FUNCTION` and is not extended by this exercise.

The structural ABAC findings from the scoping doc (`#7 principal-set-from-joined-tables`, `#8 principal-set-match-modifiers`, etc.) are unrelated to ABAC column masking and were not exercised here.

---

## 5. Recommended actions

1. ✓ **Phase 3 deployment + Scenario 2 observation** — done 2026-05-19. Result: γ-path with refinement (§2.2 and §4.2).
2. ✓ **Brice shares the existing implementation** — done 2026-05-19, after Phase 2 commit. Blind-derivation property preserved through Phase 2.
3. ✓ **Populate §3 of this document** with the structural comparison — done. Tessera derivation structurally matches Brice's Mechanism A. Brice's Mechanism B alternative surfaced a new finding (§3.2).
4. **Draft a follow-on ADR (ADR-023)** recording the cross-policy combination resolution for Databricks ABAC column masks: capability-profile vocabulary for the `single-column-mask-per-column` constraint, emission-diagnostic shape for the conflict surface, and the relationship to ADR-019's α/β/γ framing.
5. **File the three new v1-candidate issues** per §4.3 (`column-mask-conflict-detection`, `policy-table-access-grants`, `column-mask-mechanism-a-canonical`).
6. **Workspace state.** Policy A (Redact) remains attached at catalog scope. Policy B was dropped. Brice's environment is in a usable state for further work or for tearing down. The two UDFs (`tessera__abac_column_mask_clerk_redact__mask`, `tessera__abac_column_mask_clerk_hash__mask`) are still defined; the Hash UDF is unused after Policy B drop.

---

## 6. What this comparison did not do

- **Did not exercise hierarchical-axis subsumption** (the original Policy B design that was simplified before Phase 2; see inputs §8.2). Remains a follow-on exercise.
- **Did not verify Scenario 1 (Brice in privileged group) empirically.** The EXCEPT clause behavior is well-documented Databricks ABAC behavior; verification would have added little.
- **Did not measure tag-binding cache propagation lag.** Both policies attached and the multi-mask error surfaced quickly; no toggle-and-re-query sequence was run.

These are deliberate scope choices, not gaps. The substantive observations (cross-policy combination, Mechanism A vs B, GRANT SELECT) are recorded; the exercise's load-bearing question (ADR-019's α/β/γ) is answered.

---

## 7. Closing observation

This exercise produced the most substantive design output of the worked-example series so far. Three findings of real consequence:

1. **ADR-019's α/β/γ has an empirical answer** (γ-with-refinement). Databricks ABAC rejects multi-mask evaluation; Tessera's response is to require adapters to declare the constraint and surface conflicts at emit time, not to pick a combining algorithm in the IR. A follow-on ADR captures this.

2. **Tessera v0's IR is opinionated toward Mechanism A** for ABAC column masks. The principal logic lives in the policy header (`rules[].principal` + `defaultStrategy`); the transformation is unconditional. This is structurally analogous to the explicit-baseline-group vs negated-complement distinction at the row-visibility layer. The opinion is probably right; it should be documented.

3. **One real operational-grant concern remains.** Function-execute (`GRANT EXECUTE ON FUNCTION`, issue #10) is a genuine IR gap. An initial draft of this exercise also flagged `GRANT SELECT ON TABLE` as a parallel concern, but the §3.3 correction shows it's deployment scaffolding for new tables, not a policy concern. The series surfaces *one* operational-grant question (function execute), not two.

The blind-derivation property held through Phase 2; the structural match with Brice's primary Mechanism A is tight; the Mechanism B alternative surfaced a design dimension the Phase 1 inputs did not anticipate. The framework's "exercises drive design" principle continues to pay for itself.
