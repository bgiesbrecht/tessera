# Tessera Worked Example — ACL Pattern Validation

**For:** Claude Code, working in the `bgiesbrecht/tessera` repository.
**Prerequisite reading:** `CLAUDE.md`, then `DECISIONS.md`. Do not start until both are read.
**Purpose:** Use the Tessera v0 specification to express a real, existing policy pattern. Produce Tessera artifacts (YAML and JSON-LD) and a translation back to platform-native enforcement. Then compare the result to the existing working implementation, which will be provided only after the Tessera artifacts are complete.

---

## Why this exercise matters

Brice has an existing, working implementation of an ACL-driven row-visibility pattern on Snowflake. The functions, views, and supporting structures all exist and have been validated against real data. That implementation was written directly, without Tessera.

The question this exercise answers is: **does the Tessera framework, starting only from the spec, arrive at something behaviorally equivalent to what was built directly?**

If the answer is yes, the spec earns confidence as a real abstraction over the problem. If the answer is no — if Tessera can't express something the direct implementation captures, or if the derived implementation has a subtly different behavior — that finding is more valuable than the artifact, because it tells us where the spec needs revision before more is built on top of it.

This is the kind of test that the technical design (§3 of `docs/technical-design-v0.2.md`) describes as the criterion for whether the IR design holds: *does this still work for the ACL-table customer?* The answer up to now has been "we think so." This exercise produces evidence.

---

## How this exercise is structured

The exercise runs in three phases. Each phase is gated: do not begin a phase until the prior phase is complete and reviewed.

**Phase 1 — Inputs only.** Brice provides the inputs that describe the policy intent and the structural facts (the ACL table schema, the protected tables, the principal model, the obligations needed). Claude Code does not see the existing implementation.

**Phase 2 — Tessera derivation.** Claude Code produces, from the spec alone:
- A YAML authoring-form policy file expressing the intent.
- The corresponding JSON-LD canonical form.
- A first-cut translation to Snowflake-native enforcement, as the Tessera-derived adapter would emit.
- A diagnostic report explaining what is enforced, what is approximated, and what cannot be expressed.

**Phase 3 — Comparison.** Brice provides the existing implementation. Claude Code and Brice together compare the two implementations against criteria stated in advance (see §6). Findings are categorized and either fed back into v0 corrections or recorded as v1 considerations.

The phasing is non-negotiable. The exercise's value depends on Phase 2 happening without sight of the answer.

---

## Phase 1 — The inputs

The following will be provided by Brice as a separate brief at the start of the exercise. The structure of that brief should follow the categories below; Claude Code may request clarifications but should not request the existing implementation.

### 1.1 The protected resource

- The fully qualified name of the table or tables under row-visibility control.
- The columns of interest (those involved in policy decisions, plus the row-key columns).
- Any relevant classifications already applied to the resource — if it's tagged PII, Financial, etc.

### 1.2 The ACL table

- The fully qualified name of the ACL table.
- Schema of the ACL table: column names and types.
- Which column identifies the principal (and how — by username, email, group ID).
- Which column identifies the resource (and how — by FQN, by ID, by some indirection).
- Which column carries the permission (and what values are used: 'read', 'select', 'view', etc.).
- Any other columns that affect the policy (effective dates, conditions, tenant IDs).

### 1.3 The principal model

- How principals are identified at session time in Snowflake (current_user, current_role, session tag).
- How the ACL's principal column matches against the session identity (direct match, lookup, group expansion).
- Any role hierarchy or group inheritance that matters.

### 1.4 The policy intent

- In plain English, what the policy is supposed to do.
- What should happen for a principal with an ACL entry.
- What should happen for a principal without an ACL entry.
- Whether there are exceptional principals (admins, break-glass roles).
- Any purpose binding ("for analytics use only," "for fraud investigation").
- Any obligations (audit log, notification, watermark).

### 1.5 Edge cases the implementation handles

This is where the most useful information lives. Brice should describe, without showing the code, what edge cases the existing implementation handles. Examples of the kinds of questions to ask:

- What happens when the ACL table has duplicate entries for the same principal-resource pair?
- What happens when a principal's group membership changes mid-session?
- What happens for queries that join the protected table with other tables?
- What happens when the ACL table itself is unavailable?
- How is the policy applied to views over the protected table?
- What happens for service accounts vs. human users?

The answers to these tell Claude Code what the policy actually requires, which is often broader than the headline intent.

### 1.6 Non-functional requirements

- Performance constraints (is the policy on a hot path? what query latency must be preserved?).
- Auditability requirements (what must be logged and to where).
- Operational constraints (can the policy be updated without downtime? are there change-control requirements?).

---

## Phase 2 — The Tessera derivation

Claude Code produces four artifacts in this phase, in roughly the following order. Each is a deliberate exercise of a specific part of the spec.

### 2.1 The YAML policy file

Location: `spec/v0/examples/acl-driven-row-visibility.tessera.yaml`

Express the policy in the YAML authoring form, conforming to the IR structure described in §4 of `docs/technical-design-v0.2.md`. Key decisions and constraints:

- **Use the `byDataset` selector** for the principal set. This is the v0 pattern for data-driven principal sets (ADR-003) and is what the ACL pattern requires. Reference the `PrincipalSetFromTable` class from the ontology.
- **Use classification selectors where possible** for resource selection, not enumeration. If the protected table has a classification, the policy should reference it by classification, not by name. If the input does not give a classification, propose one and note it as part of the output.
- **Capture purpose binding via the condition algebra** if the input specifies purpose constraints. Use `purposeIn` from the closed condition algebra (§4.4 of the technical design). Do not invent new operators.
- **Capture obligations explicitly.** Audit-log, notify, watermark — use the obligation classes from the ontology (`tessera:AuditLog`, `tessera:Notify`, `tessera:Watermark`).
- **Include comments.** This is the use case for YAML being the authoring form. Comments explaining business rationale, regulatory tracing, edge-case handling.
- **Include provenance metadata** even though the policy is being authored rather than extracted. Author, date, source-of-truth indication, version.
- **Reference the published context URL.** `@context: https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld`.

Edge cases discovered during Phase 1 should each correspond to an explicit element in the policy file. If an edge case cannot be expressed within v0 of the spec, do not paper over it — surface it explicitly (see §2.4 below).

### 2.2 The JSON-LD canonical form

Location: `spec/v0/examples/acl-driven-row-visibility.jsonld`

Produce the canonical JSON-LD form of the same policy. Per ADR-004:

- `@`-prefixed keys.
- `@context` referenced by URL, not inlined.
- CURIE-style identifiers (`tessera:PII`, `dpv:Analytics`) resolved against the context.
- Comments dropped or, where attached to a node, mapped to `rdfs:comment`.
- Structure equivalent to the YAML; the JSON-LD is what adapters and reasoners consume.

The JSON-LD form should be machine-verifiable against the published context and ontology. If a Python or Node toolchain is available in the working environment, validate by loading the JSON-LD in an RDF library (`rdflib` for Python, `jsonld.js` for Node) and confirming that the document parses cleanly and references resolve.

### 2.3 The Snowflake-native translation

Location: `spec/v0/examples/acl-driven-row-visibility.snowflake.sql`

Produce the SQL that a Tessera-derived Snowflake adapter would emit for this policy. This is the most important output of the exercise because it's what will be compared against the existing implementation.

Approach this as if writing the adapter for the first time. The Tessera spec tells you:

- The policy is a `RowVisibilityConstraint` (technical design §3.2). This maps to Snowflake's row access policy mechanism.
- The principal selector is `byDataset` referencing the ACL table. The Snowflake row access policy body must join against the ACL table at evaluation time.
- The condition algebra includes `purposeIn` — Snowflake supports session tags via `ALTER SESSION SET TAG`, which can be read in policy bodies. This is how purpose binding gets enforced.
- Obligations: `AuditLog` maps to Snowflake's Access History plus an event table; `Notify` requires external integration and may not be fully enforceable in pure Snowflake DDL.

The output should include:

- The `CREATE ROW ACCESS POLICY` statement, complete and well-commented.
- The `ALTER TABLE ... ADD ROW ACCESS POLICY` statement.
- Any supporting DDL (functions, secure views) that the policy depends on.
- Comments at the top of each generated artifact tracing back to the policy ID and Tessera version (e.g., `-- Generated from policy:acl-driven-row-visibility v0.1.0 via Tessera v0`).

Use deterministic naming: `tessera__acl_driven_row_visibility__row_access_policy` or similar, so re-runs are idempotent.

### 2.4 The diagnostic report

Location: `spec/v0/examples/acl-driven-row-visibility.diagnostic.md`

Per §5.3 of the technical design, every emission produces a diagnostic report. Even for a hand-derived example, produce this report explicitly. It is one of the most valuable artifacts of the exercise because it forces honest accounting of what the framework can and cannot do.

The report should categorize each element of the policy:

- **Fully enforced.** The native SQL enforces this exactly.
- **Partially enforced.** The native SQL enforces this with a stated limitation. Name the limitation precisely.
- **Unenforced.** The framework cannot express this on Snowflake; describe what is missing and recommend a compensating control or a future spec extension.

Specifically, the report should address:

- Whether each edge case from Phase 1 §1.5 is handled. For each, state which category above it falls into.
- Whether each obligation is enforced, approximated, or surfaced as a manual control.
- Whether purpose binding is enforced by the platform or relies on the application setting session tags correctly.
- Whether the ACL table being unavailable causes the policy to fail-closed (deny) or fail-open (allow) — and whether that matches the intent.

This report is not a sales document. It is honest accounting. If the framework cannot enforce something, that is acceptable — but it must be visible.

---

## Phase 3 — Comparison

After Phase 2 is complete and the Tessera-derived artifacts are committed (in a branch or as a draft PR), Brice provides the existing implementation. The comparison phase produces a final artifact:

Location: `spec/v0/examples/acl-driven-row-visibility.comparison.md`

The comparison addresses the following dimensions explicitly:

### 3.1 Behavioral equivalence

Do the two implementations produce the same observable behavior? For a set of test cases (drawn from Phase 1 §1.5 plus any additional ones that surface), what rows does each implementation expose to which principals?

If both implementations agree on every test case, the Tessera derivation is *behaviorally equivalent* to the direct implementation. This is the strongest possible result and is the criterion the project actually cares about.

If they disagree, the disagreements are categorized:

- **Tessera derivation is wrong.** The Tessera derivation has a bug or the spec was misapplied. Fix the derivation.
- **Existing implementation is wrong.** The existing implementation has a behavior the policy intent did not require, or has a bug. Note for future remediation but does not affect the Tessera assessment.
- **Spec is wrong.** The Tessera derivation faithfully implemented the spec but the spec produces a behavior different from the existing implementation, and the existing implementation is the intended behavior. This is the finding that drives spec revision.
- **Intent was ambiguous.** The two implementations made different reasonable choices when the policy intent could be read multiple ways. This drives spec clarification or a more rigorous intent capture.

### 3.2 Structural comparison

Even where behavior agrees, the implementations may differ structurally. Compare:

- How is the ACL join expressed? (Subquery in the policy body, function call, secure view?)
- How is purpose binding handled? (Session tag, context function, parameter?)
- How are obligations emitted? (Inline logging, separate audit infrastructure, event hooks?)
- How is naming managed? (Deterministic, hand-named, prefixed?)

Structural differences are not necessarily bugs. The interesting cases are where the existing implementation does something the Tessera derivation does not — those are candidates for either spec extensions or for the existing implementation being more specific to its environment than the spec needs to be.

### 3.3 Lessons for v0

The comparison concludes with a categorized list of findings:

- **v0 bug fixes.** Things the spec gets wrong and must fix in v0. These are rare and serious — v0 is supposed to be immutable per ADR-004, so anything fixed here is a "we caught it before publication" correction.
- **v0 corrections in non-immutable artifacts.** Things the technical design, README, or other documents get wrong and can update freely.
- **v1 candidates.** Things v0 cannot express that v1 should consider. Track these as open issues, not commitments.
- **Out-of-scope.** Things the existing implementation does that Tessera deliberately does not address (e.g., runtime concerns per ADR-001). Confirm these are out of scope rather than gaps.

### 3.4 What to do with the findings

For each finding, propose an action and an owner:

- v0 bug fixes → fix in this branch, ADR if a decision changes.
- Documentation corrections → fix in the same branch as the example.
- v1 candidates → open issues on the repository with the `v1-candidate` label.
- Out-of-scope confirmations → note in the comparison document itself.

---

## What good output looks like

The exercise succeeds if:

1. The Phase 2 artifacts exist, are well-commented, and reference each other correctly.
2. The JSON-LD parses cleanly and validates against the context and ontology.
3. The Snowflake translation is plausibly correct as a first cut.
4. The diagnostic report is honest about gaps, including ones that may be politically uncomfortable to admit.
5. The Phase 3 comparison categorizes findings without flinching.
6. The lessons feed into either v0 corrections, v1 issues, or confirmed out-of-scope items — none are silently lost.

The exercise fails if:

- The Phase 2 derivation requires inputs Phase 1 did not specify, and those inputs come from inferring what the existing implementation must have done.
- The diagnostic report claims everything is fully enforced when something isn't.
- The comparison concludes the implementations agree without producing the test-case evidence.
- Findings are noted in chat but not converted to issues or commits.

---

## Sequencing and timing expectations

This is intended as a focused exercise, not an open-ended project. A reasonable timeline:

- Phase 1 inputs: Brice prepares and shares; ~1 hour of his time to write up.
- Phase 2 derivation: Claude Code working through the four artifacts; expect 2–4 hours of focused work, possibly with clarification questions interleaved.
- Phase 3 comparison: Brice shares the existing implementation; Claude Code produces the comparison; expect 1–2 hours.

If Phase 2 is taking substantially longer than this, the spec may be the problem rather than the work — surface the friction explicitly.

---

## Things to be careful about

- **Do not invent vocabulary terms.** If a needed term is not in the published ontology or context, surface the gap; do not silently add a term. New vocabulary is a v1 candidate or an ADR proposal.
- **Do not centralize evaluation in tooling.** The Snowflake translation must be SQL that Snowflake itself evaluates. Tessera does not run policy logic at query time.
- **Do not assume the existing implementation is correct.** Phase 3 is comparison, not deference. If the existing implementation has a bug or a behavior the policy intent did not require, note it.
- **Do not edit `spec/v0/` files** other than to add the new `examples/` directory. The vocabulary, context, and ontology are immutable. If the exercise reveals they should change, that's a finding, not an action.
- **Do not soften the diagnostic report.** Its value is in its honesty.

---

## After this exercise

Regardless of outcome, the artifacts produced become test fixtures for the rest of the project. The YAML/JSON-LD pair is what the converter (Priority 5 in the handoff) gets validated against. The Snowflake SQL is what the Snowflake adapter (Priority 6) is initially expected to emit. The diagnostic report shape becomes the template for the actual adapter's diagnostic output.

So even if the exercise reveals problems, the artifacts are not throwaway — they're the seed corpus the next phase of work builds on.

If the exercise reveals significant problems with v0, the right response is to halt subsequent work, fix what needs fixing, and re-run the exercise against the corrected spec. The project's value depends on the spec being honest about what it can do, and that honesty starts with this exercise.
