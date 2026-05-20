# Phase 1 Inputs — Snowflake `byDataset` Row-Visibility Exercise

**For:** Claude Code (in-repo) running Phase 2.
**Companion documents:** `docs/exercises/acl-row-visibility-inputs.md` (Databricks counterpart, business-requirement source), `docs/worked-example-exercise.md`, `CLAUDE.md`, `DECISIONS.md`.
**Status:** Approved by Brice for handoff. Brice has no Snowflake implementation of this pattern; business requirements are inherited from the Databricks ACL brief and Snowflake-specific decisions are made explicit below.
**Effective spec version:** v0, post-Stage-4 (ADRs 013–023). `byDataset` selector and `PrincipalSetFromTable` class first-class. ADR-024 adapter contract in effect.

---

## 0. Framing

**0.1 — Demo or production scope?**

Demo. Same posture as the prior exercises: express the demonstrated pattern correctly; out of scope are concurrency, hot paths, audit, operational resilience.

**0.2 — Target platform**

Snowflake. Account `FBGQMMZ-DCC90967`, database `ACME`, schema `TESSERA`. Compute warehouse `COMPUTE_WH`.

**0.3 — Scope of this exercise**

An ACL-table-driven row-visibility pattern on Snowflake, equivalent to the Databricks `acl-row-visibility-*` exercise. Validates two claims simultaneously:

1. The `byDataset` selector + `PrincipalSetFromTable` class are platform-neutral — the same IR shape can lower to a Snowflake row-access policy that joins a mapping table, with no IR changes.
2. The mapping-table pattern is Snowflake's documented best-practice for non-trivial row-access policies (Snowflake docs: *Use row access policies* — *Mapping table placement*) and naturally aligns with Tessera's `byDataset` selector. This exercise produces the empirical grounding for that recommendation.

A single Tessera policy is requested, not two parallel policies. No Mechanism A / Mechanism B distinction — ACL-driven visibility has no default-branch analogue.

**Differences from the Databricks counterpart, declared up front:**

- Identifiers: Snowflake folds unquoted identifiers to uppercase. ACL tables and user references will be UPPER_CASE in the emitted DDL.
- Principal function: `CURRENT_USER()` (Snowflake builtin returning login name), not `current_user()` (Databricks email).
- `EXISTS` semantics: Snowflake row-access policies accept correlated subqueries; the same `EXISTS` idiom works.
- Secondary-roles immunity: because the policy gates on `CURRENT_USER()` (a user-identity function), the BCR-1692 `DEFAULT_SECONDARY_ROLES=('ALL')` gotcha that affects `IS_ROLE_IN_SESSION` does **not** apply. This is the specific reason this pattern is the recommended Snowflake authoring style.

---

## 1. The protected resource

**1.1 — Protected table**

`ACME.TESSERA.SNOW_ORDERS_RLS_ACL`. A copy of the existing `ACME.TESSERA.SNOW_ORDERS` table (which itself is the 1.5M-row TPC-H sample). Created fresh for this exercise so unrelated policies do not interact.

**1.2 — Relevant columns**

The visibility-bearing column is `O_ORDERPRIORITY`, same five values as the Databricks counterpart:

- `1-URGENT`
- `2-HIGH`
- `3-MEDIUM`
- `4-NOT SPECIFIED`
- `5-LOW`

Row-identifying column: `O_ORDERKEY`.

**1.3 — Existing classifications**

None. The Snowflake table is not tagged with object tags.

---

## 2. The ACL tables

**2.1 — ACL table names**

Two tables, mirroring the Databricks two-table indirection:

- `ACME.TESSERA.RLS_ACL_MAPPING` — maps usernames to codenames.
- `ACME.TESSERA.RLS_PRIORITY_ACL` — maps codenames to order-priority values.

**2.2 — ACL schema**

`RLS_ACL_MAPPING`:
- `USERNAME` VARCHAR — the principal's Snowflake login name (matches `CURRENT_USER()`).
- `CODE_NAME` VARCHAR — opaque identifier representing a set of priority values.

`RLS_PRIORITY_ACL`:
- `CODE_NAME` VARCHAR — matches `CODE_NAME` in `RLS_ACL_MAPPING`.
- `ORDERPRIORITY` VARCHAR — a value from `SNOW_ORDERS_RLS_ACL.O_ORDERPRIORITY`.

The codename indirection is preserved — it's the load-bearing feature for this pattern's interest to Tessera (data-driven indirection between principal and resource).

**2.3 — Principal column**

`RLS_ACL_MAPPING.USERNAME`. Matched against `CURRENT_USER()` (Snowflake login name, returned in the user's stored case — typically uppercase for accounts created via SSO/SCIM).

**2.4 — Resource column**

Indirect, same as the Databricks counterpart. The match is between `RLS_PRIORITY_ACL.ORDERPRIORITY` and `SNOW_ORDERS_RLS_ACL.O_ORDERPRIORITY`.

**2.5 — Permission column**

None explicit. Implicit-read semantics: presence in the joined ACL chain grants visibility.

**2.6 — Other relevant columns**

None.

**2.7 — Indirection between ACL and protected table**

Two-step join, evaluated at query time:

1. `RLS_ACL_MAPPING.USERNAME = CURRENT_USER()` → set of codenames for the session user.
2. `RLS_PRIORITY_ACL.CODE_NAME` joined to those codenames → set of permitted priority values.
3. A row in the protected table is visible iff its `O_ORDERPRIORITY` is in that set.

Expressed in the row-access policy body as a correlated `EXISTS` subquery.

**2.8 — Sample data for behavioral verification**

`RLS_PRIORITY_ACL`:
- `('urgent_priority_ops', '1-URGENT')`
- `('high_priority_ops', '2-HIGH')`
- `('standard_ops', '3-MEDIUM')`
- `('standard_ops', '4-NOT SPECIFIED')`
- `('standard_ops', '5-LOW')`

`RLS_ACL_MAPPING`:
- `('BGIESBRECHT', 'urgent_priority_ops')`
- `('BGIESBRECHT', 'high_priority_ops')`

Under this seed, the user `BGIESBRECHT` sees only `1-URGENT` and `2-HIGH` priorities; any other principal sees no rows. The Databricks brief seeded a second user; this exercise can extend during Phase 3 if a second test identity is available, otherwise the second user's absence is itself a test (any non-`BGIESBRECHT` session sees zero rows).

---

## 3. The principal model

**3.1 — Principal identification at session time**

`CURRENT_USER()` (Snowflake builtin). Returns the login name of the current session user. Unaffected by `USE ROLE`, by primary/secondary role activation, or by warehouse choice.

This function is the specific reason the `byDataset` pattern is secondary-roles-immune: it gates on user identity (which Snowflake resolves deterministically per session), not on role activation (which the `DEFAULT_SECONDARY_ROLES = ('ALL')` default collapses).

**3.2 — Matching session identity to ACL**

Default: exact-match on `CURRENT_USER() = RLS_ACL_MAPPING.USERNAME`. Snowflake folds unquoted identifiers to uppercase by default, so seed-data usernames should be stored uppercase (`'BGIESBRECHT'`).

A `lower(trim(...))` normalization (as in the Databricks brief) is optional and not required for this exercise — Snowflake's identifier folding handles the case-normalization case structurally. If the diagnostic finds a real-world need for trim normalization (e.g., ACL data sourced from a CSV with whitespace), that is a v1 candidate, not an in-scope finding.

**3.3 — Role or group hierarchy**

Not used. Membership is per-user, individual. Roles are irrelevant to the policy logic.

**3.4 — Exceptional principals**

None. No admin bypass. ACCOUNTADMIN is subject to the policy unless explicitly granted access via the ACL tables. (Snowflake row-access policies do not exempt the table owner; verify during Phase 3.)

---

## 4. The policy intent

**4.1 — In plain English**

A user sees rows in `SNOW_ORDERS_RLS_ACL` if and only if the ACL mapping tables grant them access to that row's `O_ORDERPRIORITY` value via the codename indirection. The grant is computed at query time as the result of the two-table join.

**4.2 — Principals with an entry**

A principal whose username appears in `RLS_ACL_MAPPING`, with a codename that appears in `RLS_PRIORITY_ACL` for a given `ORDERPRIORITY`, sees rows in the protected table with that priority value. Multiple codenames → union of permitted priorities.

**4.3 — Principals without an entry**

A principal with no row in `RLS_ACL_MAPPING` sees no rows. Fail-closed; `defaultStrategy: none` in v0 vocabulary.

**4.4 — Purpose binding** — None.

**4.5 — Time-of-day or jurisdiction conditions** — None.

**4.6 — Obligations** — None.

---

## 5. Edge cases

**5.1 — Duplicate ACL entries.** `EXISTS` semantics: idempotent under duplicates.

**5.2 — Stale or expired ACL entries.** Not modeled. ACL entries are valid until administratively removed.

**5.3 — Mid-session changes.** ACL changes take effect on the next query (no caching layer; the policy body re-evaluates per query).

**5.4 — Joins with other tables.** Snowflake row-access policies apply at the base table before downstream joins.

**5.5 — Views over the protected table.** Snowflake row-access policies propagate through views.

**5.6 — Service accounts.** Treated as ordinary principals. No bypass.

**5.7 — ACL table unavailability.** Fail-closed by `EXISTS` construction. If the policy body cannot evaluate `EXISTS`, the row is hidden.

**5.8 — Empty ACL tables.** All users see zero rows. Fail-closed.

**5.9 — Secondary-roles activation.** Not relevant — `CURRENT_USER()` is unaffected. This is the specific reason this pattern is preferable to `IS_ROLE_IN_SESSION`-based policies on Snowflake. Phase 3 should confirm by toggling `USE SECONDARY ROLES ALL | NONE` and verifying row counts are unchanged.

**5.10 — Table owner / ACCOUNTADMIN.** Snowflake row-access policies are not exempt-by-owner. ACCOUNTADMIN running the test query is subject to the policy. Confirm in Phase 3 — if the test user is also the table owner, this should be visible in the verification output.

---

## 6. Non-functional requirements

All not applicable for the demo. The mapping-table join is a real query-time cost; out of scope for this exercise.

---

## 7. What success looks like

**7.1 — Behavioral equivalence criteria**

Per the seed data in §2.8, three scenarios:

| Scenario | Setup | Expected visible priorities |
|---|---|---|
| 1 | Seed data as-is | `BGIESBRECHT`: `1-URGENT`, `2-HIGH` |
| 2 | Add `('BGIESBRECHT', 'standard_ops')` to `RLS_ACL_MAPPING` | `BGIESBRECHT`: all five priorities |
| 3 | Remove all `BGIESBRECHT` rows from `RLS_ACL_MAPPING` | `BGIESBRECHT`: zero rows |

A fourth: with seed data restored, switch session to `USE SECONDARY ROLES NONE` and again to `USE SECONDARY ROLES ALL`; row counts must be identical (confirms the secondary-roles-immunity claim).

**7.2 — Acceptable divergences**

Same as the prior exercises: policy name differences, formatting/whitespace, comment/header variations, choice of `EXISTS`/`IN`/`JOIN` structure as long as semantically equivalent.

**7.3 — Disqualifying divergences**

The Tessera-derived row-access policy must:

- Be accepted by Snowflake via `CREATE ROW ACCESS POLICY ...` and `ALTER TABLE ... ADD ROW ACCESS POLICY ...`.
- Reference the two ACL tables verbatim (`ACME.TESSERA.RLS_ACL_MAPPING`, `ACME.TESSERA.RLS_PRIORITY_ACL`).
- Use `CURRENT_USER()` to match the session principal.
- Use `EXISTS` semantics (or equivalent — existence of a matching row chain, not counting).
- Be fail-closed for principals without ACL entries.

The diagnostic should confirm each.

---

## 8. Anything not covered above

**On Snowflake adapter implementation status (Phase 2):** the `byDataset` selector is not yet implemented in `adapters/snowflake/emission.py`. This exercise's Phase 2 includes implementing it. Per the scaffold's contract (ADR-024), this means extending `emit_policy` and `_emit_row_visibility` to dispatch on `appliesTo.selector` for `byIdentity` vs `byDataset`, plus handling the `PrincipalSetFromTable` reference resolution (the ACL table name needs to come from the IR's dataset reference, not from configuration).

**On adapter config additions:** the `byDataset` emission path may surface a need for `AdapterConfig` to carry per-ACL-table configuration (e.g., column-name overrides if the IR's logical column names don't match the platform's). Document any such finding; do not pre-add config fields.

**On comparing to the Databricks counterpart.** The Phase 3 diagnostic should include a side-by-side comparison of the Tessera-emitted Snowflake row-access policy and the Tessera-emitted Databricks row filter (from `spec/v0/examples/acl-row-visibility.databricks.sql`), highlighting where the same IR lowers to platform-divergent DDL. This is the empirical content that grounds the user-documentation recommendation.

---

## Handoff to Claude Code

Phase 2 produces, all under `spec/v0/examples/`:

- `snowflake-byDataset-row-visibility-policy.tessera.yaml`
- `snowflake-byDataset-row-visibility-policy.jsonld`
- `snowflake-byDataset-row-visibility.snowflake.sql`
- `snowflake-byDataset-row-visibility.diagnostic.md`

Plus, under `adapters/snowflake/`:

- Extended `emission.py` covering `byDataset` for `RowVisibilityConstraint`.
- Capability-profile update if `DATASET_DRIVEN_PRINCIPALS` moves from PARTIAL to SUPPORTED for row visibility.

Phase 3 deliverable:

- `snowflake-byDataset-row-visibility.findings.md` — live-execution results, including the secondary-roles-immunity verification and the side-by-side comparison with the Databricks counterpart.

Brice has no competing implementation, so there is no "implementation comparison" section. The Phase 3 doc is `findings.md` rather than `comparison.md`.
