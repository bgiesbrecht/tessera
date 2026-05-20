# Phase 1 Inputs — Group-Based Row-Visibility Exercise

**For:** Claude Code.
**Companion documents:** `docs/worked-example-exercise.md`, `CLAUDE.md`, `DECISIONS.md`.
**Status:** Approved by Brice for handoff. Replaces the earlier ACL-based draft, which is deferred to a separate later exercise.
**Effective spec version:** v0, including ADR-013 (default-handling strategy).

---

## 0. Framing

**0.1 — Demo or production scope?**

Demo. The exercise validates that Tessera can express the demonstrated patterns; operational hardening, hot-path latency, and production audit infrastructure are out of scope for this comparison.

**0.2 — Target platform**

Databricks Unity Catalog.

**0.3 — Scope of this exercise**

Group-based row visibility only. The ACL-table pattern is deferred to a separate later exercise.

This exercise produces **two parallel Tessera policies** expressing the same observable behavior via the two default-handling mechanisms introduced in ADR-013:

- **Policy A** uses `defaultStrategy: explicit-baseline-group`. The baseline group is `account users` (Databricks' standard universal group). The default branch is an affirmative grant keyed off membership in `account users`.
- **Policy B** uses `defaultStrategy: negated-complement`. No baseline group. The default branch applies to principals not in either restrictive group.

Both policies produce the same observable behavior. The semantic distinction between them is the point — Policy A grounds the default in explicit baseline membership; Policy B grounds it in the absence of restrictive memberships. Both patterns are needed: Policy A is cleaner when a universal group exists; Policy B is necessary on platforms without one.

**The comparison target for Phase 3 is Policy B**, because the existing implementation is structurally a negated-complement (an `ELSE` clause, not a third affirmative rule). Policy A is the parallel demonstration that the framework can also express the alternative pattern.

---

## 1. The protected resource

**1.1 — Protected table**

`acme.tpch.orders`. Derived from the TPC-H `orders` sample data.

**1.2 — Relevant columns**

The column the policy reads to decide visibility is `o_orderpriority`, a string with five possible values:

- `1-URGENT`
- `2-HIGH`
- `3-MEDIUM`
- `4-NOT SPECIFIED`
- `5-LOW`

Row-identifying column: `o_orderkey` (TPC-H convention).

**1.3 — Existing classifications**

None. The protected table is not tagged with classifications in Unity Catalog.

**1.4 — Should the protected table carry a classification?**

Not for this exercise. The policy selects against a specific table by name. Introducing a classification would be a separate design exercise.

---

## 2. The ACL table

**Not applicable.** This exercise uses group membership only; no ACL table is consulted at policy evaluation time. Group membership is the source of truth and is determined by Databricks' `is_account_group_member()` function.

The ACL-table pattern is the subject of a separate, deferred exercise.

---

## 3. The principal model

**3.1 — Principal identification at session time**

The current principal is identified at session time via Databricks' session user. The membership check itself uses `is_account_group_member('group_name')`, which evaluates membership against the session user implicitly. The policy body does not need to call `current_user()` directly for membership checks.

**3.2 — Matching session identity to group**

The match is whatever `is_account_group_member` performs internally. Per Databricks documentation, this function returns true if the session user is a direct or indirect member of the named group at the account level. The framework does not need to reason about hierarchy explicitly; Databricks handles it.

**3.3 — Group hierarchy**

`is_account_group_member` handles direct and indirect membership transparently. A user who is in a child group whose parent group is named in the policy will match. This is a Databricks platform behavior, not something the policy or the framework expresses.

**3.4 — Exceptional principals**

None. All visibility is determined by group membership. No admin bypass, no break-glass role, no service-account exception. The two restrictive groups and the default branch (handled per the chosen strategy) cover all principals uniformly.

---

## 4. The policy intent

**4.1 — In plain English**

Members of `acme_all_priority_ops` see all rows. Members of `acme_high_priority_ops` see rows with `o_orderpriority` in (`1-URGENT`, `2-HIGH`). All other users see rows with `o_orderpriority` in (`3-MEDIUM`, `4-NOT SPECIFIED`, `5-LOW`).

**4.2 — Principals with an entry**

- Members of `acme_all_priority_ops`: see all rows regardless of `o_orderpriority`.
- Members of `acme_high_priority_ops`: see rows with `o_orderpriority IN ('1-URGENT', '2-HIGH')`.
- (If a principal is in both, the more permissive grant applies, which is `all_priority_ops`. Standard union semantics; the policies should not require explicit overlap resolution.)

**4.3 — Principals without an entry**

Principals who are not in either of the above groups see rows with `o_orderpriority IN ('3-MEDIUM', '4-NOT SPECIFIED', '5-LOW')`. This is the *default branch*, expressed differently in Policy A and Policy B per the framing in §0.3.

**4.4 — Purpose binding**

None.

**4.5 — Time-of-day or jurisdiction conditions**

None.

**4.6 — Obligations**

None expressed by the policy. Observed audit behavior in this exercise is the operator manipulating group membership and observing the change in query results. Tessera should not insert audit-log obligations the existing implementation does not have; doing so would introduce a divergence the comparison would have to handle.

---

## 5. Edge cases

**5.1 — Duplicate group memberships**

Not applicable. Group membership is a set; a principal is either a member or not.

**5.2 — Stale or expired group memberships**

Not applicable. Group memberships do not expire in this demonstration. Membership changes are administrative.

**5.3 — Mid-session changes**

`is_account_group_member` reflects current account-level membership. Mid-session group changes propagate at query evaluation time per Databricks' caching semantics. For this demo, "next query reflects current membership" is the correct expectation.

**5.4 — Joins with other tables**

Unity Catalog row filters apply to the base table; joins downstream see only the filtered rows. Standard behavior; no special handling needed in the policy.

**5.5 — Views over the protected table**

Unity Catalog row filters propagate to views over the protected table. Standard behavior.

**5.6 — Service accounts**

Treated as ordinary principals. A service account that is not in either restrictive group falls into the default branch.

**5.7 — Group lookup unavailability**

If `is_account_group_member` cannot determine membership (Databricks internal failure), the row filter returns no rows for that user. Fail-closed by default; consistent with the framework's disposition.

**5.8 — Empty membership for restrictive groups**

If `acme_all_priority_ops` and `acme_high_priority_ops` are both empty (no members), all users fall into the default branch and see priorities 3-5. This is the expected behavior, not a degenerate case.

**5.9 — Cross-tenant or cross-region**

Not applicable.

**5.10 — Other edge cases**

The interesting case for this exercise: a principal who is removed from `acme_high_priority_ops` mid-session should, on the next query, fall into the default branch (priorities 3-5) and lose visibility of priorities 1-2. Brice will exercise this scenario by changing his own group memberships and re-running queries.

---

## 6. Non-functional requirements

All not applicable for this demo. No latency budget, no compliance traceability, no change-control window. Policy DDL is dropped and recreated as needed during demonstration.

---

## 7. What success looks like

**7.1 — Behavioral equivalence criteria**

Brice will exercise three scenarios using his own account, manipulating group membership between runs:

| Scenario | Brice's membership | Expected priorities visible |
|---|---|---|
| 1 | Member of `acme_all_priority_ops` | All five (`1-URGENT`, `2-HIGH`, `3-MEDIUM`, `4-NOT SPECIFIED`, `5-LOW`) |
| 2 | Member of `acme_high_priority_ops` only | `1-URGENT`, `2-HIGH` |
| 3 | Member of neither restrictive group | `3-MEDIUM`, `4-NOT SPECIFIED`, `5-LOW` |

A query `SELECT DISTINCT o_orderpriority FROM acme.tpch.orders` under each scenario should return exactly the rows in the expected column. Row counts per priority should match the unfiltered table's distribution.

The Tessera derivation is behaviorally equivalent if all three scenarios produce the expected priorities.

**7.2 — Acceptable divergences**

The Tessera-derived row filter function may differ from the existing implementation in:

- Function name (as long as it is deterministic, references the policy ID, and is appropriately namespaced).
- SQL formatting and whitespace.
- Comments and header text.
- Choice of `CASE`/`WHEN`/`ELSE` versus equivalent constructs, as long as the readability principle is honored.

**7.3 — Disqualifying divergences**

The Tessera derivation must:

- Produce a row filter that Unity Catalog accepts via `ALTER TABLE ... SET ROW FILTER`.
- Reference the two restrictive group names verbatim (`acme_all_priority_ops`, `acme_high_priority_ops`). These appear in the policy file directly; no identity-binding indirection in this exercise.
- For Policy A, reference `account users` verbatim as the baseline group.
- Produce a `CASE`/`WHEN`/`ELSE` row filter for Policy B. This is the readability preference noted above. If the Tessera framework's natural derivation produces a structurally different form (explicit `NOT is_account_group_member(...) AND ...`), the diagnostic report should note this as adapter quality-of-output work to be improved, but it does not disqualify the exercise.

---

## 8. Anything not covered above

**On the relationship between the two policies.** Policy A and Policy B are not alternative formulations of one policy. They are two policies — same observable behavior, different intent. The exercise produces *both* as separate YAML files and separate JSON-LD files. The comparison in Phase 3 evaluates Policy B against the existing implementation (because the existing implementation is structurally negated-complement). Policy A is evaluated for its own correctness (does the framework express the explicit-baseline-group pattern correctly?) but is not directly compared against existing code.

**On the default strategy field as a v0 element.** The `defaultStrategy` field was added to v0 as a deliberate enhancement (ADR-013) prompted by this exercise. This is itself a finding worth recording in the Phase 2 diagnostic report and the Phase 3 comparison: the worked example surfaced a gap in the IR that the framework was right to fix before v0 publication. The exercise's value is partly measured by what it taught the spec about itself.

**On the readability preference for CASE/WHEN/ELSE.** This is a Databricks adapter quality-of-output expectation, not a per-policy directive. The Tessera policy file itself should not include emission directives; the policy expresses meaning declaratively. The Databricks adapter is expected to recognize the negated-complement pattern with a small set of affirmative rules and emit a `CASE`/`WHEN`/`ELSE` row filter. If the adapter does not, the diagnostic report notes the adapter improvement opportunity.

---

## Handoff to Claude Code

Ready to proceed. Phase 2 produces, per `docs/worked-example-exercise.md`:

- `spec/v0/examples/group-row-visibility-policy-a.tessera.yaml` (explicit baseline group)
- `spec/v0/examples/group-row-visibility-policy-a.jsonld`
- `spec/v0/examples/group-row-visibility-policy-b.tessera.yaml` (negated complement)
- `spec/v0/examples/group-row-visibility-policy-b.jsonld`
- `spec/v0/examples/group-row-visibility.databricks.sql` (the Tessera-derived row filter function and table alteration; one per policy if the SQL differs meaningfully, or a single file with both row filters clearly delineated)
- `spec/v0/examples/group-row-visibility.diagnostic.md` (covers both policies)

The existing implementation is **not** to be shared during Phase 2. Phase 3 comparison occurs after these artifacts are committed.
