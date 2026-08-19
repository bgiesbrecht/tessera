# Changelog

All notable changes to Tessera are recorded here. Versioning follows the spec's evolution: the major version stays at `0` while the IR is pre-immutability (ADR-017's suspended-immutability framing applies until external dependency exists). Minor-version bumps correspond to one or more ADRs landing alongside meaningful artifact additions.

The format draws on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project additionally references ADRs (in `DECISIONS.md`) for every change of substance.

## [0.14.1] — 2026-08-17

Oracle adapter live-verified on Oracle 23ai Free — and three emission bugs the live run caught, now fixed and guarded.

### Fixed

- **byDataset VPD used a correlated `EXISTS (... AND p.<col> = <col>)`** whose bare outer column resolved to the same-named ACL column *inside* the subquery (`p.<col> = p.<col>`, always true) — so any mapped user saw all rows. Replaced with a non-correlated `<col> IN (SELECT p.<col> FROM ...)`. (Live: 5 rows where 2 were expected → now 2 / 5 / 0 as ACL mappings change.)
- **Data Redaction role test used `SYS_CONTEXT(...) IS NULL`** — `SYS_SESSION_ROLES` returns `'TRUE'`/`'FALSE'`, never NULL, for an ungranted role, so redaction never applied. Corrected to `= 'FALSE' OR IS NULL` (redact-by-default; reveal only on `'TRUE'`). `NVL` is rejected by the redaction-expression grammar (ORA-28087), so the explicit form is required.
- **`regexp_occurrence => 0`** doubled the replacement (greedy `(.*)` also matches the trailing empty position) → `CLERK-REDACTEDCLERK-REDACTED`. Changed to `=> 1`.

### Notes

- **Live-verified 2026-08-17 on Oracle 23ai Free:** byDataset VPD row visibility returned 2 / 5 / 0 rows as ACL rows were added/removed (fail-closed when absent); Data Redaction showed a non-exempt reader `CLERK-REDACTED` without the allowed role and the real value with it. Capability profile stamped accordingly.
- Exemption facts recorded: SYS and `EXEMPT ACCESS POLICY` bypass VPD; SYS and `EXEMPT REDACTION POLICY` (held via DBA, so SYSTEM) bypass redaction — the redaction check therefore uses a non-DBA reader. `adapters/tests/live_oracle.py` documents the run.

## [0.14.0] — 2026-08-17

Fourth adapter: **Oracle** (ADR-033) — a third native platform, proving IR portability against a materially different mechanism set (Virtual Private Database, Data Redaction, GRANT — none resembling the UC/Snowflake primitives).

### Added

- **`adapters/oracle/`** (`OracleAdapter`), full ADR-024 cycle:
  - **emit** — row visibility → VPD (`DBMS_RLS.ADD_POLICY` + a PL/SQL policy function): `byIdentity` becomes an `IF/ELSIF` ladder over `SYS_CONTEXT('SYS_SESSION_ROLES','<ROLE>')` returning each rule's predicate with a fail-closed `ELSE`, `byDataset` returns a correlated `EXISTS` over the ACL tables. Column masking → Data Redaction (`DBMS_REDACT.ADD_POLICY`, `function_type => REGEXP` so the `Redact` replacement literal is honored — FULL can't). Access grants → `GRANT`. `byScope` ABAC refused with a diagnostic (no tag-driven attachment; OLS deferred). `RetentionConstraint` → `RETENTION_EXPRESSION_ONLY`.
  - **discover** — `ALL_POLICIES` (+ function body from `ALL_SOURCE`), `REDACTION_POLICIES`/`REDACTION_COLUMNS`, `ALL_TAB_PRIVS`.
  - **extract** — VPD (byDataset/byIdentity), redaction, and grant artifacts lifted back to IR; **reconcile** via the default contract path.
  - Honest capability profile (docs cited per ADR-027); marked emitted-not-live-verified until the live run stamps a date.
- **Worked artifacts** `spec/v0/examples/acl-row-visibility.oracle.sql` (a fourth mechanism for the ACL policy, beside UC / Snowflake / custom-ACL) and `oracle-mechanisms.oracle.sql` (VPD byIdentity, Data Redaction, GRANT).
- **CLI**: `--adapter oracle` (alias `ora`) on all four adapter subcommands.
- **Parity tests**: VPD row-visibility lowering, Data Redaction with a doubled-quote `expression` regression guard, byDataset VPD emit→extract round-trip, GRANT lowering, and honest `byScope` refusal.
- **Live-verify** `adapters/tests/live_oracle.py` (reads `oracle_auth.txt`, gitignored; `pip install oracledb`), gated on a provided instance.

### Notes

- **Portability finding (ADR-033):** Oracle FULL redaction cannot carry an arbitrary replacement, so `Redact` lowers to REGEXP — a mask-value-fidelity fact worth carrying into future Mask/Hash work. The `DBMS_REDACT` `expression` is a PL/SQL string literal, so inner quotes are doubled (a real bug caught and guarded in test).
- Oracle has no catalog tier; a 3-part `catalog.schema.table` maps to `SCHEMA.OBJECT` (catalog dropped), overridable via `resource_bindings`. Non-identifier group names (e.g. `account users`) must be bound via `identity_bindings`.

## [0.13.0] — 2026-08-17

Third adapter: **custom-ACL** (ADR-032) — the ADR-003 reference *pattern* adapter. A peer of the native Unity Catalog and Snowflake adapters against the same contract (ADR-024), whose enforcement target is the customer's own ACL-table + wrapping-view convention rather than a platform primitive.

### Added

- **`adapters/custom_acl/`** (`CustomACLAdapter`): `emit` lowers a `byDataset` `RowVisibilityConstraint` (the two-table ACL-join shape) to `CREATE OR REPLACE VIEW <base>_secured AS SELECT * FROM <base> WHERE EXISTS (…)` — the view is the enforcement mechanism; `extract` parses such a view definition back into `byDataset` IR at confidence 0.9 (the selective-migration on-ramp — ADR-003); `discover` inventories ACL-wrapping views (offline via `config.extras['acl_views']` or live via a DB-API cursor); `reconcile` uses the default contract path. Honest capability profile: `ROW_VISIBILITY` / `DATASET_DRIVEN_PRINCIPALS` / `DATASET_DRIVEN_RESOURCES` SUPPORTED, `COLUMN_VISIBILITY` PARTIAL, tag/ABAC/obligation/purpose/retention UNSUPPORTED.
- **Worked artifact** `spec/v0/examples/acl-row-visibility.custom-acl.sql` — the custom-ACL emission of the committed ACL IR, alongside the UC and Snowflake emissions of the same policy.
- **CLI**: `--adapter custom-acl` (alias `acl`) on `emit` / `discover` / `extract` / `reconcile`.
- **Parity tests**: `test_bydataset_acl_lowers_to_three_distinct_mechanisms` (UC row-filter vs Snowflake RAP vs custom-ACL view, all carrying the shared EXISTS join), `test_custom_acl_emit_extract_round_trips_to_equivalent_ir` (emit → extract reconstructs the source IR), `test_custom_acl_profile_is_pattern_adapter`.

### Notes

- **Pattern adapter, not a platform (ADR-032).** The emitted SQL is engine-neutral (`current_user()`, `lower(trim(...))`, correlated `EXISTS`); the customer runs it on whichever engine hosts the ACL pattern. The adapter never executes.
- Issue #13 (`ResourceSetFromTable.resourceColumn` conflated as ACL value column vs protected discriminator) surfaces here as an INFO diagnostic; the aligned convention (`p.<col> = b.<col>`) is used, matching the native adapters.
- The custom ACL-table pattern moves from "larger horizon" to Shipped on the roadmap. A fourth adapter (Oracle, a native platform) is in flight.

## [0.12.0] — 2026-08-14

Retention / deletion (ADR-031, closing [#21](https://github.com/bgiesbrecht/tessera/issues/21)) — the last of the three scoped governance gaps. A new expression-first policy kind; no adapter emission (no platform declarative-retention primitive).

### Added

- **`RetentionConstraint` policy kind** in `spec/v0/`: a `PolicyConstraint` subclass carrying `retention` → a `RetentionSpec` with `direction` (`DeleteAfter` for minimization / `RetainFor` for preservation — the two are opposite obligations and must be distinguished), `period` (ISO-8601 duration), `basis` (the event the clock starts from — a timestamp column or lifecycle event), and `disposition` (`Purge` / `Anonymize` / `Archive`). Classes + individuals + properties in `ontology.ttl`; `@vocab`/`@type` context terms; `retentionSpec` + `retentionDocument` in `schema.json`; `RetentionConstraintShape` + direction/disposition value shapes in `shapes.ttl`.
- **Worked example** `spec/v0/examples/retention-delete-after-policy.{tessera.yaml,jsonld}` — a freestanding `RetentionConstraint` on `acme.tpch.orders`: `DeleteAfter` P30D from `o_orderdate`, disposition `Purge`. Validates clean.
- **`Capability.RETENTION`** (UNSUPPORTED) on both adapters; a `RETENTION_EXPRESSION_ONLY` INFO diagnostic and zero statements on emit; parity test `test_retention_constraint_is_expression_only_on_both_adapters`.

### Notes

- **Honest scope (ADR-031):** neither Databricks nor Snowflake has a declarative "delete after N" primitive (Snowflake `DATA_RETENTION_TIME_IN_DAYS` is Time-Travel; Delta `VACUUM` is history cleanup — neither is record expiry). Real retention is an operational scheduled job. Tessera carries the full intent as a first-class, portable, checkable policy but emits nothing; a scheduled-`DELETE` emitter is a deferred, opt-in increment. This keeps the ADR-001 line (Tessera does not run or emit destructive jobs in v0).
- **All three governance gaps (#25 / #19 / #21) now shipped.** The "in-scope gaps — scoping needed" track is retired.

### Fixed

- **`PolicyConstraintShape` over-broad target.** The shape's `sh:targetClass tessera:PolicyConstraint` was catching `RetentionConstraint` via subclass reasoning and wrongly demanding `principal`/`action`/`effect`. Narrowed to the five access-shaped subclasses (`AccessConstraint`, `RowVisibilityConstraint`, `ColumnVisibilityConstraint`, `DistributionConstraint`, `AccessGrantConstraint`).

## [0.11.0] — 2026-08-14

Audit-logging obligation refinement (ADR-030, closing [#19](https://github.com/bgiesbrecht/tessera/issues/19)) — the second of the three scoped governance gaps. An obligation-vocabulary refinement; no new policy kind, expression-first.

### Added

- **`AuditLog` obligation parameters** in `spec/v0/`: `auditFields` (the semantic fields to capture — `AccessPrincipal` / `AccessResource` / `AccessAction` / `AccessTimestamp` / `AccessPurpose` / `AccessOutcome`), `auditSink` (destination category — `PlatformNative` / `ExternalSIEM` / `ImmutableStore`), and `auditRetention` (ISO-8601 duration). Value classes + individuals + properties in `ontology.ttl`; `@type: @vocab` context terms; `auditFields`/`auditSink` value shapes in `shapes.ttl`; three optional properties on the obligation in `schema.json`.
- **Worked example** `spec/v0/examples/audit-obligation-sensitive-read.{tessera.yaml,jsonld}` — a freestanding `AccessConstraint` where fraud-investigator reads carry a rich audit obligation (who/what/action/when/purpose/outcome → immutable store, retained P7Y). Validates clean; audit values resolve to `vocab#` IRIs.

### Notes

- **Honest scope (ADR-030):** platforms audit access account-wide by default (Databricks `system.access.audit`, Snowflake `ACCESS_HISTORY`), so the obligation is typically *satisfied-by-assertion* — a portable, checkable requirement rather than a newly-enforced mechanism. No adapter emission is claimed; an emit-time coverage diagnostic (and an `asserted-satisfied` capability level) is a tracked follow-up.
- Obligations attach to the freestanding `PolicyConstraint` shape (unchanged); extending them to Policy-container rules is a separate item.
- Two of the three governance gaps now shipped (#25, #19); #21 (retention) remains, pending its scope-framing decision.

## [0.10.0] — 2026-08-13

AI-governance attribute axes (ADR-029, closing [#25](https://github.com/bgiesbrecht/tessera/issues/25)) — the first of the three scoped governance gaps to land. An additive IR change extending the ADR-018 attribute-axis framework; no new policy kind, no new emission path.

### Added

- **Two flat attribute axes** in `spec/v0/`: `trainingEligibility` (`NoTraining`, `TrainingWithConsent`, `TrainingAllowed`) and `automatedDecision` (`NoAutomatedDecision`, `ADMWithHumanReview`, `AutomatedDecisionAllowed`). Declared like the other flat axes — `AttributeAxis` individual + `axisType flat`, an object property on `Resource`, well-known `NamedIndividual` values (`ontology.ttl`); `@type: @vocab` context terms (`context.jsonld`); per-axis value shapes (`shapes.ttl`). `schema.json` unchanged (the attributes map is open on axis keys by design).
- **Worked example** `spec/v0/examples/ai-governance-training-mask-policy.{tessera.yaml,jsonld}` — a `byScope` `ColumnVisibilityConstraint` keyed off `trainingEligibility: NoTraining` that masks matching columns to all but a consented group. Validates clean; emits real masking DDL on **both** adapters via the existing byScope emitters (`has_tag_value(...)` on UC, `SYSTEM$GET_TAG_ON_CURRENT_COLUMN(...)` on Snowflake). Regression test in `adapters/tests/test_parity.py`.

### Notes

- **Honest scope (ADR-029):** no data platform natively enforces an AI-use restriction. The axes are portable classifications; their enforcement leverage is *by composition* with the access machinery (the worked example is the pattern). Capability profiles must not claim the platform enforces the AI restriction itself.
- The change-impact kernel picks the new axes up automatically as flat (equality-only) from the ontology; no tool change needed.
- Design surface for all three gaps: `docs/v1-candidates/governance-gaps-scoping.md`. #19 (audit) and #21 (retention) remain scoped-not-built.

## [0.9.1] — 2026-08-13

Live verification of the 0.9.0 Snowflake ABAC `byScope` emission, and the one emitter fix it surfaced.

### Fixed

- **Snowflake ABAC row-filter `ON` clause**: the `ALTER TAG ... SET ROW ACCESS POLICY ... ON (...)` clause now names the real discriminator column (derived from the matching attribute value), not the abstract `matched` parameter. Live testing showed the abstract name doesn't bind, so no rows were filtered; with the real column the per-role slices enforce correctly.

### Added / Changed

- **`ABAC_ROW_ACCESS_TABLE_TAG` diagnostic**: row-access emission now notes that the driving tag must be set on the **table** (masking tags the column), and names the discriminator column that must exist — both facts discovered in live verification.
- **`adapters/tests/live_snowflake_abac_byscope.py`**: self-contained live-verification script (creates roles/db/table/tags, applies, verifies per-role enforcement, cleans up).
- Snowflake `CapabilityProfile.ATTRIBUTE_BASED_SCOPING` prose records the 2026-08-13 live-verification result and the column-tag-vs-table-tag distinction.

### Verification

Run on a fresh Enterprise account (`TESSERA_VERIFY.ABAC`): column mask redacted `O_CLERK` for `PUBLIC` while `ACME_ALL_PRIORITY_OPS` saw real values; row filter returned all rows for `ACME_ALL_PRIORITY_OPS`, 1-URGENT/2-HIGH only for `ACME_HIGH_PRIORITY_OPS`, and 3-MEDIUM/4/5 for `PUBLIC`. Both paths enforce as designed.

## [0.9.0] — 2026-08-13

Snowflake ABAC `byScope` emission — row and column ([#31](https://github.com/bgiesbrecht/tessera/issues/31)). The last open adapter coverage gap; a tooling/adapter release, no IR change. The mechanism was verified against Snowflake's docs (per ADR-027): Snowflake attaches both masking *and* row-access policies via tags, so both halves of #31 have a clean tag-based path — correcting an earlier assumption that row-ABAC had no tag mechanism.

### Added

- **`adapters/snowflake/emission.py`** — `_emit_column_visibility_by_scope` and `_emit_row_visibility_by_scope`, dispatched when a `ColumnVisibilityConstraint` / `RowVisibilityConstraint` uses `selector: byScope`:
  - **Column:** `CREATE MASKING POLICY` whose body reads `SYSTEM$GET_TAG_ON_CURRENT_COLUMN('<schema.tag>')` to scope the mask to the matched value, allow-roles passing through via `IS_ROLE_IN_SESSION`; attached with `ALTER TAG ... SET MASKING POLICY`.
  - **Row:** `CREATE ROW ACCESS POLICY` as an ordered-first-match `CASE` ladder over `IS_ROLE_IN_SESSION` + a predicate on the matched discriminator column (the IR's `column:$matched` sentinel binds to the policy parameter); attached with `ALTER TAG ... SET ROW ACCESS POLICY ... ON (<col> VARCHAR)`.
  - The `(axis, value) → (tag_key, tag_value)` mapping is per-environment `config.tag_taxonomy` (ADR-021); an unbound attribute or a non-schema-qualified tag key surfaces a diagnostic. The policy object schema is the scope's schema, or `config.extras['abac_policy_schema']`, or an inferred `<db>.PUBLIC`.
- Regression tests in `adapters/tests/test_parity.py` for both paths and the configured-taxonomy case.

### Changed

- **Snowflake `CapabilityProfile.ATTRIBUTE_BASED_SCOPING`**: `PARTIAL` → `SUPPORTED`, documenting the tag-based mechanism and its Snowflake constraints (one row-access policy per tag; masking vs row-access mutually exclusive on a tag). `COLUMN_VISIBILITY` prose updated (byScope no longer "queued").
- `docs/showcase.md` policy-shape table: the two Snowflake ABAC-byScope cells now show real DDL instead of "queued (#31)".

## [0.8.0] — 2026-08-05

Attribute values become vocabulary IRIs (ADR-028), so the ontology hierarchy can reason over them. A change-impact graph spike found that `sensitivity` was defined `"@type": "@id"` — bare values like `PIIClerk` expanded to document-base junk instead of `vocab#` IRIs, blocking `subClassOf*` subsumption. No external consumer exists (ADR-017), so this is a clean break.

### Changed

- **`spec/v0/context.jsonld`**: `sensitivity` is now `"@type": "@vocab"` (matching the other three axes, which already were), and a top-level `"@vocab"` is declared. Together these default a bare attribute value to the Tessera vocabulary namespace (`sensitivity: PII` ⇒ `tessera:PII`), while an explicit prefix (`acme:PIIClerk`) marks an adopter specialization and is preserved. The authoring rule: **bare = Tessera's vocabulary; a prefix = the adopter's** (ADR-028, reinforcing ADR-018).
- **`spec/v0/examples/abac-column-mask-policy-{a,b}`**: the bare `PIIClerk` value — described in the examples' own comments as an adopter stand-in — is now `acme:PIIClerk`, honoring the rule. JSON-LD regenerated; worked-example records updated for the namespaced token.

### Fixed

- **UC adapter ABAC column-mask / row-filter alias**: a namespaced attribute value leaked its colon into `AS <alias>` / `ON COLUMN <alias>`, producing invalid Databricks SQL (`AS acme:PIIClerk`). The alias is now sanitized to a legal identifier (`acme_PIIClerk`). Surfaced by the example change; regression test in `adapters/tests/test_parity.py`.

### Notes

- Change-impact tool: no code change (the kernel already strips prefixes). The graph spike's blocked-subsumption finding is resolved — `subClassOf*` now reaches the ontology for Tessera-namespace values. `tools/impact/spikes/FINDINGS.md` updated.
- Deferred (recorded in ADR-028): tightening SHACL to flag undeclared bare values as non-`Classification` needs ontology inference the current validation pass does not run.

## [0.7.0] — 2026-08-05

A tooling release, not an IR change. It adds **change-impact analysis** — a tool that, given a corpus of policies and a proposed change, reports how the change alters what the corpus decides about data, before the change is validated or emitted. No ADR and no `spec/v0/` change accompanies it (the minor bump reflects a meaningful new capability rather than an ADR landing); it grounds in existing decisions (ADR-001 for the scope line, ADR-013–016 and ADR-023 for what each check reasons about).

### Added

**`tools/impact/`** — the change-impact analyzer. Reasons about selector *expressions*, never the populations they denote (the ADR-001 line): it compares selector literals, IRIs, and ontology-typed values, and never resolves group membership or reads ACL-table rows. Every finding is selector-relative and confidence-tagged — `PROVEN` (follows from policy text + ontology) or `CANDIDATE` (would require a platform-tagging fact the tool does not read).

Diff checks (`tessera impact`, comparing two corpus versions):

- **C1** fall-through coverage — a selector that loses its last governing rule, and where its principals now fall through per `defaultStrategy` (ADR-013).
- **C2** default-net change — `defaultStrategy` / `baselineGroup` / `defaultBranch` edits (ADR-013/014).
- **C3** reachability — a rule newly *shadowed* (dead code) or newly *un-shadowed* (dormant policy activated) under ordered first-match (ADR-015).
- **C4** cross-policy overlap — two same-kind policies resolving to an overlapping target under a single-policy platform constraint (ADR-023's `single-column-mask-per-column` / `single-row-filter-per-table`); a multiplicity constraint, so it fires whether the effects differ (Redact vs Hash) or duplicate.
- **C5** dangling reference — a reference left dangling by the change.
- **C6** exposure polarity — WIDEN / NARROW / INVERT / NEUTRAL. Transformation swaps (Redact→Hash) are INVERT-with-review, since transforms have no total order (scoping-doc §9.4).

Standing lints (`tessera lint`, auditing one corpus state):

- **L1** dead rules across the corpus; **L2** all current cross-policy overlaps.

**Corpus discovery is git-tracked by default** (committed policies are the corpus; uncommitted drafts excluded until staged), with a `--corpus DIR` filesystem override and an explicit `--baseline`/`--proposed` file mode. Report formats: text / md / json. Advisory by default (exit 0); opt-in CI gating via `--exit-on <POLARITY>`.

- **`tessera impact` / `tessera lint`** wired into the unified CLI (`tools/cli/`), delegating to the tool.
- **`docs/user-guide/analyzing-changes.md`** — practitioner guide (modes, corpus boundary, reading findings, PROVEN vs CANDIDATE, CI use).
- **`docs/v1-candidates/change-impact-analysis.md`** — the design/scoping document (reasoning kernel, check catalog, worked exercises, resolved open questions §9.1 corpus boundary and §9.4 transform swaps).
- **Three generated, drift-tested artifacts** under `tools/impact/demo/`: a dead-rule timeline demo, a cross-policy overlap demo (both in `docs/exercises/`), and `OUTPUT-REFERENCE.md` capturing per-check and per-format output.
- **`docs/ROADMAP.md`** — consolidated project roadmap (previously scattered across README, scoping docs, and the issue log).

### Notes

- Reasoning is grounded in the published ontology: attribute subsumption reads `spec/v0/ontology.ttl` via rdflib (hierarchical axes subsume declared subclasses; flat axes equality-only).
- No tracked issues closed (this is tooling); the ABAC emission gap [#31](https://github.com/bgiesbrecht/tessera/issues/31) remains the open adapter item.

## [0.6.3] — 2026-05-21

A small adapter increment: UC ABAC byScope column-mask emission, closing issue [#30](https://github.com/bgiesbrecht/tessera/issues/30). Parallel to the byScope row-filter emission that has been working since 0.3.0; the hand-derived target SQL has existed in `spec/v0/examples/abac-column-mask.databricks.sql` since the ABAC scoping work landed. This commit makes the UC adapter produce that DDL from the IR.

### Added

**`_emit_column_visibility_by_scope` in `adapters/unity_catalog/emission.py`.** Lowers a `byScope` + `matching` `ColumnVisibilityConstraint` to Databricks ABAC DDL:

```
CREATE OR REPLACE FUNCTION <fn>(val STRING) RETURNS STRING
RETURN <transformation_expression>;

GRANT EXECUTE ON FUNCTION <fn> TO `account users`;

CREATE OR REPLACE POLICY <policy>
  ON <CATALOG|SCHEMA> <id>
  COMMENT '...'
  COLUMN MASK <fn>
    TO `account users`
    EXCEPT `<allowed_group>`
    FOR TABLES
    MATCH COLUMNS has_tag_value('<tag_key>', '<tag_value>') AS <alias>
    ON COLUMN <alias>;
```

The function dispatches from `_emit_column_visibility` when `selector == 'byScope'`. Expected IR shape: `defaultStrategy=negated-complement`, one or more rules with `effect=allow` naming the privileged group(s), `defaultBranch.transformation` carrying the mask transformation. Rule principals become the `EXCEPT` clause; the defaultBranch transformation becomes the UDF body. Tag taxonomy translation (ADR-021) maps Tessera axis+value to Databricks tag key+value; unbound attributes fall back with a warning.

### Changed

- **UC `CapabilityProfile.COLUMN_VISIBILITY`**: still `SUPPORTED`, prose updated to record both byIdentity and byScope paths and the verification artifact.
- **UC `CapabilityProfile.ATTRIBUTE_BASED_SCOPING`**: promoted from `PARTIAL` to `SUPPORTED` (both row-filter and column-mask ABAC paths now real on UC).
- **`docs/showcase.md`**: policy-shape table gains a row for `ColumnVisibilityConstraint (byScope ABAC)`; the "UC ABAC byScope column-mask emission is queued" limitation removed; tracked-issue tally updated 21 → 20 open.

### Verification

Emission against `spec/v0/examples/abac-column-mask-policy-{a,b}.jsonld` produces DDL functionally equivalent to the hand-derived `spec/v0/examples/abac-column-mask.databricks.sql`. Only differences are stylistic: the auto-generated `MATCH COLUMNS ... AS <alias>` uses the tag value directly (`clerk`) instead of the hand-stylized `pii_clerk_col`, and the Hash UDF emits `sha2(cast(val AS STRING), 256)` instead of `sha2(val, 256)` (defensive no-op cast). The existing parity test (`adapters/tests/test_parity.py`) passes.

### Issue tracker activity

- Closed [#30](https://github.com/bgiesbrecht/tessera/issues/30): UC ABAC byScope column-mask emission.

Twenty open issues now (down from twenty-one). The remaining ABAC gap is [#31](https://github.com/bgiesbrecht/tessera/issues/31) (Snowflake ABAC byScope; different platform mechanism — Snowflake uses tag-based-attachment masking/row-access policies rather than `MATCH COLUMNS`).

## [0.6.2] — 2026-05-20

A repo-wide cleanup: personal identifiers replaced with the conventional "any adopter" stand-in `acme` / `ACME` / `acme:`. No spec semantics change; no adapter logic change. 80 files updated mechanically; regression tests (converter + parity) pass; all worked-example YAMLs re-validate clean against JSON Schema and SHACL.

### Changed

**Infrastructure identifiers — Databricks side**
- Catalog `bg_rls_demo` → `acme`
- Groups `bg_rls_demo_all_priority_ops` → `acme_all_priority_ops`; `bg_rls_demo_high_priority_ops` → `acme_high_priority_ops` (any other `bg_rls_demo_*` group follows the same prefix swap)
- Uppercase variants `BG_RLS_DEMO_*` → `ACME_*` in `AdapterConfig.bind_resource` examples and Snowflake role identity-bindings

**Infrastructure identifiers — Snowflake side**
- Database `BRICETEST` → `ACME` (schema name `TESSERA` unchanged)
- Roles `BG_RLS_DEMO_*` → `ACME_*` consistently across worked-example DDL, live-test scripts, and capability profile prose

**Adopter-namespace IRI prefix in worked examples**
- `bg:rowDiscriminator` → `acme:rowDiscriminator` in `spec/v0/examples/abac-row-filter-priority.{jsonld,tessera.yaml}` and prose in `docs/technical-design-v0.2.md`, `spec/v0/schema.json` description, the `abac-row-filter-priority` comparison and diagnostic, and the ABAC scoping document.

### What this does not change

- **Spec semantics.** No ontology, JSON-LD context, schema, or SHACL shape changed. The rename is purely identifier substitution.
- **Adapter logic.** Adapters take identifiers from `AdapterConfig` bindings, not from hardcoded constants. The capability-profile prose was updated for honesty; the emission code paths are unchanged.
- **Person-name attribution.** "Per Brice's framing," `@bgiesbrecht`, `bgiesbrecht.github.io/tessera/` (canonical namespace URLs per ADR-011), and the Snowflake user `BGIESBRECHT` and email `brice.giesbrecht@databricks.com` remain in place. Those are legitimate identity references, not "names scattered."

### Operational follow-up (complete, 2026-05-20)

Live integration scripts (`live_databricks.py`, `live_snowflake.py`, `live_snowflake_bydataset.py`, `live_migration_demo.py` and reverse, etc.) now target the new identifiers. Required infrastructure was provisioned on each platform via the new `setup_demo_infra.py` script:

- **Snowflake:** `ACME` database, `ACME.TESSERA` schema, seed tables (`SNOW_ORDERS` and `SNOW_ORDERS_RLS_ACL` from `SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS`, ~1.5M rows each; empty `RLS_ACL_MAPPING` and `RLS_PRIORITY_ACL`), and three roles (`ACME_ALL_PRIORITY_OPS`, `ACME_HIGH_PRIORITY_OPS`, `ORDERS_FULL_ACCESS`). All created via SQL through ACCOUNTADMIN.
- **Databricks:** `acme` catalog (pre-existing), `acme.tpch` and `acme.tpch_staging` schemas, seed tables (`orders` / `orders_rls_acl` / `orders_abac` from `samples.tpch.orders`, ~7.5M rows each; `initial_table` LIMIT 100; empty ACL tables), the `compute_customer_ltv` UDF, and five account-level groups (`acme_all_priority_ops`, `acme_high_priority_ops`, `acme_marketing_analytics`, `acme_data_engineering`, `orders_full_access`).

**Lesson recorded in `setup_demo_infra.py`:** Databricks groups for UC GRANT must be account-level (`resource_type='Group'`) **and** assigned to the target workspace. The workspace SDK's `groups.create()` makes `WorkspaceGroup`-typed groups that are visible to `SHOW GROUPS` but rejected by `GRANT` with `PRINCIPAL_DOES_NOT_EXIST`. The script no longer attempts group creation; it prints the manual provisioning step instead.

### Empirical validation (end of cycle, 2026-05-20)

`live_migration_demo` re-run end-to-end on the new infra. All six policies migrate cleanly Snowflake → IR → Databricks and verify on the target. Verification numbers identical to the pre-rename baseline (CHANGELOG [0.6.0] "Empirical verification" table):

| Policy kind | Target | Verified |
|---|---|---|
| RowVisibilityConstraint (group, multi-rule) | `acme.migration_demo.demo_orders` | 59,998 rows (third branch) |
| RowVisibilityConstraint (byDataset, EXISTS) | `acme.migration_demo.demo_orders_rls_acl` | 40,002 rows |
| ColumnVisibilityConstraint (mask) | `acme.migration_demo.demo_orders.o_clerk` | `CLERK-REDACTED` |
| AccessGrantConstraint (table) | `acme.migration_demo.demo_orders` | 3 grants visible via `SHOW GRANTS` (`acme_all_priority_ops`, `acme_high_priority_ops`, `account users`) |
| AccessGrantConstraint (schema → all tables) | `acme.migration_demo_staging.staged_orders` | 1 grant visible (`acme_all_priority_ops`) |
| AccessGrantConstraint (function) | `acme.migration_demo.compute_customer_ltv` | 1 grant visible (`acme_high_priority_ops` EXECUTE) |

The rename is fully validated end-to-end.

### Why this is a patch version

No new ADR; no spec or adapter semantics changed; no API surface added or removed. Worked-example artifacts now read generically (`acme` as the conventional adopter stand-in), making the repo cleaner for any future third-party reader. Patch-bump per the CHANGELOG framing.

## [0.6.1] — 2026-05-20

A documentation-and-principle increment. No spec or adapter changes. Captures a recurring framing slip as a recorded ADR so the next instance gets caught at the principle layer rather than after seven docs have to be corrected.

### Added

**ADR-027 — Descriptive representation: that which can be defined can be represented.** Records the principle that Tessera's authoring guidance and capability profiles are descriptive, not prescriptive. The framework represents any well-defined policy intent; it does not synthesize cross-platform authoring recommendations the platforms themselves do not make. Where a platform's docs make a recommendation, Tessera surfaces and cites it. Where the IR cannot represent a definable intent, the gap is an IR-extension candidate (e.g., issue #14 for Intent A primary-role-only semantics) — not a constraint on authors.

Empirical motivation: two consecutive correction passes hit the same drift — the 2026-05-19 secondary-roles reframe and the 2026-05-20 Snowflake-guidance reframe. Both fixed instances of Tessera inventing recommendations Snowflake itself does not document. ADR-027 abstracts the recurring principle so the failure mode is caught at the ADR layer.

### Changed

**`docs/user-guide/contributing.md`** gains a "Descriptive, not prescriptive (ADR-027)" section establishing the principle as a contribution norm. PRs that introduce "Tessera recommends X" framing without a platform-side source will be redirected.

**`docs/user-guide/authoring.md`** gains an opening "A note on this page's voice" section stating the principle so practitioners encounter it before any per-selector guidance.

**`README.md`** updates the Foundational decisions section: ADR count bumped from 26 → 27; ADR-027 added under Posture and framing.

### Snowflake guidance corrections (rolled forward from 2026-05-20)

The 0.6.0 cycle's last commit (`97ff1d5`) corrected seven authoritative documents and the Snowflake capability profile to drop the "Snowflake prefers byDataset for non-trivial policies" overreach. Each corrected claim now carries an inline citation to Snowflake's actual documentation (`docs.snowflake.com/en/user-guide/security-row-using` and adjacent pages). The corrections realize what ADR-027 records as principle.

### Issue tracker activity

No issues opened or closed in this cycle. The 2026-05-19 secondary-roles correction and the 2026-05-20 Snowflake-guidance correction were both completed and abstracted into ADR-027.

## [0.6.0] — 2026-05-20

RBAC support landed in the adapter cycle. The full ADR-024 four-responsibility set — emit, discover, extract, reconcile — now covers `AccessGrantConstraint` policies alongside the row/column-visibility shapes. The migration demo grew from three policies to six, with the table-grants exercise's RBAC patterns flowing through the same Snowflake → IR → UC pipeline as everything else.

### Added

**UC adapter `_emit_access_grant`** in `adapters/unity_catalog/emission.py`. Dispatches on `byIdentity` (table/function targets) vs `byScope` (schema/catalog targets). Action mapping: `Read → SELECT`, `Write → MODIFY`, `Execute → EXECUTE`. Schema/catalog grants emit `USE SCHEMA` / `USE CATALOG` scaffolding alongside the substantive privilege. Output matches the hand-derived `spec/v0/examples/table-grants.databricks.sql`.

**UC grant discovery** in `adapters/unity_catalog/discovery.py`. Walks `SHOW GRANTS ON TABLE` for each table in the schema, `SHOW GRANTS ON SCHEMA`, `SHOW GRANTS ON FUNCTION` for functions enumerated via `INFORMATION_SCHEMA.ROUTINES` (the `SHOW USER FUNCTIONS IN <schema>` surface requires session-level `USE CATALOG` which the statement-execution API doesn't carry). Filters: `OWN`/`ALL PRIVILEGES`/`MANAGE` skipped as ownership noise; `USE SCHEMA`/`USE CATALOG` skipped as scaffolding; inherited grants (source object ≠ attached object) skipped (the source produces its own IR independently). Pseudo-principals (`account users`/`users`) lifted with an INFO diagnostic.

**Snowflake `_emit_access_grant`** in `adapters/snowflake/emission.py`. Parallel to UC. Snowflake-specific:

- **Schema/database read grants** expand to `GRANT USAGE` + `GRANT SELECT ON ALL TABLES IN SCHEMA` + `GRANT SELECT ON FUTURE TABLES IN SCHEMA`. Snowflake doesn't accept `SELECT` directly on a schema; this expansion is the canonical idiom and matches Tessera's byScope downward-propagation semantics (ADR-019).
- **Function grants** require a Snowflake call signature. If the binding doesn't supply one and `config.extras["snowflake_cursor"]` is available, `_resolve_function_signature` queries `INFORMATION_SCHEMA.FUNCTIONS` to look it up. Falls back to `()` placeholder with a warning.
- **Action mapping** fans out where Snowflake splits: `Write → INSERT + UPDATE + DELETE`. `Execute` on a function → `USAGE` (Snowflake's invoke privilege).

**Snowflake grant discovery** extends `adapters/snowflake/discovery.py` to walk `SHOW GRANTS ON SCHEMA`, `SHOW GRANTS ON TABLE` (for each table in the schema), `SHOW GRANTS ON FUNCTION` (for each function in the schema, signature resolved from `SHOW USER FUNCTIONS`).

**Snowflake grant extract** maps Snowflake privileges to IR actions: `SELECT → Read`, `INSERT/UPDATE → Write`, `DELETE → Delete`, `USAGE` on `FUNCTION → Execute`, `USAGE` on `SCHEMA/DATABASE` skipped as scaffolding, `OWNERSHIP`/`ALL` skipped.

**Migration demo extension** (`adapters/tests/live_migration_demo.py`) covers RBAC alongside row/column visibility. Six source-policy YAMLs now (three visibility shapes + three table-grants scenarios). Phase 1 provisions a `compute_customer_ltv` function and a staging schema; Phase 2 deploys all six policies on Snowflake; Phase 3 walks both `MIGRATION_DEMO` and `MIGRATION_DEMO_STAGING` for discovery; Phase 8 verifies grants on the migrated TABLE / staging-table / FUNCTION on Databricks.

### Changed

- **`AdapterConfig.bind_resource`** lookups for `byScope` now try `scope:<raw>` first (with inner prefix preserved), falling back to `scope:<stripped>`. Lets bindings be authored either way.
- **UC AccessGrantConstraint dispatch** in `emit_policy` joins the existing dispatch for the other two policy kinds.

### Fixed

- **Snowflake schema-level `GRANT SELECT ON SCHEMA`** previously emitted a Snowflake-invalid statement. Now expands correctly to `GRANT SELECT ON ALL TABLES IN SCHEMA` + `GRANT SELECT ON FUTURE TABLES IN SCHEMA`.
- **Snowflake function-grant signature resolution** previously emitted `()` placeholder which Snowflake rejected. Now resolves via `INFORMATION_SCHEMA.FUNCTIONS` when a cursor is available in `config.extras`.

### Empirical verification (end of cycle)

Migration demo runs end-to-end on fresh schemas both sides with all six policy shapes deploying and verifying:

| Policy kind | Target | Verified |
|---|---|---|
| RowVisibilityConstraint (group, multi-rule) | `acme.migration_demo.demo_orders` | 59,998 rows visible (third branch) |
| RowVisibilityConstraint (byDataset, EXISTS) | `acme.migration_demo.demo_orders_rls_acl` | 40,002 rows (caller's ACL codenames) |
| ColumnVisibilityConstraint (mask) | `acme.migration_demo.demo_orders.o_clerk` | `CLERK-REDACTED` |
| AccessGrantConstraint (table) | `acme.migration_demo.demo_orders` SELECT | 3 grants visible via SHOW GRANTS |
| AccessGrantConstraint (schema → all tables) | `acme.migration_demo_staging.staged_orders` SELECT | 1 grant visible via SHOW GRANTS |
| AccessGrantConstraint (function) | `acme.migration_demo.compute_customer_ltv` EXECUTE | 1 grant visible via SHOW GRANTS |

### Issue tracker activity

No issues filed or closed in this cycle. The migration-demo's RBAC capability now empirically validates the AccessGrantConstraint policyKind from 0.4.0 (ADR-026, closed #15).

### What this version does not include

- **UC ABAC byScope column-mask emission** ([#30](https://github.com/bgiesbrecht/tessera/issues/30)) — sibling of byScope row-filter from 0.3.0.
- **Snowflake ABAC byScope** ([#31](https://github.com/bgiesbrecht/tessera/issues/31)) — different platform mechanism.
- **Phase 2 scoping docs for #19/#21/#25** — queued for claude.ai.
- **Schema-pattern resource bindings** — today the demo enumerates per-table bindings when migrating schema-scoped grants. A pattern-binding feature ("any table in schema X maps to corresponding table in schema Y") would reduce the binding boilerplate.

## [0.5.0] — 2026-05-20

Three-commit increment focused on adapter-contract completeness and the documentation debt that emerged from the 0.4.0 migration cycle. The full ADR-024 adapter responsibility set — discover, extract, emit, reconcile — is now real on both Unity Catalog and Snowflake (modulo ABAC byScope shapes that remain queued under separate issues). Five issues closed.

### Added

**Unity Catalog `discover()` and `extract()` — `adapters/unity_catalog/discovery.py`.**

Parallel to the Snowflake equivalent. discover() walks `SHOW TABLES IN <schema>` + `DESCRIBE TABLE EXTENDED` to inventory row filters and column masks attached to tables; fetches each function's body via `DESCRIBE FUNCTION EXTENDED`. extract() recognizes three body shapes that the UC adapter emits:

- byDataset row filter (`EXISTS (SELECT 1 FROM <map> m JOIN <acl> p WHERE m.<user> = current_user() AND p.<col> = <param>)`).
- byIdentity multi-OR row filter (`is_account_group_member('A') OR (is_account_group_member('B') AND col IN (…))`).
- byIdentity column mask (`CASE WHEN is_account_group_member('X') THEN col ELSE 'literal' END`).

Live-verified against `acme.migration_demo`: all three deployed policies discovered and extracted with confidence ≥ 0.9. The adapter stays SDK-agnostic — caller supplies a `run_sql` callable via `config.extras["run_sql"]`. Closes [#27](https://github.com/bgiesbrecht/tessera/issues/27).

**Platform-neutral `reconcile()` — `adapters/contract/reconcile.py`.**

The fourth ADR-024 responsibility, implemented as a default on `Adapter` so both adapters get it without per-adapter code. Composes the adapter's `discover()` + `extract()` to produce an observed IR snapshot, then runs a structural diff against the supplied intended corpus. Returns a `ReconciliationResult` with `additions` / `removals` / `modifications` plus surfaced extraction diagnostics.

Matching is by `(appliesTo.resource, action)` key, case-folded on the identifier portion of `prefix:id` strings. The diff compares only structural fields (`policyKind`, `action`, `defaultStrategy`, `rules`, `defaultBranch`) — descriptive fields (`@id`, `description`, `provenance`) are noise for reconcile purposes.

Live-verified against `acme.migration_demo`: 0 additions, 0 removals, 3 modifications (the modifications reflect real differences between the source YAMLs and the migration-bindings-translated deployed form). Closes [#26](https://github.com/bgiesbrecht/tessera/issues/26).

### Changed (documentation)

- **`docs/user-guide/contributing.md` § Design rules every adapter must follow** gains the UDF parameter-name collision convention. Bug was fixed in three emission paths during 0.3.0 and 0.4.0; the convention now lives in the authoring docs so future emission paths don't reintroduce it. Closes [#28](https://github.com/bgiesbrecht/tessera/issues/28).
- **`docs/user-guide/operating.md` § Identifier case in extracted IR** documents the chosen convention: carry source-platform case verbatim in extracted IR; rely on `AdapterConfig.bind_principal` / `bind_resource` case-insensitivity (added 0.4.0) as the bridge. Closes [#29](https://github.com/bgiesbrecht/tessera/issues/29).
- **`docs/technical-design-v0.2.md` §5.5a — Emission readability** documents the negated-complement → readable-ELSE expectation. Largely automatic post-ADR-014 (`defaultBranch` is structural); remains a quality expectation for pre-container IR shapes. Closes [#5](https://github.com/bgiesbrecht/tessera/issues/5).

### Issue tracker activity

- **Closed**: [#5](https://github.com/bgiesbrecht/tessera/issues/5), [#26](https://github.com/bgiesbrecht/tessera/issues/26), [#27](https://github.com/bgiesbrecht/tessera/issues/27), [#28](https://github.com/bgiesbrecht/tessera/issues/28), [#29](https://github.com/bgiesbrecht/tessera/issues/29).
- **Comments added** to touched-but-not-closed issues: [#8](https://github.com/bgiesbrecht/tessera/issues/8) (binding-layer fix vs IR-level vocabulary distinction), [#13](https://github.com/bgiesbrecht/tessera/issues/13) (migration-demo workaround), [#14](https://github.com/bgiesbrecht/tessera/issues/14) (extractor collapses Intent A/B).
- **Filed** at the start of this cycle: [#26](https://github.com/bgiesbrecht/tessera/issues/26)–[#31](https://github.com/bgiesbrecht/tessera/issues/31) — six new issues capturing gaps the 0.4.0 migration cycle surfaced. Four of these closed during 0.5.0; #30 (UC ABAC byScope column-mask) and #31 (Snowflake ABAC byScope) remain.
- 31 total issues; 10 closed; 21 open at version close.

### What this version does not include

- **ABAC byScope emission gaps remain queued.** [#30](https://github.com/bgiesbrecht/tessera/issues/30) (UC column-mask) and [#31](https://github.com/bgiesbrecht/tessera/issues/31) (Snowflake row + column) cover the remaining adapter coverage gaps.
- **Tessera CLI thin wrapper** — converter's `python -m tools.converter` is still the only command-line surface.
- **Phase 2 scoping documents for #19 / #21 / #25** — queued for claude.ai.

## [0.4.0] — 2026-05-20

Five-commit increment focused on closing the migration cycle: `discover` and `extract` on Snowflake are no longer stubs, `byDataset` row visibility is implemented on both adapters, and the full Snowflake → Unity Catalog migration runs end-to-end on fresh schemas with adapter-applied bindings carrying the platform translation. ADR-026 adds `AccessGrantConstraint` as the fifth v0 policyKind, closing the table-grants exercise's open question.

### Added

**Spec.**
- **ADR-026** — `AccessGrantConstraint` policyKind added to v0 across `ontology.ttl`, `context.jsonld`, `schema.json`, and `shapes.ttl`. Affirmative-grant policies (`effect: allow` on rules) now have an honest policyKind rather than squeezing into `RowVisibilityConstraint`. Three table-grants exercise YAMLs migrated to the new shape; JSON-LDs regenerated via the v1 converter; all 11 worked-example policies still validate clean. Closes [#15](https://github.com/bgiesbrecht/tessera/issues/15).

**Adapter responsibilities (no longer stubs).**
- **`SnowflakeAdapter.discover(database, schema)`** inventories row-access policies, masking policies, and their attachments on a target schema. Walks `SHOW {ROW ACCESS,MASKING} POLICIES`, `DESCRIBE` for bodies, `INFORMATION_SCHEMA.POLICY_REFERENCES` for attachments.
- **`SnowflakeAdapter.extract(artifact)`** lifts a discovered Snowflake policy into Tessera IR. Pattern-driven over the policy body text; recognizes three shapes the worked exercises have deployed: byDataset / EXISTS-with-mapping-table row-access policies, byIdentity / IS_ROLE_IN_SESSION-branched row-access policies, byIdentity / CASE-WHEN-IS_ROLE_IN_SESSION masking policies. Extracted IR validates against schema + SHACL with confidence ≥ 0.9.

**Adapter emission coverage.**
- **UC byDataset row-visibility emission** — `_emit_row_visibility_by_dataset` produces the row-filter UDF body matching the hand-derived `spec/v0/examples/acl-row-visibility.databricks.sql`. `CREATE FUNCTION ... RETURN EXISTS (SELECT 1 FROM map JOIN acl ... WHERE m.user = current_user() AND p.col = <param>)` + `ALTER TABLE ... SET ROW FILTER`. Uses a fixed parameter alias (`policy_input_value`) to avoid the case-insensitive-identifier collision that would otherwise degenerate the predicate to `col = col` (always TRUE — the bug the second deploy uncovered).

**Tooling.**
- **`adapters/tests/live_snowflake_to_uc_migration.py`** — the first round-trip migration runner. Discovers the policies already deployed on `ACME.TESSERA`, extracts to IR, emits UC DDL, deploys on `acme.tpch`, verifies behavior under the calling user.
- **`adapters/tests/live_migration_demo.py`** — the repeatable, clean-schemas-both-sides migration demo. Eight phases from fresh-Snowflake-schema provisioning through Databricks verification, plus `--cleanup` to teardown. Idempotent; safe to re-run. The runnable answer to the "could we migrate Snowflake → UC by end of day" aspiration.

**Documentation.**
- **`docs/user-guide/scenarios/migrating-snowflake-to-uc.md`** — practitioner-shaped walkthrough of the five-phase migration cycle, with the empirical results from both runs and the two findings the exercise produced as adapter improvements (resource_bindings for data tables; parameter-naming collision in the row-filter UDF).

### Changed

- **`AdapterConfig.bind_principal` / `bind_resource`** are now case-insensitive on the identifier portion after the IRI prefix. Snowflake stores identifiers uppercase; extracted IRs come back uppercase; bindings authored mixed-case would otherwise miss. IRI prefix (`table:`, `column:`, `group:`) stays case-sensitive — the semantic discriminator must not collide.
- **Snowflake byDataset row-visibility emission** now consults `bind_resource()` for the data-table references inside the policy body (mapping table, ACL table). Parallel to the UC fix from earlier in the day. Without this the emitted Snowflake DDL would carry the IR's literal table names (Databricks-shaped) and fail on Snowflake.
- **UC adapter dispatch on the `rules[].principal.selector` axis**: when all rules use `byDataset`, the row-visibility emission routes to `_emit_row_visibility_by_dataset` instead of the byIdentity path.
- **Three `table-grants-scenario-*` artifacts** migrated from `RowVisibilityConstraint + effect: allow` to `AccessGrantConstraint`. JSON-LDs regenerated via the converter.
- **`table-grants.diagnostic.md` §3.4** marked RESOLVED by ADR-026.

### Fixed

- **Row-filter parameter-name collision in UC byDataset emission.** The function parameter `O_ORDERPRIORITY` collided with the bare `o_orderpriority` column reference inside the `EXISTS` subquery; SQL is case-insensitive on identifiers, so Databricks resolved the bare identifier to the column reference, the predicate degenerated to `col = col` (always TRUE), and the filter passed everything. First deployment surfaced 7.5M visible rows; the second deployment with the fix correctly returned only the caller-permitted priorities. Same gotcha the Snowflake adapter solved in 0.2.0; same fix.

### Empirical verification (end of day)

The repeatable migration demo (`adapters/tests/live_migration_demo.py`) runs the full 8-phase cycle on fresh schemas. Under the calling user (`brice.giesbrecht@databricks.com`, in `account users` only):

| Policy | Target object | Visible result |
|---|---|---|
| Group row visibility | `acme.migration_demo.demo_orders` | 59,998 rows (priorities 3-MEDIUM / 4-NOT SPECIFIED / 5-LOW — third branch fires) |
| byDataset row visibility | `acme.migration_demo.demo_orders_rls_acl` | 40,002 rows (priorities 1-URGENT + 2-HIGH — caller's ACL codenames) |
| Column mask | `acme.migration_demo.demo_orders.o_clerk` | `'CLERK-REDACTED'` for all distinct values |

### Issue tracker activity

- **Closed**: [#15](https://github.com/bgiesbrecht/tessera/issues/15) (access-grant-constraint-policykind) by ADR-026.
- **Open at version close**: #3, #4, #5, #7, #8, #9, #11, #12, #13, #14, #16, #17, #18, #19, #20, #21, #22, #23, #24, #25.
- 25 total issues; 5 closed; 20 open.

### What this version does not include

- **`adapters/reconcile()`** still stubbed on both adapters. The full discover/extract/emit/reconcile cycle is three-of-four real now.
- **UC ABAC byScope column-mask emission** still queued. The byScope row-filter path landed in 0.3.0; the column-mask sibling remains the matching coverage gap.
- **Snowflake ABAC byScope** (row + column) — different platform mechanism (object tags + tag-based policy attachment). Out of scope for this version.
- **Tessera CLI thin wrapper** — converter's `python -m tools.converter` is the only command-line surface today; a unified CLI is a deferred convenience.
- **Phase 2 scoping documents for #19/#21/#25** — queued for claude.ai to draft.
- **Reverse-direction extraction shapes** beyond the three the project's worked exercises have deployed. Production extraction would need a SQL AST parser; the regex-driven extractor handles known shapes and reports diagnostics on the rest.

## [0.3.0] — 2026-05-20

Five-commit increment on top of 0.2.0. New tool (YAML → JSON-LD converter), three new adapter emission paths (UC column visibility, UC ABAC byScope row visibility, Snowflake column visibility), new practitioner-shaped tutorial, new W3C-savvy overview, 10 new tracked issues from the governance-gap survey, and the worked-example corpus regenerated with YAML as canonical source.

### Added

**Tools.**
- `tools/converter/` — Python YAML → JSON-LD converter. v1 accepts both envelope-form (`policy: { id, kind, … }`) and flat-form YAML. Mechanical mapping (envelope unwrap, `id → @id` with `policy:` prefix, `kind → policyKind`, context-aware `type → @type`, canonical `@context` injection, trailing-whitespace normalization). CLI: `python -m tools.converter <file> [--out path]`. Library: `tools.converter.yaml_to_jsonld(path)` / `yaml_to_jsonld_str(text)` / `convert_file(in, out)`. Uses `ruamel.yaml` from the start so comment preservation (deferred to v2) is a one-step addition. Regression test covers all 11 worked-example YAMLs.

**Adapter coverage.**
- UC `ColumnVisibilityConstraint` emission — `CREATE OR REPLACE FUNCTION` returning the masked value, `GRANT EXECUTE` adapter scaffolding (per ADR-025 boundary), `ALTER TABLE … ALTER COLUMN … SET MASK`. Live-verified against `acme.tpch.orders.o_clerk`. Covers byIdentity column targets; Redact transformation; Mask/Hash emit `NULL` placeholders pending future scaffold passes.
- UC ABAC byScope `RowVisibilityConstraint` emission — three-piece DDL: `CREATE FUNCTION` with Mechanism B CASE body, `GRANT EXECUTE`, `CREATE POLICY … ON CATALOG/SCHEMA/TABLE … ROW FILTER … FOR TABLES MATCH COLUMNS has_tag_value(<tag_key>, <tag_value>) AS alias USING COLUMNS (alias)`. Exercises `AdapterConfig.tag_taxonomy` (ADR-021). Live-verified against `acme.tpch.orders_abac`.
- Snowflake `ColumnVisibilityConstraint` emission — `CREATE OR REPLACE MASKING POLICY … AS (col VARCHAR) RETURNS VARCHAR -> CASE … END` plus `ALTER TABLE … MODIFY COLUMN … SET MASKING POLICY`. Live-verified against `ACME.TESSERA.SNOW_ORDERS.O_CLERK` with `USE SECONDARY ROLES NONE`; role-discrimination is Intent B (IS_ROLE_IN_SESSION) per Snowflake's recommendation and issue #14.

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
- **Snowflake `byDataset` row visibility** — `ACME.TESSERA.SNOW_ORDERS_RLS_ACL`; four scenarios pass including secondary-roles immunity (`USE SECONDARY ROLES NONE` and `ALL` produce identical row counts because `CURRENT_USER()` ignores role activation). Surfaced one v1 candidate (#13).
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
