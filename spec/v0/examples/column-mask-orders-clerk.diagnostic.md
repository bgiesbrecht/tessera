# Diagnostic Report — Column Mask on orders.o_clerk

**Companion artifacts:**
- `column-mask-orders-clerk-policy.tessera.yaml` / `.jsonld`
- `column-mask-orders-clerk.databricks.sql`
- `column-mask-orders-clerk.comparison.md`

**Inputs:** `docs/exercises/column-mask-orders-clerk-inputs.md`
**Exercise framing:** `docs/worked-example-exercise.md` (single-pass / combined-input mode)
**Spec version:** v0, post-ADR-016 (transformation parameterization). ADR-022 is recommended in §4 below to correct a schema constraint surfaced by this exercise.
**Target platform:** Databricks Unity Catalog (pre-ABAC `SET MASK` mechanism).

---

## 1. Summary

The Tessera-derived Policy expresses the existing column-mask behavior in v0's vocabulary: a `ColumnVisibilityConstraint` Policy with a single rule (full-access pass-through) and a `defaultBranch` carrying a Redact transformation. The SQL emission uses the pre-ABAC `ALTER COLUMN ... SET MASK` form and structurally mirrors the existing implementation modulo cosmetics (function name, grant emission).

The exercise surfaced **one substantive v0 schema gap**: the current JSON Schema requires every rule in a `ColumnVisibilityConstraint` policy to carry a `transformation` field. This rejects the pass-through case (`effect: allow` with no transformation needed), which is the natural shape for "members of this group see the unredacted value." The schema constraint should be **effect-driven** (transformation required iff `effect: transform`), not policy-kind-driven (transformation required for all ColumnVis rules). ADR-022 (recommended below) records the correction.

No other findings of substance. The behavioral logic is straightforward and maps directly between the Tessera shape and the SQL emission.

---

## 2. Per-element enforcement

| Policy element | Category | Notes |
|---|---|---|
| Resource binding (`column:acme.tpch.orders.o_clerk`) | **Fully enforced** | `ALTER TABLE ... ALTER COLUMN ... SET MASK` attaches the masking function to the specific column. |
| `orders_full_access` pass-through rule | **Fully enforced** | The `CASE WHEN is_account_group_member('orders_full_access') THEN o_clerk` branch returns the unredacted value for members. |
| Default branch — Redact with literal | **Fully enforced** | The `ELSE 'CLERK-REDACTED'` branch returns the literal redaction value. Matches the Tessera `defaultBranch.transformation: { type: Redact, replacement: 'CLERK-REDACTED' }`. |
| `defaultStrategy: negated-complement` | **Fully enforced** | The existing SQL is structurally negated-complement (unconditional `ELSE`). The Tessera declaration matches the implementation's intent. |
| `effect: allow` (pass-through) | **Fully enforced** (post-ADR-022) | The pass-through branch is implemented; what the schema rejects is the *expression* of it, not its enforcement. ADR-022 corrects the schema. |
| `effect: transform` + `Redact` transformation | **Fully enforced** | The literal `'CLERK-REDACTED'` replacement value is passed through unchanged. ADR-016's `Redact` parameter shape carries the value correctly. |
| `action: Read` | **Implicitly enforced** | Unity Catalog column masks apply to read paths. Write paths are out of scope for column visibility. |
| Provenance metadata | **Partially enforced** | The Tessera policy carries `provenance.notes`; Unity Catalog has no native facility to embed this in the function definition. The SQL header comments trace back to the policy ID, which is the most the platform supports without separate audit infrastructure. |

---

## 3. Edge-case coverage (per inputs §4)

| # | Edge case | Coverage | Notes |
|---|---|---|---|
| 4.1 | Empty `orders_full_access` membership | **Fully enforced** | Every principal falls into the ELSE branch; everyone sees `'CLERK-REDACTED'`. |
| 4.2 | Mid-session membership changes | **Fully enforced; ~2–4 minute cache lag** | Subject to the same account-group cache observed in the group exercise. Same timing-disclosure §5.2 principle applies. |
| 4.3 | Composition with existing row filter | **Fully enforced** | Unity Catalog composes column masks and row filters at evaluation time. Standard behavior; not a Tessera concern. |
| 4.4 | Joins, views | **Fully enforced** | Column masks propagate to downstream views and join projections. |
| 4.5 | Function unavailability | **Fully enforced (fail-closed at platform layer)** | Unity Catalog fails queries when the masking function can't be invoked; no silent unredacted return. |

---

## 4. v0 spec gap surfaced

### 4.1 ColumnVisibility rules with non-transform effects rejected by schema

The current JSON Schema (`spec/v0/schema.json`) contains this conditional on the Policy `allOf`:

```json
{
  "description": "ColumnVisibility policies: each rule must declare a transformation.",
  "if": {
    "properties": { "policyKind": { "const": "ColumnVisibilityConstraint" } },
    "required": ["policyKind"]
  },
  "then": {
    "properties": { "rules": { "items": { "required": ["transformation"] } } }
  },
  "else": {
    "properties": { "rules": { "items": { "not": { "required": ["transformation"] } } } }
  }
}
```

This says: for `ColumnVisibilityConstraint` policies, every rule must have `transformation`; for other policies, no rule may have it.

The Tessera derivation for this exercise has a rule like:

```yaml
- principal:
    selector: byIdentity
    resource: group:orders_full_access
  effect: allow
  # no transformation — members see the original value
```

This violates the conditional because the rule has `effect: allow` (no transformation needed; pass-through is the semantics) yet the schema demands a `transformation` field. The validator rejects the document.

The right constraint is effect-driven, not policy-kind-driven:

- `effect: transform` requires `transformation` on the rule.
- `effect: allow` (or any other non-transform effect) forbids `transformation` on the rule.

This applies symmetrically to `defaultBranch`:

- A `defaultBranch` with `effect: transform` requires `transformation`.
- A `defaultBranch` with `effect: allow` (rare but structurally legitimate — "if no rule matches, pass through") forbids it.

### 4.2 Why this wasn't surfaced by ADR-016's own validation

ADR-016 was validated against positive cases (`Redact` with `replacement`, `Mask` with parameters, `Hash` with defaults) and negative cases (missing required parameters, forbidden parameters, unknown algorithms). It did **not** include a `ColumnVisibilityConstraint` policy with a non-transform rule, because no worked example at the time had that shape.

The column-mask exercise is the first to exercise a multi-rule (or rule + defaultBranch) ColumnVisibility policy with mixed effects. The gap surfaces because this is the first time the conditional has to discriminate at the rule level rather than the policy level.

### 4.3 Recommended correction: ADR-022

A new ADR records the corrected constraint. The schema and the technical-design §4.2.2 update accordingly. The vocabulary in `ontology.ttl` does not need to change — the constraint was never an ontology axiom; it was an over-tight implementation choice in the schema. Per ADR-017, this admission of a corrected constraint is within the suspended-immutability window.

The diagnostic recommends:

- **ADR-022**: schema validation of `transformation` on rules and on `defaultBranch` is effect-driven. `transformation` required iff `effect: transform`; forbidden otherwise.
- **Schema update**: replace the policy-kind conditional with a per-rule conditional on `effect`. Apply the same conditional to `defaultBranch`.
- **Technical design §4.2.2 update**: change the bullet from "Required for `ColumnVisibilityConstraint` rules; forbidden otherwise" to "Required when `effect: transform`; forbidden otherwise."

---

## 5. Per-mechanism timing disclosure

The column-mask mechanism on Databricks (pre-ABAC `SET MASK` form, gated by `is_account_group_member`) inherits the same timing characteristic as the group-based row-visibility mechanism documented in the prior exercise: **2–4 minute propagation window for account-group membership changes via the account-group cache**.

No new mechanism-specific timing surfaces here. The column-mask SQL evaluates the same `is_account_group_member` function the row filter evaluated, on the same cache; the propagation behavior is the same.

The Databricks adapter capability profile (when built) would declare a single timing characteristic shared by both mechanisms — both depend on the account-group cache, so they share the latency. The disclosure structure from technical-design §5.2 supports this: timing is per-mechanism, but mechanisms that share a propagation path share a timing characteristic.

---

## 6. Disqualifying-divergence checklist (per inputs §6.3)

| Requirement | Status |
|---|---|
| `CREATE FUNCTION` + `ALTER COLUMN ... SET MASK` accepted by Unity Catalog | ✓ — emission matches the verified mechanism. |
| Applied to `o_clerk` on `acme.tpch.orders` | ✓. |
| References `orders_full_access` verbatim | ✓. |
| Uses literal `'CLERK-REDACTED'` | ✓ in both the Tessera `replacement` parameter and the SQL `ELSE` clause. |

---

## 7. Findings summary

| Finding | Category | Recommended action |
|---|---|---|
| ColumnVis rules with non-transform effects rejected by schema (§4) | **v0 correction (schema + technical-design)** | Write ADR-022; update schema.json's transformation conditional to be effect-driven; update technical-design §4.2.2. |
| Behavioral equivalence with existing SQL | **Pending Phase 3 verification** | Deploy and run; see the comparison document and the verification script. |
| Cosmetic divergences (function name, GRANT EXECUTE, header comments) | **Accepted divergences** | Documented in the comparison; the GRANT EXECUTE is consistent with the policy-execute-grants v1 candidate (issue #10) already filed from the ACL exercise. |

The exercise's value is in surfacing finding §4. The schema correction is small but real — without it, the natural shape for two-branch column masking (one rule + defaultBranch) cannot validate.

---

## Postscript — adapter coverage 2026-05-19

The Unity Catalog adapter now emits this policy. The hand-derived SQL in `column-mask-orders-clerk.databricks.sql` was the empirical target during this exercise; on 2026-05-19 the same IR was lowered through `adapters/unity_catalog/emission.py` and produced byte-equivalent DDL (modulo the explanatory `-- Attach the mask` comment, which is documentation-only). Live-executed against `acme.tpch.orders.o_clerk`: the caller (not a member of `orders_full_access`) saw `'CLERK-REDACTED'` for every distinct value. Capability profile for `Capability.COLUMN_VISIBILITY` updated to record the live verification.

Coverage scope of this emission path: `byIdentity` column targets; rules with `effect: allow` or `effect: transform`; `defaultBranch` with `effect: transform`; `Redact` transformation. `Mask` and `Hash` transformations have parameter-shape semantics settled in v0 but their SQL templates are queued. ABAC `byScope` column masking (the `abac-column-mask-policy-*` IR shapes) remains a separate emission path, not yet implemented.

The hand-derived SQL file stays in this directory as historical record of the empirical target the exercise validated against.

### Cross-platform coverage 2026-05-19 (same day, follow-on)

The Snowflake adapter now also emits this policy. The same IR was lowered through `adapters/snowflake/emission.py` to a Snowflake masking-policy DDL block:

```sql
CREATE OR REPLACE MASKING POLICY ACME.TESSERA.column_mask_orders_clerk_mask
AS (O_CLERK VARCHAR) RETURNS VARCHAR ->
  CASE
    WHEN IS_ROLE_IN_SESSION('ACME_HIGH_PRIORITY_OPS') THEN O_CLERK
    ELSE 'CLERK-REDACTED'
  END;

ALTER TABLE ACME.TESSERA.SNOW_ORDERS
  MODIFY COLUMN O_CLERK
  SET MASKING POLICY ACME.TESSERA.column_mask_orders_clerk_mask;
```

Live-executed against `ACME.TESSERA.SNOW_ORDERS.O_CLERK`. With `USE SECONDARY ROLES NONE` and the role bound to `group:orders_full_access` set to `ACME_HIGH_PRIORITY_OPS`:

| Active role | O_CLERK values returned |
|---|---|
| `ACME_HIGH_PRIORITY_OPS` | real `Clerk#000000…` values |
| `ACME_ALL_PRIORITY_OPS` | `CLERK-REDACTED` |
| `PUBLIC` | `CLERK-REDACTED` |
| `ACCOUNTADMIN` | `CLERK-REDACTED` |

Behavior matches the policy intent. The Tessera column-mask exercise is now empirically validated on both Databricks (column-mask-orders-clerk.databricks.sql, applied via UC adapter on the same day) and Snowflake (this run). The cross-platform parity test `adapters/tests/test_parity.py::test_column_visibility_parity_emits_clean_on_both_adapters` regression-tests both emission paths.
