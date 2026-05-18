# Federated Governance Policy Spec — Technical Design v0.2

**Status:** Draft, supersedes v0.1
**Audience:** Technical reviewers — architects, senior engineers, specification editors
**Authoritative context:** This document is consistent with ADR-001 through ADR-006 in `DECISIONS.md`. Conflicts are resolved in favor of the ADRs.

---

## 1. Purpose and scope

The Federated Governance Policy project delivers **semantic interoperability of data governance policy** across heterogeneous data platforms (ADR-001). The same business rule — who can see what, under what conditions, for what purpose — can be expressed once in a portable representation, reviewed and version-controlled as a primary artifact, and translated into native enforcement on Unity Catalog, on Snowflake, or on customer-specific enforcement patterns through adapters.

The project is a customer-enablement initiative for joint Databricks–Snowflake (and other multi-platform) environments (ADR-002). Unity Catalog remains the source of truth for governance inside a Databricks environment; the portable representation operates between governance estates. For customers running Databricks alone, the project is not applicable.

### What the project explicitly does not deliver

- A runtime policy enforcement engine. The project compiles to native enforcement.
- Data quality, retention, lifecycle, or contract policies. Reserved space; not in initial scope.
- Identity federation. Identity references and binding are supported; identity federation is not solved.
- Encryption, key management, differential privacy, anonymization. Adjacent; out of scope.
- Operational interoperability (policy on data physically moving between platforms via Delta Sharing, Iceberg, federated queries). Reserved; not in v0.
- Runtime interoperability (cross-platform query-time authorization gateway). Explicitly rejected.

---

## 2. Architecture overview

```
                  ┌──────────────────────────────────────┐
                  │       Authoring surface (YAML)       │
                  │ *.tessera.yaml files, human-readable │
                  └──────────────────┬───────────────────┘
                                     │  convert (ADR-004)
                                     ▼
                  ┌──────────────────────────────────────┐
                  │   Canonical IR (JSON-LD)             │
                  │   normative form for validation,     │
                  │   reasoning, adapters                │
                  └──────────────────┬───────────────────┘
                                     │
                  ┌──────────────────┼──────────────────┐
                  │                  │                  │
                  ▼                  ▼                  ▼
           ┌────────────┐    ┌────────────┐    ┌────────────┐
           │  Adapter   │    │  Adapter   │    │  Adapter   │
           │ Databricks │    │ Snowflake  │    │  Custom    │
           │ Unity Cat. │    │  native    │    │  pattern   │
           └─────┬──────┘    └─────┬──────┘    └─────┬──────┘
                 │                 │                 │
                 ▼                 ▼                 ▼
          Unity Catalog DDL  Snowflake DDL    Custom artifacts
          (column masks,    (masking policies, (ACL inserts,
           row filters,      row access,        view DDL,
           grants, tags)     tags, grants)      middleware config)
```

Three forms exist (ADR-004):

- **YAML.** What customers and engineers author and review. Lives in the repository. Supports comments. Familiar to engineers from the Databricks ecosystem and beyond.
- **JSON-LD.** The canonical, normative form. Generated from YAML on demand. Consumed by validators, reasoners, and adapters. Not committed to the customer repository.
- **Authoring DSL.** A possible future third form, designed after the IR stabilizes (ADR-006). Not in scope for v0.

Adapters are the unifying abstraction (ADR-003). Unity Catalog, Snowflake-native, and custom-pattern adapters are peers against a common contract. No adapter is privileged in the core design, even though the Unity Catalog adapter will be the most thoroughly developed (ADR-002).

---

## 3. The vocabulary

The vocabulary defines the entities in terms of which all policies are expressed. It is published as an ontology in Turtle/OWL form and as generated reference documentation. Where established standards cover concepts the project needs, the vocabulary imports and reuses them rather than reinventing them (ADR-005).

### 3.1 Core entities

| Entity | Definition | Standards alignment |
|---|---|---|
| `Principal` | An identifiable actor. Specializations: `User`, `Group`, `ServiceAccount`, `Role`. | Cedar principal model. |
| `Resource` | A protected thing. Specializations: `DataProduct`, `Schema`, `Table`, `View`, `Column`, `RowSet`. | — |
| `Action` | What a Principal may attempt: `Read`, `Write`, `Delete`, `Share`, `Sample`, `Aggregate`. | Cedar-style action vocabulary. |
| `Classification` | A sensitivity, regulatory, or business label. Hierarchical. | DPV `PersonalDataCategory` for the privacy subtree. |
| `Purpose` | A declared reason for access, claimed by a Principal at session or query time. | DPV `Purpose`. |
| `Jurisdiction` | A geographic or legal boundary. | — |
| `Condition` | A predicate that must hold for a policy to apply. Fixed algebra; not Turing-complete. | XACML-style condition structure. |
| `Obligation` | An action that must occur as a consequence of policy application. | XACML obligations, ODRL duties. |
| `Transformation` | A function applied to data on read. Closed vocabulary. | — |

### 3.2 Policy entities

Policies are named by what they constrain, not by how they are enforced:

| Policy entity | Constrains | Typical mechanisms |
|---|---|---|
| `AccessConstraint` | Whether a Principal may take an Action on a Resource | Grants, denials, role assignments |
| `RowVisibilityConstraint` | Which rows a Principal may see | Row-level security, row access policies, view filters |
| `ColumnVisibilityConstraint` | Whether a Principal sees a Column's true value, transformed value, or no value | Column masking, dynamic data masking, view projections |
| `DistributionConstraint` | Whether and how a Resource may be shared beyond its origin | Secure shares, listings, Delta Sharing, replication controls |

### 3.3 Selectors

Policies reference principals and resources through selectors, not enumeration:

| Selector kind | Meaning |
|---|---|
| `byIdentity` | Specific named principal or resource |
| `byAttribute` | Predicate over attributes ("Principals with role X", "Resources classified as PII") |
| `byClassification` | Resources carrying a specific classification — the preferred form |
| `byDataset` | Set membership computed from a data source (the form that supports custom ACL patterns) |
| `byComposition` | Boolean combination of other selectors |

The `byDataset` selector (ADR-003) is what enables the framework to express data-driven principal/resource sets, including the ACL-table-and-view pattern common in enterprises.

### 3.4 What the vocabulary excludes

- Identity provider specifics — handled by adapter identity bindings.
- Platform mechanism vocabulary — "masking policy," "row access policy" are emission-side terminology, not vocabulary.
- Operational concerns — deployment, monitoring, alerting.
- Lifecycle, quality, and contract concepts — reserved.

---

## 4. The intermediate representation

### 4.1 Two forms, one meaning

The IR exists in two forms (ADR-004). Both are valid; only one is normative.

**JSON-LD (canonical, normative).** This is the form the spec defines. Validators check structure and semantics against this form. Adapters consume this form. RDF reasoning operates on this form. When two tools disagree about what a policy means, the JSON-LD form is the tiebreaker. `@context` references a stable, versioned URL.

**YAML (authoring, primary).** This is the form customers and engineers see in repositories, in pull requests, in editors. YAML 1.2, strict mode. Uses `@`-prefixed keys (`@context`, `@type`, `@id`) for direct projection to JSON-LD. Supports comments, preserved positionally through YAML round trips and mapped to `rdfs:comment` on YAML → JSON-LD where attached to a node.

Conversion between forms is bidirectional, lossless within stated tolerances (comments do not survive a YAML → JSON-LD → YAML trip in synthesized form; they do survive YAML → YAML edits). The toolchain provides the converter as a foundational component.

File extension is `.tessera.yaml` for the YAML form. The JSON-LD form is not committed to customer repositories; it is generated on demand by tooling.

### 4.2 Structural properties of every IR policy

Every policy carries, regardless of policy kind:

- **Identity.** Stable opaque identifier (`@id`) and semantic version.
- **Vocabulary reference.** Explicit `@context` reference to a specific vocabulary version.
- **Type.** The policy entity (e.g., `RowVisibilityConstraint`).
- **Selectors.** Principal, resource, and action selectors as described in §3.3.
- **Condition.** Optional, drawn from the fixed condition algebra (§4.4).
- **Effect and parameters.** What the policy does when it applies — allow, deny, transform, filter, share — and the parameters of that effect.
- **Obligations.** Optional list of obligations honored when the policy applies.
- **Capability requirements.** Optional list of capabilities the policy depends on; consulted at emission time.
- **Provenance.** For authored policies: author, version-control reference, review history. For extracted policies: source platform, source artifact, extraction timestamp, confidence, notes.

### 4.3 Confidence on extracted policies

Every extracted policy carries a confidence level:

- **High.** Source artifact has unambiguous semantics; extraction is mechanical.
- **Medium.** Intent is inferable from structure or naming convention; reviewer confirmation recommended.
- **Low.** Best-effort interpretation; review required before the policy is trusted.

Extractors that cannot determine confidence emit at the lowest applicable level.

### 4.4 The condition algebra

Conditions are expressible from a fixed set of constructors:

- **Comparison.** Equality, ordering, set membership.
- **Boolean combination.** Conjunction, disjunction, negation.
- **Context predicates.** `current-purpose`, `current-jurisdiction`, `current-time-window`, `consent-granted`, `current-session-attribute`.
- **Dataset predicates.** `exists-in-dataset` — used by `byDataset` selectors.

Extensibility of the algebra is an open question (ADR-007).

### 4.5 Worked example

The same ACL-driven row visibility policy that has been the reference example throughout the design, rendered in YAML as customers would author or review it:

```yaml
"@context": https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld
"@type": RowVisibilityConstraint
"@id": policy:acl-driven-customer-orders
version: 0.1.0

# Row-level visibility for customer.orders, driven by the
# corporate ACL table. Replaces the legacy enforcing view.
# See SECURITY-1234.

description: >
  Users see rows in customer.orders only when the corporate
  ACL table contains an entry granting read access.

appliesTo:
  selector: byIdentity
  resource: table:warehouse.customer.orders

principal:
  selector: byDataset
  dataset:
    "@type": PrincipalSetFromTable
    table: governance.acl
    principalColumn: user_email
    resourceColumn: resource_fqn
    permissionColumn: permission
    permissionValue: read

effect: keep-matching-rows

condition:
  op: purpose-in
  values:
    - purpose:Analytics
    - purpose:Operations

obligations:
  - "@type": AuditLog
    target: topic:row-access-audit

capabilityRequirements:
  - data-driven-selectors
  - obligation-audit-log

provenance:
  extractedFrom: legacy-acl-adapter://corp/governance/acl
  extractedAt: 2026-05-18T14:22:00Z
  confidence: high
  notes: |
    Adapter recognized the canonical ACL-and-view pattern.
    Reviewer should verify purpose binding matches intent.
```

The corresponding JSON-LD is the same structure with comments dropped or mapped to `rdfs:comment`, the multiline strings rendered as JSON strings, and the YAML-specific syntactic affordances normalized. Adapters consume the JSON-LD; reviewers see the YAML.

---

## 5. The adapter contract

Adapters connect the IR to real systems. Every adapter implements four responsibilities (ADR-003), publishes a capability profile, and produces machine-readable reports.

### 5.1 Adapter responsibilities

1. **Discovery.** Inventory policy-bearing artifacts in the target system. For native adapters: catalog of masking policies, row access policies, grants, tags. For custom-pattern adapters: ACL tables, views, middleware configurations — whatever the pattern uses.
2. **Extraction.** Produce IR from discovered artifacts, with confidence and provenance.
3. **Emission.** Produce native artifacts from IR, with a diagnostic report.
4. **Reconciliation.** Compare current state in the target system against a desired IR state and produce a diff.

Adapters may support a subset of responsibilities. A read-only adapter implements discovery and extraction; an emit-only adapter implements emission and reconciliation. The capability profile declares which responsibilities the adapter supports.

### 5.2 The capability profile

Each adapter publishes a profile declaring, per vocabulary concept and IR construct:

- **Supported.** Adapter fully expresses the concept in the target system.
- **Partially supported.** Adapter expresses the concept with stated limitations.
- **Unsupported.** Adapter cannot express the concept.

For partially supported features, the profile names the limitation in machine-readable form. The compiler refuses to emit policies depending on unsupported features and surfaces limitations on partial features in the diagnostic report.

### 5.3 The diagnostic report

Every emission produces a report alongside the native artifacts. Per policy:

- **Fully enforced.** Native artifacts enforce the policy as stated.
- **Partially enforced.** Gap is named in machine-readable form.
- **Unenforced.** Reason and recommendation provided.

Reports are themselves machine-readable artifacts (JSON-LD by canonical form, YAML for human reading where useful).

### 5.4 The extraction report

Mirrors the diagnostic report. Per discovered artifact:

- **Lifted.** Represented in IR with High confidence.
- **Lifted with notes.** Represented with Medium or Low confidence; reviewer attention recommended.
- **Not lifted.** Adapter recognized the artifact but could not represent it. Raw source preserved in provenance.
- **Unrecognized.** Discovery found the artifact; the adapter did not recognize its purpose. Listed for human investigation.

The "unrecognized" category exists because honest reporting of unknown is part of the project's value.

### 5.5 Adapter versioning

Adapters are versioned independently of the spec. An adapter declares the spec version it implements, the vocabulary version it understands, and its own version. The compatibility matrix is published.

### 5.6 Identity binding

Adapters interacting with principals require an identity binding configuration, separate from policy IR. The configuration maps IR principal URIs to native principals in the target system. The same policy artifact, emitted to two different organizations' Snowflake accounts, binds to different native roles. The policy is portable; the bindings are local.

---

## 6. The authoring surface in v0

For the first iteration, the authoring surface is **YAML conforming to the IR schema** (ADR-006). A custom DSL is deferred until the IR has stabilized through real corpus exposure and at least two adapter implementations.

This is a deliberate sequencing choice. The DSL is a projection of the IR; projections are designed once the thing being projected is well understood. The v0.1 draft made the same recommendation and v0.2 holds to it.

YAML authoring is supported by:

- A published JSON Schema for the IR, usable by YAML-aware editors for completion and validation.
- A linter that runs YAML parse, schema validation, vocabulary resolution, and a small set of style checks (preferred selectors, well-known prefixes).
- A converter (YAML ↔ JSON-LD) usable from the command line and as a library.

If customer feedback indicates YAML authoring is a significant adoption barrier, the DSL question is revisited. Until then, YAML is the surface.

---

## 7. Cross-cutting concerns

### 7.1 Versioning

Four version streams:

- **Vocabulary version.** Semantic versioning. New concepts and properties are minor; renames or removals are major. Each version has an immutable `@context` URL.
- **Spec version.** Versions the IR structure and adapter contract.
- **Adapter version.** Per-adapter, independent of the above. Adapters declare compatibility with vocabulary and spec versions.
- **Policy version.** Per-policy semantic version, declared in the policy itself.

### 7.2 Validation

Five layers, in order:

1. **YAML parse.** Strict YAML 1.2. Fail on duplicate keys, on ambiguous types, on tags outside the allowed set.
2. **YAML → JSON-LD conversion.** Mechanical. Should not fail if YAML parse succeeded.
3. **JSON Schema validation.** Structural conformance to the IR schema.
4. **SHACL validation.** Semantic conformance against the vocabulary — references resolve, selectors are well-formed, classifications exist in the imported vocabulary.
5. **Adapter compatibility check.** For a given target adapter, all required capabilities are available. Performed at emission, not authoring.

Layers 1–4 run on every commit. Layer 5 runs when emission is requested. Errors at any layer surface with source location in the original YAML, not in the converted JSON-LD.

### 7.3 Round-trip equivalence

Per-adapter round-trip tests are a correctness gate. The contract: extract from platform A → IR → emit to platform A → extract again → IR'. The two IR documents are equivalent up to stated tolerances (timestamps, generated names, ordering).

Cross-platform behavioral equivalence — extract from A, emit to B, observe equivalent behavior — is reported, not gated. The framework makes lossiness explicit rather than denying it.

### 7.4 Reasoning

The vocabulary supports RDF reasoning. Use is optional but two applications are worth naming:

- **Classification propagation.** A policy applied to `PersonalData` automatically applies to `EUResidentData` if the latter is a subclass.
- **Contradiction detection.** Two policies granting and denying the same access under the same conditions are detectable at compile time.

Reasoning is not on the critical path for the first reference implementation but the vocabulary is designed so that reasoning becomes possible without rework.

---

## 8. Reference implementation scope

| Component | First-iteration scope |
|---|---|
| Vocabulary | Core entities (§3.1, §3.2), selectors (§3.3), condition algebra (§4.4); Turtle + generated docs |
| Context document | Published JSON-LD context at a stable URL; v0 immutable once cut |
| IR schema | JSON Schema for structural validation, SHACL for semantic validation |
| Converter | YAML ↔ JSON-LD, bidirectional, lossless within ADR-004 tolerances |
| Unity Catalog adapter | All four responsibilities; column-visibility, row-visibility, access constraints; tags |
| Snowflake-native adapter | Same scope, same responsibilities |
| Custom-pattern adapter | One adapter, against the real customer's ACL-table pattern |
| Linter | YAML parse, schema validation, vocabulary resolution, style checks |
| Round-trip test suite | Per adapter; gating |
| Reference policy corpus | Real policies (anonymized) from the customer engagement |

Explicitly not in the first reference implementation:

- Reasoning beyond classification subsumption.
- Reconciliation tooling beyond per-adapter diff.
- A web UI.
- Cross-platform behavioral equivalence testing as a gate.
- Production-grade operational tooling.
- The DSL.

These are deliberate omissions (ADR-006 covers the DSL specifically).

---

## 9. Open technical questions

Distinct from stakeholder/leadership decisions; these are for technical reviewers. Tracked in ADR-007 until resolved.

1. **Condition algebra extensibility.** Closed (no per-adopter extensions) or open with registration? Recommendation: closed for v0; revisit after corpus review.
2. **Dataset-selector resolution timing.** Emit-time materialization vs. query-time join? Recommendation: adapter's choice, declared in capability profile; query-time preferred where supported.
3. **Obligation enforcement model.** Single IR concept with adapter capability declaration, or distinct IR concepts per enforceability class? Recommendation: single concept, adapter declares.
4. **Action vocabulary extensibility.** Closed per vocabulary version, open with registration, or fully open? Recommendation: open with registration; closed per any specific version.
5. **Operational interoperability scope.** How and whether policies follow data through Delta Sharing, Iceberg, federated queries.

---

## 10. Sequencing

Given stakeholder decisions and ADRs accepted, work proceeds:

1. **Vocabulary v0.** Turtle, generated reference docs, alignment notes for ODRL/DPV/Cedar.
2. **Context document v0.** Published JSON-LD context, immutable once cut.
3. **IR schema v0.** JSON Schema and SHACL.
4. **Converter v0.** YAML ↔ JSON-LD, including comment-preservation logic.
5. **Adapter contract v0.** Capability profile schema, report formats, versioning rules.
6. **First adapter end-to-end.** Unity Catalog (the platform the team knows best). Discovery, extraction, emission, reconciliation; round-trip suite passing.
7. **Second adapter end-to-end.** Snowflake-native. IR and contract get pressure-tested; expect revisions.
8. **Custom-pattern adapter.** Real customer engagement.
9. **Reference policy corpus.** Real, anonymized, demonstration artifact.
10. **DSL.** Designed only after the above stabilizes (ADR-006).

Resist designing the DSL earlier. Resist treating any one platform as privileged in the IR.

---

## 11. Risks and mitigations

| Risk | Mitigation |
|---|---|
| IR accumulates platform-shaped concepts because the first adapter is Unity Catalog | Build Snowflake adapter early; treat IR revisions during Snowflake-adapter work as the success metric for the Unity Catalog adapter |
| Custom-pattern adapters proliferate without stabilizing the contract | First two custom adapters built by the project team specifically to stabilize the contract |
| Vocabulary grows by accretion as adopters request additions | Vocabulary changes require explicit governance; registered extensions are namespaced and not part of core |
| YAML authoring proves a barrier despite ecosystem familiarity | DSL question revisited (ADR-006 reopened) based on customer feedback |
| Adapter capabilities are over-claimed | Capability claims are testable; round-trip tests per claimed capability are part of adapter certification |
| Round-trip equivalence becomes a moving target | Per adapter, with stated tolerances documented and frozen |
| Internal Databricks pushback on representational neutrality | Position holds: Unity Catalog is source of truth inside Databricks; the IR is the lingua franca between estates (ADR-002) |

---

*End of v0.2 draft. Next: context document v0 (§10 step 2), then resumption against the sequencing above.*
