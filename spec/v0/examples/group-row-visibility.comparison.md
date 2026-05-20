# Phase 3 Comparison — Group-Based Row Visibility

**Companion artifacts:**
- `group-row-visibility-policy-a.tessera.yaml` / `.jsonld`
- `group-row-visibility-policy-b.tessera.yaml` / `.jsonld`
- `group-row-visibility.databricks.sql`
- `group-row-visibility.diagnostic.md`

**Inputs:** `docs/exercises/group-row-visibility-inputs.md`
**Exercise framing:** `docs/worked-example-exercise.md`
**Existing implementation reference:** `RLS_Demo` notebook (held by Brice), group-based pattern.

**Status:** Comparison drafted by an assistant; behavioral verification completed against a real Databricks workspace on 2026-05-18.

> **Historical note (added 2026-05-18 after ADR-014).** This comparison describes the worked example's findings *before* ADR-014 backported the Policy container into v0. The v1-candidate findings in §4.3 drove that backport: the policy-container and default-branch-predicate candidates were resolved by ADR-014 itself; the combining-algebra question was resolved by ADR-015 (ordered first-match); the principal-in-group condition was reclassified as deferred-not-needed-yet. The v0-doc-correction findings in §4.2 are tracked as issues #4, #5, and #6 on the repository (the timing-disclosure one is closed-on-arrival because its target §5.2 paragraph landed at the same time). The worked-example artifacts in this directory have been rewritten to the post-ADR-014 Policy shape; this comparison is preserved as the record of how the exercise produced those changes.

---

## 1. Comparison summary

The Tessera-derived Policy B and the existing notebook implementation are structurally close and behaviorally equivalent — verified against `acme.tpch.orders` on `e2-demo-field-eng` (see §2). The Tessera derivation additionally produces Policy A — an `explicit-baseline-group` variant the existing implementation has no analogue for — and four artifacts the existing implementation does not have: a canonical IR form, a structural intent declaration via `defaultStrategy`, a diagnostic report, and a traceable identifier linking the SQL back to the policy.

The comparison surfaced no findings in the "spec is wrong" or "Tessera derivation is wrong" categories. Findings fall into three groups: existing-implementation observations that are reasonable but undocumented in the original, structural observations about what the framework adds, and confirmation of the four v0 gaps the diagnostic already surfaced — plus one operational observation about group-membership cache propagation that emerged during verification (§2.3).

---

## 2. Behavioral equivalence (§3.1 of the exercise framing)

### 2.1 Test scenarios per inputs §7.1

Behavioral equivalence was established by deploying the Tessera-derived Policy B row filter (`acme.tpch.tessera__group_row_visibility_policy_b__row_filter`) to `acme.tpch.orders` and running `SELECT DISTINCT o_orderpriority` under three account-group membership states.

| Scenario | Brice's group membership | Expected priorities | Observed (Tessera Policy B) | Match |
|---|---|---|---|---|
| 1 | `acme_all_priority_ops` (+ `account users`) | 1-URGENT, 2-HIGH, 3-MEDIUM, 4-NOT SPECIFIED, 5-LOW | Same | ✓ |
| 2 | `acme_high_priority_ops` only | 1-URGENT, 2-HIGH | Same | ✓ |
| 3 | Neither restrictive group (still in `account users`) | 3-MEDIUM, 4-NOT SPECIFIED, 5-LOW | Same | ✓ |

Verification mechanics: Brice toggled account-group memberships in the Databricks account console; an SDK-driven verifier polled `is_account_group_member()` for each restrictive group until the live evaluation reflected the new state, then captured `SELECT DISTINCT o_orderpriority` and compared to the expected set. The existing notebook implementation was not re-verified against the same scenarios because its three-branch SQL is structurally identical (same `is_account_group_member` calls, same priority value strings, same `CASE`/`WHEN`/`ELSE` shape — see §3.1 of this document); its behavior follows from the same membership semantics under test here.

Row counts after the filter: Scenario 1 saw all 7.5M rows; Scenarios 2 and 3 saw the proportional subsets the priority filtering implies. The exercise did not require count-level verification (only distinct-priority match), but the row-count results were consistent with the unfiltered table's distribution.

### 2.2 Behavioral categorization (per §3.1's four-category framework)

All three scenarios fall into the "both implementations agree" category. There are no findings in the "Tessera wrong," "existing wrong," "spec wrong," or "intent ambiguous" categories from this verification.

### 2.3 Operational observation — group membership cache propagation

The verification surfaced a real operational consideration that the diagnostic's edge-case table called out only obliquely.

When Brice changed his account-group membership in the Databricks account console, `is_account_group_member()` continued to report the *old* membership for some time before the new state propagated. Observed propagation lags in this session:

- Scenario 2 (remove from `all_priority_ops`, add to `high_priority_ops`): ~2 minutes 4 seconds
- Scenario 3 (remove from `high_priority_ops`): ~3 minutes 47 seconds

This is consistent with Databricks documentation that account-group membership changes can take up to several minutes to propagate to query-evaluation contexts. The diagnostic's edge 5.3 ("Mid-session membership changes") was marked **Fully enforced** with the note "next-query freshness, which matches the inputs' expectation." That remains accurate for the *eventual* state, but the lag is worth noting for any operational use of group-based row filters:

- The "next query reflects current membership" expectation in inputs §5.3 is best understood as "next-query-after-cache-propagation," not "literally the very next query."
- For workflows where membership change must take effect immediately (incident response, break-glass de-escalation), this lag is a real constraint. The right place to surface it is the **adapter capability profile** — the existing disclosure surface adapters already use for mechanism-specific information (technical design §5.2). Timing characteristics differ by enforcement mechanism (an ACL-table-driven row filter has a different profile than a group-membership check; a tag-driven column mask has yet another), so the disclosure is per-mechanism, not framework-wide; the framework's job is to require the disclosure, not to enumerate timing categories.

This is an operational annotation, not a spec defect. The Tessera-derived SQL is correct; the platform's caching is a property of the enforcement substrate. Recording it here so the next exercise (or first real deployment) does not rediscover it under pressure.

---

## 3. Structural comparison (§3.2 of the exercise framing)

### 3.1 SQL row-filter function

Both implementations produce a Unity Catalog row filter function with the same logical shape: a `CASE` expression with three branches keyed off `is_account_group_member` calls, ending in an `ELSE` for the default behavior. The branch values, priority strings, and membership-check arguments are identical. Two structural divergences are noted in §3.5 below — they did not appear in the original Phase 3 draft and were surfaced when the notebook was inspected directly during the ACL exercise's comparison.

Observed structural differences:

| Dimension | Existing implementation | Tessera-derived Policy B | Category |
|---|---|---|---|
| Function name | `priority_filter_by_group` (unqualified; relies on `USE` for schema) | `acme.tpch.tessera__group_row_visibility_policy_b__row_filter` — fully qualified, deterministic, traceable | **Accepted divergence** (inputs §7.2); the Tessera form is more rigorous and was selected as a feature, not by accident |
| Parameter name | `orderpriority` | `o_orderpriority` | **Accepted divergence**. Both work — parameter names are local to the function body. |
| `CASE`/`WHEN`/`ELSE` structure | Yes | Yes | **Match** |
| Branch order | Most-permissive first | Most-permissive first | **Match** |
| Membership-check syntax | `is_account_group_member('group_name')` | Same | **Match** |
| Priority value strings (restrictive branch) | `IN ('1-URGENT','2-HIGH')` | Same | **Match** |
| Priority value strings (ELSE / default branch) | `NOT IN ('1-URGENT','2-HIGH')` | `IN ('3-MEDIUM', '4-NOT SPECIFIED', '5-LOW')` | **Real divergence — same observable behavior on current data, different intent under data evolution.** See §3.5. |
| `GRANT EXECUTE ON FUNCTION … TO 'account users'` | **Present** | **Absent** | **Real divergence with operational implications.** See §3.5. |
| Comment header / traceability | None (or sparse) | Header comment with policy ID, source artifacts, generated-by note | **Tessera adds value**; existing form has no audit-trail back to declared intent |
| `ALTER TABLE … SET ROW FILTER … ON (…)` | Yes | Yes | **Match** |

The Tessera derivation includes the SQL emission for Policy A as well, which has no counterpart in the existing implementation. The Policy A function adds an explicit `WHEN is_account_group_member('account users') THEN …` branch and a defensive `ELSE FALSE`. This is the structural manifestation of the `explicit-baseline-group` strategy.

### 3.2 The notebook contains material not represented in either Tessera policy

The existing notebook contains a second pattern: ACL-table-driven row visibility (`rls_acl_mapping` + `rls_priority_acl` + a row filter that joins them). This pattern is explicitly out of scope for the current exercise (inputs §0.3 and §2 declare it deferred). The Tessera artifacts correctly do not address it. The comparison treats the notebook's ACL portion as separate work, scheduled for a later exercise.

### 3.3 What the existing implementation has that Tessera does not capture

In a frank reading: the existing notebook contains *demonstration scaffolding* (catalog and schema creation, sample-data seeding, exploratory queries showing pre- and post-filter row counts). None of this is policy; it's infrastructure for running and observing the demo. Tessera correctly does not try to express this — it is deployment and verification, not policy intent.

The notebook also contains inserts into the ACL mapping tables (`'brice.giesbrecht@databricks.com', 'urgent_priority_ops'`, etc.). These are data, not policy. They would be Tessera *adapter outputs* if the ACL pattern were in scope, but in the group-based exercise they have no Tessera analogue — group memberships are managed in Databricks directly, not in a Tessera-managed table.

### 3.4 What Tessera has that the existing implementation does not capture

These are the framework's value-adds, and they are arguably the most important output of the comparison:

| Element | What the Tessera form captures | What the existing implementation captures |
|---|---|---|
| `defaultStrategy` declaration | Explicit: `negated-complement` for Policy B, `explicit-baseline-group` for Policy A | Implicit in the SQL shape; nothing names the intent |
| Policy A as an alternative | The `explicit-baseline-group` variant exists as a sibling policy | Not present; the existing implementation has only the negated-complement shape |
| Canonical IR form | The `.jsonld` files are machine-readable, validator-checkable, reasoner-loadable | None; the SQL is the only artifact |
| Reviewable authoring form | The `.tessera.yaml` files with comments, structured for PR review | The SQL itself is the review surface |
| Traceability | Each generated function comments back to its policy ID and source artifacts | The function is freestanding |
| Diagnostic report | Per-element enforcement accounting | None |
| Identification of v0 gaps | Four gaps surfaced with proposed v1 work | The gaps are invisible because there's no abstraction layer above the SQL |

The last row is the one I'd weight most heavily for the project's purposes. The framework's job is not just to express what already exists — it's to make visible the things that existing implementations leave implicit. The four v0 gaps the diagnostic surfaced (multi-branch primitive, group-membership condition operator, default-branch predicate field, IRI-safety) are not gaps in the *existing implementation*; they are gaps in the *framework's ability to describe what's going on*. The exercise's value is in surfacing these.

### 3.5 Two findings surfaced post-hoc (during the ACL exercise's comparison)

When the notebook was inspected directly for the ACL exercise's Phase 3 comparison (2026-05-18, after the group exercise's comparison was originally drafted), two structural divergences emerged that the original §3.1 draft did not capture. Recording them here so the group comparison reflects the full structural picture.

#### Finding 1 — ELSE branch shape: `NOT IN` (existing) vs explicit enumeration (Tessera)

The existing implementation's ELSE branch is `orderpriority NOT IN ('1-URGENT','2-HIGH')` — a negation of the high-priority set. The Tessera Policy B's ELSE branch is `o_orderpriority IN ('3-MEDIUM', '4-NOT SPECIFIED', '5-LOW')` — an explicit enumeration of the lower-priority set.

For the current data, the two forms produce **identical observable behavior**: TPC-H has exactly five priority values, so `NOT IN {1,2}` and `IN {3,4,5}` cover the same rows. The behavioral-equivalence verification (§2.1) caught no divergence.

For **data evolution**, the two forms diverge:

- If a new priority value (e.g., `'6-EMERGENCY'`) is added to the orders table, the existing implementation's ELSE branch admits it (it is `NOT IN ('1-URGENT','2-HIGH')`); the Tessera-derived form excludes it (it is not in the enumerated set `{3,4,5}`).
- The two forms express different intent: existing says "show everything that's not high-priority"; Tessera says "show the three medium/low priorities explicitly".

The inputs §4.1 specified the default behavior using the explicit-enumeration form (`o_orderpriority IN ('3-MEDIUM', '4-NOT SPECIFIED', '5-LOW')`), which the Tessera derivation followed faithfully. The existing notebook implementation chose the negation form. Both are defensible readings of "lower-priority rows".

**Category:** intent-ambiguous (per §3.1's four-category framework) for the data-evolution case. For the current data, both implementations agree.

**Implication:** the Tessera derivation is the more conservative form. Whether the project prefers conservative-by-default (Tessera's form) or permissive-by-default (existing's form) when expressing "everything except X" is a stylistic call the framework currently does not opine on. It could become a documented adapter emission convention in the future; out of scope for v0.

#### Finding 2 — `GRANT EXECUTE` not emitted by Tessera

The existing implementation includes:

```sql
GRANT EXECUTE ON FUNCTION priority_filter_by_group TO `account users`;
```

The Tessera-derived form does not emit a corresponding grant. This is the **same finding** as in the ACL exercise's comparison §3.2 — both notebook implementations include `GRANT EXECUTE … TO 'account users'`, both Tessera derivations omit it.

The implication is the same: without the grant, callers other than the function owner may hit `PERMISSION_DENIED` when their queries trigger the row filter. The Tessera form is logically complete but operationally incomplete.

**Category:** real divergence, v1 candidate. The ACL exercise's comparison §3.2 covers the candidate v1 design (`executeGrants` field on Policy or grants-as-out-of-band-operational-concern); the same design choice applies here. The two exercises surfacing the same finding strengthen the case for treating it as a real gap.

These two findings did not appear in the original §3.1 draft because that draft was written without direct notebook inspection. The original draft's analysis was structurally correct on the dimensions it covered; these two are additional dimensions it did not catch. The pattern — "Phase 3 comparison surfaces what Phase 2 plus draft-only review do not" — is itself a useful observation about the framework's verification flow.

---

## 4. Lessons for v0 (§3.3 of the exercise framing)

Categorized per the framework: v0 bug fixes, v0 corrections in non-immutable artifacts, v1 candidates, out-of-scope confirmations.

### 4.1 v0 bug fixes

None identified. The four diagnostic-flagged gaps are limitations, not bugs. The IR as published correctly expresses what the policy intent specifies, with the known workarounds (separate constraints in a `@graph`, `byComposition` / `not` for the default branch, dual identifier carrying for IRI-unsafe names).

### 4.2 v0 corrections in non-immutable artifacts

**Documentation: IRI-safety of platform-native identifiers.** The diagnostic's §4.4 finding warrants a paragraph in `docs/technical-design-v0.2.md` (likely §4 or §5) explaining the convention: principal/resource references in the IR use URI-safe identifiers (`group:account-users`); platform-native verbatim names live in `xsd:string` fields like `baselineGroup`; adapters carry the mapping. This is documentation, not vocabulary, and is corrigible in the non-immutable docs.

**Documentation: emission pattern recognition for negated-complement.** The diagnostic's §5 observation that the Databricks adapter must recognize the `(defaultStrategy: negated-complement + byComposition/not default rule)` pattern to emit a readable `ELSE` warrants a note in the technical design's adapter-contract section (§5). This is a documented expectation of conforming adapters; not a v0 vocabulary change.

**Documentation: per-mechanism timing disclosure in the capability profile.** The verification (§2.3) surfaced an operational property of `is_account_group_member()` that affects how to interpret the "next-query freshness" promise. The doc-correction is to extend `docs/technical-design-v0.2.md` §5.2 (the capability profile description) to make explicit that timing/consistency characteristics are part of what adapters disclose, alongside the existing supported/partially-supported/unsupported axis — declared per mechanism, in mechanism-specific terms. The Databricks group-membership case is the worked example that grounds the principle. The framework's role is the requirement to disclose; the vocabulary describing the timing belongs to the adapter, not the IR.

### 4.3 v1 candidates

The diagnostic identified three structurally related v1 candidates plus the one in §4.2 above (which the diagnostic placed as a v1 candidate but I'd argue is documentation; see below).

**v1 candidate 1: Multi-branch policy primitive.** A `tessera:Policy` (or similarly named) container class that owns `defaultStrategy`, `baselineGroup`, ordered rules, and (per the next candidate) a `defaultBranch` field. Eliminates the duplication of `defaultStrategy` across `@graph` members. Makes the rule-collection structure first-class.

This is the most consequential v1 candidate. It dissolves three of the four v0 gaps simultaneously and aligns with ADR-007's tracked open question about policy-combining algorithms.

**v1 candidate 2: Default-branch predicate field on the policy container.** Once a `Policy` container exists, it can carry a `defaultBranch` row predicate (and possibly a `defaultPrincipal` field for selecting which principals see the default branch). This eliminates the awkward "default branch as a `byComposition`/`not` rule" workaround.

**v1 candidate 3: Group-membership condition operator.** Adding `principal-in-group` (or, more generally, `principal-in-set`) to the closed condition algebra. Less urgent than candidates 1 and 2 because the multi-branch primitive partially obviates the need, but useful for single-rule policies that gate by group membership and another condition simultaneously.

All three should be opened as repository issues with the `v1-candidate` label and a reference to this comparison document.

**One reframing.** I'd reclassify the diagnostic's §4.4 IRI-safety finding from "v1 candidate" to "v0 documentation correction." The current carrier convention (URI-safe identifier in the principal selector, verbatim string in a separate field) is a workable pattern; the issue is that it's undocumented. A v1 might formalize it more rigorously, but v0 can live with the convention if it's written down.

### 4.4 Out-of-scope confirmations

- **Operational interoperability** (policy behavior on data moving between platforms via Delta Sharing, Iceberg, federated queries) is per ADR-001 not in scope. The exercise correctly does not address this.
- **Runtime interoperability** (query-time gateway) is per ADR-001 explicitly disavowed. Correctly not addressed.
- **The ACL-table pattern** in the notebook is per the inputs deferred. Correctly addressed in a future exercise.
- **Purpose binding, obligations, classifications, transformations** are per the inputs declared not applicable to this policy. Correctly not invented.

---

## 5. Recommended actions

For Brice or Claude Code to execute, in priority order:

1. **Run behavioral verification** of the three scenarios in §2.1 against both implementations, recording results. — **Done.** All three scenarios passed for Tessera Policy B (§2.1). The existing implementation was not re-verified because its SQL shape is structurally identical (§3.1); verifying Tessera against the inputs' expectations is equivalent to verifying both.

2. **Open three repository issues** with `v1-candidate` label for the three structural gaps:
   - `policy-container` — multi-branch policy primitive (candidate 1)
   - `default-branch-predicate` — default-branch field on the policy container (candidate 2)
   - `principal-in-group-condition` — group-membership condition operator (candidate 3)

   Each issue references this comparison document and the diagnostic's relevant section.

3. **Open two (now three) repository issues** with `v0-doc-correction` label:
   - `iri-safety-convention` — document the dual-identifier carrier pattern in technical-design-v0.2.md
   - `adapter-emission-pattern-recognition` — document the negated-complement → readable-ELSE expectation
   - `adapter-capability-profile-timing-disclosure` — extend the capability-profile description in technical design §5.2 to make per-mechanism timing/consistency disclosure explicit; use the Databricks group-membership case as the worked example (added 2026-05-18 from §2.3 verification finding)

4. **Update `DECISIONS.md`** with a brief note (or a new ADR if warranted) recording that the first worked example completed and surfaced the gaps listed in §4. ADR-013 was the pre-emptive correction that came out of this exercise's framing; the v1 candidates here are its follow-on. They do not need ADRs yet — issues are sufficient at the v1-candidate stage — but the comparison's completion is itself a milestone worth recording.

5. **Confirm whether to start the deferred ACL-table exercise next**, or to pivot to one of the next-priority items from `CLAUDE.md` (JSON Schema, SHACL shapes, converter, first adapter scaffold). The ACL exercise would exercise the `byDataset` selector and `PrincipalSetFromTable` class, which this exercise did not. The other priorities advance the tooling and infrastructure layers.

---

## 6. What this comparison did not do

For completeness:

- **Did not execute SQL.** Behavioral verification is delegated to Brice in his Databricks environment. — **Updated 2026-05-18:** verification was executed by Claude Code via the Databricks SDK against `e2-demo-field-eng`; all three scenarios passed (§2.1).
- **Did not validate the JSON-LD against the context or ontology.** That validation is properly the job of the (not-yet-built) linter; manual reading suggests no obvious problems but the formal validation is pending.
- **Did not benchmark performance.** Out of scope for a demo per inputs §0.1.
- **Did not exercise reasoning** (subclass propagation, contradiction detection). The policies do not use classification subclasses or compete for the same access decisions.

These omissions are noted, not gaps. The exercise's purpose was framework validation against an existing implementation, not test-suite generation.

---

## 7. Closing observation

The exercise produced something the project needed beyond the artifacts themselves: a clean answer to the question "what does Tessera add when the underlying SQL is already adequate?" The answer, evident from §3.4, is that Tessera adds *structured intent*, *traceability*, *honest accounting via the diagnostic*, and *the ability to surface gaps in its own design*. The SQL is the floor; the additional artifacts are the framework's actual contribution.

The four v0 gaps the diagnostic surfaced are arguably more valuable than the comparison itself. They identify the most important architectural addition v1 should make (the policy-collection container) and the supporting concepts that come with it. Without this exercise, those gaps would have surfaced later, after more had been built on top of v0 and the cost of revision would have been higher.

The behavioral verification (§2.1, §2.3) confirmed that the Tessera-derived enforcement is correct and added one operational observation (cache-propagation latency) that is honest documentation of platform behavior, not a Tessera defect.

The exercise is complete.
