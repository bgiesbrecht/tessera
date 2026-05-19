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

### 4.2 Top-level shapes: Policy container and single PolicyConstraint

The IR has **two top-level shapes**. Both are valid; one is canonical, one is a backward-compat affordance.

**`tessera:Policy` (canonical, ADR-014).** A container holding an ordered list of `rules` plus policy-level metadata. The canonical shape for any policy that has more than one rule, and the recommended shape for single-rule policies as well. Identified by `@type: Policy` and a `policyKind` discriminator (`RowVisibilityConstraint`, `AccessConstraint`, `ColumnVisibilityConstraint`, `DistributionConstraint`) that determines the legal shape of rules within the policy.

**Single `PolicyConstraint`.** A standalone policy constraint at the document root. Backward-compatible from before ADR-014. Equivalent to a Policy with a single rule. Customers may continue to use this shape for single-rule policies; tools normalize to Policy form for internal processing.

A third shape — a JSON-LD `@graph` of multiple `PolicyConstraint` instances — was used to represent multi-branch policies before ADR-014. It is deprecated; the converter accepts it during the v0 lifecycle and normalizes to Policy form. At v1 cut, only the Policy shape will be accepted for multi-branch policies.

#### 4.2.1 Properties of a Policy

A `tessera:Policy` carries:

- **Identity.** Stable opaque identifier (`@id`) and semantic version.
- **Vocabulary reference.** Explicit `@context` reference to a specific vocabulary version.
- **Kind.** `policyKind` — the policy domain discriminator. References one of the existing PolicyConstraint subclasses.
- **Applies to.** `appliesTo` — a resource selector identifying the resource(s) the policy applies to. Policy-wide; shared across all rules.
- **Action.** The action the policy concerns (e.g., `Read` for visibility policies).
- **Rules.** `rules` — an **ordered** list of rule sub-objects. Each rule carries a principal selector, optional condition, effect, and kind-specific extras (`transformation` for `ColumnVisibilityConstraint`). Order is semantically meaningful: rules are evaluated in declaration order under first-match combining (§4.7 and ADR-015).
- **Default strategy.** Optional. Names how principals matching no rule are handled. One of `explicit-baseline-group`, `negated-complement`, or `none`. See §4.6 and ADR-013.
- **Baseline group.** Required iff `defaultStrategy` is `explicit-baseline-group`. Names the universal baseline group (e.g., `account users` on Databricks). The rule whose principal references this group is, by convention, the last rule in `rules` and is recognized by the framework as the default branch.
- **Default branch.** Required iff `defaultStrategy` is `negated-complement`. A slimmer rule (effect plus optional condition; no principal selector) describing what principals matching no rule see. Forbidden under other strategies.
- **Capability requirements.** Optional list of capabilities the policy depends on; consulted at emission time.
- **Provenance.** For authored policies: author, version-control reference, review history. For extracted policies: source platform, source artifact, extraction timestamp, confidence, notes.

#### 4.2.2 Properties of a rule within a Policy

A rule is a structurally slimmer object than a freestanding PolicyConstraint. It carries:

- **Principal.** `principal` — a principal selector identifying the principals the rule applies to.
- **Condition.** Optional, drawn from the condition algebra (§4.4).
- **Effect.** What the rule does when it matches — `keep-matching-rows` and `drop-matching-rows` for RowVisibility; `allow`, `deny`, `transform` for AccessConstraint; etc.
- **Transformation.** Required for `ColumnVisibilityConstraint` rules; forbidden otherwise. When present, the transformation field carries a structured `TransformationInstance` object — a `type` identifying the transformation kind, plus any parameters specific to that kind. See §4.8 for the parameter shapes formalized in v0.

Rules do not carry their own `@type`, `appliesTo`, or `action` — those are inherited from the containing Policy.

#### 4.2.3 Properties of a freestanding PolicyConstraint

For the backward-compat single-constraint shape, a freestanding `PolicyConstraint` carries the same properties as a Policy rule plus the Policy-level metadata (Type as `@type`, appliesTo, action, etc.) all in a single document. The properties are exactly the v0 pre-ADR-014 set; see ADR-014 for the migration story.

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

A multi-branch row-visibility Policy, rendered in YAML as customers would author or review it. This is the canonical Policy-container shape introduced in ADR-014.

```yaml
"@context": https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld
"@type": Policy
"@id": policy:group-row-visibility
version: 1.0.0
policyKind: RowVisibilityConstraint

# Three-branch row visibility on the orders table, driven by group
# membership. The default branch is the rule keyed off `account users`
# — the universal baseline group on Databricks.

description: >
  Members of bg_rls_demo_all_priority_ops see all rows; members of
  bg_rls_demo_high_priority_ops see rows with high priority; all other
  principals (caught by the baseline `account users` rule) see rows
  with lower priority.

appliesTo:
  selector: byIdentity
  resource: table:bg_rls_demo.tpch.orders

action: Read
defaultStrategy: explicit-baseline-group
baselineGroup: "account users"

rules:
  - principal: { selector: byIdentity, resource: group:bg_rls_demo_all_priority_ops }
    effect: keep-matching-rows
    # No condition — every row is kept for matching principals.

  - principal: { selector: byIdentity, resource: group:bg_rls_demo_high_priority_ops }
    effect: keep-matching-rows
    condition:
      op: in
      operands: [column:bg_rls_demo.tpch.orders.o_orderpriority]
      values: ["1-URGENT", "2-HIGH"]

  - principal: { selector: byIdentity, resource: group:account-users }
    effect: keep-matching-rows
    condition:
      op: in
      operands: [column:bg_rls_demo.tpch.orders.o_orderpriority]
      values: ["3-MEDIUM", "4-NOT SPECIFIED", "5-LOW"]

provenance:
  notes: Worked example from the first Tessera exercise (group-based row visibility).
```

Notes on the shape:

- `appliesTo`, `action`, `defaultStrategy`, and `baselineGroup` live on the Policy, not on individual rules.
- Each rule is structurally slimmer than a freestanding constraint: just `principal`, optional `condition`, and `effect`.
- The third rule's principal references the baseline group named in `baselineGroup`. The framework recognizes this as the default branch (per ADR-013 and ADR-014).
- The rules are evaluated in order under first-match combining (§4.7 and ADR-015). A principal in both `bg_rls_demo_all_priority_ops` and `bg_rls_demo_high_priority_ops` matches the first rule (sees all rows); ordering determines the effect.

The corresponding JSON-LD is the same structure with comments dropped or mapped to `rdfs:comment`. Adapters consume the JSON-LD; reviewers see the YAML.

Other shapes in current use:

- **`negated-complement` variant.** Same observable behavior, different intent: no baseline group; the default branch (rule for non-matchers) is expressed via a `defaultBranch` field on the Policy. See `spec/v0/examples/group-row-visibility-policy-b.tessera.yaml`.
- **Single-rule (backward-compat) shape.** A freestanding `RowVisibilityConstraint` at document root, equivalent to a one-rule Policy. Used by the deferred ACL-table exercise example (see `docs/exercises/`).

For the data-driven (ACL-table) variant of row visibility — exercised by the deferred custom-pattern adapter work — a Policy contains a single rule with a `byDataset` principal selector and a `PrincipalSetFromTable` reference. Conceptually the same shape as the worked example, with one rule and no default branch.

### 4.6 Default-handling strategy

A multi-rule Policy may have an affirmative default branch — a behavior for principals matching no other rule. The framework's default disposition is fail-closed; an affirmative default is opt-in via `defaultStrategy`.

Two semantically distinct mechanisms produce the same observable default behavior:

- **Explicit baseline group.** A universal group (e.g., Databricks `account users`) is referenced affirmatively as one of the Policy's rules. Principals get the default by virtue of explicit membership in this group. The default is grounded in an administrative artifact. The rule keyed off the baseline group is, by convention, the last rule in `rules`; the framework recognizes it as the default branch.
- **Negated complement.** No baseline group exists; the default branch applies to principals who are not members of any of the affirmative-grant rules. The default is grounded in the absence of restrictive memberships. The default branch's effect and (optional) condition live in a separate `defaultBranch` field on the Policy (introduced in ADR-014); no rule is keyed off a baseline group.

Both patterns are common, and the choice between them is intent, not just SQL shape. A policy expressed with `explicit-baseline-group` has cleaner audit semantics ("did this principal have baseline access at time T?"); a policy expressed with `negated-complement` works on platforms without a universal group concept. Treating them as indistinguishable flattens an important semantic distinction.

The IR makes the choice explicit via the `defaultStrategy` field. The values are:

- `explicit-baseline-group` — the Policy asserts a specific group is the universal baseline. The companion field `baselineGroup` names the group. A rule keyed off that group is the default branch.
- `negated-complement` — the Policy asserts no baseline group. The `defaultBranch` field on the Policy carries the default-branch row predicate. Required iff this strategy.
- `none` — the Policy has no default branch. Principals matching no rule see nothing. Equivalent to omitting the field, but preferred when the author wants to assert the choice explicitly.

Field-level rules summarized: `baselineGroup` is required iff `defaultStrategy: explicit-baseline-group`; `defaultBranch` is required iff `defaultStrategy: negated-complement`; both are forbidden under any other strategy.

Adapters consult `defaultStrategy` when emitting native code. The `negated-complement` strategy with a clear set of affirmative-grant rules plus a single `defaultBranch` should produce a readable structural shape (a `CASE`/`WHEN`/`ELSE` row filter on Databricks, for example) — the `defaultBranch` lowers to the `ELSE` clause directly, without pattern-recognition heuristics. The `explicit-baseline-group` strategy produces affirmative emission referencing the named baseline, with an extra `WHEN` branch keyed off the baseline group.

If a target platform cannot natively support the declared strategy — for example, a platform without a universal group concept cannot honor `explicit-baseline-group` directly — the adapter's diagnostic report names this as a partial-enforcement gap and either falls back to negated-complement form (with a clear note in the report) or refuses to emit, depending on adapter policy.

See ADR-013 (the `defaultStrategy` decision) and ADR-014 (the Policy container and `defaultBranch` decision) for the decision history.

### 4.7 Rule combining algebra

Multi-rule Policies use **ordered first-match** semantics. Rules are evaluated in declaration order; the first rule whose principal selector and condition both match an evaluation context applies; subsequent rules are not evaluated. If no rule matches, the policy falls back to its `defaultStrategy`-dictated behavior: `defaultBranch` under `negated-complement`; the baseline-group rule under `explicit-baseline-group`; fail-closed under `none`.

First-match is the only combining algorithm v0 supports. The choice forecloses three alternatives that the framework deliberately does not adopt at this layer:

- **Deny-overrides** and **permit-overrides** are XACML-style algorithms for reconciling independently-authored policies at decision time. Tessera Policies are coherent authored artifacts; multi-rule precedence is expressed by ordering, not by algebra. Cross-policy interaction is a separate problem and is not in v0 scope.
- **Non-deterministic combination** (multiple rules contributing to a single decision) is not supported. First-match is deterministic by ordering. The framework does not blend rule effects.
- **Declared-per-policy combining algorithm** (a `combiningAlgorithm` field on Policy that lets customers choose among algorithms) is deferred. v0 ships with first-match only.

See ADR-015 for the decision and the foreclosures.

### 4.8 Transformation parameters

A `ColumnVisibilityConstraint`'s transformation is a structured object, not a bare class reference. The structure has a `type` field naming the transformation (one of `Mask`, `Hash`, `Tokenize`, `Redact`, `Bucketize`) plus per-transformation parameter fields. This uniform structure applies even for parameterless transformations — `type: Hash` (with defaults for algorithm) is valid and is the canonical shape, not `transformation: Hash`.

The parameter shapes formalized in v0 are:

**`Redact`** replaces the column value with a literal. Required parameter: `replacement` (JSON-encodable value — string, number, boolean, or null). The adapter checks type-compatibility with the column at emission time.

**`Mask`** replaces characters with a fixed mask character, optionally preserving a prefix or suffix. Optional parameters: `maskChar` (default `'X'`), `preserveFirst` (non-negative integer, default 0), `preserveLast` (non-negative integer, default 0). If `preserveFirst` and `preserveLast` together meet or exceed the value's character length, the value is returned unchanged (forgiving behavior). Character counts are over Unicode code points, not bytes.

**`Hash`** replaces the column value with a hash digest. Optional parameter: `algorithm` (one of `sha256`, `sha512`, `sha1`; default `sha256`). Salted hashing is deferred to v1 pending a secret-reference vocabulary.

**`Tokenize`** and **`Bucketize`** are valid transformation types in v0 but their parameter shapes are not yet formalized. Policies using them may declare adapter-specific parameter fields; the adapter is responsible for supporting the parameters or rejecting the policy with a diagnostic. Their parameter shapes will be pinned down by follow-on ADRs when worked examples drive them.

See ADR-016 for the design rationale and the choice of the uniform structured form.

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

The profile also covers **timing and consistency characteristics** of the mechanisms an adapter emits. The Databricks adapter, for the group-based row-visibility mechanism, declares a 2–4 minute propagation window for membership changes via the account-group cache — observed empirically during the first worked example (see `spec/v0/examples/group-row-visibility.comparison.md` §2.3). The general principle is that timing characteristics belong to specific enforcement mechanisms, not to the framework as a whole: an ACL-table-driven row filter on the same adapter would have a different timing profile than a group-membership check; a tag-driven column mask has yet another; a Snowflake session-tag-gated row access policy has yet another still. The framework's role is to require the disclosure; the vocabulary describing the timing is mechanism-specific and lives in the adapter's profile, not in the IR or in the policy. Conversely, enumerating a fixed set of "timing categories" at the framework layer would push mechanism vocabulary up into the IR and would not survive contact with the next adapter.

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
