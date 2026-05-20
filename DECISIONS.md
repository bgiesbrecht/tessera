# Tessera — Decision Log

This document records decisions that shape the Federated Governance Policy project. Each decision is recorded once, dated, and not revised — superseding decisions are recorded as new entries that explicitly reference the entry they supersede.

All technical and stakeholder documents in this project must be consistent with the decisions recorded here. When a document conflicts with a recorded decision, the decision takes precedence and the document is revised.

The format follows the Architecture Decision Record (ADR) convention: context, decision, consequences, status.

---

## ADR-001 — Project framing: semantic interoperability, not migration

**Date:** 2026-05-18
**Status:** Accepted

### Context

Initial framing of the project leaned toward migration (moving workloads between platforms) as the primary use case. Stakeholder review identified that this framing understates the project: most organizations running multiple data platforms are not consolidating, and the policy problem is continuous, not transitional.

### Decision

The project's primary value proposition is **semantic interoperability of governance policy** across heterogeneous data platforms — a shared meaning for governance concepts (PII, purpose, jurisdiction, obligations, etc.) that means the same thing wherever it is enforced.

Migration is a derived benefit, framed as the most acute case of the same capability, not as the headline.

The project is adjacent to but does not deliver:

- Operational interoperability (policy behavior on data physically moving between platforms).
- Runtime interoperability (query-time gateway imposing a single authorization decision).

### Consequences

- Documents lead with continuous coexistence, not one-time migration.
- Success criteria emphasize ongoing reconciliation and diff-based consistency, not event-based re-emission.
- Operational interoperability is named as reserved space; runtime interoperability is explicitly disavowed.

---

## ADR-002 — Organizational posture: skunkworks, customer enablement

**Date:** 2026-05-18
**Status:** Accepted

### Context

The project is being developed by an engineer at Databricks. Databricks leadership holds that Unity Catalog is the source of truth for governance, and any framing that concedes that position is a no-go internally. At the same time, joint Databricks–Snowflake customers have a real and unmet governance interoperability need.

### Decision

The project is positioned as a **skunkworks customer-enablement initiative**, not an official Databricks product and not a standards effort. Specifically:

- Unity Catalog remains the source of truth for governance *inside a Databricks environment*. This is not negotiable.
- The portable representation is the lingua franca *between* governance estates, applicable only to multi-platform customers.
- The project does not coordinate with Snowflake; it does not exclude Snowflake either. The Snowflake adapter is built against public platform surfaces, as any third-party integration would be.
- For customers running Databricks alone, the project is explicitly stated as not applicable.

### Consequences

- The audience and tone of internal Databricks documents differs from customer-facing documents. Two parallel document tracks exist.
- The Unity Catalog adapter receives extra investment as the platform the team knows best; this is acceptable because the IR layer remains platform-neutral.
- Standards-body engagement is deferred indefinitely under this posture; the project remains a tool, not a standard.

---

## ADR-003 — Architecture: adapter model is the unifying abstraction

**Date:** 2026-05-18
**Status:** Accepted, supersedes initial v0.1 framing

### Context

The v0.1 technical design treated Snowflake-native and Databricks-native emitters/extractors as the primary architecture, with custom enforcement patterns as a potential extension. A real customer engagement revealed that many enterprises enforce policy through custom patterns (ACL tables, view layers, middleware) that predate or sit alongside native mechanisms. A design that treats these as edge cases produces a spec that cannot accommodate the real world.

### Decision

Adapters are the unifying abstraction. Snowflake-native, Databricks-native (Unity Catalog), and custom-pattern adapters are peers against a common contract. There is no privileged "native" path in the core design.

Every adapter implements four responsibilities: discovery, extraction, emission, reconciliation. Every adapter publishes a capability profile declaring which IR concepts it supports, partially supports, or does not support.

### Consequences

- The IR must support data-driven principal and resource selectors (e.g., `byDataset`), not only attribute-based selectors, to accommodate ACL-table-style custom patterns.
- The diagnostic and extraction reports are first-class artifacts of every emit/extract operation.
- Adapter versioning is independent of spec versioning.

---

## ADR-004 — Canonical form: JSON-LD, authoring form: YAML

**Date:** 2026-05-18
**Status:** Accepted

### Context

The IR needs a serialization format. JSON-LD provides RDF compatibility, formal semantics, and standards alignment. YAML provides human readability, comment support, and ecosystem familiarity (DABs, Lakeflow Declarative Pipelines, metric views, dbt, Kubernetes). Neither fully replaces the other.

### Decision

**JSON-LD is the canonical form of the IR.** It is the normative serialization defined by the spec; validators, adapters, and reasoners consume it; when two tools disagree, the JSON-LD form is the tiebreaker.

**YAML is the primary authoring form.** Customers and engineers write policies in YAML; pull-request reviews show YAML; comments are preserved through round-trips where possible.

A bidirectional, lossless conversion between the two is part of the toolchain. The repository contains YAML; JSON-LD is generated on demand and not committed (except for spec examples and test fixtures).

Specific sub-decisions:

- YAML uses `@`-prefixed keys (`@context`, `@type`, `@id`) for direct projection from JSON-LD.
- `@context` is referenced by stable URL, not inlined. Context documents are immutable per version.
- File extension is `.fgp.yaml`.
- YAML 1.2, strict mode. Explicit quoting required for fields where implicit-typing ambiguity exists.
- CURIE-style identifiers (`fgp:PII`, `dpv:Purpose`) are resolved at the JSON-LD layer. Well-known prefixes are published in the context; per-file prefix declarations are not supported in v0.
- Comments are preserved positionally for YAML round trips; comments map to `rdfs:comment` on YAML → JSON-LD where attached to a node; JSON-LD → YAML does not synthesize comments.

### Consequences

- The toolchain requires a strict YAML parser and a YAML ↔ JSON-LD converter as foundational components.
- Validation surfaces errors with YAML source locations even though validation operates on the JSON-LD form.
- Spec versioning and context versioning are linked but distinct; context URLs are immutable per version.
- The DSL, if and when it exists, is a third form that compiles to YAML (or directly to JSON-LD). YAML is not the DSL.

---

## ADR-005 — Vocabulary alignment with existing standards

**Date:** 2026-05-18
**Status:** Accepted in principle, specific alignments pending context document

### Context

Multiple existing vocabularies cover parts of the governance domain: W3C ODRL (permissions, prohibitions, duties), W3C DPV (purposes, legal bases, personal data categories), Cedar's schema model (principals, resources, actions), XACML (obligations, combining algorithms).

### Decision

The vocabulary reuses concepts from established standards where they fit, rather than reinventing parallels. Specifically:

- DPV is the source for purpose and personal data category taxonomies.
- ODRL patterns inform permission/prohibition/duty structures.
- Cedar's principal/resource/action shape informs the IR structure.
- XACML's obligation algebra is the conceptual basis for the obligation model.

Where the FGP vocabulary extends or specializes these, it does so under its own namespace (`fgp:`), with documented relationships to the imported vocabulary.

### Consequences

- The context document explicitly imports and references external vocabularies.
- Term URIs follow the imported namespace where reused; only FGP-specific terms use the `fgp:` namespace.
- Versioning the FGP context requires considering compatibility with the imported vocabularies' versions.

---

## ADR-006 — Sequencing: DSL is designed last

**Date:** 2026-05-18
**Status:** Accepted

### Context

The conventional instinct in language design is to design the human-friendly surface first. For this project, doing so would encode assumptions about what policies need to express before the IR is well-understood.

### Decision

The DSL (FGP-L authoring language) is designed *after* the IR has stabilized through corpus exposure and at least two adapter implementations. YAML serves as the authoring form in the interim.

### Consequences

- The first iteration ships without a custom DSL. Authoring is in YAML conformant to the IR schema.
- DSL design begins only after IR revisions have settled.
- This decision is revisited if customer feedback indicates YAML authoring is a significant barrier.

---

## ADR-007 — Open technical questions deferred from v0.2 (status: still open)

**Date:** 2026-05-18
**Status:** Tracking — not yet decided

The following technical questions are recorded as open. They will be resolved as the work proceeds and converted into ADRs at that time.

- **Condition algebra extensibility:** Closed (no per-adopter extensions) or open with registration?
- **Dataset-selector resolution timing:** Emit-time materialization vs. query-time join — adapter's choice or spec-mandated?
- **Obligation enforcement model:** Single IR concept with adapter capability declaration, or distinct IR concepts per enforceability class?
- **Action vocabulary extensibility:** Closed per vocabulary version, open with registration, or fully open?
- **Operational interoperability scope:** How (and whether) policies follow data through Delta Sharing, Iceberg, federated queries.

---

## ADR-008 — Project name: Tessera

**Date:** 2026-05-18
**Status:** Accepted

### Context

The project was developed under the working name FGP (Federated Governance Policy). FGP was always understood to be a placeholder — functional but bland, an acronym whose expansion did not signal what the project does. Naming was deferred until the architecture and framing had stabilized enough to choose a name that fit the work rather than the other way around.

With ADRs 001–007 accepted, the framing is now stable: semantic interoperability of policy across platforms, with adapters carrying meaning between governance estates that would otherwise drift.

### Decision

The project is named **Tessera**.

The name is from the Latin *tessera*: a small token, often split between parties to a covenant, where matching halves later prove the agreement. The metaphor maps directly to the project's function — different platforms hold matching tokens of meaning, and the matching is what proves they enforce the same policy.

Specific sub-decisions:

- The vocabulary namespace prefix is `tessera:`.
- The placeholder canonical URL is `https://tessera.example/...` pending decision on the real hosting URL when the repository is established.
- The file extension for the YAML authoring form is `.tessera.yaml`.
- Documents written under the FGP name (ADRs 001–007 in this file) are not retroactively edited. Per ADR convention, the historical record is preserved.

### Consequences

- A clean rename pass was performed across all new documents (technical design, executive summary, problem statement, stakeholder agenda, README, context document) prior to repository setup.
- Future renames, if they occur, follow the same convention: add a new ADR, perform the rename across non-ADR documents, leave the historical ADRs intact.
- The hosting URL decision is deferred and will be recorded as a separate ADR once the repository is created.
- The license decision (referenced in the README as pending) is similarly deferred.

### Note on the skunkworks posture

Under ADR-002 the project is positioned as a skunkworks customer-enablement initiative. The name Tessera does not carry official Databricks branding, does not imply standards-body affiliation, and is chosen for its semantic fit rather than its commercial value. A future change in the project's organizational posture (productization, open-source release under a sponsoring organization, contribution to a standards body) may warrant a rename; the rename mechanism above accommodates that.

---

## ADR-009 — License: Apache 2.0

**Date:** 2026-05-18
**Status:** Accepted

### Context

The README referenced the license as pending. A decision was needed before any meaningful contribution or external review.

The project comprises both specification artifacts (vocabulary, IR schema, context, ontology) and code artifacts (planned converters, validators, adapters). Three options were considered:

1. Apache 2.0 for everything.
2. MIT for everything.
3. CC BY 4.0 for the specification, Apache 2.0 for code.

### Decision

**Apache 2.0 for the entire project** — both specification and code.

The reasoning:

- Apache 2.0 is the Databricks open-source default, which is consistent with the project's skunkworks-but-Databricks-origin posture (ADR-002).
- The patent grant in Apache 2.0 is material for a project that may eventually involve contributions from organizations with patent portfolios.
- A single license is simpler than a split license and avoids the "which license applies to this file?" friction.
- Apache 2.0 is broadly compatible with both commercial and open-source use, which matters for a tool that customers may want to embed in their own systems.

### Consequences

- A `LICENSE` file containing the standard Apache 2.0 text is added to the repository root.
- All source files in the repository are governed by Apache 2.0.
- Contributions are accepted under Apache 2.0 by default (per the Apache 2.0 Section 5 inbound=outbound convention); a separate Contributor License Agreement is not required initially.

---

## ADR-010 — Repository established at github.com/bgiesbrecht/tessera

**Date:** 2026-05-18
**Status:** Accepted

### Context

The project needed a canonical home for its specification artifacts, documents, and eventual code.

### Decision

The Tessera repository lives at **`https://github.com/bgiesbrecht/tessera`**.

The repository is owned by an individual account, consistent with the skunkworks posture (ADR-002). Migration to an organizational account is anticipated if and when the project's organizational posture changes.

### Consequences

- All Tessera artifacts are committed to this repository.
- The hosting URL for the JSON-LD context and ontology is decided separately (ADR pending) but is constrained to be either a path under this repository (raw GitHub content, GitHub Pages) or a custom domain that resolves to repository-served content.
- Internal references in documents to file paths use the repository's directory structure rather than absolute URLs.

---

## ADR-011 — Canonical namespace URL: GitHub Pages

**Date:** 2026-05-18
**Status:** Accepted

### Context

The Tessera vocabulary, context document, and ontology need stable, dereferenceable URLs. These URLs appear in every Tessera policy file (via the `tessera:` prefix expansion and the `@context` reference) and are difficult to change later — a change requires either a v0 → v1 cut of the entire specification, or coordinated rewrites across every customer's policy files.

Four options were considered:

1. GitHub raw content (`raw.githubusercontent.com/...`).
2. GitHub Pages on the repository (`bgiesbrecht.github.io/tessera`).
3. A purchased domain (e.g., `tessera.dev`).
4. Continued use of the `tessera.example` placeholder.

### Decision

The canonical namespace URL is hosted on **GitHub Pages**:

- **Namespace URL** (the `tessera:` prefix expansion): `https://bgiesbrecht.github.io/tessera/spec/v0/vocab#`
- **Context URL** (referenced from `@context` in policies): `https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld`
- **Ontology URL** (referenced from `owl:Ontology` headers and `rdfs:seeAlso`): `https://bgiesbrecht.github.io/tessera/spec/v0/ontology.ttl`

The path structure follows the repository's directory layout exactly, which means GitHub Pages serves these files at the URLs above without redirect configuration.

### Reasoning

- **Free and immediate.** No domain purchase or DNS setup required to make the URLs resolve.
- **Custom-domain compatible.** GitHub Pages supports CNAME configuration. If the project later moves to a custom domain (e.g., `tessera.dev`), the existing GitHub Pages URLs continue to work and a custom domain can be added that serves the same content. Policy files written today do not need to change.
- **Avoids commercial commitment.** Consistent with the skunkworks posture (ADR-002), no spend is required.
- **Path matches repository structure.** The URL `/spec/v0/context.jsonld` corresponds directly to the file at `spec/v0/context.jsonld` in the repository. Future contributors can find the file from the URL trivially.

### Consequences

- GitHub Pages must be enabled for the repository, configured to serve from the default branch's root.
- The `spec/v0/` directory in the repository is the authoritative source for the v0 vocabulary; files there must not be modified after v0 is cut (immutability per ADR-004).
- A future migration to a custom domain follows the GitHub Pages CNAME pattern; the namespace URLs in committed policy files continue to resolve through both URLs.
- A future migration of the repository to an organizational GitHub account (e.g., `databricks-labs/tessera` or `tessera-spec/tessera`) requires either preserving `bgiesbrecht.github.io/tessera` as a redirect or cutting v1 of the specification at the new URL. The implications of this should be considered before any such migration.

### Notes on the URL structure

The base namespace URL is `https://bgiesbrecht.github.io/tessera/spec/v0/vocab#` rather than `https://bgiesbrecht.github.io/tessera/vocab/v0#` for two reasons:

1. The `/spec/v0/` prefix groups all v0 specification artifacts together (vocabulary, context, ontology, future schema and shapes). This is conventional in standards-style projects.
2. The fragment-style `#` at the end of the namespace URL means individual terms (e.g., `tessera:PII`) expand to `https://bgiesbrecht.github.io/tessera/spec/v0/vocab#PII`, which is a single dereferenceable document with the terms as fragments. This is one of the two canonical RDF naming patterns (the other being "hash-less" with per-term documents); the fragment form is simpler and is conventional for small-to-medium vocabularies.

The `vocab` path segment is distinct from the `ontology.ttl` and `context.jsonld` file paths because the *vocabulary* is conceptually separate from any specific document that describes it. The ontology file is one description of the vocabulary; the context is another, in JSON-LD form; a future SHACL shapes file would be a third. Each is at its own URL; the namespace URL identifies the vocabulary itself.

---

## ADR-012 — Repository visibility: public

**Date:** 2026-05-18
**Status:** Accepted

### Context

After initial setup, the repository was briefly made private and then returned to public. The episode surfaced a constraint not explicit in ADR-011: the canonical namespace URL (`https://bgiesbrecht.github.io/tessera/spec/v0/...`) only resolves anonymously when the repository is public.

GitHub Pages on private repositories requires a paid plan and serves content only to authenticated users with repository read access. Anonymous fetches — by RDF reasoners, JSON-LD validators, third-party tooling, or any consumer that does not authenticate to GitHub — fail.

### Decision

The Tessera repository is **public**, and remains public as long as the published namespace URLs are expected to resolve anonymously.

### Reasoning

- The Tessera spec is meant to be consumable. Any tool that parses a Tessera policy file may fetch the `@context` URL during processing; failing those fetches breaks the basic flow.
- The skunkworks posture (ADR-002) does not require privacy. The project is non-strategic from a competitive standpoint and benefits from being visible to potential customers and contributors.
- The Apache 2.0 license (ADR-009) presumes public availability; a private repo under a permissive open-source license is an awkward posture.

### Consequences

- The repository remains public; any future change to private status requires a deliberate decision recorded as a new ADR superseding this one.
- If the project ever requires a temporary private phase (embargo before an announcement, sensitive customer engagement, etc.), the corresponding plan must account for namespace-URL resolution — either by accepting that URLs will not resolve during the private phase, by mirroring spec files to a public location, or by routing through a custom domain on an independent host.
- Customers and tools can safely fetch the published URLs without authentication.

### Note on the alternative

A more robust long-term posture would decouple the namespace URLs from GitHub entirely by routing them through a custom domain (e.g., `tessera.dev`) served from a host independent of the repository's visibility. This was considered in ADR-011 and deferred. The decision remains: GitHub Pages is the canonical host while the project is skunkworks; a custom domain becomes the right answer if the project's organizational posture changes.

---

## ADR-013 — Default-handling strategy is a first-class field on policies

**Date:** 2026-05-18
**Status:** Accepted, v0 correction

### Context

The first worked-example exercise surfaced a real-world policy pattern that the IR, as initially designed, could not express self-describingly: a policy with multiple branches where one branch is the default for principals who do not match the others.

Two semantically distinct mechanisms produce the same observable behavior:

- **Explicit baseline group.** A universal group (in Databricks: `account users`) is referenced affirmatively, granting visibility to principals via their membership in it. The default is grounded in an explicit administrative artifact.
- **Negated complement.** No baseline group exists; the default branch applies to principals who are not members of any of the affirmative-grant groups. The default is grounded in the absence of restriction.

Both patterns are common. Real policies depend on one or the other for different reasons: the baseline-group pattern has cleaner audit semantics ("did this principal have baseline access at time T?"); the negated-complement pattern works in environments without a universal group concept.

Treating them as indistinguishable — both compile to similar SQL — flattens an important semantic distinction. The IR's job is to capture intent, not just observable behavior, and the choice between these two mechanisms is intent.

### Decision

A new field, `defaultStrategy`, is added to the `PolicyConstraint` class in the IR. It is optional. Its value is one of three named individuals:

- `tessera:explicitBaselineGroup` — the policy asserts a specific group is the universal baseline. A companion field, `baselineGroup`, names the group. The framework treats the rule keyed off this group as the default branch.
- `tessera:negatedComplement` — the policy asserts no baseline group. The default branch applies to principals who do not match any of the other affirmative-grant rules. The framework treats the negation as inherent to the policy structure.
- `tessera:none` — the policy has no default branch. Principals who do not match any rule see nothing. This is the framework's fail-closed disposition stated explicitly.

When the field is omitted, the framework treats the policy as `tessera:none` (fail-closed). This matches existing behavior and does not break policies authored before this addition.

### Consequences

- The ontology (`spec/v0/ontology.ttl`) gains the `tessera:defaultStrategy` and `tessera:baselineGroup` properties and three named individuals.
- The JSON-LD context (`spec/v0/context.jsonld`) gains short names for the new terms.
- The technical design (`docs/technical-design-v0.2.md` §4.2) gains the new field in the structural properties of every policy.
- Adapters consult `defaultStrategy` when emitting SQL. The `negatedComplement` strategy with a clear two-or-three-rule structure should produce a readable `CASE`/`WHEN`/`ELSE` row filter on Databricks. The `explicitBaselineGroup` strategy should produce structurally affirmative emission referencing the named baseline. Implementation details are adapter concerns, not policy concerns.
- The diagnostic report from an adapter notes the strategy and whether the target platform can support it natively. Most platforms can; some (without a universal group concept) cannot support `explicitBaselineGroup` and must fall back to negated-complement form with a diagnostic.

### Note on v0 immutability

This is a v0 correction made before v0 is treated as immutable. Per ADR-004, the canonical JSON-LD context and ontology become immutable when published and depended on by external consumers. As of this ADR, no external consumer has built against v0. The window for v0 corrections is the gap between repository setup and the first external dependency; this correction is within that window.

After the worked-example exercise completes and any final v0 corrections it surfaces are applied, the v0 immutability bar comes down. Subsequent changes require a v1 cut, not in-place edits.

### What this is not

This ADR does not introduce a general policy-rule-priority or rule-combining-algorithm framework. The three strategies are deliberately limited to the default-handling case, which is the specific pattern surfaced by the worked example. A more general combining-algorithm framework (XACML-style: permit-overrides, deny-overrides, first-applicable, etc.) is out of scope for v0 and is tracked as a v1 candidate via ADR-007.

---

## ADR-014 — Policy container backported into v0

**Date:** 2026-05-18
**Status:** Accepted, v0 correction (parallel to ADR-013)

### Context

The first worked example (group-based row visibility, completed 2026-05-18) surfaced a structural gap in v0: the IR has no explicit multi-branch policy primitive. Multi-branch policies — including the simple three-rule group-membership policy that drove this exercise — were represented as a JSON-LD `@graph` of multiple `RowVisibilityConstraint` instances, with `defaultStrategy` and `baselineGroup` duplicated across every constraint in the graph. The diagnostic flagged this as the most consequential of four gaps. The Phase 3 comparison categorized it as a v1 candidate (issue [#1](https://github.com/bgiesbrecht/tessera/issues/1)).

A design sketch (`docs/v1-candidates/policy-container.md`) worked the question through. The conclusion was that holding the container for a v1 cut would have larger downstream costs than fixing it now:

- Every v0 tool built between now and v1 (JSON Schema, SHACL shapes, converter, first adapter) would encode the `@graph` workaround. Each would need revision at v1 cut.
- v0 customers who adopt the workaround in their own files would face a migration cliff at v1. The project would either ship a migration tool — committing to migration infrastructure that wouldn't otherwise be necessary — or strand early adopters.
- Both alternatives are worse than backport.

ADR-013 set the precedent: pre-publication v0 corrections are admissible while no external consumer has built against v0. That window is still open.

### Decision

A new top-level class **`tessera:Policy`** is added to v0. It acts as a container holding an ordered set of rules plus policy-level metadata (`appliesTo`, `defaultStrategy`, `baselineGroup`, `defaultBranch`, `kind`, provenance). The existing constraint classes (`AccessConstraint`, `RowVisibilityConstraint`, `ColumnVisibilityConstraint`, `DistributionConstraint`) remain valid as `kind` discriminators inside Policy, and as standalone top-level shapes for single-branch policies (backward compatibility).

Specific sub-decisions:

- `tessera:Policy` is a subclass of `tessera:Entity`, not of `tessera:PolicyConstraint`. A Policy *contains* constraints; it does not refine the constraint concept.
- New properties on Policy: `tessera:rules` (ordered list of rule sub-objects), `tessera:policyKind` (discriminator referencing the existing constraint class hierarchy), `tessera:defaultBranch` (slimmer rule applying when no other rule matches under `negated-complement`).
- `defaultStrategy`, `baselineGroup`, and `appliesTo` have their domains extended to include Policy. They remain on `PolicyConstraint` for backward compatibility but are deprecated at that level.
- The `@graph`-of-constraints shape used in the worked example before this ADR is deprecated as a multi-branch representation. The converter accepts both shapes during the v0 lifecycle (it normalizes to Policy form internally). At v1 cut, only the Policy shape will be accepted.
- The combining algebra for ordered rules is recorded in a separate decision: ADR-015. The two are logically distinct — the container is structural; the algebra is semantic — and conflating them would obscure the second.

The full design is in `docs/v1-candidates/policy-container.md` (which becomes the implementation reference now that backport is decided; it is not renamed because the design content remains accurate and the v1-candidates directory may accumulate other sketches).

### Consequences

- Ontology, context, and JSON Schema receive corresponding revisions in this commit chain.
- The technical design `docs/technical-design-v0.2.md` §4 is substantively reworked to describe Policy-as-container; §4.5 worked example is rewritten.
- The first worked example's artifacts (`spec/v0/examples/group-row-visibility-policy-{a,b}.{tessera.yaml,jsonld}`) are rewritten to the Policy shape. The diagnostic and comparison documents are updated with a top-note explaining that the artifacts are post-backport.
- Three v1-candidate issues are partly or fully resolved by this ADR: #1 (closed by ADR-014), #2 (closed by ADR-014 since `defaultBranch` is part of the container), and #3 (recategorized as deferred-not-needed-yet rather than v1-candidate, per `docs/v1-candidates/policy-container.md` §4).
- The capability profile vocabulary will need new entries for Policy support, defaultBranch support, and ordered-rule support. This is adapter-side work, not in this commit chain.
- ADR-015 follows immediately, recording the combining-algebra choice that the Policy container enables.

### When backport would have been the wrong call

Recording this so future backport decisions inherit the framework, in the same spirit as ADR-013's "no external consumer yet" note.

If external dependencies on v0 existed at this point — customer policy files referencing the v0 context URL in production, adapters compiled against the v0 schema and deployed, third-party tooling depending on the v0 shape — backport would not be the right call. The cost of breaking external consumers exceeds the cost of carrying a known workaround forward; in that situation, the right path is v1 with a migration tool, with v0 frozen in its imperfect state.

The principle: pre-publication corrections are admissible; post-adoption corrections are not. The window between them is real and finite. ADR-013 and ADR-014 are within the window; ADR-014 is its likely endpoint.

### Note on v0 immutability

ADR-013 explicitly noted: "After the worked-example exercise completes and any final v0 corrections it surfaces are applied, the v0 immutability bar comes down." This ADR is one of those final corrections. The expectation now is that no further v0 corrections will be made — the v0 immutability bar comes down with this commit chain. Subsequent IR changes require a v1 cut at `spec/v1/`.

---

## ADR-015 — Combining algebra for multi-rule policies: ordered first-match

**Date:** 2026-05-18
**Status:** Accepted, resolves the policy-combining-algorithm question tracked in ADR-007

### Context

With Policy containers introduced in ADR-014, a Policy can hold multiple rules. The semantics of multi-rule evaluation has to be specified: when more than one rule could apply to a given principal/row, what happens?

ADR-007 tracked "policy-combining algorithm" as an open question. The framing was open with several candidates: union, first-match, deny-overrides, permit-overrides, declared-per-policy. The first worked example exercised one shape (first-match), and the natural emission on every SQL-style platform mirrors that shape, but neither was formally chosen.

### Decision

Multi-rule Policies use **ordered first-match** semantics. Rules are evaluated in declaration order. The first rule whose principal selector and condition both match an evaluation context applies; its effect is the policy's effect for that context. Subsequent rules are not evaluated. If no rule matches:

- Under `defaultStrategy: negated-complement`, the `defaultBranch` applies.
- Under `defaultStrategy: explicit-baseline-group`, the rule keyed off `baselineGroup` is structurally the last rule in `rules` and is expected to match all principals in the baseline group; the framework validates this structurally.
- Under `defaultStrategy: none` or omitted, no rule applies and the policy's fail-closed disposition takes effect (for row visibility: row dropped; for access: deny; analogously for other kinds).

### Reasoning

- **Mirrors natural emission.** The CASE/WHEN/ELSE SQL shape that adapters produce for row visibility is exactly first-match. Authors and adapters share one mental model.
- **Composes cleanly with `defaultStrategy`.** The default branch is naturally the last-match position, which is what `negated-complement` and `explicit-baseline-group` already imply.
- **Rule ordering becomes semantically meaningful.** Moving a rule changes behavior. This is a cost (it removes the ability to sort rules cosmetically) and a benefit (it forces authors to express precedence explicitly rather than relying on policy-combining magic).
- **Predictable.** A reader of the policy can determine the effect for any input by reading rules top to bottom.

### Foreclosures

Recording these explicitly so future readers see them as choices, not oversights:

- **Deny-overrides and permit-overrides are not supported as combining algorithms within a single Policy.** These XACML-style algorithms are appropriate when multiple independently-authored policies must be reconciled at decision time. Tessera Policies are coherent authored artifacts; multiple-rule combination within one Policy is the author's responsibility, expressed via ordering, not the framework's responsibility to resolve via algebra. If multi-policy combination becomes a need (cross-policy interaction at evaluation time), it is a separate design problem requiring its own treatment, likely in v2 or later.
- **Non-deterministic combination is not supported.** First-match is deterministic by ordering. Algorithms that allow multiple rules to contribute to a single decision (e.g., "the strictest effect wins among matching rules") are not in scope. The framework does not blend rule effects.
- **Declared-per-policy combining algorithm is not supported in v0.** A `combiningAlgorithm` field on Policy would allow customers to choose among algorithms. Deliberately deferred — adding the field now would commit the project to designing and validating multiple algorithms before the corpus has demonstrated they are needed. v0 ships with first-match only; later versions may revisit.

### Consequences

- The Policy container's `rules` property has list semantics (`@container: @list` in JSON-LD). Order is preserved through YAML ↔ JSON-LD conversion.
- The technical design's adapter contract names ordered-first-match as the emission expectation: adapters lower Policies to platform constructs that preserve the first-match evaluation order.
- SHACL shapes can validate that `rules` is non-empty and ordered, that the baseline rule appears last under `explicit-baseline-group`, and that `defaultBranch` appears iff `defaultStrategy: negated-complement`.
- ADR-007's "policy-combining-algorithm" open question is closed by this ADR. ADR-007's other open items (condition algebra extensibility, dataset-selector resolution timing, obligation enforcement model, action vocabulary extensibility, operational interoperability) remain open.

---

## ADR-016 — Transformation parameterization

**Date:** 2026-05-18
**Status:** Accepted, v0 addition

### Context

The first column-masking exercise (`bg_rls_demo.tpch.orders.o_clerk` redacted to `'clerk-redacted'` unless the user is in `orders_full_access`) surfaced that v0 had no way to express transformation *parameters*. The ontology declares `Mask`, `Hash`, `Tokenize`, `Redact`, `Bucketize` as `Transformation` subclasses, and the policy IR references them via a `transformation` field. But the field accepts only a class name; there is no place to carry the replacement string for a `Redact`, the preserve-count for a `Mask`, the algorithm for a `Hash`, or the bucket boundaries for a `Bucketize`.

A policy intent like "redact `o_clerk` to `'clerk-redacted'`" cannot be expressed in v0 as currently shaped. The fact-of-redacting can be expressed; the *what to redact to* cannot. Likewise, SSN-style masking ("show last 4") and hashing with a specified algorithm have no place to put their parameters.

This is an *addition* — v0 is silent on the matter, not wrong about it. The immutability commitment from ADR-014 covers corrections to existing shapes, not additions of new capability. New optional capability is a minor version bump, not a structural revision.

### Decision

The `transformation` field in the IR carries a **structured `TransformationInstance` object**, not a bare class reference. Every transformation reference is structured, including parameterless ones, for schema uniformity.

The structure is:

```
transformation:
  type: <Transformation subclass name>
  <parameter fields per the transformation's declared shape>
```

The `type` field discriminates which transformation is being applied. Additional fields carry parameters specific to that transformation. The fields a given transformation accepts are declared in the ontology.

### Parameter shapes per transformation (v0 scope)

**`Redact`** — replaces the column value with a literal.

- `replacement` (required): the literal to substitute. JSON-encodable value. Strings, numbers, booleans, and `null` are all valid. The adapter is responsible for type-compatibility with the column at emission time; if `replacement` is type-incompatible with the column, emission fails with a diagnostic, not silent coercion.

**`Mask`** — replaces the column value with a fixed character, optionally preserving a prefix or suffix.

- `maskChar` (optional, default `'X'`): the character used for the masked positions. Single character.
- `preserveFirst` (optional, default `0`): non-negative integer. The first N characters of the value pass through unchanged.
- `preserveLast` (optional, default `0`): non-negative integer. The last N characters of the value pass through unchanged.
- Behavior: if both `preserveFirst` and `preserveLast` are set, both apply; the masked region is the characters between them. If the sum of `preserveFirst` and `preserveLast` is greater than or equal to the value's character length, the value is returned unchanged (forgiving rather than failing). Character counts are over Unicode code points, not bytes.

**`Hash`** — replaces the column value with a hash digest.

- `algorithm` (optional, default `'sha256'`): one of `'sha256'`, `'sha512'`, `'sha1'`. Algorithms outside this set require a v1 spec extension.
- Salted hashing is **deferred to v1**, pending a secret-reference vocabulary that v0 does not include. A policy author who needs salted hashing should use `Tokenize` if the platform supports it, or wait for v1.

### Parameter shapes deferred

**`Tokenize`** and **`Bucketize`** are declared structurally as `TransformationInstance` subclasses with the `type` field carrying their name, but their parameter shapes are deferred. No worked example has driven them; specifying parameter shapes for transformations the project has not yet tested would be premature. When an exercise drives them, their parameter shapes are added via a follow-on ADR.

A policy author wishing to use `Tokenize` or `Bucketize` in v0 may declare them in the structured form (`type: Tokenize` with adapter-specific parameter fields), and the adapter is responsible for either supporting the parameters declared or rejecting the policy with a diagnostic. This is a deliberately loose contract during v0; v1 will tighten it.

### Why a uniform structured form (option α) rather than polymorphic (option β)

Option β allowed `transformation` to be either a class-name string (for parameterless transformations) or a structured object (for parameterized ones). Option α — the chosen design — requires structured form always, even for parameterless transformations.

Reasoning:

- **Schema simplicity.** Validating polymorphic field types is harder to express in JSON Schema and harder to reason about for tool authors. A uniform shape is easier.
- **Future-proofing.** A transformation that starts parameterless may gain parameters later. Under option β, this would require either tolerating both legacy and new forms or doing a migration. Under option α, adding a parameter is purely additive.
- **JSON-LD cleanliness.** Structured objects are RDF-natural; bare class names as field values require either `@vocab` typing or `@id` reference, both of which mix awkwardly with the structured form.

The verbosity cost (writing `type: Hash` rather than just `Hash`) is small and worth the schema simplicity.

### Consequences

- **`spec/v0/ontology.ttl`** gains the `tessera:TransformationInstance` class and parameter properties (`replacement`, `maskChar`, `preserveFirst`, `preserveLast`, `algorithm`).
- **`spec/v0/context.jsonld`** gains short names for the new properties.
- **`spec/v0/schema.json`** adds the structured-transformation shape with conditional requirements (`replacement` required iff `type: Redact`; algorithm-validity check for `Hash`; non-negative integer constraints on `preserveFirst`/`preserveLast`).
- **`docs/technical-design-v0.2.md` §4** is updated. The transformation reference in §4.2's structural properties is amended to specify the structured form. A new §4.8 documents the transformation parameter shapes per transformation.
- **Adapter contracts** must declare in their capability profiles which transformations they support and with which parameters. The Databricks adapter (when built) should support all the v0 transformations with their declared parameters; other adapters may declare narrower support.
- **The worked-example brief for column masking** uses the structured transformation form throughout. The column-masking exercise produces the first artifact exercising parameterized transformations.

### Note on the v0-additions pattern

This is the third addition to v0 since initial publication (ADR-013 default-handling, ADR-014 policy container, ADR-016 transformation parameterization). The pattern is: focused exercises drive small spec additions, each captured as an ADR, each addressing a specific discovered gap.

The pace is intentional. v0 is being shaped by evidence rather than by speculation. The cost is that v0 is not yet stable in the way a published standard would be; the benefit is that v0 is being shaped to fit real use cases rather than imagined ones.

ADR-014's defensive note applies here too: this addition is acceptable because no external dependencies on v0 yet exist. If external dependencies existed, the addition would be a v1 minor-version concern, not a v0 amendment.

---

## ADR-017 — Immutability bar suspended until external dependency

**Date:** 2026-05-18
**Status:** Accepted; supersedes the immutability claim in ADR-014's closing note

### Context

ADR-014's closing note stated: *"The expectation now is that no further v0 corrections will be made — the v0 immutability bar comes down with this commit chain. Subsequent IR changes require a v1 cut at `spec/v1/`."*

That statement was anticipatory. It assumed publication of v0 would coincide with external adoption of v0 — that the commit chain landing ADR-014 was the moment after which v0 was depended upon by someone outside the project.

In fact, no external consumer has built against v0 at any point. The published URLs at `https://bgiesbrecht.github.io/tessera/spec/v0/...` resolve, but resolving and being depended upon are different things. ADR-016 (transformation parameterization) landed after ADR-014's stated bar, and a substantial structural addition (ABAC support via attribute axes, scoped policy attachment, and composable selectors) is now under design and intended for v0.

Continuing to amend v0 while claiming the immutability bar came down with ADR-014 produces a contradiction in the decision log. The honest framing is that the immutability bar was tied to a calendar event that did not occur, and the bar's actual condition — external dependency — has not been met.

### Decision

The v0 immutability bar is suspended until external dependency exists. "External dependency" means at least one of:

- A customer policy file references the v0 context URL in production.
- An adapter compiled against the v0 schema is deployed outside the project repository.
- Third-party tooling depends on the v0 shape and is in use.
- An external contributor commits to or builds against the spec.

Until external dependency exists, v0 remains malleable. Spec changes that improve the shape of the IR are admissible. The discipline of recording each change as an ADR continues; the discipline of preserving backward compatibility within v0 lifecycle continues; but the "no further v0 corrections" claim of ADR-014 is rescinded.

ADR-014's other content (the policy container backport itself, the design rationale, the consequences) remains in force. Only the closing note's immutability claim is superseded.

### Quality thresholds for "core baseline"

The project does not know in advance when external dependency will occur, but it can name what should be true *before* it occurs, so that what gets locked in is the better-shaped spec. Candidate thresholds:

1. **A working adapter end-to-end.** The first real adapter (Unity Catalog) builds, emits policies, extracts policies, round-trips correctly.
2. **A worked exercise that surfaces no spec additions.** Currently every exercise has driven an ADR; the threshold is when an exercise runs cleanly against the existing spec.
3. **An external collaborator engages.** Someone other than the project's current participants builds against or contributes to the spec. *This is the definitional threshold; once met, immutability is no longer optional.*
4. **A second platform's adapter is built.** Snowflake adapter alongside Databricks adapter. Cross-platform claims become evaluable, not just asserted.

Thresholds 1, 2, and 4 are quality thresholds the project aims to cross before threshold 3 occurs. Threshold 3 is the gating event for immutability regardless of the others.

### Consequences

- `CLAUDE.md` is updated to remove the stale "immutability bar comes down with ADR-014" claim and replace it with the suspended-immutability framing.
- The ABAC scoping work (in flight at time of this ADR) lands as v0 additions, not v1.
- Future v0 additions remain disciplined: each is captured as an ADR; the test of admissibility is "does this improve the shape of v0 before it locks" rather than "is the change small enough."
- A reader of the ADR sequence should understand: ADR-014's immutability claim was correct in spirit but premature in timing; ADR-017 corrects the timing.

### Note on this kind of correction

ADR-014's overreach was anticipating immutability before external dependency made it real. The lesson recorded here for future ADRs: claims about when a project's malleability ends should be conditioned on observable events, not on calendar moments. ADR-014's stated bar was a date; this ADR's stated bar is a condition. The condition is the better discipline.

---

## ADR-018 — AttributeAxis and the Classification refactor

**Date:** 2026-05-18
**Status:** Accepted, v0 addition per ADR-017

### Context

The existing `Classification` hierarchy in v0 handles the single-axis hierarchical case well — `PII ⊂ PersonalData` carries useful subsumption inference. What it does not handle is the orthogonal-dimensions case: a column may simultaneously be `sensitivity: PII`, `dataSubject: EUResident`, `regulatoryRegime: GDPR`, and `businessDomain: CRM` — four independent axes, each with its own value vocabulary.

The ABAC scoping document (`docs/v1-candidates/abac-and-attribute-axes.md` §2) establishes that real-world classification across Databricks ABAC, Snowflake tagging, and W3C DPV consistently treats these as separate dimensions, not as a single hierarchy. Forcing them into one hierarchy produces combinatorial class names (`MarketingTeamGDPREmailPII`) that age badly.

### Decision

A new top-level concept, **`tessera:AttributeAxis`**, names an independent semantic dimension. Resources carry zero or more attribute assignments; each assignment names an axis and a value. The same resource may carry multiple axis values; values on different axes are orthogonal.

Each axis declares its own **structural type**:

- **Hierarchical axis.** Values form a subsumption hierarchy via `rdfs:subClassOf`. Inference applies: `sensitivity: PIIEmail` implies `sensitivity: PII`. Schema and SHACL expect class references.
- **Flat axis.** Values are independent enumeration members. No subsumption. Schema expects scalar references.

The type is per-axis because the underlying domain dictates it. Declaring it up front lets validators reject malformed references early.

### v0 axes

Four well-known axes ship with v0:

| Axis | Type | Example values |
|---|---|---|
| `sensitivity` | Hierarchical | `PII ⊂ PersonalData ⊂ RegulatedData`; `PIIEmail ⊂ PII`; `Public`, `Confidential` as siblings. Existing `Classification` hierarchy lives here. Aligned with DPV `PersonalDataCategory`. |
| `dataSubject` | Flat | `EUResident`, `USResident`, `Employee`, `Customer`, `Minor`. Aligned with DPV `DataSubject`. |
| `regulatoryRegime` | Flat | `GDPR`, `HIPAA`, `PCI-DSS`, `SOX`, `CCPA`. |
| `businessDomain` | Flat (adopter may extend hierarchically under their own namespace) | `CRM`, `Finance`, `HR`, `Engineering`, `Marketing`. |

Adopters extend the axis set under their own namespace; each adopter-declared axis declares its own structural type.

### Backward compatibility with existing Classification

The refactor preserves the existing `Classification` subclass hierarchy. The mapping is:

- `tessera:PII` becomes a value of the `sensitivity` axis. Existing references to `Classification: PII` (or the equivalent `byClassification` selector) continue to validate during the v0 lifecycle.
- The canonical post-refactor form is `attributes.sensitivity: PII`. The schema accepts both shapes; the converter normalizes to the new form on YAML → JSON-LD. Bare-classification references in YAML are accepted with a deprecation note in the SHACL output.
- The `byClassification` selector continues to work for bare-class references; new policies using attribute matching use the `matching:` shape (ADR-020).

### Consequences

- `spec/v0/ontology.ttl` gains `tessera:AttributeAxis`, an `tessera:axisType` property (with values `hierarchical`/`flat`), `tessera:axisValue` references, the four well-known axes as `AttributeAxis` individuals, and an `tessera:attributes` property on `tessera:Resource` of type `AttributeAssignment` collection.
- `spec/v0/context.jsonld` gains short names for the new terms and a context mapping for the implicit-AND shortcut (ADR-020).
- `spec/v0/schema.json` adds the attributes-on-resource shape and per-axis-type validation (hierarchical axes expect class references; flat axes expect strings or named individuals).
- `docs/technical-design-v0.2.md` §3 (the vocabulary) gains attribute axes as a first-class concept; §4 (the IR) gains the resource-side `attributes:` field.
- Adapter capability profiles declare which axes they support natively, partially, or not. The Databricks adapter (when built) maps axes to governed-tag taxonomies via the configuration pattern in ADR-021.

### Note on what this is not

ADR-018 introduces a vocabulary refactor, not a runtime change. The framework still does not enforce policies at runtime (ADR-001). Attribute axes are how policies *describe* the data they protect; the platform's enforcement mechanism (governed tags, object tags, classification tables) is the adapter's concern.

This ADR does not introduce coordination labels (`team`, `cost-center`, `environment`) into the axis vocabulary. Those are operational metadata, not data attributes (CLAUDE.md anti-patterns; `docs/v1-candidates/abac-and-attribute-axes.md` §1).

---

## ADR-019 — Scoped policy attachment via `byScope`

**Date:** 2026-05-18
**Status:** Accepted, v0 addition per ADR-017

### Context

Tessera v0 attaches policies to specific resources via `appliesTo` with a `byIdentity` selector — the policy says "this applies to `bg_rls_demo.tpch.orders`." This is fine for table-specific policies but does not express ABAC's defining behavior: a policy attaches at a *level* in the resource hierarchy (catalog, schema, table) and automatically applies to anything within that scope matching its conditions.

A single ABAC policy can protect every PII column in a catalog without enumerating tables. The IR needs a primitive for this.

See scoping document §3 for the full design rationale.

### Decision

A new selector kind, **`tessera:byScope`**, attaches a policy at a level in the resource hierarchy. A `byScope` selector carries a `scope` (the resource at which the policy attaches), an optional `except` list (resources to exclude), and an optional `matching` block (attribute conditions narrowing which resources within the scope the policy applies to; see ADR-020).

```yaml
appliesTo:
  selector: byScope
  scope: catalog:bg_data
  except:
    - schema:bg_data.sandbox
    - table:bg_data.metrics.staging_only
  matching:
    attributes:
      sensitivity: PII
```

### Scope kinds are inferred from the resource IRI prefix

The Tessera context defines URI prefixes for catalogs, schemas, tables, and columns. The `byScope` selector infers the scope kind from the resource's prefix:

- `catalog:` → applies to all schemas, tables, and columns within the catalog.
- `schema:` → applies to all tables and columns within the schema.
- `table:` → applies to all columns within the table.
- `column:` → applies only to the specific column (equivalent to today's `byIdentity` selector targeting a column).

Inference avoids redundancy — the `kind` is recoverable from the IRI and does not need to live as a separate policy field.

### Inheritance is implicit and downward

A policy at catalog scope applies to schemas, tables, and columns within that catalog. The adapter handles platform-specific inheritance details (Databricks does not propagate tags from table to column by default; Snowflake does for certain tag types — these are mechanism differences, not policy differences).

### Scope exclusion is distinct from principal exclusion

The `except` list narrows the *resource set*. It is structurally different from principal exclusion (narrowing the principal set), which is handled by `byComposition` over principal selectors and by the policy container's ordered first-match (ADR-015). The two kinds of exclusion serve different purposes and are kept separate in the IR.

The `except` facility is included in v0 because both Databricks ABAC and Snowflake tag policies support scope-level exclusion, and a v0 without it would force a follow-on amendment shortly after publication.

### Deferred: cross-policy combining algorithm

ABAC's multi-policy aspect — multiple policies attached at overlapping scopes — raises a question ADR-015 explicitly did not answer: what happens when two policies both apply to the same resource? Snowflake has explicit ordering rules; Databricks ABAC evaluates dynamically; the two differ.

**ADR-019 does not prescribe a cross-policy combining algorithm.** The decision is held until the worked exercise (scoping doc §9 Stage 3) produces evidence. The three resolution paths under consideration are documented in scoping doc §8 Q3:

- **α.** Tessera ignores cross-policy combination; adapters handle it per platform conventions.
- **β.** Tessera adopts a single algorithm (deny-overrides, permit-overrides, or declared priority).
- **γ.** Tessera declares it adapter-configurable per capability profile.

A follow-on ADR (number TBD) records the choice once the exercise discriminates among them.

### Consequences

- `spec/v0/ontology.ttl` gains `tessera:byScope` as a `Selector` individual, `tessera:scope` and `tessera:exceptFromScope` properties.
- `spec/v0/context.jsonld` gains short names for `byScope`, `scope`, `except`.
- `spec/v0/schema.json` adds the `byScope` selector variant with `scope` required, `except` and `matching` optional.
- `docs/technical-design-v0.2.md` §3.3 (selectors) and §4.2 (top-level shapes) incorporate `byScope` and the inheritance semantics.
- The Databricks adapter (when built) maps `byScope` to `CREATE POLICY ON {CATALOG|SCHEMA|TABLE}`. Scope exclusion maps to per-adapter mechanisms (Databricks: `EXCEPT` patterns on the scope; Snowflake: tag-exemption patterns).
- The cross-policy combining decision remains open and is targeted by Stage 3 of the ABAC work.

---

## ADR-020 — Composable attribute matching reuses `byComposition`

**Date:** 2026-05-18
**Status:** Accepted, v0 addition per ADR-017

### Context

ABAC policies need to match resources whose attributes satisfy boolean combinations of axis-value conditions: "sensitivity PII AND dataSubject EUResident," "sensitivity PII OR regulatoryRegime GDPR," "NOT sensitivity Public," etc.

The existing `byComposition` selector already composes principal selectors via `match: and|or|not` over a `criteria` list. The composable-attribute-matching requirement has the same algebraic shape. Introducing a parallel composition vocabulary (`any:`, `not:`, implicit conjunction) would produce three shapes for one concept and propagate inconsistency into schema, SHACL, and adapter code.

See scoping document §4 for the full discussion and the rejected parallel-shape alternative.

### Decision

The `matching:` block on a `byScope` selector (ADR-019) accepts the same composition algebra as the existing `byComposition` selector, with attribute leaves rather than principal-selector leaves.

**Canonical form:**

```yaml
matching:
  match: and
  criteria:
    - attribute:
        axis: sensitivity
        value: PII
    - attribute:
        axis: dataSubject
        value: EUResident
```

Each leaf is an `attribute` reference naming an axis and a value. `match: and` requires all to hold; `match: or` requires any; `match: not` negates a single criterion (which may itself be a composed criterion via nesting).

**Nesting:**

```yaml
matching:
  match: or
  criteria:
    - attribute: { axis: sensitivity, value: PII }
    - match: and
      criteria:
        - attribute: { axis: regulatoryRegime, value: GDPR }
        - attribute: { axis: dataSubject, value: EUResident }
```

### Implicit-AND shortcut

The most common case — conjunction over a small set of attributes — would read significantly worse in the canonical form than in shorthand. The schema accepts an implicit-conjunction shortcut:

```yaml
matching:
  attributes:
    sensitivity: PII
    dataSubject: EUResident
```

This is **syntactic sugar that desugars to the canonical form with `match: and`**. The converter, the JSON Schema, and adapters all treat the two as equivalent. The canonical form is what reasoners and validators see; the shortcut exists for authoring ergonomics only.

The desugaring is unambiguous because the keys of `attributes:` are axis names and the values are axis values. There is no overlap between the shortcut shape and the canonical shape; both are accepted, the canonical is normative.

### Consequences

- `spec/v0/ontology.ttl` gains `tessera:AttributeMatcher` as the leaf concept under matching, plus `tessera:axis` and `tessera:axisValue` properties.
- `spec/v0/context.jsonld` gains short names for `matching`, `attribute`, `attributes`. The `attributes:` mapping is described as the implicit-AND shortcut.
- `spec/v0/schema.json` accepts both shapes for the `matching` field (`oneOf` over the canonical and shortcut forms); semantic equivalence is enforced by the converter, not the schema.
- Adapters compile the composition algebra directly to platform booleans: `match: and` → SQL `AND`, `match: or` → SQL `OR`, `match: not` → SQL `NOT`. The tag-taxonomy mapping (ADR-021) handles the leaf translation from `attribute.axis: sensitivity, value: PII` to platform-specific `has_tag_value` calls (Databricks) or `SYSTEM$GET_TAG_*` calls (Snowflake).

### Note on extensibility

The composition algebra is closed in v0 (and/or/not). The condition algebra (ADR-007's open extensibility question) is a separate algebra and is not affected by this ADR. Adopters who need more expressive matching beyond `and`/`or`/`not` describe their need as a v1 candidate; v0 stays closed.

---

## ADR-021 — Adapter configuration mapping pattern

**Date:** 2026-05-18
**Status:** Accepted, v0 addition per ADR-017

### Context

Adapters need to translate between platform-specific identifiers and Tessera's semantic vocabulary. The translation is per-environment because adopters use different tag taxonomies, identity providers, and naming conventions. The mapping is bidirectional: emission lowers Tessera identifiers to platform-specific ones; extraction lifts platform-specific identifiers back.

Tessera has had one instance of this pattern from the beginning — **identity binding** (ADR-002, where principals in the IR are mapped to platform-native principals per-environment). The ABAC work introduces a second: **tag-taxonomy mapping** (Databricks governed-tag keys/values ↔ Tessera attribute axes/values; ADR-018). More instances are likely as the framework grows — classification-name mapping, group-hierarchy mapping, possibly more.

Rather than treating each instance as a one-off, this ADR establishes the **adapter configuration mapping pattern** as the general shape, with tag-taxonomy and identity-binding as the first two named instances.

See scoping document §5 for the full design.

### Decision

An adapter configuration mapping declares pairings between platform-specific identifiers and Tessera semantic identifiers, grouped by *kind*. Each kind determines the shape of the platform-specific side; the Tessera side always references a Tessera identifier in the IR's namespace.

Configuration lives in adapter-side files (`adapters/<name>/configuration.yaml` or equivalent), not in the policy IR. A policy that says `sensitivity: PII` means the same thing on every platform; the policy author does not need to know whether the Databricks adapter expects this to emit as `has_tag('pii')`, `has_tag_value('classification', 'pii')`, or `has_tag('data_class')` with allowed value `PII`.

### Two well-known instance kinds in v0

**`identityBindings`** — per-adapter mapping between Tessera principal IRIs and platform-native principals. Pre-existing pattern (ADR-002), now formalized.

```yaml
identityBindings:
  - tesseraPrincipal: group:data-stewards
    platformGroup: bg_data_stewards
  - tesseraPrincipal: user:brice@databricks.com
    platformUser: brice.giesbrecht@databricks.com
```

**`tagTaxonomy`** — per-adapter mapping between Tessera attribute axes/values and platform-native tag keys/values. New with ABAC.

```yaml
tagTaxonomy:
  - axis: sensitivity
    axisValue: PII
    tagKey: classification
    tagValue: pii
  - axis: dataSubject
    axisValue: EUResident
    tagKey: region
    tagValue: EMEA
```

The structural shape is the same across kinds; platform-specific fields vary per adapter and per kind.

### Default behavior on unmapped identifiers

During extraction (or emission), the adapter may encounter a platform-specific identifier with no Tessera counterpart in the configuration, or a Tessera identifier with no platform counterpart. Three configurable behaviors, with **strict as the default**:

- **Strict (default).** Unmapped identifier is an extraction/emission error. The adapter refuses to lift or lower without an explicit mapping. The IR stays clean of unknown identifiers. Adopters configuring strict accept that they must declare their mappings explicitly.
- **Permissive.** Unmapped identifier is lifted onto a synthetic axis or principal namespace (e.g., `unknown:tagKey` for a tag key not mapped) with extraction confidence `low`. The IR carries the information; the policy semantics are not validated. Useful during migration.
- **Pass-through.** Unmapped identifier is lifted verbatim with confidence `low`. Preserves round-trip fidelity at the cost of IR cleanliness. Useful for diagnostic scenarios.

The strict default reflects the project's broader "honesty over completeness" disposition. Opting into looser semantics is explicit configuration.

### Consequences

- Adapter capability profiles declare which configuration-mapping kinds they support and which defaults they use.
- The Databricks adapter (when built) ships with `identityBindings` and `tagTaxonomy` support out of the box, with strict default.
- The Snowflake adapter (whenever built) follows the same pattern with Snowflake-specific platform fields (tag schema, tag name, role naming).
- The adapter contract (`docs/technical-design-v0.2.md` §5) gains a sub-section describing the configuration-mapping pattern and the strict-default convention.
- Future configuration-mapping kinds (classification-name mapping, group-hierarchy mapping) follow the same shape without requiring a new ADR per kind. The pattern is the general decision; individual kinds are local concerns.

### Note on what this is not

ADR-021 is *adapter contract*, not IR vocabulary. The IR has no `IdentityBinding` or `TagMapping` class. The mapping lives in adapter configuration, parsed by the adapter, not represented in the policy file. A reader of a Tessera policy never sees configuration mappings; a reader of an adapter deployment sees both the policy and the configuration but they remain structurally distinct.

This separation is structural, not cosmetic. Conflating them would violate the §1 meaning-vs-mechanism principle from the ABAC scoping document. The IR carries meaning; the adapter configuration carries the per-environment mechanism. Both have their place; neither belongs in the other.

---

## ADR-022 — Transformation constraint is effect-driven, not policy-kind-driven

**Date:** 2026-05-18
**Status:** Accepted, v0 correction per ADR-017

### Context

ADR-016 introduced structured transformations: a `TransformationInstance` with `type` plus per-type parameters, referenced from policy rules. The decision text correctly framed `transformation` as the parameter shape carried *when a rule applies a transformation*. The technical-design §4.2.2 text and the JSON Schema implementation, however, took a tighter position: they required `transformation` on every rule in a `ColumnVisibilityConstraint` policy.

The column-mask worked example (`spec/v0/examples/column-mask-orders-clerk-*`) surfaced the gap. The natural Tessera shape for two-branch column masking is one rule with `effect: allow` (pass-through for a privileged group) plus a `defaultBranch` with `effect: transform` and a `Redact` transformation (for everyone else). The pass-through rule has no transformation to declare because no transformation is applied — but the schema rejects it.

The constraint as written is over-tight. The right rule is **effect-driven**, not policy-kind-driven: a rule (or `defaultBranch`) carries `transformation` iff its `effect` is `transform`.

ADR-022 records the correction. This is admissible per ADR-017 (v0 immutability bar suspended until external dependency); the underlying ADR-016 decision is unchanged.

### Decision

The `transformation` field on a rule (and on a `defaultBranch`) is required if and only if `effect: transform`. For any other effect value (`allow`, `deny`, `keep-matching-rows`, `drop-matching-rows`, `tessera:allow`, etc.), `transformation` is forbidden.

This constraint applies uniformly across:

- Rules inside a `Policy` container (any `policyKind`).
- The `defaultBranch` of a `Policy` (any `policyKind`).
- Freestanding `PolicyConstraint` documents (backward-compat single-constraint shape, any `@type`).

The previous policy-kind-driven conditional (every `ColumnVisibilityConstraint` rule must carry `transformation`) is rescinded.

### Why effect-driven

- **Matches ADR-016's actual intent.** Transformation is the parameter shape for applying a transformation; rules that don't apply one shouldn't carry it.
- **Supports the natural shape for binary column masking.** "Privileged group sees the value, everyone else sees a masked value" is one rule + one default branch. The rule's effect is `allow`; the default branch's effect is `transform`. The schema must accept both.
- **Composes correctly across policy kinds.** A `ColumnVisibilityConstraint` policy can mix transform rules and allow rules; an `AccessConstraint` can carry `transformation` if a rule's effect is `transform` (though this is rare). The constraint is local to the rule, not to the enclosing policy.
- **Does not relax the structural constraints ADR-016 introduced.** A `transformation` that *is* present still must have a valid `type` and the appropriate per-type parameters (Redact requires `replacement`; Mask/Hash forbid it; etc.). ADR-016's per-transformation parameter requirements are unchanged.

### Consequences

- **`spec/v0/schema.json`** — the policy-level `if/then/else` requiring `transformation` for all `ColumnVisibilityConstraint` rules is replaced with a per-rule `allOf` conditional on `effect`. The same conditional applies to the `defaultBranch`. The freestanding `policyConstraint` shape's `@type`-based conditional becomes an `effect`-based one.
- **`docs/technical-design-v0.2.md` §4.2.2** — the transformation bullet changes from "Required for `ColumnVisibilityConstraint` rules; forbidden otherwise" to "Required when `effect: transform`; forbidden otherwise." §4.2.3 (freestanding `PolicyConstraint`) inherits the same constraint.
- **The column-mask worked-example artifacts** (`spec/v0/examples/column-mask-orders-clerk-*`) validate cleanly after the schema correction lands.
- **The ontology (`spec/v0/ontology.ttl`)** does not change. The constraint was never an ontology axiom; it was a schema implementation choice.

### Note on the implementation-vs-decision pattern

The original constraint over-implemented ADR-016. The decision text said "transformations are parameterized via `TransformationInstance`"; the implementation said "every ColumnVis rule must have one." Those are not the same statement, and the implementation should mirror the decision, not impose tighter constraints than the decision justified.

This is a useful pattern to record for future ADR implementations: when translating an ADR's decision into schema or code, double-check that the implementation's constraints match the ADR's declared scope. The column-mask exercise surfaced this gap because it produced the first artifact whose natural shape exceeded the over-tight constraint's bounds. The framework's "exercises drive design" principle catches these on the first valid example; the cost of correction now is small.

---

## ADR-023 — Cross-policy combination resolution: γ-with-refinement

**Date:** 2026-05-19
**Status:** Accepted, resolves the question deferred in ADR-019

### Context

ADR-019 (`byScope` + scoped attachment) deliberately did **not** prescribe a cross-policy combining algorithm. The decision named three candidate resolutions:

- **α** — Tessera defers to platform conventions; adapters handle combination per-platform.
- **β** — Tessera adopts a single combining algorithm (deny-overrides, permit-overrides, declared priority) and requires adapters to enforce it.
- **γ** — Tessera declares it adapter-configurable per capability profile.

The ABAC column-mask worked exercise (`spec/v0/examples/abac-column-mask-*`, Phase 3 observation 2026-05-19) produced the discriminating empirical result: **Databricks ABAC rejects multi-mask evaluation** when two column-mask policies resolve to the same column. The full error:

```
[COLUMN_MASKS_FEATURE_NOT_SUPPORTED.MULTIPLE_MASKS]
Column mask policies for `bg_rls_demo`.`tpch`.`orders_abac` are not supported:
Table has access control policies resulting in multiple column masks ...
applying to the same column(s) `o_clerk`. Please contact the table owner or
policy definer to resolve the issue by updating policies such that at most
one mask appl[ies]
```

Both policies attached successfully (the rejection is at **query-evaluation time**, not at policy-creation time). The platform's response is neither α nor β: it rejects the configuration outright, naming both conflicting policies and the affected column, and asks the operator to resolve the conflict in the policy definitions.

The companion ABAC row-filter exercise (`spec/v0/examples/abac-row-filter-priority-*`, 2026-05-19) reinforced this with a cross-mechanism finding: Brice's design notes confirm that ABAC row filter + legacy `SET ROW FILTER` on the same table coexist *unless* they resolve to different functions for the same table and user, in which case Databricks again blocks access. Same shape; different boundary.

### Decision

Tessera adopts **γ-with-refinement**: cross-policy combination is adapter-configurable, but the IR does **not** pick a combining algorithm. The refinement is that Tessera *names the platform's constraint* via the adapter capability profile rather than treating "adapter-configurable" as an open-ended invitation to pick an algorithm.

Specifically:

1. **The IR remains expressive.** Authors may declare multiple policies whose effective resource sets overlap. This is legitimate authored intent — for example, a redaction policy and a hashing policy on the same PII columns reflecting two different downstream consumers' needs. The IR does not preemptively reject this configuration.

2. **The adapter capability profile declares platform constraints** as machine-readable vocabulary. Initial v0 vocabulary:
   - `single-column-mask-per-column` — at most one ColumnVis policy may resolve to any given column on the platform.
   - `single-row-filter-per-table` — at most one RowVis policy may resolve to any given table on the platform.
   - `cross-mechanism-conflict-blocked` — ABAC policies and legacy `SET MASK` / `SET ROW FILTER` on the same column/table compose only if they resolve to the same function; otherwise the platform blocks access.

   Databricks declares all three. Other platforms (Snowflake, custom adapters) declare their own constraints; the vocabulary is open per ADR-021's adapter-configuration pattern.

3. **The adapter's emission diagnostic surfaces detected conflicts** at emit time, not at runtime. When the adapter compiles a set of policies and detects two whose effective resource sets overlap (in a way the platform constraint forbids), it emits a structured diagnostic naming both policies, the affected resources, and the constraint. The author resolves the conflict before deployment.

4. **The author resolves conflicts before deployment.** Tessera does not pick a winner in the IR or pick a combining algorithm; the platform never sees an ambiguous configuration because the adapter refuses to emit one. Resolution mechanisms (merging policies, narrowing matchers, scoping one to a subset, splitting across catalog/schema/table scope levels) are author concerns guided by the diagnostic.

### Why γ-with-refinement and not pure α or β

- **Pure α** (defer to platform) would leave Tessera silent about conflicts that the platform will reject. The author would learn about conflicts only at runtime, after deployment. This contradicts the framework's "diagnostics at emit time" principle (technical design §5.3).
- **Pure β** (pick an algorithm) would commit Tessera to enforcing a combining semantics — say, deny-overrides — that may not match any platform's actual behavior. Customers would write policies expecting one algorithm and the platform would enforce another. This is worse than silence.
- **γ-with-refinement** names the platform's constraint without inventing one. The IR is honest about what the platform supports; the adapter is honest about what it can emit; the author is honest about what conflicts they're carrying. Each layer does its job.

This framing also generalizes: as Tessera grows additional adapters with different constraints, each adapter declares its own capability vocabulary; the IR remains neutral; the framework's "meaning over mechanism" principle is preserved.

### Consequences

- **Adapter capability profile vocabulary** (per ADR-021) gains the three initial entries above. The Databricks adapter (when built) declares all three; future adapters declare their own.
- **Adapter emission contract** (technical design §5) now explicitly requires a conflict-detection phase before SQL generation. The Tessera CLI / linter / converter surfaces detected conflicts as structured findings before any DDL is emitted.
- **The capability-profile vocabulary itself remains open.** ADR-021's pattern (well-known instance kinds + adopter extensibility) applies here too. Future findings — for example, a platform that rejects multiple obligations on the same policy — extend the vocabulary; no new ADR per constraint kind.
- **ADR-019's deferred decision is closed by this ADR.** ADR-019's "α / β / γ" framing now refers to this ADR for the canonical resolution.
- **ADR-007's "policy-combining algorithm" open question is partially closed.** The specific case of cross-policy *conflict* on the same effective resource set is now resolved (Tessera defers to adapters; adapters declare and emit diagnostics). Cross-policy combination across *orthogonal* effects (column mask + row filter on the same table, for example) is a different question — addressed by the platform's natural composition, not by Tessera's IR — and remains correct under the v0 design.

### What this ADR does not do

- **Does not introduce an IR-level conflict-detection facility.** The detection is the adapter's job, not the IR's. The IR is expressive; the adapter is selective.
- **Does not specify the diagnostic format.** Each adapter declares its diagnostic output shape; consistency across adapters is encouraged but not required.
- **Does not preclude future addition of an IR-level "preferred algorithm" annotation.** If a real customer engagement surfaces the need for the author to declare an intended combining algorithm (independent of the platform's enforcement), a future ADR can add it. v0 stays neutral.

### Note on the empirical-grounding pattern

ADR-019 was honest about deferring this decision until evidence arrived. The evidence arrived in the ABAC column-mask exercise; the row-filter exercise generalized it. The framework's discipline of "exercises drive design, not speculation" produced a sharper resolution than ADR-019 could have chosen up-front — the γ-with-refinement framing required knowing what the platform actually does, and that knowledge required deployment, not just documentation.

The lesson worth recording: deferring a design decision until empirical observation can ground it is a real practice, not just a procrastination. ADR-019's deferral was correct; ADR-023's resolution is sharper for having waited.

---

## ADR-024 — Adapter contract shape

**Date:** 2026-05-19
**Status:** Accepted

### Context

ADR-003 established that adapters are peers and that each adapter is responsible for four activities — discovery, extraction, emission, reconciliation — plus a capability profile declaring which IR concepts the platform supports. The technical design (§5) elaborated this in prose. But until a concrete adapter implementation exists, the contract between the IR and the platforms remains a sketch: the interface boundary, the result types, the configuration injection point, and the diagnostic vocabulary are all underspecified.

Two adapter scaffolds were built simultaneously (Unity Catalog and Snowflake) precisely to pressure-test the contract. If only one adapter existed, the contract would inevitably specialize to that platform's idioms. With two implementations of the same interface emitting from the same IR, the contract has to express the platform-neutral surface explicitly.

### Decision

The adapter contract is defined by the types in `adapters/contract/`:

- **`Adapter` ABC** — an abstract base class with four methods (`emit`, `discover`, `extract`, `reconcile`) and a `capability_profile` property. Adapters subclass `Adapter` and override what they implement; default implementations of the three non-emission methods return `NotImplemented`-style diagnostics so that callers can probe an adapter's surface without dispatching on adapter identity.
- **`AdapterConfig`** — per-environment configuration mapping IR concepts to platform mechanisms. This is the implementation of ADR-021's adapter-configuration-mapping pattern. Concrete fields: `identity_bindings` (PrincipalRef IRI → platform principal id) and `tag_taxonomy` ((axis, value) → (tag key, tag value)). An `extras` dict carries per-adapter conventions (warehouse, default schema) without polluting the typed surface.
- **`CapabilityProfile`** — per-adapter declaration of supported / partial / unsupported entries keyed by a closed `Capability` enum. The enum is normative: adding a value is a contract change. Diagnostic emission cites capability entries by enum value, so the gap between two platforms is comparable across adapters.
- **`EmissionResult`, `DiscoveryResult`, `ExtractionResult`, `ReconciliationResult`** — every adapter method returns a structured Result, never a raw string or dict. Results carry `diagnostics: list[Diagnostic]` alongside their payload. Callers attach the diagnostic stream to whatever downstream surface (CLI output, JSON report, IDE annotation) is appropriate.
- **`Diagnostic`** — severity (info / warning / error), short code (e.g., `UNIMPLEMENTED_POLICY_KIND`), human-readable message, optional location pointer into the source policy. Adapters declare their codes; cross-adapter code naming converges by convention, not enforcement.

Emission lowers a parsed JSON-LD policy dict to platform-native DDL/SQL statements. **Adapters never execute** — execution is the caller's responsibility (the calling tool layers in the SDK, the Snowflake connector, audit-log handling, dry-run flags, etc.). This separation keeps adapters testable without platform credentials and keeps the contract synchronous and pure.

### Rationale

- **Two implementations from day one.** Building Unity Catalog alone would have produced a contract specialized to Databricks idioms (account groups, governed tags). The Snowflake scaffold immediately pressured the principal-binding axis (roles, not groups), the policy-attachment DDL (row-access policy vs row filter), and the naming convention (schema-qualified policy objects in Snowflake; function-named filters in Databricks). The `AdapterConfig.identity_bindings` mapping emerged from this pressure.
- **Structured Results, not raw output.** Returning a bare list of SQL strings was rejected because it forecloses on capability-gap reporting, partial extraction confidence, and reconciliation diff output. The Result types are simple dataclasses — auditable, serializable, testable.
- **Closed `Capability` enum.** A free-form string vocabulary for capability declarations would let each adapter invent its own gap names, defeating the cross-adapter comparison the profile is meant to support. The enum is small (eight entries today); future additions are deliberate.
- **Emission separated from execution.** The same scaffold runs in unit tests with no platform credentials and in integration tests against real workspaces. Callers compose execution with their own logging, retry, dry-run, and audit policy without negotiating with the adapter.

### Consequences

- **Adapters are import-light.** Neither `databricks-sdk` nor `snowflake-connector-python` is imported at module load time. The Snowflake scaffold tolerates the connector being absent; a caller wanting to execute must install it.
- **Capability profiles become a live document.** As emission paths fill in, capability entries move from `PARTIAL`/`UNSUPPORTED` to `SUPPORTED` with rationale text describing how the IR concept maps to platform DDL. The profile is the running record of how the abstract IR resolves into concrete mechanisms.
- **The parity test in `adapters/tests/test_parity.py` is a structural fixture.** It asserts that the same IR produces different, platform-correct outputs. Adding adapters or adding emission paths means adding parity assertions; regressions surface immediately.
- **The four-responsibility shape (ADR-003) is now concrete.** Discovery, extraction, reconciliation each have a stub method, a Result type, and a diagnostic code; the future work to fill them in is bounded by the contract rather than open-ended design.

### What this ADR does not do

- **Does not specify a DSL or YAML authoring layer for adapter configuration.** `AdapterConfig` is the Python type; how authors express it (TOML, YAML, environment variables) is a future deliberate choice tracked in the converter / linter work.
- **Does not prescribe an execution framework.** Tessera's adapter contract terminates at structured emission output. A separate runner (CLI subcommand, library wrapper) composes execution.
- **Does not address streaming or pagination of large extraction results.** For v0 the assumption is that extraction returns a finite policy dict per artifact and discovery returns a finite list. A streaming variant is deferrable until a real customer corpus surfaces the need.

### Note on ordering

ADR-024 lands together with the first concrete scaffolds (commit on 2026-05-19). Future adapters — `custom-acl/` per ADR-003's third-target customer — inherit the contract as it stands today; if their platform surfaces concepts that strain the current shape, those strains land as new ADRs amending or extending this one, not as silent edits.

### Findings from the first live cross-platform exercise (2026-05-19)

The scaffold was exercised end-to-end against both target platforms on the same day it landed. The same `spec/v0/examples/group-row-visibility-policy-a.jsonld` was lowered through both adapters and the resulting DDL was executed against:

- **Databricks** — `bg_rls_demo.tpch.orders` (7.5M rows from `samples.tpch.orders`).
- **Snowflake** — `BRICETEST.TESSERA.SNOW_ORDERS` (1.5M rows from `SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS`).

Three findings worth recording — none reshape the contract but each refines the platform-specific surface:

1. **Resource bindings are a real config gap.** The same IR target (`table:bg_rls_demo.tpch.orders`) lowers to two different platform identifiers (`bg_rls_demo.tpch.orders` on Databricks; `BRICETEST.TESSERA.SNOW_ORDERS` on Snowflake). `AdapterConfig.resource_bindings` was added during the live exercise as the natural counterpart to `identity_bindings`. The pattern (ADR-021) already supported this implicitly; the live run made it concrete.

2. **Snowflake's role hierarchy is not flat group membership.** Snowflake roles inherit from each other (HIGH inherits PUBLIC ⇒ HIGH-active users satisfy PUBLIC's predicates). Databricks account groups are flat: `is_account_group_member('A')` and `is_account_group_member('B')` are independent. IR authors targeting both platforms see different effective row-set arithmetic from the same IR. This is now noted in the Snowflake adapter's capability profile.

3. **Snowflake role-discrimination semantics — two distinct primitives, adapter chooses one (see issue #14).** Initial framing of the live-test observation as "DEFAULT_SECONDARY_ROLES = ('ALL') collapses policy discrimination" was sloppy. Snowflake offers two intentionally-distinct primitives: `CURRENT_ROLE()` (primary-role-only; strict semantics, useful for audit/compliance) and `IS_ROLE_IN_SESSION(X)` (any active role; permission-scope semantics, matches standard RBAC). The adapter currently emits `IS_ROLE_IN_SESSION` for byIdentity principal selectors, matching Snowflake's documented recommendation. Under that emission, `DEFAULT_SECONDARY_ROLES = ('ALL')` (the platform default since BCR-1692) is consistent and correct — secondary roles activate, the predicate sees them, permission-scope semantics hold. The "discrimination collapse" observation only manifests when a policy author *expects* primary-role-only semantics (Intent A) but the adapter *emits* permission-scope semantics (Intent B); that is an authoring/emission mismatch, not a platform misfeature. Verified empirically: `SHOW PARAMETERS LIKE '%SECONDARY%' IN SESSION` returns no rows (it is a user property, not a session parameter); `DESCRIBE USER` exposes `DEFAULT_SECONDARY_ROLES = ["ALL"]`. Operational implication for Tessera: be deliberate about which discrimination semantic the policy carries. The byDataset path sidesteps this entirely by gating on `CURRENT_USER()`, which is orthogonal to role activation; the byIdentity path inherits the adapter's current Intent B emission choice. Whether to extend the IR to express the Intent A vs Intent B distinction is deferred to a future exercise — see issue #14. This finding also sharpens the proposed `verify` adapter responsibility: only platform structural assumptions (table exists, column types match) are true verify territory; policy intent ambiguities are resolved at authoring time, not by adapter verification.

These findings are pinned in `adapters/snowflake/capability.py` (entry: `ROW_VISIBILITY`). The scripts that produced them (`adapters/tests/live_snowflake.py`, `adapters/tests/live_databricks.py`) are committed alongside the scaffold and re-runnable for regression checks.

---

## ADR-025 — Add `Execute` to the v0 well-known action vocabulary

**Date:** 2026-05-19
**Status:** Accepted

### Context

The v0 well-known action vocabulary in `spec/v0/ontology.ttl` enumerates `Read`, `Write`, `Delete`, `Share`, `Sample`, and `Aggregate`. The table-grants worked exercise (Scenario C — gating who may invoke `bg_rls_demo.tpch.compute_customer_ltv`) required expressing "principal P may invoke business-logic function F." None of the existing six actions express that intent; the closest, `Read`, conflates retrieving rows with invoking computation.

The migration use case (ADR-003's reference customer engagement) requires lifting Databricks `GRANT EXECUTE ON FUNCTION` statements and Snowflake `GRANT EXECUTE` / `GRANT USAGE ON FUNCTION` statements into IR with no information loss. Without an `Execute` action, the corpus cannot round-trip through Tessera.

A Glean enumeration of Unity Catalog EXECUTE uses surfaced six concrete cases, which split into two semantically distinct categories:

1. **Business-logic invocation** (semantic):
   - Calling a UDF directly in SQL or PySpark.
   - Databricks Apps invoking UC functions as service-principal-bound resources.
   - AI agent tools backed by UC functions.

2. **Policy-mechanism scaffolding** (mechanism):
   - Policy author needs EXECUTE on a UDF to attach it as a row filter or column mask.
   - EXECUTE required when assigning a function via `SET ROW FILTER` or `SET MASK`.
   - Batch Python UC UDFs delegating service credentials.

The two categories require different design treatment: the first is policy intent the IR should express; the second is the same kind of adapter-scaffolding consideration as the GRANT SELECT lesson from the column-mask exercise (where the worked-example diagnostic incorrectly framed deployment-time GRANTs as IR concerns, since corrected via Glean).

### Decision

`Execute` is added to v0 as the seventh well-known action across the four spec files:

- `spec/v0/ontology.ttl` — `tessera:Execute a tessera:Action ; rdfs:label "Execute"@en ; rdfs:comment "Invoke a callable Resource (typically a user-defined function or stored procedure). Scoped to policy intent (gating who can invoke business-logic resources); platform-mechanism uses of EXECUTE (e.g., the grants required to attach a UDF to an enforcement policy) are adapter scaffolding, not modeled in the IR."@en .`
- `spec/v0/context.jsonld` — `"Execute": "tessera:Execute"` short-name binding alongside the existing actions.
- `spec/v0/schema.json` — `Execute` and `tessera:Execute` added to the `action` enum, with the inline description noting the addition's empirical grounding.
- `spec/v0/shapes.ttl` — `tessera:Execute` added to both PolicyShape and PolicyConstraintShape `sh:in` action enumerations.

The semantic-vs-mechanism boundary is explicit in the ontology comment: `Execute` is for policy intent (Glean's category 1). Mechanism uses (Glean's category 2) remain adapter scaffolding, modeled neither in the IR nor in capability profiles — the adapter handles them as part of emit-and-deploy hygiene, parallel to how `GRANT SELECT` on a newly-created table is adapter scaffolding (`feedback_glean_for_databricks_semantics` memory note).

### Rationale

- **Migration completeness.** Without `Execute`, the IR cannot lift `GRANT EXECUTE ON FUNCTION` corpus rows without information loss, breaking ADR-003's primary use case.
- **Cross-platform applicability.** Both Databricks (`GRANT EXECUTE ON FUNCTION`) and Snowflake (`GRANT USAGE ON FUNCTION` / `GRANT EXECUTE ON PROCEDURE`) have the concept. `Execute` is platform-neutral.
- **Closed enum hygiene.** v0 declared its action vocabulary closed for the v0 lifecycle. Suspended-immutability framing (ADR-017) admits this kind of empirically-grounded addition; the exercise's diagnostic is the empirical grounding.
- **Boundary-keeping discipline.** Explicitly recording the semantic-vs-mechanism split prevents future contributors from accidentally pulling implementation-scaffolding uses of EXECUTE into the IR. This is the same boundary the GRANT-SELECT-is-not-policy lesson holds: the IR expresses meaning, not deployment mechanics.

### Consequences

- **All seven previously-committed worked examples re-validate.** No existing policy used `Execute`; the addition is purely additive.
- **The Scenario C IR shape in the table-grants exercise validates cleanly** under schema and SHACL. The exercise's Phase 3 confirmed the Databricks DDL (`GRANT EXECUTE ON FUNCTION ... TO ...`) deploys and is observable via `SHOW GRANTS ON FUNCTION`.
- **Issue [#10](https://github.com/bgiesbrecht/tessera/issues/10) (policy-execute-grants)** is substantively closed by this addition. The exercise's diagnostic records the boundary-keeping discipline; the issue may be closed on GitHub with a pointer to ADR-025 and the diagnostic.
- **The semantic-vs-mechanism boundary documented here applies recursively to future additions.** Subsequent adoptions of platform-specific permission verbs (e.g., `Modify`, `Manage`, `Grant` itself) should follow the same discipline: declare the boundary explicitly in the ontology comment; do not pull mechanism uses into the IR.

### What this ADR does not do

- **Does not introduce `AccessGrantConstraint`** as a policyKind for affirmative grants. The table-grants exercise's Phase 2 surfaces this as an open design question (see the diagnostic §3.4); the decision is deferred to a follow-up ADR after at least one migration exercise touches the affirmative-grant space.
- **Does not declare a `function:` IRI prefix in `context.jsonld`.** The prefix is used informally in the worked example's resource string (`function:bg_rls_demo.tpch.compute_customer_ltv`) but is not validated by the IR layer. Formalization queued alongside [#4](https://github.com/bgiesbrecht/tessera/issues/4) (iri-safety-convention).
- **Does not address `USE SCHEMA`-style scaffolding privileges.** The Databricks emission of Scenario B requires both `GRANT USE SCHEMA` and `GRANT SELECT ON SCHEMA`. `USE SCHEMA` has no Tessera-action analog; the adapter emits it as scaffolding for `Read`. Whether to model it as an additional implicit grant is deferred.

### Note on ordering

ADR-025 lands alongside the table-grants exercise's Phase 2 commit on 2026-05-19. The exercise's Phase 3 results (the diagnostic) are committed in the same commit, demonstrating the exercises-drive-design discipline in action: the gap was discovered empirically, the boundary was sharpened by an external Glean check, and the addition was accepted with explicit scope.

---

## ADR-026 — Add `AccessGrantConstraint` as a first-class policyKind

**Date:** 2026-05-20
**Status:** Accepted; closes issue [#15](https://github.com/bgiesbrecht/tessera/issues/15)

### Context

v0 enumerated four `policyKind` discriminators: `AccessConstraint`, `RowVisibilityConstraint`, `ColumnVisibilityConstraint`, and `DistributionConstraint`. All four are *restriction-shaped* — each declares limits on what is seen, distributed, or accessed.

The table-grants worked exercise (2026-05-19; `spec/v0/examples/table-grants-scenario-{a,b,c}.*`) surfaced a real gap: affirmative grants like `GRANT SELECT ON TABLE foo TO group_bar` have no natural `policyKind` in v0. Phase 2 squeezed them into `RowVisibilityConstraint` with `effect: allow`, which validates structurally but is semantically misleading on three concrete axes (the diagnostic's §3.4 enumerates them):

1. **Reader comprehension.** A `.tessera.yaml` file with `kind: RowVisibilityConstraint` that's actually a table-level grant misleads readers about its intent.
2. **Tooling dispatch.** Adapters typically dispatch on `policyKind` to choose between row-filter emission, column-mask emission, and other shapes. A "RowVisibilityConstraint with effect: allow on a table" forces the adapter to internally detect the affirmative-grant shape and emit `GRANT` SQL — dispatchable but not natural.
3. **Migration extraction.** Lifting a `SHOW GRANTS ON TABLE` row into IR has no honest `policyKind` to assign — `RowVisibilityConstraint` is structurally wrong (no row visibility involved); `ColumnVisibilityConstraint` is also wrong. The IR was missing the concept.

### Decision

Add `tessera:AccessGrantConstraint` as the fifth `policyKind`, across all four v0 spec files:

- `spec/v0/ontology.ttl` — `tessera:AccessGrantConstraint` declared as `rdfs:subClassOf tessera:PolicyConstraint` with a comment explaining the affirmative-grant semantic and the contrast with restriction-shaped constraints.
- `spec/v0/context.jsonld` — `"AccessGrantConstraint": "tessera:AccessGrantConstraint"` short-name binding alongside the existing four kinds.
- `spec/v0/schema.json` — `AccessGrantConstraint` and `tessera:AccessGrantConstraint` added to both `policyKind` enums (the Policy container's and the freestanding-PolicyConstraint enum).
- `spec/v0/shapes.ttl` — `tessera:AccessGrantConstraint` added to the PolicyShape's `sh:in` policyKind enumeration.

The three table-grants exercise YAMLs migrate from `kind: RowVisibilityConstraint` to `kind: AccessGrantConstraint`. The JSON-LDs regenerate cleanly through the v1 converter. All 11 worked-example policies (validation regression set) still pass JSON Schema and SHACL.

### Semantic shape

An `AccessGrantConstraint` policy reads as: "the principals matching the rules' principal selectors are authorized to perform the policy's `action` on the policy's resource." Rules carry `effect: allow` (or `effect: deny` for explicit denial). No `transformation` field (the policy is not value-shaping). `defaultStrategy` is optional — affirmative grants are additive, so principals matching no rule fall through to whatever other policies or platform defaults apply.

Example:

```yaml
policy:
  id: example-table-grant
  kind: AccessGrantConstraint
  appliesTo: { selector: byIdentity, resource: table:catalog.schema.foo }
  action: Read
  rules:
    - principal: { selector: byIdentity, resource: group:bar }
      effect: allow
```

### Rationale

- **Empirically grounded.** The table-grants exercise's diagnostic §3.4 documented the awkwardness concretely; the resolution lands as a small spec addition (parallel in size to ADR-025's `Execute` addition).
- **Migration completeness (per Brice's framing 2026-05-19).** Tessera's primary driving activity is migration — lifting an existing platform's policy corpus into IR and re-emitting on another platform. RBAC table grants are the most common shape in real corpora; the IR has to express them cleanly, not via a misleading squeeze. ADR-003's reference customer engagement explicitly drives this.
- **`effect: allow` and `effect: deny` already exist** in the rule effect enum. No new effects required. The IR vocabulary is purely additive.
- **Suspended-immutability framing (ADR-017) admits this addition** while v0 remains pre-external-dependency. Same posture as ADR-022 (transformation effect-driven) and ADR-025 (`Execute` action): empirically-grounded small additions land in v0 without breaking existing policies.

### Consequences

- **Three artifacts migrated** (`table-grants-scenario-{a,b,c}` YAMLs); JSON-LDs regenerated via the converter. The table-grants diagnostic's §3.4 (the open-question section) becomes resolved-by-ADR-026.
- **All 11 worked-example JSON-LDs re-validate clean** against schema and SHACL.
- **Adapter dispatch becomes cleaner.** An adapter implementing emission can dispatch on `policyKind == "AccessGrantConstraint"` and emit `GRANT` SQL directly, rather than detecting the affirmative shape inside `RowVisibilityConstraint`. Existing adapter code that emitted `GRANT` SQL from `RowVisibilityConstraint + effect: allow` should be updated to recognize the new policyKind; today's UC and Snowflake adapters don't yet emit `GRANT` SQL at all (table-grants emission was hand-derived for the exercise), so this is a forward concern rather than a breaking change.
- **Issue [#15](https://github.com/bgiesbrecht/tessera/issues/15) closes.** The disposition the issue suggested ("defer until a Snowflake-byDataset-migration exercise drives it") is superseded by Brice's 2026-05-20 ask to land it ahead of the migration story rather than alongside.

### What this ADR does not do

- **Does not implement `GRANT`-style emission in either adapter.** The table-grants exercise's hand-derived SQL stays in place as the empirical target; adapter code that lowers `AccessGrantConstraint` to `GRANT` SQL is a queued follow-up, not in scope here.
- **Does not introduce a separate `AccessDenyConstraint` policyKind.** Affirmative denials use `effect: deny` on an `AccessGrantConstraint`; modeling explicit denials as a separate policyKind is not currently justified.
- **Does not address `USE SCHEMA`-style scaffolding privileges.** Same disposition as in ADR-025: those remain adapter scaffolding, not IR-modeled.
- **Does not migrate prior hand-authored JSON-LDs in places other than the table-grants exercise.** No other worked example was using the squeeze pattern.

---

## How to use this document

- Every new technical or stakeholder document begins by reading this file.
- Every claim in a downstream document that depends on a decision references the ADR by number.
- New decisions are added to this file before they are reflected elsewhere.
- Superseded decisions are not edited; a new ADR is added with explicit reference to the superseded one.
- Quarterly review: confirm every "Accepted" ADR is still consistent with the project's direction.
