# Diagnostic Report — Group-Based Row Visibility (Policy A & Policy B)

**Companion artifacts:**
- `group-row-visibility-policy-a.tessera.yaml` / `.jsonld` (explicit-baseline-group)
- `group-row-visibility-policy-b.tessera.yaml` / `.jsonld` (negated-complement)
- `group-row-visibility.databricks.sql`

**Inputs:** `docs/exercises/group-row-visibility-inputs.md`
**Exercise framing:** `docs/worked-example-exercise.md`
**Spec version:** v0, including ADR-013, ADR-014, ADR-015.
**Target platform:** Databricks Unity Catalog.

> **Historical note (added 2026-05-18 after ADR-014).** This diagnostic describes the worked example's findings *before* ADR-014 backported the Policy container into v0. The four v0 gaps it surfaced (§4) drove that backport — three of them (multi-branch primitive, default-branch predicate, IRI-safety) were resolved by ADR-014; the fourth (group-membership condition operator) was reclassified as deferred-not-needed-yet. The worked-example YAML and JSON-LD artifacts in this directory have since been rewritten to the post-backport Policy shape. This document is preserved as the record of what the worked example surfaced and why the backport happened. Read §4 as historical narrative, not as a list of current gaps.

This report is the honest accounting required by §2.4 of the exercise: which elements of each policy are fully enforced, which are partially enforced, which are unenforced — and which gaps in v0 of the IR the exercise surfaced.

---

## 1. Summary

Both Policy A and Policy B compile to Unity Catalog row filter functions that should produce the behavior described in inputs §7.1. The Tessera-derived SQL preserves group names verbatim, uses `is_account_group_member()` for membership, and emits the readable `CASE`/`WHEN`/`ELSE` form. Behavioral equivalence cannot be confirmed from this side of the Phase 2 / Phase 3 boundary — the existing implementation has not been seen — but no element of either policy is silently approximated.

The exercise surfaced three real gaps in the v0 IR. They are described in §4. None of them blocks the exercise; all three are honest spec-revision candidates.

---

## 2. Per-element enforcement (both policies)

| Policy element | Category | Notes |
|---|---|---|
| Resource binding (`acme.tpch.orders`) | **Fully enforced** | The `ALTER TABLE … SET ROW FILTER` statement attaches the function to the protected table. |
| Restrictive group: `acme_all_priority_ops` | **Fully enforced** | `is_account_group_member('acme_all_priority_ops')` returns `TRUE` for all rows when matched. |
| Restrictive group: `acme_high_priority_ops` | **Fully enforced** | Row filter narrows to `o_orderpriority IN ('1-URGENT', '2-HIGH')` when matched. |
| Default branch — Policy A (`account users` baseline) | **Fully enforced** | Explicit `WHEN is_account_group_member('account users')` branch; trailing `ELSE FALSE` fail-closes for principals not even in the universal group (defense in depth). |
| Default branch — Policy B (negated complement) | **Fully enforced** | Trailing `ELSE` branch handles principals matching neither restrictive group. |
| `defaultStrategy` semantic distinction | **Fully enforced** (at SQL emission) | Policy A and Policy B emit structurally different SQL (extra `WHEN` vs. `ELSE`) reflecting the intent difference declared in the IR. The audit-semantics benefit of `explicit-baseline-group` (per ADR-013) is preserved by the explicit `account users` branch being present in Policy A's SQL. |
| `action: Read` | **Implicitly enforced** | Unity Catalog row filters apply to all read paths against the table. Tessera's `Read` action maps cleanly to this. Write/delete paths are out of scope for row visibility. |
| `effect: keep-matching-rows` | **Fully enforced** | The row filter function returning `TRUE`/`FALSE` is exactly the "keep matching rows" effect at the platform layer. |
| Purpose binding | **Not applicable** | Inputs §4.4 declares no purpose. |
| Obligations (audit log / notify / watermark) | **Not applicable** | Inputs §4.6 declares none. Tessera correctly does not inject any. |
| Provenance metadata | **Partially enforced** | The Tessera policy carries `provenance.notes`; Unity Catalog has no native facility to embed this in the row filter. The function body includes a comment block tracing back to the policy ID, which is the most Unity Catalog can do without a separate audit-store. |

---

## 3. Edge-case coverage (per inputs §5)

| # | Edge case | Coverage | Notes |
|---|---|---|---|
| 5.1 | Duplicate group memberships | **N/A** | Group membership is set-valued; duplicates don't occur. |
| 5.2 | Stale / expired memberships | **N/A** | Memberships don't expire in this demo. |
| 5.3 | Mid-session membership changes | **Fully enforced** | `is_account_group_member` reflects current state per Databricks caching semantics. Next-query freshness, which matches the inputs' expectation. |
| 5.4 | Joins with other tables | **Fully enforced** | Unity Catalog row filters apply to the base table; downstream joins see only filtered rows. |
| 5.5 | Views over the protected table | **Fully enforced** | Unity Catalog row filters propagate to views. |
| 5.6 | Service accounts | **Fully enforced** | Service accounts are treated as ordinary principals; they fall into whichever branch their group memberships place them in. The default branch catches service accounts in neither restrictive group. |
| 5.7 | `is_account_group_member` failure | **Fully enforced (fail-closed)** | If the membership lookup itself fails, Databricks returns `FALSE`/`NULL` from the function, which in a row filter means "no rows visible." Consistent with the framework's fail-closed disposition. |
| 5.8 | Empty restrictive group memberships | **Fully enforced** | If both restrictive groups are empty, every principal falls into the default branch and sees priorities 3–5. Expected behavior. |
| 5.9 | Cross-tenant / cross-region | **N/A** | Out of scope. |
| 5.10 | Demo scenario: principal removed mid-session | **Fully enforced** | Next-query reflects current membership; the principal falls into the default branch (priorities 3–5) on the next query. |

---

## 4. v0 IR gaps surfaced by this exercise

These are findings the exercise produced. None is fatal to v0, but each is a candidate for either a pre-publication correction (like ADR-013 was) or a v1 revision.

### 4.1 No explicit multi-branch policy primitive

The v0 IR (§4.2 of the technical design) describes a single policy as having one `principal` selector, one `condition`, and one `effect`. Real policies — including the one in this exercise — have multiple branches: different principal selectors with different row predicates.

The artifacts represent each branch as a separate `RowVisibilityConstraint` under a JSON-LD `@graph`. This works, but it has costs:

- `defaultStrategy` and `baselineGroup` are duplicated across every constraint in the `@graph`, because v0 attaches them to `PolicyConstraint` and has no policy-collection container.
- The aggregation algebra across constraints on the same resource (union? first-match? policy-combining-algorithm?) is not specified in v0. Adapters must make a choice; that choice is implicit.
- The "this rule is the default branch" relationship between `defaultStrategy: explicit-baseline-group` and the rule whose principal is the baseline group has to be inferred by the adapter from string matching between `baselineGroup` and `principal.resource`. There's no explicit link in the IR.

**Candidate v1 shape:** a policy-collection container class (e.g., `tessera:Policy`) that owns `defaultStrategy`, `baselineGroup`, and an ordered list of rules. Each rule is a slimmer structure than a full `PolicyConstraint`. ADR-007 already tracks "policy-combining algorithm" as an open question; this would fold into that work.

### 4.2 No group-membership condition operator

The closed condition algebra (§4.4) has `purpose-in`, `located-in`, `time-window`, `consent-granted`, `exists-in-dataset` — but no `principal-in-group` or `is-member-of`. This is workable: group membership is expressed by the principal selector, not the condition. But it constrains expressiveness in adjacent cases (a single-rule policy that gates by group membership AND another condition can't naturally combine them).

**Candidate v1 shape:** add `principal-in-group` (or, more generally, `principal-in-set`) to the condition algebra. ADR-007 covers algebra extensibility as a tracked open question.

### 4.3 No default-branch predicate field

For `defaultStrategy: negated-complement`, the IR declares the strategy but has nowhere to put the actual default-branch predicate (the row filter that applies to non-matchers). Without an explicit field, the predicate has to live in an explicit "default rule" — which Policy B does via `byComposition` / `match: not` over the restrictive group selectors.

This works but is awkward: the rule is structurally a regular `RowVisibilityConstraint` even though it semantically represents the strategy-declared default. An adapter has to recognize the pattern to emit the readable `ELSE` form (see §5).

**Candidate v1 shape:** when a policy-collection container exists (per §4.1), it can carry an optional `defaultBranch` field — a row predicate that applies when the strategy is `negated-complement` and no rule matches.

### 4.4 Bonus gap — IRI-safety of platform-native identifiers

The baseline group on Databricks is named `account users` — with a space, which is not a valid IRI segment. The artifacts work around this by using a URI-safe Tessera identifier (`group:account-users`) in the `principal.resource` field and carrying the verbatim platform-native name in `baselineGroup` (a `xsd:string`, no IRI constraint). This is honest but inconsistent: the same group appears under two different identifiers in the same policy.

**Candidate v1 shape:** define an `@type: @vocab`-like mechanism for principal references that explicitly carries a platform-native string alongside the IRI, or require platform identifiers to be URL-encoded at the IR layer with adapters decoding for emission. Either is a minor change.

---

## 5. Adapter quality-of-output observation (Policy B)

Inputs §7.3 explicitly notes that the readable `CASE`/`WHEN`/`ELSE` form is a Databricks-adapter quality-of-output expectation, not a per-policy directive. The Tessera-derived SQL emits the readable form, which requires the adapter to recognize a specific pattern:

> A `defaultStrategy: negated-complement` policy with N affirmative-grant rules plus exactly one default-complement rule (a `byComposition` / `not` over the affirmative selectors) compiles to a `CASE` with N `WHEN` branches plus a single `ELSE` carrying the default rule's row predicate.

A naive Tessera adapter that emitted each rule in isolation would produce three `WHEN` branches, the third of which would be:

```sql
WHEN NOT is_account_group_member('acme_all_priority_ops')
 AND NOT is_account_group_member('acme_high_priority_ops')
THEN o_orderpriority IN ('3-MEDIUM', '4-NOT SPECIFIED', '5-LOW')
```

This is behaviorally equivalent but harder to read. Inputs §7.3 accepts the naive form but flags it as adapter improvement work. The artifacts here emit the readable form because the adapter (modelled as part of this exercise) recognizes the pattern.

For Policy A (`explicit-baseline-group`), no such pattern recognition is needed: each rule maps directly to one `WHEN` clause, with an explicit `WHEN is_account_group_member('account users')` for the default branch. The trailing `ELSE FALSE` is defensive, not algorithmic.

---

## 6. What the exercise did not exercise

By design, this exercise omits:

- **The `byDataset` selector and `PrincipalSetFromTable` class.** Reserved for the deferred ACL-table exercise. The data-driven principal-set path through the IR is therefore unexercised here.
- **Purpose binding** (`purpose-in` condition). No purpose in this policy.
- **Obligations** of any kind. No `AuditLog`, `Notify`, or `Watermark` emission.
- **Column visibility / transformations.** Out of scope for a row-only policy.
- **Cross-platform translation.** Databricks only; the Snowflake adapter is not used.

These are not gaps; they are the exercise's deliberate scope. The deferred ACL-table exercise will cover the first; later exercises will cover the rest.

---

## 7. Recommended findings to track

| Finding | Category | Suggested action |
|---|---|---|
| No multi-branch policy primitive (§4.1) | **v1 candidate** | Open issue with label `v1-candidate`; couple with ADR-007 policy-combining algorithm question. |
| No group-membership condition operator (§4.2) | **v1 candidate** | Open issue; fold into condition-algebra extensibility (ADR-007). |
| No default-branch predicate field (§4.3) | **v1 candidate** | Same as §4.1 — design together. |
| IRI-safety of platform-native group names (§4.4) | **v0 documentation correction** | Add a note to the technical design clarifying the carrier-of-verbatim-names convention. Not a vocabulary change. |
| Adapter pattern recognition for negated-complement (§5) | **Adapter implementation note** | Documented here for the Databricks adapter when it is built (Priority 6). Not a spec issue. |

The Phase 3 comparison (when the existing implementation is shared) will produce a parallel set of findings categorized along the same axes. Items here are likely to be confirmed, qualified, or supplemented by that comparison.
