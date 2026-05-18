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

## How to use this document

- Every new technical or stakeholder document begins by reading this file.
- Every claim in a downstream document that depends on a decision references the ADR by number.
- New decisions are added to this file before they are reflected elsewhere.
- Superseded decisions are not edited; a new ADR is added with explicit reference to the superseded one.
- Quarterly review: confirm every "Accepted" ADR is still consistent with the project's direction.
