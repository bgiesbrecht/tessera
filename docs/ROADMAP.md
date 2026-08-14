# Tessera roadmap

**Purpose.** One place to see what is built, what is in flight, and what is deliberately deferred or out of scope. This document consolidates status that otherwise lives scattered across the README, per-feature scoping documents, and `docs/issue-drafts/README.md`.

**How to read it.** This is a *living* document, revised by appending dated updates rather than rewriting history (same discipline as the CLAUDE.md handoff). It is not a commitment schedule — ordering reflects current priority, not promised dates. The authoritative decision log remains `DECISIONS.md`; tracked work items remain the GitHub issues. Where an item has an issue or ADR, it is cited.

Current version: **0.11.0** (`VERSION`, `CHANGELOG.md`). Last roadmap update: **2026-08-14**.

---

## Shipped

The spine of the project is real and exercised end-to-end.

- **The v0 IR** — JSON-LD context, OWL ontology, JSON Schema, SHACL shapes — in `spec/v0/`. The immutability bar is suspended per ADR-017 until external dependency exists; additions land in v0, each as an ADR.
- **Both reference adapters** (Unity Catalog, Snowflake) run the full ADR-024 cycle — `emit` / `discover` / `extract` / `reconcile`. Three policy shapes across both platforms: `RowVisibilityConstraint` (`byIdentity`, `byScope`, `byDataset`), `ColumnVisibilityConstraint` (`Redact`), `AccessGrantConstraint` (table, function, schema fan-out). ABAC `byScope` (tag-driven) emits on both — UC via `MATCH COLUMNS has_tag_value(...)`, Snowflake via tag-based masking / row-access attachment (#31). Bidirectional Snowflake↔UC migration is demonstrated with behavioral-equivalence verification.
- **The converter** (`tools/converter/`) — YAML → JSON-LD, both authoring shapes.
- **The unified CLI** (`tools/cli/`, `python -m tools.cli`) — `validate`, `convert`, `emit`, `discover`, `extract`, `reconcile`, and `impact` / `lint` (change-impact analysis).
- **Change-impact analysis** (`tools/impact/`) — given a policy corpus and a proposed change, reports how the change alters what the corpus decides about data, *before* it is emitted. All planned checks are built: C1 (fall-through coverage), C2 (default-net removal), C3 (reachability/shadowing), C4 (cross-policy overlap, ADR-023), C5 (dangling reference), C6 (exposure polarity), plus standing lints L1 (dead rules) and L2 (cross-policy overlap). Reasons only about selector *expressions*, never populations (the ADR-001 line); findings are PROVEN or CANDIDATE. Design in [`docs/v1-candidates/change-impact-analysis.md`](v1-candidates/change-impact-analysis.md); worked demos in `docs/exercises/`.
- **AI-governance attribute axes** ([#25](https://github.com/bgiesbrecht/tessera/issues/25), ADR-029) — `trainingEligibility` / `automatedDecision` flat axes extending the ADR-018 framework. Advisory on their own (no platform enforces "no training"); they get teeth by composing with the access machinery — the worked example masks `NoTraining` columns to all but a consented group, emitting on both adapters unchanged.
- **Audit-logging obligation refinement** ([#19](https://github.com/bgiesbrecht/tessera/issues/19), ADR-030) — the `AuditLog` obligation gains `auditFields` / `auditSink` / `auditRetention`. Expression-first: on account-wide-audit platforms it's satisfied-by-assertion, so it's a portable, checkable requirement rather than a newly-enforced mechanism (adapter coverage-diagnostic is a follow-up).
- **Worked examples** (`spec/v0/examples/`) — Databricks, Snowflake, and cross-cutting, each with diagnostic/comparison records.

For a demo-ready tour, read [`docs/showcase.md`](showcase.md).

---

## Near-term (decided, not yet built)

Work that is scoped and committed in direction, awaiting implementation.

- **Converter v2 — comment preservation** (ADR-004). Round-trip YAML comment retention and `rdfs:comment` mapping. The converter is already comment-preservation-ready (ruamel round-trip parser); the feature is a follow-up, not a refactor.

---

## In-scope gaps — scoping needed

Governance needs Tessera should express but for which the IR shape is not yet designed. Each needs a scoping document and an ADR before implementation. **Scoping document:** [`docs/v1-candidates/governance-gaps-scoping.md`](v1-candidates/governance-gaps-scoping.md) covers all three — its through-line is that current platforms have thin/advisory native enforcement for these, so Tessera's value is portable expression + honest capability reporting. Two of the three (#25 AI axes, #19 audit) have shipped; #21 remains.

- **Retention and deletion** ([#21](https://github.com/bgiesbrecht/tessera/issues/21)). A `RetentionConstraint` policy kind — highest design risk: retention is lifecycle, not access, and enforcement is operational (a scheduled job), pressing on ADR-001. Scope framing is an open author decision (§6 of the scoping doc) — the one remaining gap of the three.

---

## IR refinements surfaced by worked examples

Smaller, well-characterized adjustments that real exercises exposed. Each is a bounded change to the IR or a convention.

- **Data-driven principal sets** — multi-table join support ([#7](https://github.com/bgiesbrecht/tessera/issues/7)), case-insensitive/trim match modifiers ([#8](https://github.com/bgiesbrecht/tessera/issues/8)), `existsInDataset` operand formalization ([#9](https://github.com/bgiesbrecht/tessera/issues/9)), ACL integrity checks ([#11](https://github.com/bgiesbrecht/tessera/issues/11), lower priority).
- **Two-axis attribute matching** ([#12](https://github.com/bgiesbrecht/tessera/issues/12)) — table-level + column-level attribute predicates in one policy.
- **`ResourceSetFromTable.resourceColumn` conflation** ([#13](https://github.com/bgiesbrecht/tessera/issues/13)) — one field carries two distinct identifiers (ACL column vs. protected-table column); split at v1.
- **Snowflake role-discrimination semantics** ([#14](https://github.com/bgiesbrecht/tessera/issues/14)) — primary vs. active role.
- **IRI-safety convention** ([#4](https://github.com/bgiesbrecht/tessera/issues/4)) — dual-identifier carrier for non-IRI-safe platform names (e.g. the `account users` group with a space).
- **Group-membership condition operator** ([#3](https://github.com/bgiesbrecht/tessera/issues/3)) — deferred; not needed yet.

---

## Integration questions

Open questions about how Tessera meets adjacent systems, not gaps in Tessera itself.

- **Consent-record integration** ([#24](https://github.com/bgiesbrecht/tessera/issues/24)). Consent is partially covered; how the IR references external consent records is undefined.
- **Cross-border transfer controls** ([#23](https://github.com/bgiesbrecht/tessera/issues/23)). Covered by the vocabulary but unexercised — needs a worked example to confirm the shape holds.

---

## Confirmed in scope, no action needed

Coverage checks from the 2026-05-19 governance-gap survey that the existing vocabulary already handles. Recorded so they are not re-litigated: fine-grained access control ([#16](https://github.com/bgiesbrecht/tessera/issues/16)), dynamic masking/redaction ([#17](https://github.com/bgiesbrecht/tessera/issues/17)), sensitive-data classification ([#18](https://github.com/bgiesbrecht/tessera/issues/18)), purpose limitation ([#22](https://github.com/bgiesbrecht/tessera/issues/22)).

---

## Out of scope

Deliberate non-goals. These are load-bearing to the project's posture (ADR-001, ADR-002); they are not deferred work.

- **Runtime policy evaluation / enforcement engine** (ADR-001). Tessera compiles to platform-native enforcement; it does not sit in the query path or decide access itself. This is the line the change-impact tool is careful to stay behind.
- **Data-lineage tracking** ([#20](https://github.com/bgiesbrecht/tessera/issues/20), confirmed out of scope per ADR-001).
- **A universal authorization language.** Scope is data-platform governance specifically.
- **Operational interoperability** (policy behavior on data physically moving between platforms via Delta Sharing / Iceberg). Reserved space, not v0.
- **The DSL** (ADR-006). Deferred until the IR stabilizes through more corpus exposure. YAML remains the authoring form.
- **Displacing Unity Catalog inside Databricks** (ADR-002). UC is the source of truth for governance *inside* Databricks; Tessera operates *between* governance estates. This concession is irreducible.

---

## Larger horizon

Directions that are real but not yet scoped, recorded so the shape of the project stays visible.

- **A third adapter — the custom ACL-table pattern** (`adapters/custom-acl/`). The reference real-world engagement that drove the adapter-first architecture (ADR-003). Building it is the strongest test of whether the peer-adapter design is real.
- **Sharing / distribution constraints.** Reserved space for the `DistributionConstraint` shape; scoping sketch in `docs/v1-candidates/sharing-and-distribution-constraint.md`.
- **A standing corpus-health mode.** The `--lint` checks (L1, L2) are the seed of a broader "audit my whole policy corpus" capability separate from change-diffing.

---

## Revision log

- **2026-08-04** — Initial roadmap. Consolidated scattered status; recorded change-impact tool as fully shipped (C1–C6, L1/L2) and the decision to fold `impact`/`lint` into the `tessera` CLI.
- **2026-08-04** — `impact` / `lint` wired into the `tessera` CLI (`tessera impact`, `tessera lint`); the standalone `python -m tools.impact` entry point remains. Added the [Analyzing changes](user-guide/analyzing-changes.md) user-guide page.
- **2026-08-05** — Correction: UC ABAC `byScope` column-mask emission ([#30](https://github.com/bgiesbrecht/tessera/issues/30)) was listed as near-term but shipped in 0.6.3; moved out of near-term. (The initial roadmap propagated a stale status from the issue-drafts log.) Added `OUTPUT-REFERENCE.md` to the generated demos.
- **2026-08-05** — ADR-028: attribute values are vocabulary IRIs (bare = Tessera, prefix = adopter); 0.8.0.
- **2026-08-13** — Snowflake ABAC `byScope` emission (row + column) shipped ([#31](https://github.com/bgiesbrecht/tessera/issues/31)); 0.9.0. Both adapters now emit ABAC `byScope`. Moved out of near-term.
- **2026-08-13** — Live-verified the Snowflake ABAC `byScope` emission end-to-end on a real account; 0.9.1. Fixed the row-filter `ON` clause (must name the real discriminator column) and recorded the column-tag-vs-table-tag distinction. Both paths enforce as designed.
- **2026-08-13** — Scoping doc for the three governance gaps (#19/#21/#25) drafted; then #25 (AI-governance axes) implemented (ADR-029, 0.10.0) — `trainingEligibility` / `automatedDecision`, with a worked example that composes with the column-mask machinery. #19 and #21 remain scoped-not-built (#21 pending the author's scope-framing decision).
- **2026-08-14** — #19 (audit-logging obligation refinement) implemented (ADR-030, 0.11.0) — `auditFields` / `auditSink` / `auditRetention` on the `AuditLog` obligation, expression-first, with a worked example. Only #21 (retention) of the three remains, pending its scope-framing decision.
