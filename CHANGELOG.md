# Changelog

All notable changes to Tessera are recorded here. Versioning follows the spec's evolution: the major version stays at `0` while the IR is pre-immutability (ADR-017's suspended-immutability framing applies until external dependency exists). Minor-version bumps correspond to one or more ADRs landing alongside meaningful artifact additions.

The format draws on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project additionally references ADRs (in `DECISIONS.md`) for every change of substance.

## [0.2.0] — 2026-05-19

Substantial inflection: spec v0 reaches feature-complete-for-the-current-evidence-corpus, first adapter scaffolds land for two platforms simultaneously, first cross-platform live exercises run end to end, full user documentation lands. The morning's `e8a1422` "Checkpoint" commit was the previous state; everything below is what was added on top.

### Added

**Spec.**
- `spec/v0/shapes.ttl` — SHACL shapes for semantic validation. All eight worked-example JSON-LDs validate; seven negative tests catch unknown policyKind / action / selector / effect / defaultStrategy / condition op / canonical-axis IRI.
- `Execute` well-known action — across `ontology.ttl`, `context.jsonld`, `schema.json`, `shapes.ttl`. Semantic-only scope (gating who can invoke business-logic resources); platform-mechanism EXECUTE uses remain adapter scaffolding. (ADR-025)
- Stage 4 ABAC vocabulary in `spec/v0/ontology.ttl`, `context.jsonld`, `schema.json` — implements ADRs 018–021. `tessera:AttributeAxis` class; four well-known axes (`sensitivityAxis` hierarchical; `dataSubjectAxis`, `regulatoryRegimeAxis`, `businessDomainAxis` flat); `byScope` selector with `scope` / `except` / `matching` properties; `AttributeMatcher` class.

**Adapters.**
- `adapters/contract/` — `Adapter` ABC, `CapabilityProfile` (closed `Capability` enum), `AdapterConfig` (with `identity_bindings`, `resource_bindings`, `tag_taxonomy`, `extras`), structured Result types (`EmissionResult`, `DiscoveryResult`, `ExtractionResult`, `ReconciliationResult`), `Diagnostic` with severity / code / message / location. (ADR-024)
- `adapters/unity_catalog/` — Databricks adapter scaffold; emission live for group-driven row visibility via `is_account_group_member` + `SET ROW FILTER`.
- `adapters/snowflake/` — Snowflake adapter scaffold; emission live for `byIdentity` row visibility (via `IS_ROLE_IN_SESSION` + `ADD ROW ACCESS POLICY`) and for `byDataset` row visibility (via `EXISTS(...)` against ACL mapping tables, gating on `CURRENT_USER()`).
- `adapters/tests/test_parity.py` — same IR → both adapters → meaningfully different SQL; structural fixture for the contract.
- `adapters/tests/live_databricks.py`, `live_snowflake.py`, `live_snowflake_bydataset.py` — runnable cross-platform live exercises.
- `adapters/tests/setup_table_grants.py` — idempotent workspace provisioner for the table-grants exercise.

**Worked exercises (eight total, three added in this version).**
- **Cross-platform live emission** — same IR (`group-row-visibility-policy-a`) lowered through both adapters; both row filters enforce correctly on Databricks (7.5M rows) and Snowflake (1.5M rows). Drove `AdapterConfig.resource_bindings` and the empirical reframing of Snowflake secondary-roles behavior.
- **Snowflake `byDataset` row visibility** — `BRICETEST.TESSERA.SNOW_ORDERS_RLS_ACL`; four scenarios pass including secondary-roles immunity (`USE SECONDARY ROLES NONE` and `ALL` produce identical row counts because `CURRENT_USER()` ignores role activation). Surfaced one v1 candidate (#13).
- **Table-grants RBAC** — three scenarios (single-table read, schema-level read with propagation, function execute). Drove ADR-025 (`Execute`) and surfaced #15 (`AccessGrantConstraint` candidate). Closed #10 (policy-execute-grants).

Previously committed exercise artifacts (group, ACL, column-mask, ABAC column-mask, ABAC row-filter) now live in `spec/v0/examples/` alongside the new ones.

**Documentation.**
- `docs/user-guide/` — six-page user documentation: README (audience routing), tutorial (end-to-end walkthrough), authoring (vocabulary reference + Snowflake byDataset recommendation), operating (adapter config + per-platform checklists), evaluating (scope, non-goals, decision framework), contributing (ADR discipline, adapter extension, exercise methodology).
- `docs/handoffs/2026-05-19-claude-ai-update.md` — synchronization point for the design-partner / implementor collaboration.
- `docs/exercises/` — Phase 1 inputs for the worked exercises (group, ACL, column-mask, ABAC column-mask, ABAC row-filter, Snowflake byDataset, table-grants).
- `docs/v1-candidates/abac-and-attribute-axes.md` — ABAC scoping document that drove ADRs 018–021.

### Changed

- **ADR-024 postscript reframed** the Snowflake secondary-roles finding as an adapter emission choice (Intent A vs Intent B for role discrimination) rather than a platform "gotcha." Initial framing conflated policy intent ambiguity with platform configuration assumption; corrected after claude.ai design-review. Three artifacts re-framed accordingly: `adapters/snowflake/capability.py` ROW_VISIBILITY entry, ADR-024 postscript finding #3, `docs/user-guide/operating.md` § Role-discrimination semantics.
- **`AdapterConfig.resource_bindings` field added** during the first cross-platform live exercise. Mirrors `identity_bindings` for resources; the same IR target can lower to different platform identifiers per environment.
- **CLAUDE.md state refresh** — eight exercises listed; ADRs 017–025 noted; adapter section updated to "complete (scaffold)"; spec section updated to "post-Stage-4."
- **Snowflake capability profile rationale** — sharpened with the role-discrimination-semantics distinction, with empirical verification of the `DEFAULT_SECONDARY_ROLES` finding (user property, not session parameter).
- **Technical design v0.2** — §3.3 / §3.3a / §4.9 / §4.10 / §5.6 / §5.7 added/updated for ABAC vocabulary, Mechanism A vs B observation, adapter configuration mapping pattern, cross-policy conflict detection.

### Fixed

- **ADR-022** corrected ADR-016's over-tight transformation constraint: `transformation` is required iff `effect: transform`, not for all `ColumnVisibilityConstraint` rules. Effect-driven, not policy-kind-driven.

### ADRs landed in this version

- **ADR-017** — Immutability bar suspended until external dependency exists (supersedes ADR-014's date-based framing).
- **ADR-018** — `AttributeAxis` and the Classification refactor.
- **ADR-019** — Scoped policy attachment via `byScope`.
- **ADR-020** — Composable attribute matching reuses `byComposition`.
- **ADR-021** — Adapter configuration mapping pattern.
- **ADR-022** — Transformation constraint is effect-driven.
- **ADR-023** — Cross-policy combination resolution: γ-with-refinement.
- **ADR-024** — Adapter contract shape, plus postscript with live-cross-platform findings and the refined role-discrimination framing.
- **ADR-025** — `Execute` action added to v0 with semantic-vs-mechanism boundary.

### Issue tracker activity

- **Closed**: [#10](https://github.com/bgiesbrecht/tessera/issues/10) (policy-execute-grants, closed by ADR-025).
- **Filed**: [#12](https://github.com/bgiesbrecht/tessera/issues/12) (policy-two-axis-attribute-matching), [#13](https://github.com/bgiesbrecht/tessera/issues/13) (resourcecolumn-conflation), [#14](https://github.com/bgiesbrecht/tessera/issues/14) (snowflake-role-discrimination-semantics), [#15](https://github.com/bgiesbrecht/tessera/issues/15) (access-grant-constraint-policykind).
- **Open at version close**: #3, #4, #5, #7, #8, #9, #11, #12, #13, #14, #15.

---

## [0.1.x] — prior to 2026-05-19

Pre-versioning era. Captured here as a single block by reference; the detailed history is in the commit log up to and including `e8a1422` ("Checkpoint"). Key milestones from that period:

- Repository established; canonical name and license decisions (ADRs).
- v0 spec drafted: `spec/v0/ontology.ttl`, `spec/v0/context.jsonld`, `spec/v0/schema.json`.
- First three worked exercises completed (group row-visibility A/B, ACL row-visibility, column-mask on `o_clerk`).
- ADRs 001–016 landed: project framing and posture, three-form IR shape (YAML / JSON-LD / DSL), adapter-first architecture, ODRL/DPV alignment, deferred DSL, well-known IRI conventions, policy container (ADR-014), ordered first-match (ADR-015), transformation parameterization (ADR-016).
- ABAC scoping document drafted (`docs/v1-candidates/abac-and-attribute-axes.md`); two additional ABAC worked exercises ran.

For the per-commit narrative of this period, see `git log --oneline` from the initial commit through `e8a1422`.
