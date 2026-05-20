# Tessera — Handoff to Claude Code

**Purpose:** This document is for Claude Code, working in the `bgiesbrecht/tessera` repository. It transfers the context from the design conversation that produced the current state of the repo. Read this once before any non-trivial work; refer back when uncertain about direction.

**How to use this document:** Read it before reading any specific file in the repo. Then read `DECISIONS.md`. Then read whatever specific files the task at hand requires. Most of the content here will not be relevant to most tasks; the value is having it available so that when an instruction sounds odd or a direction seems unclear, the answer is probably in here or in the ADRs.

---

## What Tessera is, in 60 seconds

Tessera is a portable representation of data governance policy. It lets organizations running multiple data platforms (typically Databricks alongside Snowflake) express what their access policies *mean* once, in a vocabulary that is independent of any platform, and translate that meaning into native enforcement on each platform via adapters.

The value proposition is **semantic interoperability of policy**: an agreement that "PII," "fraud investigation purpose," "EU residency," and "audit-log obligation" mean the same thing wherever they are enforced.

The project does *not* deliver:
- A runtime enforcement engine. Tessera compiles to platform-native enforcement; it does not insert into the query path.
- Operational interoperability (policy behavior on data physically moving between platforms via Delta Sharing or Iceberg). Reserved space; not in scope for v0.
- A universal authorization language. Scope is data-platform governance specifically.

For customers running only Databricks, Tessera is not applicable — Unity Catalog already does what they need.

---

## How to operate in this repository

### The decision log is authoritative

`DECISIONS.md` contains numbered ADRs (Architecture Decision Records). Every significant choice in the project is recorded there. Read it before proposing changes that touch architecture, scope, naming, or posture.

When a user request conflicts with a recorded ADR, the right response is to flag the conflict and reference the ADR by number, not to silently override the decision. If the user wants to change a recorded decision, propose adding a new ADR that supersedes the old one — do not retroactively edit ADRs.

The ADRs cover, at a high level: project framing and posture, architectural choices about the IR and adapters, vocabulary alignment with standards, the canonical name and license, repository hosting decisions, and specific IR-design refinements that emerged during early work. The authoritative current list lives in `DECISIONS.md`; do not maintain a parallel enumeration here.

### When unsure, ask before drifting

The skunkworks posture (ADR-002) is fragile and depends on the project not overreaching. If a request would push Tessera toward becoming a standards-body submission, an official Databricks product, or a runtime enforcement engine, surface the tension rather than implementing silently. The user (Brice) makes those calls.

### Voice and tone

The project speaks as an honest engineering effort, not a marketing initiative. It is direct about what it is, what it isn't, and what's uncertain. It does not oversell. It does not bury limitations. When emitting code, documents, or commit messages, this voice should be preserved. Read the README for the tone calibration.

The project is also explicit about its political position: Unity Catalog is the source of truth for governance *inside* Databricks; Tessera operates between governance estates. This concession is irreducible and load-bearing. Documents that contradict it produce internal Databricks friction that the project cannot survive.

---

## Current state of the repository

### What exists

```
README.md                         — front door, project overview
LICENSE                           — Apache 2.0
DECISIONS.md                      — numbered ADRs covering all major decisions
docs/
  executive-summary.md            — one-page leadership brief
  problem-and-recommendation.md   — stakeholder framing, no implementation
  technical-design-v0.2.md        — current technical specification
  stakeholder-meeting-agenda.md   — decision-meeting template
spec/v0/
  context.jsonld                  — JSON-LD context, v0 (immutable)
  ontology.ttl                    — OWL/Turtle ontology, v0 (immutable)
  schema.json                     — JSON Schema 2020-12 for IR structural validation
  shapes.ttl                      — SHACL shapes for semantic validation (Priority 4, complete)
  examples/                       — worked policy examples in YAML and JSON-LD
adapters/                         — adapter contract + first two implementations (scaffold, 2026-05-19)
  contract/                       — Adapter ABC, CapabilityProfile, DiagnosticReport, AdapterConfig
  unity_catalog/                  — Databricks adapter (row-visibility emission live; other paths stubbed)
  snowflake/                      — Snowflake adapter (parity coverage with UC for row-visibility)
  tests/test_parity.py            — same IR → both adapters → meaningfully different SQL
```

### What's planned but not built (in rough order of priority)

```
tools/
  converter/                      — YAML ↔ JSON-LD converter
  linter/                         — full validation pipeline
adapters/
  custom-acl/                     — third adapter (real customer engagement); contract inherits from contract/
```

### Canonical URLs

These resolve via GitHub Pages once Pages is enabled for the repo (ADR-011):

- Namespace: `https://bgiesbrecht.github.io/tessera/spec/v0/vocab#`
- Context: `https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld`
- Ontology: `https://bgiesbrecht.github.io/tessera/spec/v0/ontology.ttl`

The contents of `spec/v0/` are **conditionally immutable**: they become immutable when external dependency exists (a customer policy file references the v0 URL in production, an external adapter is deployed, third-party tooling depends on the v0 shape, or an external collaborator contributes). Until that condition is met, v0 remains malleable and admits additions and corrections per the discipline recorded in ADR-017. The published URLs above will not silently change once external consumers exist.

This is a substantive correction to an earlier framing in ADR-014's closing note. ADR-017 supersedes that note: the immutability bar is a condition (external dependency), not a date (the ADR-014 commit chain). Read ADR-017 if uncertain about whether a proposed change is admissible.

---

## The architecture, briefly

Three forms of policy exist:

1. **YAML** (`.tessera.yaml` files). Primary authoring form. What customers and engineers write and review. Lives in the customer's repository.
2. **JSON-LD.** Canonical form. The normative serialization defined by the spec. Generated from YAML by tooling. Consumed by validators, reasoners, and adapters.
3. **DSL.** Future third form, deferred per ADR-006. Designed only after the IR has stabilized through real corpus exposure and at least two adapter implementations.

Adapters connect the IR to real systems. Each adapter has four responsibilities: discovery (inventory policy-bearing artifacts), extraction (lift to IR), emission (lower from IR), and reconciliation (diff state). Each adapter declares a capability profile listing which IR concepts it supports, partially supports, or cannot support. Diagnostic reports are first-class artifacts of every emit operation.

Adapters are *peers*. Unity Catalog adapter, Snowflake-native adapter, and custom-pattern adapters all implement the same contract. The IR layer is platform-neutral by design — privileging one platform there would defeat the project.

Two v0 IR details worth knowing about up front because the first worked example surfaced them and they reshape how policies are written:

- **`tessera:Policy` container (ADR-014).** The canonical top-level shape for any multi-rule policy. A `Policy` holds policy-level metadata (`appliesTo`, `defaultStrategy`, `baselineGroup`, `defaultBranch`, `policyKind`) plus an ordered `rules` list. The pre-ADR-014 `@graph`-of-constraints shape is deprecated for multi-branch policies (still accepted during the v0 lifecycle for backward compat; not accepted at v1 cut). Single-rule policies may still use a freestanding `PolicyConstraint` at document root. See `docs/technical-design-v0.2.md` §4.2 and ADR-014.
- **`defaultStrategy` and `defaultBranch` (ADR-013, ADR-014).** Policies carry an optional `defaultStrategy` field (`explicit-baseline-group`, `negated-complement`, `none`) capturing *intent* about how the policy handles principals matching no rule. Two policies with the same observable behavior may differ in `defaultStrategy`, and the difference is real. Under `explicit-baseline-group`, `baselineGroup` is required; under `negated-complement`, `defaultBranch` is required; both forbidden otherwise. See §4.6 of the technical design.

Multi-rule Policies use **ordered first-match** combining (ADR-015). The first rule whose principal selector and condition both match wins; subsequent rules don't evaluate. If no rule matches, `defaultStrategy` controls the fallback.

Another v0 IR detail worth knowing: column-visibility transformations are referenced as structured `TransformationInstance` objects, not bare class names. A redaction policy carries `transformation: {type: Redact, replacement: 'value'}`, not `transformation: Redact`. Per-transformation parameter shapes are defined for `Redact` (required `replacement`), `Mask` (`maskChar`, `preserveFirst`, `preserveLast`), and `Hash` (`algorithm`); `Tokenize` and `Bucketize` are valid types but their parameter shapes are deferred. See `docs/technical-design-v0.2.md` §4.8 and ADR-016.

A foundational principle worth absorbing: **Tessera expresses meaning, not mechanism.** When a policy references "PII columns" or "EU-resident customer data," the IR carries the semantic attribute (`sensitivity: PII`, `dataSubject: EUResident`), not the platform-specific mechanism that identifies it (governed tags on Databricks, object tags on Snowflake, classification tables elsewhere). The same Tessera policy is portable across platforms because the meaning is preserved; the platform translation is the adapter's job, configured via per-environment tag-taxonomy mappings.

This principle has practical consequences: do not introduce a `Tag` class to the IR (that models mechanism, not meaning). Do not put platform-specific tag references in policy files. Do not model coordination labels (`team: fraud-ops`, `cost-center: 12345`) as data attributes — those are operational metadata. The IR's vocabulary stays semantic; the adapter's configuration handles platform mechanics. See `docs/v1-candidates/abac-and-attribute-axes.md` for the design that formalizes this for ABAC support.

---

## What to do next — recommended priorities

These are not strict orderings; the user may redirect. But this is what the project most needs:

### Priority 1 — Enable GitHub Pages and verify URLs resolve

Settings → Pages → Source: deploy from a branch (main, root). Once it builds, verify:

```bash
curl -I https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld
curl -I https://bgiesbrecht.github.io/tessera/spec/v0/ontology.ttl
```

Both should return 200. Content types will be wrong (`.ttl` and `.jsonld` served as `text/plain` by default); this is acceptable for v0 and not worth fixing unless tools choke on it.

### Priority 2 — ABAC support and attribute axes (in flight)

The two row-visibility worked examples (group-based and ACL-table) are complete. The next substantial design work is adding ABAC support to v0: orthogonal attribute axes, scoped policy attachment, composable attribute selectors, and tag-taxonomy mapping as adapter configuration.

The scoping document is `docs/v1-candidates/abac-and-attribute-axes.md`. The directory name (`v1-candidates`) is historical — these additions now land in v0 per ADR-017. The scoping document proposes four structural additions to v0 and outlines a worked exercise to validate them.

The framing principle is **View 2: meaning over mechanism**. Tessera expresses *what* policies decide about data (semantic attributes like "PII" or "EU resident"), not *how* the platform records those attributes (governed tags on Databricks, object tags on Snowflake, classification tables elsewhere). The IR carries axes and values; the adapter handles the mechanism translation via per-environment tag-taxonomy configuration.

What lands when this work completes:

- ADR-018 through ADR-021 (or fewer ADRs if the design consolidates), covering attribute axes, scoped attachment, composable matching, and taxonomy mapping.
- Updates to `spec/v0/ontology.ttl`, `spec/v0/context.jsonld`, `spec/v0/schema.json`.
- Updates to `docs/technical-design-v0.2.md` §4.
- A worked exercise (column masking driven by a `sensitivity: PIIClerk` attribute, with Databricks ABAC emission and a Snowflake-adapter sketch) validating the design.

The user may need to construct an ABAC example in the test notebook to enable Phase 3 verification. The current notebook does not use ABAC; the existing examples use per-table row filters and column masks (the older mechanism). This is itself a finding: the framework's first adapter cannot credibly claim Databricks coverage without ABAC support, because ABAC is what Databricks now recommends.

A separate, deferred ACL-table-driven exercise (using the `byDataset` selector and a custom-pattern adapter) is also tracked but completed in an earlier round.

### Priority 3 — JSON Schema for structural validation (done)

`spec/v0/schema.json` exists. JSON Schema 2020-12; structural validation only, per §4.2 of the technical design. Validates both single-policy and `@graph` documents. Enforces conditional dependencies (e.g., `baselineGroup` required when `defaultStrategy` is `explicit-baseline-group`; `transformation` required iff `@type` is `ColumnVisibilityConstraint`). Semantic constraints (CURIE resolution, classification membership) are deliberately left for SHACL.

Validated against the worked-example artifacts and the technical-design §4.5 ACL example.

### Priority 4 — A first cut of SHACL shapes (complete, 2026-05-19)

`spec/v0/shapes.ttl` exists and validates all seven worked-example JSON-LD policies. The shape coverage is intentionally scoped to the semantic checks JSON Schema cannot perform: closed vocabularies (policyKind, action, effect, defaultStrategy, condition operator, selector kind), IRI/class typing of axis references (AttributeAxis), and node shapes invoked via `sh:node` (the JSON-LD `@type` is not asserted on blank nodes, so `sh:targetClass` is unreliable). Conditional dependencies (baselineGroup↔defaultStrategy, defaultBranch↔defaultStrategy, transformation↔effect, selector-kind→required-fields, transformation-type→required-params) are deliberately deferred to the JSON Schema layer; SHACL would express them as verbose `sh:or`/`sh:not` biconditionals with no additional safety beyond what the schema already provides. The shapes file also surfaced one semantic clarification worth recording: `defaultBranch` carries no `principal` (it applies to whichever principals match no preceding rule), so the rule-shape requirement of `principal` does not extend to it. This is implicit in ADR-014 and now also visible in shapes.ttl's comment.

### Priority 5 — The converter tool (v1 complete, 2026-05-20)

`tools/converter/` — Python YAML → JSON-LD converter. v1 scope:
- **Envelope-form** YAML (the practitioner shape: `policy: { id, kind, ... }`) and **flat-form** YAML (JSON-LD-shaped YAML used in earlier worked examples) both accepted.
- Mechanical mapping: envelope unwrap, `id → @id` with `policy:` prefix injection, `kind → policyKind`, context-aware `type → @type` (datasets and operands convert; transformation `type` stays — the schema explicitly requires lowercase).
- Canonical `@context` URL injected at root.
- Trailing-whitespace normalization on string values (handles YAML block-scalar artifacts).
- CLI entry: `python -m tools.converter <file.tessera.yaml> [--out path]`.
- Library entry: `yaml_to_jsonld(path)`, `yaml_to_jsonld_str(text)`, `convert_file(in, out)`.
- Regression test: all 11 worked-example YAMLs convert structurally-equivalent to the committed JSON-LDs.
- `ruamel.yaml` used from the start (sets up comment-preservation as a future v2 increment, not a refactor).

v1 deferred:
- **Comment preservation** per ADR-004 (positional YAML round-trips; `rdfs:comment` mapping on YAML → JSON-LD). Architecture is comment-preservation-ready (round-trip ruamel parser); the feature is a follow-up.
- **JSON-LD → YAML direction.** Single-direction (YAML as source of truth) covers the practitioner path. Reverse direction belongs with the adapter extraction story (migration use case).
- **Descriptive-field drift in the existing corpus** — 5 of 11 examples have prose differences between their YAML and committed JSON-LD (the regression test surfaces these as informational findings). A follow-up regeneration commit would zero this out by re-running the converter against every YAML and committing the new JSON-LDs as the canonical form.

### Priority 6 — Adapter scaffolds (complete, 2026-05-19)

Two adapters were scaffolded simultaneously (Unity Catalog and Snowflake) to pressure-test the contract from two platforms at once. ADR-024 records the resulting contract shape. The scaffold ships:

- `adapters/contract/` — `Adapter` ABC, `CapabilityProfile` (closed `Capability` enum), `AdapterConfig` (the concrete implementation of ADR-021's identity-binding / tag-taxonomy mapping), structured Result types (`EmissionResult`, `DiscoveryResult`, `ExtractionResult`, `ReconciliationResult`), `Diagnostic` with severity / code / message / location.
- `adapters/unity_catalog/` — emission live for group-driven row-visibility policies; uses `is_account_group_member(...)` and `SET ROW FILTER`.
- `adapters/snowflake/` — emission live for the same policy shape; uses `IS_ROLE_IN_SESSION('...')` and `ADD ROW ACCESS POLICY`. Connection-handling lazy-imports `snowflake-connector-python` (not in `.venv` by default).
- `adapters/tests/test_parity.py` — loads `spec/v0/examples/group-row-visibility-policy-a.jsonld`, emits through both adapters, and asserts the platform-specific principal-binding mechanism is present in each output and that the SQL diverges meaningfully.

Adapters never execute. They return structured Results; the caller composes execution with its own logging, retry, dry-run, and audit policy. The Databricks `.venv` already includes `databricks-sdk`; Snowflake live testing requires `pip install snowflake-connector-python` against the provided account (`FBGQMMZ-DCC90967.snowflakecomputing.com`, user `BGIESBRECHT`, warehouse `COMPUTE_WH`, db `BRICETEST`, schema `TESSERA`).

The scaffold deliberately does not implement: discovery, extraction, reconciliation (all three return `*_NOT_IMPLEMENTED` diagnostics), `ColumnVisibilityConstraint` emission, ABAC-scoped policy emission, or selector kinds beyond `byIdentity`. Each gap surfaces as a structured diagnostic; adding coverage is incremental rather than open-ended design.

---

## Things to actively avoid

These are anti-patterns this project specifically rejects. Mentioned not because they're tempting at first glance, but because they often appear as plausible suggestions in adjacent projects:

- **Do not propose a runtime policy engine.** ADR-001 disclaims this category explicitly. If a user request seems to require it, surface the conflict.
- **Do not introduce platform-specific concepts into the vocabulary or IR.** Words like "masking policy" or "row access policy" belong to platform DDL; the IR uses platform-neutral terms like "ColumnVisibilityConstraint." Platform-specific concepts live in adapters.
- **Do not "improve" the vocabulary by tightening alignment with ODRL or DPV unilaterally.** The current alignment is documented as `skos:exactMatch` / `skos:closeMatch` per ADR-005; tightening these to `owl:equivalentClass` requires deliberate decision because it has reasoning consequences.
- **Do not introduce a `Tag` class to the IR.** Tags are a platform mechanism, not policy meaning. Per the meaning-over-mechanism principle and the ABAC scoping document, semantic attributes (sensitivity, data subject, regulatory regime) live in the IR; the platform's mechanism for recording those attributes (governed tags, object tags, classification tables) lives in adapter configuration.
- **Do not model coordination labels as data attributes.** `team: fraud-ops`, `cost-center: 12345`, `environment: production` are operational metadata, not properties of the data a policy protects. Policies that gate on team membership do so via principal selectors; policies that gate on cost-center do not exist in Tessera's scope.
- **Do not retroactively edit existing ADRs.** They are historical record. If something needs to change, propose a new ADR that supersedes the old one.
- **Do not start the DSL.** ADR-006 defers it. If the user asks for DSL syntax design, the answer is "not yet, per ADR-006; YAML is the authoring form."
- **Do not centralize policy evaluation in tooling.** Even helper utilities like "decide whether this policy applies" cross into runtime-engine territory. The project compiles to platform-native enforcement and does not evaluate policies itself.
- **Do not assume Snowflake is competitive or hostile.** Per ADR-002, the project is neutral. Snowflake-related work proceeds against public platform surfaces as any partner integration would.

---

## The customer engagement that shaped the design

The reference real-world case that drove the adapter-first architecture (ADR-003) is a customer running Snowflake but enforcing policy through a custom pattern: ACL tables joined with views, predating Snowflake's native row-access policies. They have hundreds or thousands of ACL rows representing effective policies; they have no intention of manually rewriting these as native Snowflake masking and row-access policies; they want a path to migrate selectively while keeping the ACL pattern operational for the parts that aren't ready to move.

This is why the IR has the `byDataset` selector and the `PrincipalSetFromTable` class. This is why adapters are peers rather than core-and-extension. This is why extraction confidence is first-class. The custom-pattern customer is not an edge case; they are *the* test case for whether the design is real.

When designing extensions or adjustments to the IR, the question to ask is: does this still work for the ACL-table customer? If the answer is "no," the design is wrong.

---

## Communication conventions

When working in this repository:

- **Commits are coherent.** Each commit does one thing and explains it. The commit message references ADR numbers where relevant.
- **PR descriptions explain the why.** A PR that touches the IR or vocabulary should explain how it relates to existing ADRs and whether it implies a new one.
- **The README is not a sales pitch.** Changes to it preserve the honest engineering tone. The "What Tessera is not" section is load-bearing; do not soften it.
- **Documents reference ADRs by number.** "Per ADR-004, the canonical form is JSON-LD" is preferred to "JSON-LD is the canonical form" without justification.

---

## Where the user is in the work

The user (Brice, github: `bgiesbrecht`) established the repository and has run several rounds of design refinement on top of the initial commits. The immediate context as of this handoff:

- Documents and spec artifacts are committed at v0 — including ADR-013 (`defaultStrategy`/`baselineGroup`), ADR-014 (Policy container), ADR-015 (ordered first-match combining), ADR-016 (transformation parameterization), ADR-017 (suspended immutability), ADR-018–021 (ABAC additions — AttributeAxis, `byScope`, composable attribute matching, adapter configuration mapping pattern), ADR-022 (transformation constraint is effect-driven, not policy-kind-driven), and ADR-023 (cross-policy combination γ-with-refinement).
- **The v0 immutability bar is suspended** per ADR-017, until external dependency exists. ADR-014's closing claim that the bar came down with its commit chain was anticipatory and is now superseded. Spec additions continue to land in v0, each captured as an ADR.
- GitHub Pages is enabled; URLs under `https://bgiesbrecht.github.io/tessera/spec/v0/` resolve.
- **Eight worked examples complete** (seven Databricks; one Snowflake):
  - **Group-based row visibility** — Phase 1 / 2 / 3 done against `RLS Demo (3).ipynb` cells 1–9. Artifacts at `spec/v0/examples/group-row-visibility-*`. Drove ADR-014 / ADR-015.
  - **ACL-table-driven row visibility** — Phase 1 / 2 / 3 done against `RLS Demo (3).ipynb` cells 11–15. Artifacts at `spec/v0/examples/acl-row-visibility-*`. Exercised `byDataset` / `PrincipalSetFromTable`; surfaced four v1-candidate gaps (issues #7–#11).
  - **Column mask on `orders.o_clerk`** — single-pass / combined-input exercise (the SQL was shared up front). Artifacts at `spec/v0/examples/column-mask-orders-clerk-*`. Surfaced and corrected the over-tight transformation constraint (ADR-022).
  - **ABAC column mask on `orders_abac.o_clerk`** — full blind derivation. Artifacts at `spec/v0/examples/abac-column-mask-*`. Drove ADR-023 (γ-with-refinement for cross-policy combination via the `MULTIPLE_MASKS` observation).
  - **ABAC row filter on `orders_abac.o_orderpriority`** — full blind derivation. Artifacts at `spec/v0/examples/abac-row-filter-priority-*`. Surfaced issue #12 (`policy-two-axis-attribute-matching`); reinforced the Mechanism A vs B design observation (§4.10 of technical design).
  - **Snowflake `byDataset` row visibility on `BRICETEST.TESSERA.SNOW_ORDERS_RLS_ACL`** — adapted-business-requirements derivation (no competing impl). Artifacts at `spec/v0/examples/snowflake-byDataset-row-visibility-*`. All four scenarios pass including secondary-roles immunity (`USE SECONDARY ROLES NONE` and `ALL` produce identical row counts because `CURRENT_USER()` ignores role activation). Empirically grounds the user-doc recommendation of `byDataset` + mapping table as the preferred Snowflake authoring pattern. Surfaced one v1 candidate: `ResourceSetFromTable.resourceColumn` is conflated as both ACL column and protected-table column.
  - **Table-grants RBAC exercise** — three scenarios (single-table read, schema-level read with downward propagation, function execute). Artifacts at `spec/v0/examples/table-grants-*`. Brief at `docs/exercises/table-grants-handoff.md`. Live-verified on Databricks; propagation test confirmed `GRANT ... ON SCHEMA` extends to new tables created post-grant. Drove ADR-025 (`Execute` action added to v0 with semantic-vs-mechanism boundary) and surfaced two open candidates: `AccessGrantConstraint` policyKind (#15), `function:` IRI prefix formalization. Closed issue #10 (policy-execute-grants).
- **ABAC scoping work complete; Stage 4 spec changes landed 2026-05-19.** `docs/v1-candidates/abac-and-attribute-axes.md` is the design document. ADRs 018–021 are filed, the two ABAC worked exercises (column-mask and row-filter) validated the design empirically, and Stage 4 spec changes are now in `spec/v0/ontology.ttl`, `spec/v0/context.jsonld`, `spec/v0/schema.json`, and `docs/technical-design-v0.2.md` §3.3 / §3.3a / §4.9 / §4.10 / §5.6 / §5.7. ADR-023 records the cross-policy combination resolution.
- **Thirty-one GitHub issues** total. Resolved/closed: #1, #2, #5, #6, #10 (ADR-025), #15 (ADR-026), #26, #27, #28, #29. Open from worked-example findings: #3 (deferred-not-needed-yet), #4, #7, #8, #9, #11, #12, #13, #14. Open from the 2026-05-19 governance-gap survey: #16–#25 (see `docs/handoffs/2026-05-19-governance-gaps-handoff.md`). Open from the 2026-05-20 migration-cycle work (0.4.0+): #30 (UC ABAC byScope column-mask), #31 (Snowflake ABAC byScope). Phase 2 scoping documents for #19/#21/#25 are still queued.
- `spec/v0/schema.json` exists and reflects the Policy container, ADR-016/022 transformation shape, and (post Stage 4) the ABAC `byScope` + `matching` vocabulary. All **seven** committed JSON-LD examples validate cleanly.
- No converter, linter, or adapter scaffolding exists yet. SHACL shapes (`spec/v0/shapes.ttl`) is the next concrete deliverable.

The user's current preferred sequencing prioritizes the ABAC work (Priority 2 in this document) over additional infrastructure (SHACL, converter, first adapter). The reasoning: the framework's first real adapter cannot credibly cover Databricks without ABAC support, since Databricks recommends ABAC over the per-table mechanisms the existing worked examples used. Resolving ABAC before adapter work means the adapter targets the actual recommended pattern, not a deprecated one.

The user values:

- Honesty over completeness. Better to ship less and label it correctly than to ship more and overstate.
- Posture preservation. The skunkworks framing and the Unity-Catalog-source-of-truth concession are non-negotiable.
- Drift prevention. New decisions get ADRs; existing decisions are respected.
- Working artifacts over speculative design. The worked example proves more than another spec revision.
- Meaning over mechanism. The IR models what policies decide; platform-specific mechanisms live in adapter configuration.

---

## Final note

This document is itself an artifact and may need updating. When ADRs are added, when the project's state changes meaningfully, when the priorities shift — this document should be revised so that the next handoff (whether to another tool, another contributor, or a future session) inherits an accurate picture rather than a stale one.

The document should be revised by appending updates with dates, not by silently rewriting history. Stale sections can be marked as such rather than deleted.
