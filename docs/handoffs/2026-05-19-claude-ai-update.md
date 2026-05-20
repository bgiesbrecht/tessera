# Tessera — Update for claude.ai (2026-05-19)

**For:** claude.ai, which has been the design-architect collaborator on this project alongside Claude Code (the in-repo implementor). Brice will provide direct repo access; this document synthesizes what has landed since your last substantive input (the ABAC scoping document revision, ~mid-May 2026).

**Purpose:** orient on the current state without rereading every artifact. Pointers into the repo are throughout. Read this once before any design discussion; refer back when uncertain about temporal context.

---

## What's the headline?

Five things happened, in order:

1. **Stage 1 (Databricks ABAC syntax verification) completed.** The scoping document's §6 sketches were corrected against current Databricks ABAC docs. Three real DDL gaps fixed in the sketch: the `FOR TABLES` clause, the `MATCH COLUMNS ... AS alias` requirement, and `ON COLUMN alias`. Design unchanged; sketch refined.

2. **ADRs 018–021 landed** as planned in the scoping doc. The four ABAC additions are now in the decision log. Spec changes (ontology, context, schema, technical design §3–§4) are still pending Stage 4; the four ADRs prefigure them.

3. **Pre-ABAC column-mask exercise ran** as a single-pass / combined-input exercise (Brice shared the existing SQL up front). It surfaced **ADR-022** — the over-tight transformation constraint in the schema, which now correctly says `transformation` is required iff `effect: transform`. Small spec correction; clean.

4. **ABAC column-mask exercise ran** with full blind-derivation. The deliberate two-policy overlap (Redact + Hash, same matching predicate) produced **the discriminating empirical result for ADR-019's α/β/γ question**: Databricks ABAC rejects multi-mask evaluation with a `COLUMN_MASKS_FEATURE_NOT_SUPPORTED.MULTIPLE_MASKS` error. **ADR-023** records the γ-with-refinement resolution.

5. **ABAC row-filter exercise ran** with full blind-derivation. Reinforced the Mechanism A vs B distinction (three branches force B), confirmed cross-policy/cross-mechanism behavior, and surfaced a new v1 candidate (`policy-two-axis-attribute-matching` — issue #12) when Brice's existing implementation revealed a table-level + column-level matching pattern Tessera v0 doesn't model.

The project has effectively moved from "design sketched" to "design validated against three platform-level worked examples, with one substantive design refinement at each."

---

## The four worked exercises in the series so far

| # | Exercise | Mechanism | Phase 3 outcome | Drove |
|---|---|---|---|---|
| 1 | `group-row-visibility-*` | Legacy `SET ROW FILTER` | Group memberships behaved as expected; cache lag ~2–4 min | ADR-014 (Policy container), ADR-015 (first-match), ADR-017 (immutability bar reframing) |
| 2 | `acl-row-visibility-*` | Legacy `byDataset` (two-table join) | Three scenarios passed | Four v1 candidates (#7–#11) around `PrincipalSetFromTable` limitations |
| 3 | `column-mask-orders-clerk-*` | Legacy `ALTER COLUMN ... SET MASK` | Single-pass; structural equivalence confirmed | ADR-022 (schema effect-driven constraint) |
| 4 | `abac-column-mask-*` | ABAC `CREATE POLICY ... COLUMN MASK` | Two-policy overlap → multi-mask rejection | ADR-023 (cross-policy combination resolution) |
| 5 | `abac-row-filter-priority-*` | ABAC `CREATE POLICY ... ROW FILTER` | Scenario 3 verified; structural match tight; one new v1 candidate | Issue #12 (two-axis attribute matching) |

All artifacts live under `spec/v0/examples/` (Phase 2 deliverables) and `docs/exercises/` (Phase 1 inputs). Each exercise produced YAML + JSON-LD + Databricks SQL + diagnostic.md + comparison.md. The diagnostics and comparisons carry the substantive findings.

---

## ADRs since your last touch (017 → 023)

| ADR | Title | One-line summary |
|---|---|---|
| 017 | Immutability bar suspended until external dependency | Replaces ADR-014's date-based immutability claim with an event-based one. |
| 018 | AttributeAxis and the Classification refactor | Four v0 axes (sensitivity hierarchical; dataSubject/regulatoryRegime/businessDomain flat); adopter-extensible. |
| 019 | Scoped policy attachment via `byScope` | catalog/schema/table/column scope, IRI-prefix kind inference, `except` facility, cross-policy combining **deferred**. |
| 020 | Composable attribute matching reuses `byComposition` | Uniform algebra (`match: and|or|not, criteria: [...]`) over attribute leaves; implicit-AND shortcut as sugar. |
| 021 | Adapter configuration mapping pattern | General pattern (tag-taxonomy + identity-binding); strict default with permissive/pass-through alternatives. |
| 022 | Transformation constraint is effect-driven | Schema bug from ADR-016 implementation: `transformation` required iff `effect: transform`, not for all ColumnVis rules. |
| 023 | Cross-policy combination resolution: γ-with-refinement | Closes ADR-019's deferred question. Tessera doesn't pick a combining algorithm; adapters declare platform constraints; emit diagnostics surface conflicts. |

`DECISIONS.md` has the full text. The ADR-023 / ADR-022 framing is especially worth reading because both involved correcting prior decisions; the discipline of "ADRs supersede, not edit" held cleanly.

---

## Where v0 stands

`spec/v0/` post-ABAC content:

- `ontology.ttl` — ADRs 013, 014, 015, 016 landed (Policy container, ordered first-match, transformation parameterization). ADR-022's correction implemented. **ADRs 018–021 spec changes NOT yet landed** — the prefigured ABAC vocabulary lives in the Phase 2 artifacts but not in the ontology yet. Stage 4 is the remaining work.
- `context.jsonld` — same state as ontology.
- `schema.json` — JSON Schema 2020-12; validates the pre-ABAC shapes plus ADR-022's effect-driven transformation constraint. ABAC additions pending Stage 4.
- `examples/` — five worked exercises' artifacts. All current artifacts validate against the current schema (the ABAC-shape artifacts will validate against the post-Stage-4 schema; they currently use the prefigured vocabulary and don't conflict with the existing schema rules).
- `shapes.ttl` — **not yet created**. SHACL shapes are the next priority item.

The "v0 immutability bar suspended" framing from ADR-017 continues to hold. No external consumer has built against v0; spec changes remain admissible and have been landing one ADR at a time.

---

## Open issues — 12 total

Resolved / closed by ADRs:
- #1 (policy-container), #2 (default-branch-predicate) — closed by ADR-014.
- #6 (adapter-capability-profile-timing-disclosure) — closed-on-arrival when §5.2 paragraph landed.

Deferred (low priority):
- #3 (principal-in-group-condition) — obviated by container; commented as deferred-not-needed-yet.

Open as queued v0 doc / adapter work:
- #4 (iri-safety-convention)
- #5 (adapter-emission-pattern-recognition)

Open as v1 candidates from worked exercises:
- #7 (principal-set-from-joined-tables) — ACL exercise
- #8 (principal-set-match-modifiers) — ACL exercise
- #9 (exists-in-dataset-operand-formalization) — ACL exercise
- #10 (policy-execute-grants) — recurring across all exercises
- #11 (acl-integrity-checks) — ACL exercise, lower priority
- #12 (policy-two-axis-attribute-matching) — ABAC row-filter exercise, just filed

Issue tracker: <https://github.com/bgiesbrecht/tessera/issues>

---

## Design questions resolved since your last input

1. **Mechanism A vs Mechanism B** (where principal logic lives — policy header vs UDF body). The ABAC column-mask exercise surfaced this distinction (binary exempt/not-exempt → A; multi-branch → B forced). Tessera v0's IR shape essentially mandates Mechanism A; multi-branch exercises (like the row-filter exercise) collapse to Mechanism B at SQL emission via a single CASE-based UDF.

2. **Cross-policy combination on the same effective resource** — γ-with-refinement per ADR-023. Tessera doesn't pick an algorithm; adapters declare platform constraints; emit diagnostics surface conflicts.

3. **GRANT SELECT on the protected table** (initially flagged as a Tessera IR gap; corrected via Glean) — it is **deployment scaffolding for new tables**, not a policy concern. The IR correctly does not model it. Note: a corresponding lesson was written to Claude Code's memory file — verify Databricks platform claims via Glean before flagging them as IR findings.

4. **Transformation constraint scope** — effect-driven, not policy-kind-driven. ADR-022.

5. **Immutability bar timing** — condition-based (external dependency), not date-based (commit chain). ADR-017.

---

## Design questions still open

1. **The two-axis matching design** (issue #12). Tessera's `matching.attributes` is single-axis (column-level). ABAC supports two-axis (table-level via `WHEN`, column-level via `MATCH COLUMNS`). Brice's existing impl uses the two-axis pattern as the safe-migration recommendation alongside legacy mechanisms. Worth designing into v0 or holding for v1 — the choice has the same shape as the ADR-013/014/017 sequence (small structural addition during the suspended-immutability window).

2. **Stage 4 spec changes for ADRs 018–021.** Five files need updating per the ADRs' Consequences sections: ontology, context, schema, technical design §3 + §4, and the technical design adapter-contract section. The worked examples have validated the design; the spec changes are the mechanical implementation. **Suggested timing:** drive this work soon, because the next exercises (and SHACL shapes, and the converter) all want to see the post-ABAC vocabulary in the actual spec files.

3. **Mechanism-A-vs-B documentation.** ADR-022 fixed the schema; the technical design §4.2.2 was also updated. But the **design distinction** itself (when do you use Mechanism A vs B, what does Tessera prefer) doesn't yet have a dedicated paragraph. Worth a short addition to the technical design adapter-contract section so the principle survives turnover.

4. **The recurring "ELSE form" finding.** Brice's row-visibility impls consistently use `NOT IN ('1-URGENT', '2-HIGH')` for the default branch; Tessera derivations consistently use `IN ('3-MEDIUM', '4-NOT SPECIFIED', '5-LOW')`. Both expressible in the IR; the inputs templates have specified enumeration. This is a UX/documentation finding, not a spec gap.

5. **The recurring "scope choice" finding.** Brice prefers schema scope; Tessera defaults to catalog. Worth making explicit in the Phase 1 inputs template so this stops showing up in every comparison.

---

## What's next on the project's path

Per CLAUDE.md's priority order (which now reflects the suspended-immutability framing and the ABAC work):

- **Priority 2 (in progress)** — ABAC work. ADRs landed, exercises run, ADR-023 resolution; remaining: **Stage 4 spec changes** for ADRs 018–021 and the v0 doc updates from issues #4, #5.
- **Priority 4** — SHACL shapes (`spec/v0/shapes.ttl`). Brice just authorized starting this; it's the next concrete deliverable.
- **Priority 5** — Converter tool (YAML ↔ JSON-LD).
- **Priority 6** — First adapter scaffolding (Unity Catalog).

SHACL shapes work begins after this update doc lands.

---

## What claude.ai might want to weigh in on

Listed in rough order of consequence:

1. **Stage 4 spec changes ordering.** Do them now (before SHACL/converter/adapter) to give downstream work the right vocabulary? Or do them as part of the SHACL shapes work (since SHACL validates the ontology and benefits from a clean reference)? My recommendation: do them now, before SHACL. SHACL writes shapes against the ontology; the ontology should be complete first.

2. **Two-axis matching (issue #12) — backport candidate?** Same precedent as ADRs 013/014: the design surface is real, the immutability bar is suspended, the cost of waiting until v1 compounds. The scoping document treated all ABAC-related work as "lands in v0 per ADR-017." This new candidate is structurally similar.

3. **`policy-execute-grants` (issue #10) recurring across all exercises.** Five out of five exercises have surfaced GRANT EXECUTE asymmetry. Worth designing v0-time. The actual design (an `executeGrants` field on Policy that names principals authorized to invoke the policy's compiled UDF) is small.

4. **The recurring scope-choice and ELSE-form findings.** These are inputs-template issues — the Phase 1 inputs document should prompt the author for the scope level and the default-branch idiom explicitly so they stop being divergence points. Small change; non-load-bearing.

5. **Whether the worked-example series should continue or pause.** Five exercises have now covered the main design surface (row visibility, ACL-table-driven, column mask, ABAC column mask, ABAC row filter). The next exercises (if any) would target either: ABAC + hierarchical-axis subsumption (the deferred Policy B design from the column-mask exercise), cross-platform (a Snowflake adapter exercise), or operational testing (multi-policy load tests). Pausing and consolidating (Stage 4 spec changes + SHACL + converter) is also defensible. My recommendation: pause exercises; consolidate; resume when a new design question demands evidence.

---

## Where to read in the repo

| Concern | Primary doc | Supporting docs |
|---|---|---|
| Current state of v0 | `CLAUDE.md` "Where the user is in the work" | `DECISIONS.md` |
| ABAC design | `docs/v1-candidates/abac-and-attribute-axes.md` (the scoping doc, after your revisions) | ADRs 018–023 |
| Worked exercise findings | `spec/v0/examples/*.diagnostic.md` and `*.comparison.md` | The corresponding `.tessera.yaml` / `.databricks.sql` |
| Immutability framing | ADR-017 + ADR-014's superseded closing note | `CLAUDE.md` "What exists" section |
| Cross-policy combination | ADR-023 | `abac-column-mask.comparison.md` §2 (the empirical observation) |
| Two-axis matching question | Issue #12 | `abac-row-filter-priority.comparison.md` §3.3 |
| Memory for Claude Code | `~/.claude/projects/-Users-brice-giesbrecht-development/memory/MEMORY.md` and linked entries (notably the Glean-for-Databricks-semantics note) | — |

This document does not duplicate anything in those sources; it points and synthesizes.

---

## Note on the cross-tool collaboration

Claude Code (in-repo, has tool access) and claude.ai (web-based, design partner) have been collaborating across the worked-example series. The pattern that's emerged:

- **claude.ai drafts design documents** that articulate the architectural shape (scoping doc, comparison templates, principle reframings like the §5.2 timing-disclosure correction).
- **Claude Code grounds them in the repo** — writing ADRs, spec files, worked-example artifacts, running empirical observations, surfacing findings against actual platform behavior.
- **Brice mediates and corrects** when either side overreaches or misframes (notable corrections: the Glean-for-platform-semantics lesson, the GRANT SELECT correction, the Mechanism A/B framing).

The relationship is genuinely complementary; neither would have produced the current state alone. This update doc is the explicit synchronization point — claude.ai catches up on what's in the repo before contributing the next design layer.

The next natural collaboration moment is the Stage 4 spec changes (mechanical but substantial) and the design question on whether to backport issue #12. claude.ai's design-shape input on the latter would be valuable before any ADR drafts.

---

# Update appended later same day (2026-05-19 PM)

The morning snapshot above remains accurate as a point-in-time read. The afternoon shipped substantially more than the "What's next" section anticipated. This update covers what happened since.

## Headline since midday

1. **Stage 4 spec changes landed.** ADRs 018–021 are now reflected in the actual `spec/v0/` files — ontology.ttl, context.jsonld, schema.json, and technical-design-v0.2.md §3.3 / §3.3a / §4.9 / §4.10 / §5.6 / §5.7. All seven worked-example JSON-LDs validate cleanly against the post-Stage-4 schema.
2. **SHACL shapes shipped (`spec/v0/shapes.ttl`).** Priority 4 done. Closes the validation pipeline at the semantic layer; covers what JSON Schema cannot (closed vocabularies, IRI/class typing, node-shape composition). The conditional-dependency constraints (baselineGroup↔defaultStrategy, transformation↔effect, etc.) are deliberately deferred to JSON Schema — the pragmatic split is documented in shapes.ttl and CLAUDE.md.
3. **Adapter contract + both implementations scaffolded simultaneously.** Unity Catalog and Snowflake adapters were built in the same commit, pressure-testing the contract from two platforms at once. ADR-024 records the contract shape (Adapter ABC, `CapabilityProfile`, `Diagnostic`, `AdapterConfig` with `identity_bindings` + `resource_bindings` + `tag_taxonomy`, structured Result types). Adapters never execute; the caller composes execution.
4. **First live cross-platform exercise ran end-to-end.** Same Tessera IR (`group-row-visibility-policy-a.jsonld`) lowered through both adapters and executed against `acme.tpch.orders` on Databricks (7.5M rows) and `ACME.TESSERA.SNOW_ORDERS` on Snowflake (1.5M rows). Both row filters enforce correctly. Findings recorded in ADR-024's postscript and in the Snowflake adapter's capability profile.

## Updated worked-exercises table

The series now has six entries; the sixth is the cross-platform live exercise:

| # | Exercise | Mechanism | Phase 3 outcome | Drove |
|---|---|---|---|---|
| 1 | `group-row-visibility-*` | Legacy `SET ROW FILTER` | Group memberships behaved as expected | ADR-014, ADR-015, ADR-017 |
| 2 | `acl-row-visibility-*` | Legacy `byDataset` two-table join | Three scenarios passed | Four v1 candidates (#7–#11) |
| 3 | `column-mask-orders-clerk-*` | Legacy `ALTER COLUMN ... SET MASK` | Single-pass; structural equivalence | ADR-022 |
| 4 | `abac-column-mask-*` | ABAC `CREATE POLICY ... COLUMN MASK` | Two-policy overlap → multi-mask rejection | ADR-023 |
| 5 | `abac-row-filter-priority-*` | ABAC `CREATE POLICY ... ROW FILTER` | Scenario 3 verified; new v1 candidate | Issue #12 |
| 6 | **Cross-platform live emission** | UC `is_account_group_member` + RAP `IS_ROLE_IN_SESSION` | Both adapters' DDL deployed and enforced from the same IR | ADR-024, `AdapterConfig.resource_bindings`, Snowflake secondary-roles + mapping-table findings |

Exercise 6 artifacts: `adapters/tests/live_databricks.py`, `adapters/tests/live_snowflake.py`. Both are re-runnable for regression checks.

## ADRs since the morning snapshot

| ADR | Title | One-line summary |
|---|---|---|
| 024 | Adapter contract shape | `Adapter` ABC + `CapabilityProfile` (closed `Capability` enum) + structured Result types + `AdapterConfig`. Adapters never execute. ADR landed alongside the first concrete UC and Snowflake scaffolds; postscript records the cross-platform live findings. |

## Where v0 stands (refresh)

- `ontology.ttl` — **Stage 4 complete.** AttributeAxis class + four well-known axes (sensitivity hierarchical; dataSubject / regulatoryRegime / businessDomain flat) + per-axis Resource properties + byScope NamedIndividual + scope/except/matching properties + AttributeMatcher. Also fixed adjacent-string Turtle syntax (rdflib parsing).
- `context.jsonld` — Stage 4 complete.
- `schema.json` — Stage 4 complete. All seven worked-example JSON-LDs validate.
- `shapes.ttl` — **landed.** 360 triples; positive coverage on all seven examples; seven negative tests caught (unknown policyKind, unknown action, unknown selector, unknown effect, unknown defaultStrategy, unknown condition op, canonical-form unknown axis IRI).
- `adapters/` — **new directory.** Contract + UC + Snowflake + tests. README and ADR-024 explain the shape.

## Design questions resolved since the morning snapshot

1. **`AdapterConfig.resource_bindings`** — the same IR target (`table:acme.tpch.orders`) lowers to two different platform identifiers (`acme.tpch.orders` vs `ACME.TESSERA.SNOW_ORDERS`). Surfaced live during the Snowflake exercise; added as a first-class field alongside `identity_bindings`. ADR-021's "configuration mapping pattern" is now mechanically concrete on both axes (identity + resource).

2. **Snowflake's `DEFAULT_SECONDARY_ROLES = ("ALL")` default is a real operator concern, not just a testing-mode oddity.**
   - The setting is a **user property**, not a session parameter (verified: `SHOW PARAMETERS LIKE '%SECONDARY%' IN SESSION` returns nothing; `DESCRIBE USER` exposes `DEFAULT_SECONDARY_ROLES = ["ALL"]`).
   - Snowflake's BCR-1692 rolled this out as the default Aug 2024 → Mar 2025, motivated by Notebooks / Snowpark Container Services / UBAC.
   - With ALL active, `IS_ROLE_IN_SESSION(X)` returns true for every granted role, collapsing role discrimination at policy-evaluation time.
   - Per-session override is `USE SECONDARY ROLES NONE | ALL | r1, r2, ...`; durable production fix is `ALTER USER <name> SET DEFAULT_SECONDARY_ROLES = (...)`.
   - Snowflake's own canonical answer for role-discriminating policies is **the mapping-table pattern** — author against a centralized authorization table joined by `CURRENT_USER()` / `CURRENT_ROLE()`, not against role membership directly. **This is structurally identical to Tessera's `byDataset` + `PrincipalSetFromTable`** (the custom-ACL pattern that drove ADR-003). The Snowflake adapter naturally aligns with Snowflake's recommended pattern when IR authors use `byDataset`.

3. **Role hierarchy ≠ group membership.** Snowflake roles inherit (HIGH inherits PUBLIC ⇒ HIGH-active sessions satisfy PUBLIC's predicates); Databricks groups are flat. Same IR; different effective row-set arithmetic. Now in the Snowflake adapter's capability-profile rationale for `ROW_VISIBILITY`.

## Design questions still open (with new entries)

Carrying forward from the morning list:
1. Two-axis matching design (issue #12). Unchanged.
2. Mechanism-A-vs-B documentation. Partially addressed by ADR-024's contract framing; arguably still wants a dedicated technical-design paragraph.
3. The recurring "ELSE form" finding. Unchanged.
4. The recurring "scope choice" finding. Unchanged.

New entries from the afternoon:
5. **Should `byDataset` be the recommended Snowflake authoring pattern?** The mapping-table alignment is striking. The implication: IR authors targeting Snowflake should prefer `byDataset` + an ACL table over inline `byIdentity` with per-role bindings, because (a) it sidesteps the secondary-roles issue, (b) it matches Snowflake's documented best practice, (c) it isolates role-taxonomy changes to a table update instead of policy re-emission. The user-documentation pass needs to decide whether to present `byDataset` as the recommended Snowflake pattern explicitly, or leave it as one of several authoring styles.

6. **Capability-profile diagnostic vocabulary convergence.** ADR-024 declared diagnostic-code naming converges by convention, not enforcement. The UC and Snowflake adapters have started using parallel codes (`UNIMPLEMENTED_POLICY_KIND`, `UNSUPPORTED_PRINCIPAL_SELECTOR`, `ROW_FILTER_NO_COLUMN_ARG` vs `ROW_POLICY_NO_COLUMN_REF`). Worth deciding whether to formalize a shared diagnostic taxonomy in the contract module before a third adapter (`custom-acl`) drifts.

7. **Deployment-time configuration verification — sharpened scope (per claude.ai design-review 2026-05-19 PM).** The initial framing of `verify` ("any user with conflicting role grants and `DEFAULT_SECONDARY_ROLES = ('ALL')` will see the union, not the active branch") conflated two distinct concerns that the design review correctly separated:

    - **Platform structural assumptions** the adapter relies on — table exists, column types match the emission's expectations, required schema present, ACL table accessible. These are genuinely outside the policy author's choice. **True `verify` territory.**
    - **Policy intent ambiguities** the author resolves at authoring time — Intent A vs Intent B for role discrimination, case-sensitivity behavior on principal columns, primary-vs-active role semantics. These are NOT verify territory; they are resolved by IR shape or adapter configuration (per ADR-021), not by adapter-time verification of the deployed environment.

    The `DEFAULT_SECONDARY_ROLES` situation initially flagged as a verify candidate falls in the second category, not the first. It is filed under refined framing as issue [#14](https://github.com/bgiesbrecht/tessera/issues/14) — Snowflake role-discrimination semantics — under ADR-021's adapter-configuration-mapping pattern, deferred until an exercise drives the Intent A case.

    What this means for the `verify` open question: the set of things worth verifying is smaller than the original framing implied. claude.ai's design read produced the distinction; the path forward on `verify` (whether it becomes a fifth adapter method, a sub-mode of `reconcile`, or stays informal) should be scoped against the *structural-assumptions* set specifically, not the broader "deployment correctness" framing. Three concrete structural checks plausibly worth verifying on Snowflake: target table exists; target column exists with the expected type; required ACL tables exist and are SELECT-able by the role that will execute the policy body.

    Three artifacts were re-framed in this same pass to drop the "gotcha" framing of `DEFAULT_SECONDARY_ROLES`: `adapters/snowflake/capability.py` ROW_VISIBILITY entry, ADR-024 postscript finding #3, and `docs/user-guide/operating.md` § Role-discrimination semantics. The byDataset-as-Snowflake-preferred recommendation in user-guide stands but with a refined reason: byDataset gates on `CURRENT_USER()`, which is orthogonal to role activation — the two-semantics question does not arise, rather than the byDataset path being immune to a platform misfeature.

## What's next (refresh)

Of the morning's listed priorities, three are done (Stage 4, SHACL, adapter scaffold). Remaining:

- **Priority 5 — Converter** (YAML ↔ JSON-LD, comment preservation per ADR-004). Still queued.
- **User documentation** (newly explicit). The cross-platform exercise has clarified what authors need to know: tag taxonomy mapping, identity binding, resource binding, the Snowflake secondary-roles caveat, the mapping-table pattern recommendation. This is the immediate next deliverable per Brice.
- **`adapters/custom-acl/`** — third adapter from ADR-003's reference customer engagement. Inherits the contract as it stands today; if their platform strains the shape, new ADRs amend ADR-024 (not silent edits).
- **Stage-4-followup spec gaps from issues #4, #5** — still queued, lower-priority than user docs.

## What claude.ai might want to weigh in on (refresh)

Carrying forward the morning's list (items 2, 3, 4, 5 unchanged). New entries since this afternoon:

- **The `byDataset`-as-Snowflake-preferred-pattern framing.** Worth design input before it lands as user-documentation framing. The structural alignment with Snowflake's own best practice is real and reads cleanly in retrospect; the question is whether to lead with it or treat it as one option among several.
- **Diagnostic vocabulary convergence.** Should the contract module own a shared enum of well-known diagnostic codes (so `UNSUPPORTED_PRINCIPAL_SELECTOR` means the same thing in every adapter), or stay convention-based until a third adapter actually drifts?
- **`verify` as a fifth adapter responsibility.** The Snowflake secondary-roles check doesn't fit cleanly under `discover` / `extract` / `emit` / `reconcile`. claude.ai's architectural read on whether this expands the contract or shoehorns into an existing responsibility would help before user docs commit to a framing.

## Where to read in the repo (delta)

| Concern | Pointer |
|---|---|
| Adapter contract shape | `adapters/contract/` + `adapters/README.md` + ADR-024 |
| Live cross-platform results | `adapters/tests/live_databricks.py`, `adapters/tests/live_snowflake.py` (re-runnable) |
| Snowflake secondary-roles finding | ADR-024 postscript + `adapters/snowflake/capability.py` ROW_VISIBILITY entry |
| Snowflake mapping-table alignment with `byDataset` | This document (above) |
| Stage 4 spec changes | `spec/v0/ontology.ttl`, `spec/v0/context.jsonld`, `spec/v0/schema.json`, `docs/technical-design-v0.2.md` §3.3 / §3.3a / §4.9 / §4.10 / §5.6 / §5.7 |
| SHACL shapes | `spec/v0/shapes.ttl` + validation note in CLAUDE.md Priority 4 |

## A note on velocity

The morning snapshot anticipated SHACL, Stage 4, and one adapter as multi-day work. All three landed plus a cross-platform live exercise in a single working session. Worth recording the pattern: with the contract shape settled (ADR-024) and the worked-example series having pre-validated the IR design, downstream infrastructure work moves much faster than the upstream design work did. This isn't a claim that subsequent work will be similarly fast — the converter and the `custom-acl` adapter involve genuinely new design surfaces — but the spec → validators → adapters chain that took weeks to design ran cleanly through implementation in hours once the design was settled.
