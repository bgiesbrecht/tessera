# Phase 1 Inputs — Column-Mask Exercise (orders.o_clerk)

**For:** Claude Code.
**Companion documents:** `docs/worked-example-exercise.md`, `CLAUDE.md`, `DECISIONS.md`, and the prior worked examples (`group-row-visibility-*`, `acl-row-visibility-*`).
**Status:** Combined-input single-pass exercise — the existing implementation was shared up front, so the blind-derivation property of the worked-example framework is intentionally relaxed for this run. Phase 2 and Phase 3 collapse into a single derivation + comparison cycle.
**Effective spec version:** v0, post-ADR-016 (transformation parameterization). The ABAC additions (ADR-018–021) are filed but the spec changes implementing them haven't landed yet; this exercise targets the **pre-ABAC `SET MASK` mechanism**, not the new ABAC `CREATE POLICY ... COLUMN MASK` form.

---

## 0. Framing

**0.1 — Demo or production scope?**

Demo. The implementation lives in the same `bg_rls_demo` test environment as the prior two row-visibility exercises. Edge cases around concurrency, hot paths, audit, and operational resilience are out of scope.

**0.2 — Target platform**

Databricks Unity Catalog. The existing implementation uses the pre-ABAC `ALTER COLUMN ... SET MASK` mechanism (legacy column masks) rather than the newer ABAC `CREATE POLICY ... COLUMN MASK ... MATCH COLUMNS` form. The Tessera derivation targets the same mechanism for direct comparison; the ABAC mechanism is the subject of the deferred Stage 3 exercise from the ABAC scoping document.

**0.3 — Scope of this exercise**

A single-column column-mask pattern. The protected column is `o_clerk` on `bg_rls_demo.tpch.orders`. Visibility is binary: principals in the `orders_full_access` group see the real value; everyone else sees the literal redaction `'CLERK-REDACTED'`.

This is the simplest non-trivial column-masking case: one column, two branches (full-access pass-through; default redact), one masking function. Sufficient to exercise the IR's column-visibility shape and the `TransformationInstance` parameterization (ADR-016).

---

## 1. The protected resource

**1.1 — Protected table**

`bg_rls_demo.tpch.orders`. The same table the group-based row-visibility exercise used. Existing row filter (`tessera__group_row_visibility_policy_b__row_filter`) may still be attached from that exercise; the column-mask exercise is orthogonal — column masks and row filters compose at evaluation time on Unity Catalog without conflict.

**1.2 — Protected column**

`o_clerk` (STRING). TPC-H convention: a clerk identifier such as `Clerk#000000001`.

Row-identifying column: `o_orderkey` (TPC-H convention).

**1.3 — Other columns visible**

The mask affects only `o_clerk`. Other columns (`o_orderkey`, `o_orderstatus`, `o_totalprice`, `o_orderdate`, `o_orderpriority`, `o_shippriority`, `o_comment`) are unaffected.

**1.4 — Existing classifications**

None on the column. The mask is gated by principal group membership, not by data classification — this is an *attribute-on-principal* pattern, not an *attribute-on-data* pattern. (The ABAC scoping document's §1 three-category framing places this in the "properties of the principal" category.)

A future ABAC exercise might re-express the same masking intent driven by a `sensitivity: PIIClerk` (or similar) attribute axis applied to the column; that is the Stage 3 exercise in the ABAC scoping document and is not this exercise.

---

## 2. The principal model

**2.1 — Principal identification at session time**

The masking function uses `is_account_group_member('orders_full_access')`, the same Databricks account-group function the row-visibility exercises used. Membership evaluates against the session user implicitly.

**2.2 — Restrictive group**

`orders_full_access` — members see the unredacted `o_clerk` value. Members are presumed to be data engineers, auditors, or anyone with a business need to see the clerk identifier.

**2.3 — Default principals**

Everyone else (every account user not in `orders_full_access`) sees `'CLERK-REDACTED'`. The masking is unconditional for non-members; no further gating.

**2.4 — Group hierarchy**

`is_account_group_member` handles direct and indirect membership transparently, as in the prior exercises.

**2.5 — Exceptional principals**

None. Service accounts and human users alike are subject to the same gating; if not in `orders_full_access`, the mask applies.

---

## 3. The policy intent

**3.1 — In plain English**

A column-visibility policy on `o_clerk`. Members of `orders_full_access` see the column's true value; everyone else sees the literal string `'CLERK-REDACTED'`.

**3.2 — Effect taxonomy**

In Tessera terms (ADR-014, ADR-016):

- Members of `orders_full_access`: `effect: allow` — the original column value is returned unchanged. No transformation applied.
- Default (anyone not in the above group): `effect: transform` with `transformation: { type: Redact, replacement: 'CLERK-REDACTED' }`.

**3.3 — Default-handling strategy**

The existing SQL is structurally **negated-complement**: there is one explicit branch (full-access pass-through) and an unconditional `ELSE` (redact). The Tessera derivation uses `defaultStrategy: negated-complement` with `defaultBranch` carrying the Redact transformation. The alternative shape — `defaultStrategy: explicit-baseline-group` with `account users` as the baseline rule — is also valid and produces the same observable behavior; this exercise produces only the negated-complement form to match the existing SQL directly.

**3.4 — Purpose binding**

None.

**3.5 — Time-of-day or jurisdiction conditions**

None.

**3.6 — Obligations**

None.

---

## 4. Edge cases

**4.1 — Empty `orders_full_access` membership**

If the group has no members, every principal falls through to the default and sees `'CLERK-REDACTED'`. Expected behavior.

**4.2 — Mid-session membership changes**

Subject to the same 2–4 minute account-group cache propagation observed in the group row-visibility exercise. The Tessera diagnostic records the timing characteristic (consistent with the §5.2 timing-disclosure principle from the technical design); no new mechanism-specific timing here.

**4.3 — Interaction with the existing row filter on the table**

The `o_clerk` column mask and the `o_orderpriority` row filter (deployed during the group exercise) compose at evaluation time: the row filter narrows which rows are visible; the column mask redacts `o_clerk` on those visible rows. Members of `orders_full_access` who are not in `bg_rls_demo_all_priority_ops` see only the rows the row filter admits, with `o_clerk` unredacted on those rows. This is standard Unity Catalog composition and is not a finding.

**4.4 — Joins, views**

Unity Catalog column masks propagate to joins and views over the protected table, as with row filters.

**4.5 — Function unavailability**

If the masking function cannot be invoked (e.g., dropped, permissions error), Unity Catalog fails the query rather than returning unredacted values. Fail-closed at the platform layer.

---

## 5. Non-functional requirements

Not applicable for the demo. The masking function is a single `CASE` evaluated per row; performance impact is negligible for demonstration purposes.

---

## 6. What success looks like

**6.1 — Behavioral equivalence criteria**

Verify two scenarios against `bg_rls_demo.tpch.orders.o_clerk`:

| Scenario | Setup | Expected `o_clerk` value |
|---|---|---|
| 1 | Brice in `orders_full_access` | Real clerk values (e.g., `Clerk#000000001`) |
| 2 | Brice not in `orders_full_access` | `'CLERK-REDACTED'` for every visible row |

The Tessera-derived SQL should produce identical results to the existing implementation in both scenarios.

**6.2 — Acceptable divergences**

Same as the prior exercises:

- Function name (Tessera uses deterministic naming).
- SQL formatting and whitespace.
- Header comments.

**6.3 — Disqualifying divergences**

The Tessera derivation must:

- Produce a function and `ALTER COLUMN ... SET MASK` form that Unity Catalog accepts.
- Apply to the same column (`o_clerk`) on the same table.
- Reference `orders_full_access` verbatim.
- Use the literal string `'CLERK-REDACTED'` as the redacted value.

---

## 7. Anticipated findings

This exercise is expected to surface at least one real v0 schema gap:

**JSON Schema requires `transformation` on every rule in a ColumnVisibilityConstraint policy.** The existing implementation (and the Tessera derivation matching it) has a rule with `effect: allow` (pass-through) on the `orders_full_access` branch — no transformation needed because no transformation is applied. The current schema's conditional rejects this. The schema constraint should be effect-driven (`transformation` required when `effect: transform`), not policy-kind-driven (required for all ColumnVis rules).

The fix is a small clarifying correction to ADR-016's schema implementation. Per ADR-017, the immutability bar is suspended until external dependency, so the correction is admissible. The exercise's diagnostic recommends an ADR-022 capturing the correction and the corresponding schema + technical-design updates.

---

## 8. Handoff to Phase 2

Phase 2 produces, per `docs/worked-example-exercise.md` §2 (compressed for single-pass mode), all under `spec/v0/examples/`:

- `column-mask-orders-clerk-policy.tessera.yaml` — Policy in YAML with negated-complement default-handling.
- `column-mask-orders-clerk-policy.jsonld` — canonical form.
- `column-mask-orders-clerk.databricks.sql` — Tessera-derived `CREATE FUNCTION` + `ALTER COLUMN ... SET MASK` pair.
- `column-mask-orders-clerk.diagnostic.md` — per-element enforcement report; surfaces the schema gap.
- `column-mask-orders-clerk.comparison.md` — single-pass comparison against the existing SQL.

Plus ADR-022 (if the schema correction lands cleanly) and corresponding spec edits.
