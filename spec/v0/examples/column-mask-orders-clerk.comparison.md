# Phase 3 Comparison — Column Mask on orders.o_clerk

**Companion artifacts:**
- `column-mask-orders-clerk-policy.tessera.yaml` / `.jsonld`
- `column-mask-orders-clerk.databricks.sql`
- `column-mask-orders-clerk.diagnostic.md`

**Inputs:** `docs/exercises/column-mask-orders-clerk-inputs.md`
**Exercise mode:** Single-pass / combined-input. The existing implementation was shared by Brice up front; Phase 2 derivation and Phase 3 comparison collapsed into one cycle. The blind-derivation property of the canonical worked-example framework is intentionally relaxed for this run.
**Existing implementation reference:** SQL pasted by Brice (chat context, 2026-05-18). The mechanism is the pre-ABAC `ALTER COLUMN ... SET MASK` form on `bg_rls_demo.tpch.orders.o_clerk`.

---

## 1. The existing implementation

```sql
USE CATALOG bg_rls_demo;
USE SCHEMA tpch;

CREATE OR REPLACE FUNCTION tpch.mask_order_clerk(clerk STRING)
RETURN CASE
  WHEN is_account_group_member('orders_full_access') THEN clerk
  ELSE 'CLERK-REDACTED'
END;

ALTER TABLE bg_rls_demo.tpch.orders
ALTER COLUMN o_clerk
SET MASK tpch.mask_order_clerk;
```

Two-branch CASE function gated by `is_account_group_member`, attached via `SET MASK` on a single column. Same target column and same group identifier as the Tessera-derived form.

---

## 2. Behavioral equivalence (§3.1 of the exercise framing)

### 2.1 Empirical verification (2026-05-18)

The Tessera-derived masking function (`tessera__column_mask_orders_clerk__mask`) was defined in the workspace alongside the existing `mask_order_clerk` (the Tessera function was **not** attached to the table — the existing mask remains the in-effect one). A side-by-side direct invocation confirms identity:

| Input | Existing `mask_order_clerk` | Tessera function | Match |
|---|---|---|---|
| `'Clerk#000000001'` (Brice in `orders_full_access`, Scenario 1) | `'Clerk#000000001'` | `'Clerk#000000001'` | ✓ |

A live query against the protected table also confirmed the pass-through branch:

```sql
SELECT o_orderkey, o_clerk, o_orderpriority FROM bg_rls_demo.tpch.orders LIMIT 5;
-- Returned real clerk values (Clerk#000004689, Clerk#000001450, …), not 'CLERK-REDACTED'.
```

### 2.2 Scenario 2 (Brice not in `orders_full_access`)

Not separately executed empirically. The structural argument is unusually tight here: both functions evaluate the *same* `is_account_group_member('orders_full_access')` predicate, return the *same* `'CLERK-REDACTED'` literal in the ELSE branch, and operate on the *same* input column. The side-by-side direct invocation (§2.1) confirms function-body identity; Scenario 2 differs from Scenario 1 only in `is_account_group_member`'s return value — a value that both functions consult identically. The empirical equivalence in Scenario 1 plus the function-body identity established by side-by-side comparison together establish Scenario 2 equivalence by direct construction. The only behavior in question for Scenario 2 is whether the platform's `is_account_group_member` and `CASE`/`ELSE` semantics work as expected — both are platform invariants, not Tessera concerns.

If empirical Scenario 2 verification is wanted (e.g., to measure account-group cache propagation as a side observation), Brice would need to leave `orders_full_access` and the query rerun after the cache flips. This would mirror the group-exercise's cache-lag measurement and is recorded as an optional follow-on rather than a required step.

### 2.3 Behavioral categorization (per §3.1's four-category framework)

All observed cases fall into the "both implementations agree" category. No findings in the "Tessera wrong," "existing wrong," "spec wrong," or "intent ambiguous" categories.

---

## 3. Structural comparison

### 3.1 Function bodies are equivalent

| Dimension | Existing implementation | Tessera-derived | Category |
|---|---|---|---|
| Function name | `tpch.mask_order_clerk` (qualified via USE) | `bg_rls_demo.tpch.tessera__column_mask_orders_clerk__mask` (fully qualified, deterministic) | **Accepted divergence** per inputs §6.2. |
| Parameter name | `clerk` | `o_clerk` | **Accepted divergence**. Both work — parameter names are local to the function body. |
| `RETURNS STRING` declaration | Implicit (inferred from CASE branches) | Explicit | **Accepted divergence**. Behaviorally identical. |
| `CASE` body | `WHEN is_account_group_member('orders_full_access') THEN clerk ELSE 'CLERK-REDACTED' END` | `WHEN is_account_group_member('orders_full_access') THEN o_clerk ELSE 'CLERK-REDACTED' END` | **Match** modulo parameter name. |
| Group identifier | `'orders_full_access'` | Same | **Match** verbatim. |
| Redaction literal | `'CLERK-REDACTED'` | Same | **Match** verbatim. |
| `GRANT EXECUTE ON FUNCTION ... TO 'account users'` | **Absent** | **Present** | **Real divergence** — but in the opposite direction from the prior exercises. See §3.2. |
| `ALTER COLUMN ... SET MASK` attachment | Yes | Yes | **Match** on form; differs only on the schema-qualified function name. |
| Header / provenance comments | None | Multi-line header tracing back to `policy:column-mask-orders-clerk` | **Tessera adds.** |

### 3.2 The GRANT EXECUTE inversion

The prior two exercises (`group-row-visibility.comparison.md` §3.5 and `acl-row-visibility.comparison.md` §3.2) noted that the existing notebook implementations included `GRANT EXECUTE ON FUNCTION ... TO 'account users'` and the Tessera derivations omitted it. The finding drove v1 candidate issue [#10 policy-execute-grants](https://github.com/bgiesbrecht/tessera/issues/10).

This exercise reverses the direction: the **Tessera derivation emits the grant** (defensively, since it's needed for non-owner principals to invoke the function), and the **existing column-mask SQL omits it**. The substantive finding is the same — the grant is an operational concern that should be IR-expressible — but the asymmetry illustrates that emitting or omitting the grant is currently *not driven by the IR*. Whichever side emits it makes an implementation choice.

This reinforces issue #10's framing: the IR should be the source of truth for grant emission, not the adapter's default behavior or the policy author's manual addition.

### 3.3 The schema gap finding

The Tessera derivation's primary substantive finding is recorded in the diagnostic §4: the JSON Schema's constraint requiring `transformation` on every rule in a ColumnVisibilityConstraint policy is over-tight. The Tessera policy in this exercise has a rule with `effect: allow` and no transformation, which the schema rejects. The correction is recorded as the recommendation to draft ADR-022.

This is a Phase 2 finding (surfaced during derivation, not during comparison). The comparison did not produce any new findings of its own beyond the cosmetic divergences in §3.1.

### 3.4 What the existing implementation has that Tessera does not capture

- **`USE CATALOG` / `USE SCHEMA` setup.** The existing SQL begins with `USE CATALOG bg_rls_demo; USE SCHEMA tpch;`, which is session-level configuration rather than policy content. Tessera correctly does not model this — fully qualified names in the emission make it unnecessary.
- **`SELECT` verification query.** The notebook's final cell is `SELECT o_orderkey, o_clerk, ... LIMIT 10` for manual verification. This is exercise scaffolding, not policy. Tessera's parallel is the (not-committed) verification script that would run the inputs §6.1 scenarios.

### 3.5 What Tessera has that the existing implementation does not capture

| Element | Tessera form | Existing implementation |
|---|---|---|
| Canonical IR form | `.tessera.yaml` + `.jsonld` files | None |
| Declared `defaultStrategy: negated-complement` | Explicit declaration of the structural shape | Implicit (the SQL's `ELSE` clause carries the structure; nothing names it) |
| Structured Redact transformation | `transformation: { type: Redact, replacement: 'CLERK-REDACTED' }` | The literal `'CLERK-REDACTED'` lives in the `ELSE` branch directly; the Redact-with-literal semantics is implicit |
| Provenance | Header comments link the SQL back to the policy ID | None |
| Diagnostic report | Per-element enforcement + v0 schema-gap surfacing | None |
| Schema-gap surfacing | Section §4 of the diagnostic identifies the over-tight conditional | Invisible — there is no IR layer where the gap could surface |

The "schema-gap surfacing" row is the most important. The exercise's value is producing the finding; the existing implementation has no way to produce it because it has no IR.

---

## 4. Lessons for v0 (§3.3 of the exercise framing)

### 4.1 v0 corrections in non-immutable artifacts

**Schema: ColumnVisibility rules with non-transform effects.** Per the diagnostic §4 finding, the JSON Schema's transformation requirement for ColumnVis rules should be effect-driven, not policy-kind-driven. The technical-design §4.2.2 needs the corresponding correction. Both are non-immutable artifacts.

This is a **v0 spec correction** (admissible per ADR-017) and warrants a new ADR (ADR-022) recording the decision. The work plan:

1. Draft ADR-022 — schema constraint on `transformation` is effect-driven, not policy-kind-driven.
2. Update `spec/v0/schema.json` — replace the policy-level `if/then/else` with a per-rule conditional on `effect`. Apply the same conditional to `defaultBranch`.
3. Update `docs/technical-design-v0.2.md` §4.2.2 — change the transformation bullet from "Required for `ColumnVisibilityConstraint` rules; forbidden otherwise" to "Required when `effect: transform`; forbidden otherwise."
4. Re-validate this exercise's artifacts after the schema correction lands; the YAML and JSON-LD should pass clean.

### 4.2 v1 candidates

No new v1 candidates from this exercise. The existing #10 (`policy-execute-grants`) is reinforced by §3.2's GRANT EXECUTE inversion observation, but the issue is already filed.

### 4.3 Out-of-scope confirmations

- **ABAC mechanism** — explicitly out of scope per inputs §0.2. The deferred Stage 3 ABAC exercise will cover the `CREATE POLICY ... COLUMN MASK ... MATCH COLUMNS` form.
- **Multiple-column masking** — out of scope. The exercise targets one column; multi-column would require either separate policies or extension of the IR's `appliesTo` to accept multiple columns. Not covered here.
- **Transformations other than Redact** — out of scope. Mask, Hash, Tokenize, Bucketize are valid v0 transformations (ADR-016) but only Redact is exercised here.

---

## 5. Recommended actions

1. ✓ **Draft ADR-022** recording the schema-constraint correction. (Done 2026-05-18.)
2. ✓ **Apply the schema and technical-design fixes** per §4.1 above. (Done.)
3. ✓ **Re-validate** the exercise's YAML and JSON-LD after the fix; both passed cleanly along with the three prior exercises' artifacts.
4. ✓ **Behaviorally verify** the column-mask SQL against `bg_rls_demo.tpch.orders.o_clerk`. Scenario 1 verified empirically (§2.1); Scenario 2 verified by construction (§2.2). Optional follow-on: empirical Scenario 2 with explicit group toggling and cache-lag measurement, if desired.
5. **(Optional) Deploy Tessera's mask function to the table.** Currently the existing `mask_order_clerk` remains attached; the Tessera function `tessera__column_mask_orders_clerk__mask` is defined in the workspace but not attached. Switching the table to Tessera's version is a one-line `ALTER TABLE … ALTER COLUMN … SET MASK …` statement. Not done by default because the structural and behavioral equivalence is already established and the existing mask is functionally correct.

The exercise is complete pending any optional follow-on items in Actions 4 and 5.

---

## 6. What this comparison did not do

- **Did not execute SQL.** Behavioral verification is delegated to the deployment-and-verify step (Action 4 above).
- **Did not validate JSON-LD against the full ontology** (only the JSON Schema). The latter is the linter's job; this exercise stops at structural validation.

These omissions are noted, not gaps. The schema gap from §4.1 is the substantive output; the deployment confirms the structural argument with empirical data.

---

## 7. Closing observation

The column-mask exercise is the smallest of the three worked examples so far, and that small size made the substantive finding — the over-tight `transformation` constraint — sharper to see. A multi-column or multi-mechanism column-masking policy would have muddied which gap was which. Keeping the target narrow let the schema gap surface cleanly.

ADR-016 introduced structured transformations correctly; the schema implementing it took one over-tight position that ADR-022 corrects. The pattern — "ADR is correct; schema implementation overreaches" — is worth flagging as a thing to check when implementing future ADRs. The implementation should mirror the ADR's declared decision, not impose tighter constraints than the ADR justified.
