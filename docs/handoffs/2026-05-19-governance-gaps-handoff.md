# Handoff — Governance Gap Issues (Top 10 Survey)

**For:** Claude Code (in-repo implementor).
**From:** claude.ai (design partner). Survey conducted 2026-05-19 across external sources on common data governance requirements.
**Status:** Filed as issues #16–#25 on 2026-05-19.

---

## Purpose

The claude.ai conversation surveyed external sources on common data governance requirements and produced a top-10 list. Three real gaps in Tessera's current model were identified (audit logging refinement, retention/deletion, AI-specific governance). Several other needs are covered, underexercised, or explicitly out of scope. Filing all ten as issues — including the covered ones — gives future contributors a complete tracking surface and makes it visible which concerns the project considered and how it dispositioned them.

The handoff's value proposition:

- **Covered items** (issues #16/#17/#18/#22) — filed so a future contributor searching "data masking" or "purpose limitation" finds an issue explaining what's covered, not silence.
- **Out-of-scope items** (issue #20) — filed deliberately. A future proposal to add lineage tracking gets redirected to the issue rather than re-litigated in conversation.
- **Underexercised items** (issue #23) — covered in design but not yet validated by a worked exercise. Candidate for a future exercise.
- **Integration questions** (issue #24) — partially covered; the remaining question is per-environment configuration.
- **Real gaps** (issues #19, #21, #25) — these get Phase 2 scoping documents.

---

## Numbering reconciliation

The original claude.ai handoff numbered the issues #12–#21 (sequential after the prior #11). At filing time the issue counter had advanced (the table-grants exercise filed #15 and adjacent governance-gap work filed earlier issues), so the ten governance issues landed as **#16–#25**.

Original-to-actual mapping for traceability:

| claude.ai original | Actual filed |
|---|---|
| #12 fine-grained access | [#16](https://github.com/bgiesbrecht/tessera/issues/16) |
| #13 dynamic masking | [#17](https://github.com/bgiesbrecht/tessera/issues/17) |
| #14 sensitive data classification | [#18](https://github.com/bgiesbrecht/tessera/issues/18) |
| #15 audit logging | [#19](https://github.com/bgiesbrecht/tessera/issues/19) |
| #16 lineage (out-of-scope) | [#20](https://github.com/bgiesbrecht/tessera/issues/20) |
| #17 retention | [#21](https://github.com/bgiesbrecht/tessera/issues/21) |
| #18 purpose limitation | [#22](https://github.com/bgiesbrecht/tessera/issues/22) |
| #19 cross-border | [#23](https://github.com/bgiesbrecht/tessera/issues/23) |
| #20 consent management | [#24](https://github.com/bgiesbrecht/tessera/issues/24) |
| #21 AI governance | [#25](https://github.com/bgiesbrecht/tessera/issues/25) |

Internal cross-references in the AI-governance issue body (#25) were updated to point at the actual retention issue number (#21, not #17).

---

## Labels

Eight labels were created on the repo to support this taxonomy. They are now part of the project's label vocabulary and apply to future governance-related issues:

| Label | Color | Description |
|---|---|---|
| `governance-need` | blue | Documents a governance requirement from the top-10 survey |
| `coverage-confirmed` | green | Tessera already covers this; issue tracks visibility of the coverage |
| `in-scope-gap` | orange | Tessera should cover this but doesn't yet |
| `out-of-scope` | light blue | Explicitly not Tessera's responsibility per ADR-001 or similar |
| `underexercised` | yellow | Covered in design but no worked exercise has validated it |
| `integration-question` | purple | Depends on integration with external systems |
| `scoping-needed` | pale yellow | Phase 2 of the gap-handling plan will produce a scoping document |
| `v0-candidate` | light blue | Addition under consideration for v0 (immutability bar still suspended per ADR-017) |

---

## The ten dispositions, summary table

| # | Title | Disposition | Scoping doc? |
|---|---|---|---|
| 16 | Fine-grained access control | Covered (multi-exercise) | — |
| 17 | Dynamic data masking | Covered (ADR-016 + ADR-022) | — |
| 18 | Sensitive data classification | Covered (ADR-018) | — |
| 19 | Audit logging obligation vocabulary | In-scope gap | yes (Phase 2) |
| 20 | Data lineage tracking | Out of scope per ADR-001 | no |
| 21 | Retention and deletion | In-scope gap (v0 candidate; likely most urgent) | yes (Phase 2) |
| 22 | Purpose limitation | Covered (`purpose-in` condition) | — |
| 23 | Cross-border data transfer | Covered, underexercised | future exercise |
| 24 | Consent management | Partial / integration question | later |
| 25 | AI governance (training-eligibility, ADM) | In-scope gap (v0 candidate) | yes (Phase 2) |

---

## Phase 2 scope

The claude.ai assistant will draft scoping documents for **#19 (audit logging)**, **#21 (retention)**, and **#25 (AI governance)** in subsequent handoffs. The scoping documents follow the structure of `docs/v1-candidates/abac-and-attribute-axes.md` — i.e., they articulate the design surface without committing to spec changes; ADRs and spec implementations come after scoping conversations settle.

claude.ai's priority hint: retention (#21) is the most urgent of the three real gaps given universal regulatory citations (GDPR Article 5(1)(e), CCPA, HIPAA). AI governance (#25) is slightly lower priority because the regulatory landscape is still evolving. Audit logging (#19) sits in between — universally required but architecturally straightforward as an obligation-vocabulary refinement.

Brice (project lead) will signal before any scoping documents land. The signal may include a preferred order, a request to combine some, or a request to start with one.

---

## What this handoff does not include

- **No spec changes.** All issues are tracking-only.
- **No new ADRs.** Decisions to address the gaps come after scoping documents settle.
- **No worked exercises.** Exercises driven by these issues come later in the cycle.
- **No CLAUDE.md edits beyond the issue-count update.** Substantive framing changes wait until scoping documents are reviewed.

The issues create the tracking surface. Subsequent handoffs build on it.
