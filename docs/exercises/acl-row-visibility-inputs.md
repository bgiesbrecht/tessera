# Phase 1 Inputs — ACL-Table Row-Visibility Exercise

**For:** Claude Code.
**Companion documents:** `docs/worked-example-exercise.md`, `CLAUDE.md`, `DECISIONS.md`, and `spec/v0/examples/group-row-visibility.comparison.md` (the prior exercise's comparison, for context).
**Status:** Approved by Brice for handoff. The earlier ACL draft was deferred when the group-based exercise was prioritized; this is its return to the queue.
**Effective spec version:** v0, post-backport (ADR-014 + ADR-015). Policy container is canonical; `byDataset` selector and `PrincipalSetFromTable` class are first-class. This is the exercise that actually exercises them.

---

## 0. Framing

**0.1 — Demo or production scope?**

Demo. Tessera's job is to express the demonstrated pattern. Edge cases around concurrency, hot paths, audit, and operational resilience are out of scope for the comparison.

**0.2 — Target platform**

Databricks Unity Catalog. The implementation uses Unity Catalog row filter functions adapted for ACL-table joining — same platform as the group-based exercise.

**0.3 — Scope of this exercise**

An ACL-table-driven row-visibility pattern. The group-based pattern was already completed and is not in scope here.

This exercise exercises the `byDataset` selector and the `PrincipalSetFromTable` class — the parts of the v0 IR that the group-based exercise did not touch. Per ADR-003, the framework's adapter-first architecture treats custom-pattern enforcement as a peer of native enforcement; this exercise validates that claim by representing a hand-built ACL pattern in the IR.

A single Tessera policy is requested, not two parallel policies (no Mechanism A / Mechanism B framing here). The ACL pattern has no analogue to the explicit-baseline-group vs. negated-complement distinction — visibility is determined entirely by ACL entries, with no default for principals without entries.

---

## 1. The protected resource

**1.1 — Protected table**

`acme.tpch.orders_rls_acl`. A copy of TPC-H orders, separate from the group-based exercise's table.

**1.2 — Relevant columns**

The column the policy reads to decide visibility is `o_orderpriority`, with the same five possible values as the group-based exercise:

- `1-URGENT`
- `2-HIGH`
- `3-MEDIUM`
- `4-NOT SPECIFIED`
- `5-LOW`

Row-identifying column: `o_orderkey` (TPC-H convention).

**1.3 — Existing classifications**

None. The protected table is not tagged with classifications in Unity Catalog.

**1.4 — Should the protected table carry a classification?**

Not for this exercise. The policy selects against a specific table by name. The ACL pattern is fundamentally about data-driven access control; introducing a classification axis would add a dimension the existing implementation doesn't have.

---

## 2. The ACL table

**2.1 — ACL table name**

Two tables work together for this pattern, forming a logical many-to-many between users and priority values:

- `acme.tpch.rls_acl_mapping` — maps usernames to ACL codenames.
- `acme.tpch.rls_priority_acl` — maps ACL codenames to order priority values.

**2.2 — ACL schema**

`rls_acl_mapping`:
- `username` STRING — the principal's email
- `code_name` STRING — an opaque identifier representing a set of priority values

`rls_priority_acl`:
- `code_name` STRING — matches `code_name` in `rls_acl_mapping`
- `orderpriority` STRING — a specific value from the orders table's `o_orderpriority` column

The codename layer is the indirection that makes this pattern interesting for Tessera. A user is mapped to one or more codenames; each codename is mapped to one or more priorities. The policy applies if there exists a join path from the current user through the mapping table, through the codename, to a row in the protected table with a matching priority.

**2.3 — Principal column**

`rls_acl_mapping.username`. Matched against the session principal's email address (e.g., `brice.giesbrecht@databricks.com`).

**2.4 — Resource column**

Indirect. The "resource" being controlled is a priority category, not a specific row or specific table. The match is between `rls_priority_acl.orderpriority` and the protected table's `o_orderpriority` column.

This is a *categorical* mapping, not a row-level mapping — the ACL entry doesn't say "user X can see row Y," it says "user X has codename C, codename C covers priorities P1, P2, ..."

**2.5 — Permission column**

None explicit. Presence in the joined ACL tables implicitly grants read access. No permission column to filter on; no permission value to compare against.

For Tessera, this means the policy's permission semantics are "implicit read; presence in the join result = visible." A future iteration of the pattern might add an explicit permission column (the v0 `byDataset` selector supports a `permissionColumn` and `permissionValue` for this case), but the current implementation does not.

**2.6 — Other relevant columns**

None. No effective-date columns, no tenant ID, no expiration timestamp.

**2.7 — Indirection between ACL and protected table**

Two-step join, evaluated at query time:

1. Match the session user against `rls_acl_mapping.username` (case-insensitive, whitespace-trimmed) → produces a set of codenames for that user.
2. Join those codenames against `rls_priority_acl.code_name` → produces a set of `orderpriority` values the user is permitted to see.
3. A row in the protected table is visible iff its `o_orderpriority` is in that set.

The codename layer means that two users with different codename mappings can have completely different visibility profiles, but users sharing a codename have identical visibility. This is the same as role-based access control implemented at the data level.

**2.8 — Sample data, for behavioral verification**

The existing implementation seeds the ACL tables with three rows in `rls_acl_mapping` and five rows in `rls_priority_acl`:

`rls_priority_acl`:
- `('urgent_priority_ops', '1-URGENT')`
- `('high_priority_ops', '2-HIGH')`
- `('standard_ops', '3-MEDIUM')`
- `('standard_ops', '4-NOT SPECIFIED')`
- `('standard_ops', '5-LOW')`

`rls_acl_mapping`:
- `('brice.giesbrecht@databricks.com', 'urgent_priority_ops')`
- `('brice.giesbrecht@databricks.com', 'high_priority_ops')`
- `('pawanpreet.sangari@databricks.com', 'standard_ops')`

Under this seed data, the user `brice.giesbrecht@databricks.com` sees `1-URGENT` and `2-HIGH` priorities; `pawanpreet.sangari@databricks.com` sees `3-MEDIUM`, `4-NOT SPECIFIED`, and `5-LOW`; any other principal sees no rows.

This data is the basis for the behavioral verification test cases in §7.1.

---

## 3. The principal model

**3.1 — Principal identification at session time**

`current_user()` in Unity Catalog SQL, which returns the email address of the calling user. The ACL pattern explicitly calls this function in the row filter body, unlike the group pattern which delegated to `is_account_group_member`.

**3.2 — Matching session identity to ACL**

Case-insensitive, whitespace-trimmed match: `lower(trim(m.username)) = lower(trim(current_user()))`. The trim is defensive against accidental whitespace in the ACL data.

This is a substantive detail for the Tessera representation: the `byDataset` selector needs to either capture the normalization or rely on the adapter's emission to apply it. The v0 IR doesn't have a "case-insensitive match" knob on `PrincipalSetFromTable`; this should surface as a finding either in the diagnostic or as a v1 candidate.

**3.3 — Role or group hierarchy**

None. The ACL pattern doesn't use Databricks groups at all. Membership is purely individual: a user has codenames assigned to them directly by row.

**3.4 — Exceptional principals**

None. No admin bypass, no break-glass role, no service-account exception. A principal not in `rls_acl_mapping` simply sees zero rows.

---

## 4. The policy intent

**4.1 — In plain English**

A user sees rows in `orders_rls_acl` if and only if the ACL mapping tables grant them access to that row's `o_orderpriority` value via the codename indirection. The grant is computed at query time as the result of the two-table join.

**4.2 — Principals with an entry**

A principal whose username appears in `rls_acl_mapping`, with a codename that appears in `rls_priority_acl` for a given `orderpriority`, sees rows in the protected table with that priority value. A principal may have multiple codenames; the visibility is the union of priorities granted by all their codenames.

**4.3 — Principals without an entry**

A principal with no row in `rls_acl_mapping` sees no rows in the protected table. The policy is fail-closed: there is no implicit baseline access. This is unambiguously `defaultStrategy: none` in the v0 vocabulary.

The implementation makes this implicit by the `EXISTS` semantics — no matching ACL row, no visible row. There is no explicit `ELSE` branch granting anything to non-mapped users.

**4.4 — Purpose binding**

None. The policy does not depend on the principal's claimed purpose for access.

**4.5 — Time-of-day or jurisdiction conditions**

None.

**4.6 — Obligations**

None. As with the group exercise, the implementation does not emit obligations from within the row filter. Observed audit in this exercise is again the operator manipulating ACL table contents and observing the change in query results.

---

## 5. Edge cases

**5.1 — Duplicate ACL entries**

Duplicate `(username, codename)` rows in `rls_acl_mapping` would not change visibility because the row filter uses `EXISTS`, which is satisfied once or many times equivalently. Duplicate `(codename, orderpriority)` rows in `rls_priority_acl` are similarly idempotent.

For the Tessera representation: the `byDataset` selector should specify `EXISTS` semantics explicitly so the adapter emits the equivalent. The v0 IR's `existsInDataset` condition operator covers this.

**5.2 — Stale or expired ACL entries**

None. No expiration columns on either ACL table. Entries are valid until administratively removed.

**5.3 — Mid-session changes**

Changes to either ACL table take effect at the next query because the row filter function re-evaluates the join on each invocation. Unlike the group-based exercise, this pattern does not depend on a caching layer like `is_account_group_member` — the ACL tables are read directly, so propagation is synchronous on the next query.

This is a meaningful difference from the group exercise's 2-4 minute propagation window. The diagnostic report should note the timing characteristic explicitly per the §5.2 timing-disclosure principle from the technical design.

Confirm during behavioral verification that propagation is indeed synchronous; if Databricks applies any caching on the read path, the actual propagation window should be measured.

**5.4 — Joins with other tables**

Unity Catalog row filters apply to the base table before joins. A query joining the protected table with another table sees only the rows the principal is permitted to see; downstream joins operate on the filtered set.

**5.5 — Views over the protected table**

Unity Catalog row filters propagate to views over the protected table. Standard behavior.

**5.6 — Service accounts**

Treated as ordinary principals. A service account not in `rls_acl_mapping` sees no rows. There is no service-account bypass.

**5.7 — ACL table unavailability**

Fail-closed by construction. If either ACL table is unavailable, the `EXISTS` clause cannot evaluate to true for any row, and the row filter returns false for all rows — equivalent to denying all access.

Worth confirming during behavioral verification, but the structural argument is strong: there is no `ELSE` branch granting visibility when the join fails.

**5.8 — Empty ACL tables**

If both ACL tables are empty, no user sees any rows. This is consistent with fail-closed semantics — visibility requires an explicit ACL entry chain from username to priority.

**5.9 — Cross-tenant or cross-region**

Not applicable for this demonstration.

**5.10 — Other edge cases**

Three "silent failure" modes worth surfacing in the diagnostic regardless of whether they represent bugs or intent:

- *Codename collisions across users.* If two users share a codename, they share visibility on that codename's priorities. The pattern allows this by design — that is exactly how the codename indirection generalizes single-user grants to shared roles.
- *Codenames with no priority mapping.* If `rls_acl_mapping` references a codename that doesn't exist in `rls_priority_acl`, that codename grants no visibility. The join produces no rows. Silent failure mode.
- *Priorities not covered by any codename.* If a priority value exists in the protected table but no codename in `rls_priority_acl` covers it, no user ever sees rows with that priority. Also silent.

These are characteristic of data-driven access patterns. The diagnostic should name them explicitly.

---

## 6. Non-functional requirements

All not applicable for this demo. No latency budget (though the ACL join is a real query-time cost, unlike `is_account_group_member` which is platform-cached), no compliance traceability, no change-control window.

The ACL join cost is worth noting for production discussions: every query against the protected table triggers a `JOIN` against two additional tables. At scale this is a non-trivial overhead. Out of scope for the demo; worth noting in the diagnostic report's non-functional section.

---

## 7. What success looks like

**7.1 — Behavioral equivalence criteria**

Behavioral equivalence is established against the seed data in §2.8. Three scenarios, varying which ACL rows exist:

| Scenario | Setup | Brice's expected visible priorities |
|---|---|---|
| 1 | Seed data as-is | Brice's account: `1-URGENT`, `2-HIGH` |
| 2 | Add `('brice.giesbrecht@databricks.com', 'standard_ops')` to `rls_acl_mapping` | Brice's account: all five priorities |
| 3 | Remove all rows for Brice from `rls_acl_mapping` | Brice's account: zero rows |

Each scenario should be verified by running `SELECT DISTINCT o_orderpriority FROM acme.tpch.orders_rls_acl` and comparing the result to the expected set. The Tessera-derived row filter should produce identical results to the existing implementation in all three scenarios.

A fourth scenario worth considering: query as a user not in `rls_acl_mapping` at all (the implicit-fail-closed case). Optional; can be addressed by Scenario 3 if the existing implementation's behavior matches.

**7.2 — Acceptable divergences**

Same as the group exercise:

- Function name differences (as long as deterministic, references the policy ID, appropriately namespaced).
- SQL formatting and whitespace.
- Comments and header text.
- Choice of `EXISTS`/`IN`/`JOIN` structure as long as semantically equivalent.

**7.3 — Disqualifying divergences**

The Tessera derivation must:

- Produce a row filter that Unity Catalog accepts via `ALTER TABLE … SET ROW FILTER`.
- Reference the two ACL tables verbatim (`acme.tpch.rls_acl_mapping`, `acme.tpch.rls_priority_acl`) and their column names verbatim.
- Apply the same case-insensitive, whitespace-trimmed match on the principal column.
- Use `EXISTS` semantics for the join (or equivalent — any result that depends on the *existence* of a matching row chain rather than on counting).
- Be fail-closed for principals without ACL entries (no implicit `ELSE` granting visibility).

The diagnostic report should confirm each of these.

---

## 8. Anything not covered above

**On the relationship to the prior exercise.** The group-based exercise (just completed) and this ACL exercise are deliberately parallel. They exercise different parts of the IR:

- The group exercise tested attribute-based principal selection and the policy container's multi-rule semantics with branching.
- This ACL exercise tests data-driven principal selection via `byDataset` / `PrincipalSetFromTable` and a single-rule policy with `defaultStrategy: none`.

Together, the two exercises validate that the framework handles both major shapes of principal selection. Findings from this exercise should be compared with findings from the group exercise — if both exercises surface the same structural gap, that's stronger evidence than a single exercise's findings.

**On v0 vs. v1 candidates from this exercise.** Per the conversation post-ADR-014, the v0 immutability bar has come down. Findings in this exercise that would require v0 *corrections* are not in scope — they become v1 candidates instead. Findings that suggest v0 *additions* (new vocabulary, new optional fields, new well-known terms) may be candidates for minor version bumps but should be considered carefully. The default disposition is: record findings, do not backport.

**On the case-insensitive match issue.** Section §3.2 flagged that the existing implementation normalizes the principal column with `lower(trim(...))`. The v0 IR's `PrincipalSetFromTable` does not have a normalization parameter. This is expected to surface as either a diagnostic-report finding ("the adapter emits the normalization based on convention") or a v1 candidate ("the IR should support match-modifier declarations on `byDataset` selectors").

**On the two-table-join issue.** Section §2.7 described the codename indirection: visibility requires a two-table join through `rls_acl_mapping` → `rls_priority_acl`. The v0 `PrincipalSetFromTable` models a single table. This is the most consequential structural finding the exercise is expected to surface; the Tessera derivation will need to either approximate the second join leg using `existsInDataset` (best v0 fit) or surface the limitation explicitly.

---

## Handoff to Claude Code

Phase 2 produces, per `docs/worked-example-exercise.md` §2 and all in `spec/v0/examples/`:

- `acl-row-visibility-policy.tessera.yaml` — single-policy YAML using `byDataset` / `PrincipalSetFromTable`.
- `acl-row-visibility-policy.jsonld` — canonical form.
- `acl-row-visibility.databricks.sql` — Tessera-derived row filter function.
- `acl-row-visibility.diagnostic.md` — per-element enforcement report, with timing characteristics declared per §5.2 of the technical design.

Phase 3 deliverable, after behavioral verification:

- `acl-row-visibility.comparison.md` — comparison against the existing implementation, categorized per `docs/worked-example-exercise.md` §3.

The existing implementation is **not** to be shared during Phase 2. Phase 3 comparison occurs after these artifacts are committed.
