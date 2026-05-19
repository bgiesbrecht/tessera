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

## How to use this document

- Every new technical or stakeholder document begins by reading this file.
- Every claim in a downstream document that depends on a decision references the ADR by number.
- New decisions are added to this file before they are reflected elsewhere.
- Superseded decisions are not edited; a new ADR is added with explicit reference to the superseded one.
- Quarterly review: confirm every "Accepted" ADR is still consistent with the project's direction.
