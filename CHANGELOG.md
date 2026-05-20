# Changelog

All notable changes to Tessera are recorded here. Versioning follows the spec's evolution: the major version stays at `0` while the IR is pre-immutability (ADR-017's suspended-immutability framing applies until external dependency exists). Minor-version bumps correspond to one or more ADRs landing alongside meaningful artifact additions.

The format draws on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project additionally references ADRs (in `DECISIONS.md`) for every change of substance.

## [0.3.0] — 2026-05-20

Five-commit increment on top of 0.2.0. New tool (YAML → JSON-LD converter), three new adapter emission paths (UC column visibility, UC ABAC byScope row visibility, Snowflake column visibility), new practitioner-shaped tutorial, new W3C-savvy overview, 10 new tracked issues from the governance-gap survey, and the worked-example corpus regenerated with YAML as canonical source.

### Added

**Tools.**
- `tools/converter/` — Python YAML → JSON-LD converter. v1 accepts both envelope-form (`policy: { id, kind, … }`) and flat-form YAML. Mechanical mapping (envelope unwrap, `id → @id` with `policy:` prefix, `kind → policyKind`, context-aware `type → @type`, canonical `@context` injection, trailing-whitespace normalization). CLI: `python -m tools.converter <file> [--out path]`. Library: `tools.converter.yaml_to_jsonld(path)` / `yaml_to_jsonld_str(text)` / `convert_file(in, out)`. Uses `ruamel.yaml` from the start so comment preservation (deferred to v2) is a one-step addition. Regression test covers all 11 worked-example YAMLs.

**Adapter coverage.**
- UC `ColumnVisibilityConstraint` emission — `CREATE OR REPLACE FUNCTION` returning the masked value, `GRANT EXECUTE` adapter scaffolding (per ADR-025 boundary), `ALTER TABLE … ALTER COLUMN … SET MASK`. Live-verified against `bg_rls_demo.tpch.orders.o_clerk`. Covers byIdentity column targets; Redact transformation; Mask/Hash emit `NULL` placeholders pending future scaffold passes.
- UC ABAC byScope `RowVisibilityConstraint` emission — three-piece DDL: `CREATE FUNCTION` with Mechanism B CASE body, `GRANT EXECUTE`, `CREATE POLICY … ON CATALOG/SCHEMA/TABLE … ROW FILTER … FOR TABLES MATCH COLUMNS has_tag_value(<tag_key>, <tag_value>) AS alias USING COLUMNS (alias)`. Exercises `AdapterConfig.tag_taxonomy` (ADR-021). Live-verified against `bg_rls_demo.tpch.orders_abac`.
- Snowflake `ColumnVisibilityConstraint` emission — `CREATE OR REPLACE MASKING POLICY … AS (col VARCHAR) RETURNS VARCHAR -> CASE … END` plus `ALTER TABLE … MODIFY COLUMN … SET MASKING POLICY`. Live-verified against `BRICETEST.TESSERA.SNOW_ORDERS.O_CLERK` with `USE SECONDARY ROLES NONE`; role-discrimination is Intent B (IS_ROLE_IN_SESSION) per Snowflake's recommendation and issue #14.

**Documentation.**
- `docs/w3c-overview.md` — semantic-web-savvy overview of how the project uses OWL, JSON-LD 1.1, SHACL, SKOS, and the W3C stack. Shows the architecture honestly without overclaiming (no SPARQL in eval, no OWL DL reasoning, no formal vocabulary imports, no standards-body submission).
- `docs/user-guide/scenarios/acl-and-masking.md` — practitioner-shaped tutorial for the "ACL-table row visibility + column masking with a group exception" situation. Assumes YAML literacy; no semantic-web background required. Walks through two policies end to end including converter invocation and per-platform deployment.
- User-guide README routes practitioners to the scenario tutorial first.

**Issue tracker.**
- 10 governance-gap issues filed (#16–#25) from claude.ai's top-10 governance-need survey. Three flagged as in-scope gaps with scoping docs queued for Phase 2 (#19 audit logging, #21 retention — most urgent, #25 AI governance); the remaining seven captured coverage-confirmed, out-of-scope, underexercised, or integration-question dispositions for tracking visibility.
- 8 new labels created on the repo: `governance-need`, `coverage-confirmed`, `in-scope-gap`, `out-of-scope`, `underexercised`, `integration-question`, `scoping-needed`, `v0-candidate`.

**Tests.**
- `adapters/tests/test_parity.py::test_column_visibility_parity_emits_clean_on_both_adapters` — same IR, both adapters, each emits its native column-mask primitive, output meaningfully different.

### Changed

- **All 11 worked-example JSON-LDs regenerated from their YAML sources via the converter.** The corpus is canonical-YAML-driven going forward. Eliminates the descriptive-field drift the converter's regression test surfaced (5 of 11 files had prose differences between hand-maintained YAML and JSON-LD). Net diff: 60 insertions / 98 deletions across 11 files; no semantic content lost. The converter's deterministic compact output replaces hand-formatted spacing.
- `adapters/snowflake/capability.py` ROW_VISIBILITY rationale rewritten to record the role-discrimination-semantics distinction (Intent A vs B per issue #14), correcting an earlier "DEFAULT_SECONDARY_ROLES is a gotcha" framing.
- `adapters/unity_catalog/capability.py` ATTRIBUTE_BASED_SCOPING rationale records that ABAC row visibility is now implemented and live-verified; ABAC column masking via byScope remains the queued stub on this axis.
- `adapters/snowflake/capability.py` COLUMN_VISIBILITY rationale records live verification with per-role row counts.
- `adapters/unity_catalog/capability.py` COLUMN_VISIBILITY rationale records live verification.
- `DECISIONS.md` ADR-024 postscript refined per claude.ai's design review: Snowflake secondary-roles finding is an adapter emission choice (Intent A vs Intent B), not a platform misfeature.
- `docs/user-guide/{authoring,tutorial,evaluating}.md` updated to reflect converter v1 landing (was "queued" in three places).
- `CLAUDE.md` Priority 5 section marked complete with deferred items called out; eight-exercise list grew to include the table-grants Phase 3 plus the cross-platform live runs.

### Issue tracker activity

- Filed: [#16](https://github.com/bgiesbrecht/tessera/issues/16)–[#25](https://github.com/bgiesbrecht/tessera/issues/25) (governance-gap survey).
- Open at version close: #3, #4, #5, #7, #8, #9, #11, #12, #13, #14, #15, #16, #17, #18, #19, #20, #21, #22, #23, #24, #25.
- Closed prior to this version: #1, #2, #6, #10.
- 25 total issues; 4 closed; 21 open.

### What this version does not include

- **ABAC byScope column-mask emission on UC** — IR shapes exist (`abac-column-mask-policy-*`) but adapter still warns `UNIMPLEMENTED_SELECTOR_FOR_COLUMN_VISIBILITY` for byScope. Queued.
- **Snowflake ABAC byScope** (row or column) — different platform mechanism (object tags + masking-policy-attached-to-tag); deferred to a future scoping pass.
- **Adapter discover / extract / reconcile implementations** — all stubs; blocks the migration story until they're real.
- **Tessera CLI thin wrapper** — none yet; deployment remains library-shaped Python. The converter's CLI entry (`python -m tools.converter`) is the only command-line surface.
- **Phase 2 scoping documents for #19/#21/#25** — queued for claude.ai to draft.
- **JSON-LD → YAML converter direction** — deferred to v2; v1 covers the practitioner authoring direction only.
- **Comment preservation in YAML round-trips** — deferred to v2 per ADR-004; v1's `ruamel.yaml` foundation makes this a one-step addition rather than a refactor.

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
