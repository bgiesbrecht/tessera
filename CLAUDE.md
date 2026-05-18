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

Currently the recorded ADRs are 001 through 011:

- 001 — Project framing: semantic interoperability, not migration
- 002 — Organizational posture: skunkworks, customer enablement
- 003 — Architecture: adapter model is the unifying abstraction
- 004 — Canonical form is JSON-LD; authoring form is YAML
- 005 — Vocabulary alignment with existing standards (DPV, ODRL, Cedar, XACML)
- 006 — Sequencing: DSL designed last
- 007 — Open technical questions still to resolve
- 008 — Project name: Tessera
- 009 — License: Apache 2.0
- 010 — Repository at github.com/bgiesbrecht/tessera
- 011 — Canonical namespace URL: GitHub Pages

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
DECISIONS.md                      — 11 ADRs covering all major decisions
docs/
  executive-summary.md            — one-page leadership brief
  problem-and-recommendation.md   — stakeholder framing, no implementation
  technical-design-v0.2.md        — current technical specification
  stakeholder-meeting-agenda.md   — decision-meeting template
spec/v0/
  context.jsonld                  — JSON-LD context, v0 (immutable)
  ontology.ttl                    — OWL/Turtle ontology, v0 (immutable)
```

### What's planned but not built (in rough order of priority)

```
spec/v0/
  schema.json                     — JSON Schema for IR structural validation
  shapes.ttl                      — SHACL shapes for semantic validation
  examples/                       — worked policy examples in YAML and JSON-LD
tools/
  converter/                      — YAML ↔ JSON-LD converter
  linter/                         — full validation pipeline
adapters/
  unity-catalog/                  — first adapter (Databricks)
  snowflake/                      — second adapter
  custom-acl/                     — third adapter (real customer engagement)
```

### Canonical URLs

These resolve via GitHub Pages once Pages is enabled for the repo (ADR-011):

- Namespace: `https://bgiesbrecht.github.io/tessera/spec/v0/vocab#`
- Context: `https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld`
- Ontology: `https://bgiesbrecht.github.io/tessera/spec/v0/ontology.ttl`

The contents of `spec/v0/` are **immutable** once the v0 release is cut. If a change to vocabulary or context is needed, the answer is to cut v1 at `spec/v1/`, not to edit v0 in place. This is non-negotiable because the URLs above appear in every customer policy file that uses v0, and changing them silently breaks compatibility.

---

## The architecture, briefly

Three forms of policy exist:

1. **YAML** (`.tessera.yaml` files). Primary authoring form. What customers and engineers write and review. Lives in the customer's repository.
2. **JSON-LD.** Canonical form. The normative serialization defined by the spec. Generated from YAML by tooling. Consumed by validators, reasoners, and adapters.
3. **DSL.** Future third form, deferred per ADR-006. Designed only after the IR has stabilized through real corpus exposure and at least two adapter implementations.

Adapters connect the IR to real systems. Each adapter has four responsibilities: discovery (inventory policy-bearing artifacts), extraction (lift to IR), emission (lower from IR), and reconciliation (diff state). Each adapter declares a capability profile listing which IR concepts it supports, partially supports, or cannot support. Diagnostic reports are first-class artifacts of every emit operation.

Adapters are *peers*. Unity Catalog adapter, Snowflake-native adapter, and custom-pattern adapters all implement the same contract. The IR layer is platform-neutral by design — privileging one platform there would defeat the project.

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

### Priority 2 — A worked example end-to-end

Write a complete YAML policy file at `spec/v0/examples/acl-driven-row-visibility.tessera.yaml` that exercises:

- The `byDataset` selector pattern (data-driven principal set from an ACL table)
- Classification-based resource selection
- Purpose binding via condition
- An obligation (audit-log)
- Provenance metadata

Then convert it by hand to the equivalent JSON-LD at `spec/v0/examples/acl-driven-row-visibility.jsonld`. This is the artifact that proves the YAML ↔ JSON-LD pipeline conceptually works, even before the converter is built.

Validate by hand that the JSON-LD references against the published context and ontology resolve correctly. This catches any naming inconsistencies between the three files before they get baked in.

### Priority 3 — JSON Schema for structural validation

`spec/v0/schema.json` defining the structural requirements of a Tessera policy in JSON-LD form. Used by the linter (eventually) and by any tool that wants to validate IR without invoking a reasoner. Should be a JSON Schema 2020-12 document.

The schema should cover the structure described in §4.2 of the technical design (identity, vocabulary reference, type, selectors, condition, effect, obligations, capability requirements, provenance). It should not duplicate semantic constraints that belong in SHACL (e.g., "this CURIE must reference a known classification" is SHACL territory, not JSON Schema).

### Priority 4 — A first cut of SHACL shapes

`spec/v0/shapes.ttl` containing SHACL shapes that validate semantic well-formedness beyond what JSON Schema captures: classification references resolve, selector kinds match selector classes, purpose references are known purposes, etc. This is the validation layer that requires the ontology to be loaded.

### Priority 5 — The converter tool

`tools/converter/` — a small Python (or Go, user's preference) tool that converts between `.tessera.yaml` and JSON-LD in both directions. Comment preservation per ADR-004: comments preserved positionally for YAML round trips; mapped to `rdfs:comment` on YAML → JSON-LD where attached to a node; JSON-LD → YAML does not synthesize comments.

Use `ruamel.yaml` if Python (because PyYAML drops comments). Use `yaml.v3` if Go and handle comments carefully.

### Priority 6 — First adapter scaffolding

`adapters/unity-catalog/` — the first adapter, against the platform the user knows best. Even before any real translation logic, the adapter contract (discovery / extraction / emission / reconciliation, capability profile, report formats) should be scaffolded. This is what pressure-tests the IR design before the Snowflake adapter exists.

---

## Things to actively avoid

These are anti-patterns this project specifically rejects. Mentioned not because they're tempting at first glance, but because they often appear as plausible suggestions in adjacent projects:

- **Do not propose a runtime policy engine.** ADR-001 disclaims this category explicitly. If a user request seems to require it, surface the conflict.
- **Do not introduce platform-specific concepts into the vocabulary or IR.** Words like "masking policy" or "row access policy" belong to platform DDL; the IR uses platform-neutral terms like "ColumnVisibilityConstraint." Platform-specific concepts live in adapters.
- **Do not "improve" the vocabulary by tightening alignment with ODRL or DPV unilaterally.** The current alignment is documented as `skos:exactMatch` / `skos:closeMatch` per ADR-005; tightening these to `owl:equivalentClass` requires deliberate decision because it has reasoning consequences.
- **Do not edit ADRs 001–011 retroactively.** They are historical record. If something needs to change, propose a new ADR that supersedes the old one.
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

The user (Brice, github: `bgiesbrecht`) has just established the repository with the initial commits. The immediate context as of this handoff:

- Documents and spec artifacts are committed.
- GitHub Pages is *not yet* enabled (or has just been enabled — verify).
- No worked examples exist yet.
- No tooling exists yet.
- No adapter scaffolding exists yet.
- The custom-ACL customer engagement has not yet started.

The user's current preferred sequencing is roughly the priority order above, but is open to redirection based on what proves most valuable. The user values:

- Honesty over completeness. Better to ship less and label it correctly than to ship more and overstate.
- Posture preservation. The skunkworks framing and the Unity-Catalog-source-of-truth concession are non-negotiable.
- Drift prevention. New decisions get ADRs; existing decisions are respected.
- Working artifacts over speculative design. The worked example proves more than another spec revision.

---

## Final note

This document is itself an artifact and may need updating. When ADRs are added, when the project's state changes meaningfully, when the priorities shift — this document should be revised so that the next handoff (whether to another tool, another contributor, or a future session) inherits an accurate picture rather than a stale one.

The document should be revised by appending updates with dates, not by silently rewriting history. Stale sections can be marked as such rather than deleted.
