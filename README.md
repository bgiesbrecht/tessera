# Tessera

**A portable representation of data governance policy for multi-platform environments.**

Tessera lets you express what your data governance policies *mean* — who can see what, under what conditions, for what purpose — once, in a form that is independent of any single data platform. The same policy artifact can be translated into native enforcement on Databricks Unity Catalog, on Snowflake, or on custom enforcement patterns built inside your organization. Different systems hold matching tokens that prove they enforce the same thing.

The name is from the Latin *tessera*: a small token, often split in two between parties to a covenant, where each half later matches the other and proves the agreement. That is what this project does for policy across platforms.

---

## What Tessera is

Tessera is a specification, a vocabulary, and a set of reference adapters. Together they let an organization:

- **Express governance policies in a portable, intent-preserving form.** Classification, purpose, principal, conditions, obligations — captured in a shared vocabulary that means the same thing on every platform.
- **Translate policies into native enforcement** on Unity Catalog, Snowflake, and customer-specific enforcement patterns, through purpose-built adapters.
- **Extract existing policies from a platform back into the portable form**, so an organization with thousands of policies already in place doesn't have to hand-author them again.
- **Review, version-control, and audit policies** as a primary artifact — not as a secondary translation of platform DDL.

Tessera delivers **semantic interoperability of policy**: an agreement, encoded in tooling, that "PII," "fraud investigation purpose," "EU residency," and "audit-log obligation" mean the same thing wherever they are enforced.

## What Tessera is not

- **Not a runtime policy enforcement engine.** Tessera compiles to and from the platforms that already do enforcement well. It does not insert itself into the query path.
- **Not a replacement for platform-native governance.** Unity Catalog is the source of truth for governance inside a Databricks environment. Snowflake's governance is the source of truth inside Snowflake. Tessera is the lingua franca *between* governance estates, not a replacement for either of them.
- **Not an official product of any vendor.** Tessera is an initiative intended to help solve a real and continuous governance problem. It does not represent an official Databricks position, it is not coordinated with Snowflake.
- **Not a universal authorization language.** Tessera is scoped to data-platform governance and is intentionally narrower than general-purpose authorization tools like Cedar or OPA. Narrowness is a feature.

## Who Tessera is for

Tessera is useful if you run data on more than one platform — typically Databricks alongside Snowflake — and you face one or more of these problems:

- The same governance rule has to be authored, maintained, and audited separately in each platform, and the two implementations drift over time.
- Migration of workloads between platforms is blocked or slowed by the cost of manually rewriting governance policies.
- Custom enforcement patterns (ACL tables, view layers, middleware) exist inside the organization and are not visible to enterprise governance because they don't fit either platform's native catalog.
- Auditors and reviewers cannot point to a single artifact that says what the policy actually is, independent of the code that enforces it.

If you run a single platform and that platform's governance meets your needs, Tessera is not for you.

## Status

Current version: **0.6.0** (see `VERSION`, `CHANGELOG.md`).

Both reference adapters are real and exercise the full ADR-024 cycle — `emit` / `discover` / `extract` / `reconcile` — on Databricks Unity Catalog and on Snowflake. Three policy shapes are implemented across both platforms: `RowVisibilityConstraint` (`byIdentity`, `byScope`, `byDataset`), `ColumnVisibilityConstraint` (`Redact`), and `AccessGrantConstraint` (table, function, schema-fan-out). Bidirectional migration between the two platforms is demonstrated end-to-end in `adapters/tests/live_migration_demo.py` and its reverse-direction sibling, with verification queries confirming the same policy intent enforces the same way on both sides.

The IR — JSON-LD context, OWL ontology, JSON Schema, SHACL shapes — lives in `spec/v0/`. Per ADR-017, the v0 immutability bar is **suspended** until external dependency exists (a third-party adapter, a customer corpus, downstream tooling): additions continue to land in v0, each captured as an ADR. The published GitHub Pages URLs under `bgiesbrecht.github.io/tessera/spec/v0/` will not change once external consumers exist.

For a demo-ready tour of what's working today, read [`docs/showcase.md`](docs/showcase.md). For per-version detail, read `CHANGELOG.md`. Twenty-one of thirty-one tracked issues remain open; the breakdown is in `docs/issue-drafts/README.md`.

Known limitations at 0.6.0:

- UC ABAC `byScope` column-mask emission is queued ([#30](https://github.com/bgiesbrecht/tessera/issues/30)).
- Snowflake ABAC `byScope` is queued ([#31](https://github.com/bgiesbrecht/tessera/issues/31)) — different platform mechanism.
- YAML comment preservation in round-trips is deferred to converter v2.
- Schema-pattern resource bindings are not yet implemented.

## Architecture in brief

```
              ┌────────────────────────────────────┐
              │     Authoring form (YAML)          │
              │ *.tessera.yaml, comments preserved │
              └─────────────────┬──────────────────┘
                                │  convert
                                ▼
              ┌─────────────────────────────────┐
              │   Canonical IR (JSON-LD)        │
              │   normative; validators consume │
              └─────────────────┬───────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
       ┌────────────┐    ┌────────────┐    ┌────────────┐
       │  Adapter   │    │  Adapter   │    │  Adapter   │
       │ Unity Cat. │    │ Snowflake  │    │   Custom   │
       │            │    │   native   │    │  pattern   │
       └────────────┘    └────────────┘    └────────────┘
```

Three forms exist:

- **YAML** is what you author and review. It lives in your repository, supports comments, and is familiar from DABs, Lakeflow Declarative Pipelines, metric views, dbt, and Kubernetes.
- **JSON-LD** is the canonical form. It is generated from YAML and consumed by validators, reasoners, and adapters. When two tools disagree about what a policy means, the JSON-LD form is the tiebreaker.
- **Adapters** are the bridge to real systems. Each adapter handles discovery, extraction, emission, and reconciliation against one platform or pattern, and declares its capabilities explicitly so that limitations are visible and honest.

## Repository structure

```
.
├── README.md                              ← this file
├── LICENSE                                ← Apache 2.0
├── DECISIONS.md                           ← 26 numbered ADRs
├── CHANGELOG.md                           ← per-version detail
├── VERSION                                ← current: 0.6.0
├── docs/
│   ├── showcase.md                        ← demo-anchored tour of 0.6.0
│   ├── executive-summary.md               ← one-page leadership brief
│   ├── problem-and-recommendation.md      ← stakeholder framing
│   ├── technical-design-v0.2.md           ← current technical spec
│   ├── w3c-overview.md                    ← semantic-web stack tour
│   ├── worked-example-exercise.md         ← worked-example methodology
│   ├── stakeholder-meeting-agenda.md      ← decision-meeting template
│   ├── user-guide/                        ← practitioner documentation
│   │   ├── tutorial.md                    ← first policy, end to end
│   │   ├── authoring.md                   ← writing .tessera.yaml
│   │   ├── operating.md                   ← deploying and reconciling
│   │   ├── contributing.md                ← repo conventions
│   │   ├── evaluating.md                  ← adopt / don't-adopt framework
│   │   └── scenarios/                     ← scenario tutorials
│   ├── exercises/                         ← per-example input briefs
│   ├── handoffs/                          ← dated context handoffs
│   ├── issue-drafts/                      ← issue scoping documents
│   └── v1-candidates/                     ← deferred-to-v1 design notes
├── spec/
│   └── v0/
│       ├── context.jsonld                 ← JSON-LD context
│       ├── ontology.ttl                   ← OWL/Turtle ontology
│       ├── schema.json                    ← JSON Schema 2020-12
│       ├── shapes.ttl                     ← SHACL shapes
│       └── examples/                      ← worked-example artifacts
├── adapters/
│   ├── contract/                          ← Adapter ABC, Capability, AdapterConfig, reconcile
│   ├── unity_catalog/                     ← Databricks adapter (full cycle)
│   ├── snowflake/                         ← Snowflake adapter (full cycle)
│   └── tests/                             ← parity tests + live demo scripts
└── tools/
    ├── converter/                         ← YAML → JSON-LD
    └── cli/                               ← unified `tessera` CLI
```

Per ADR-017, the contents of `spec/v0/` are not yet frozen — additions land in v0 (each captured as an ADR) until external dependency exists. See `CHANGELOG.md` for what changed at each version.

## How to read the documents

Routing by goal:

- **"What does Tessera actually do today?"** — `docs/showcase.md`. The 5–10 minute demo-anchored tour. Start here if you're new.
- **"Should we adopt this?"** — `docs/user-guide/evaluating.md`, then `docs/executive-summary.md` and `docs/problem-and-recommendation.md`.
- **"How do I write a policy?"** — `docs/user-guide/tutorial.md`, then `docs/user-guide/authoring.md`, then the scenarios under `docs/user-guide/scenarios/`.
- **"How do I deploy and reconcile?"** — `docs/user-guide/operating.md`.
- **"How does the IR work? Why is it shaped this way?"** — `docs/technical-design-v0.2.md` (the current technical specification), then the relevant ADRs in `DECISIONS.md`.
- **"Why does Tessera use RDF/OWL/SHACL?"** — `docs/w3c-overview.md`.
- **"How do I build an adapter or extend the framework?"** — `docs/user-guide/contributing.md`, the adapter contract in `adapters/contract/`, ADR-024.
- **"Show me something runnable."** — `adapters/tests/live_migration_demo.py` (Snowflake → Databricks, end to end); the reverse-direction sibling; the worked-example artifacts in `spec/v0/examples/`.

`DECISIONS.md` is the authoritative record: every decision that shapes the project lives there as a numbered ADR. When other documents conflict with an ADR, the ADR wins and the document gets fixed.

## Foundational decisions

The project is grounded in **26 recorded ADRs** (see `DECISIONS.md` for the complete record and rationale). The decisions that most shape how a reader should understand the project:

**Posture and framing**
- **ADR-001** Value proposition is semantic interoperability across platforms, not migration. Migration is a derived benefit.
- **ADR-002** Skunkworks customer-enablement initiative. Unity Catalog is the source of truth *inside* Databricks; Tessera operates *between* governance estates.
- **ADR-017** v0 immutability is **conditional**: it engages when external dependency exists (third-party adapter, customer corpus, downstream tooling), not on a date.

**Architecture**
- **ADR-003** Adapters are the unifying abstraction. Native and custom enforcement patterns are peers, not core-and-extension.
- **ADR-004** JSON-LD is the canonical form of the IR; YAML is the primary authoring form.
- **ADR-005** Vocabulary reuses existing standards (W3C ODRL, W3C DPV) where they fit; alignment is declared via SKOS.
- **ADR-024** Adapter contract: every adapter implements `emit` / `discover` / `extract` / `reconcile`, plus a declared `CapabilityProfile`.

**IR shape**
- **ADR-013 / ADR-014 / ADR-015** Policy container as canonical multi-rule shape, with explicit `defaultStrategy` / `baselineGroup` / `defaultBranch` fields and ordered first-match combining.
- **ADR-016 / ADR-022** Transformations are parameterized objects (`{type: Redact, replacement: ...}`), tied to effect rather than policy-kind.
- **ADR-018 through ADR-021** ABAC additions: `AttributeAxis`, `byScope`, composable matching, adapter-configuration mapping for the platform-specific tag mechanism.
- **ADR-023** Cross-policy combination algebra (γ-with-refinement).
- **ADR-026** `AccessGrantConstraint` as a first-class policyKind alongside row and column visibility.

**Project mechanics**
- **ADR-008 / ADR-009 / ADR-010 / ADR-011 / ADR-012** Name (`tessera`), license (Apache 2.0), repository (`github.com/bgiesbrecht/tessera`, public), canonical URLs (GitHub Pages under `bgiesbrecht.github.io/tessera/spec/v0/`).

## Posture toward the platforms

Tessera takes a principled and explicit position with respect to the platforms it interoperates with:

- **Databricks (Unity Catalog).** The Unity Catalog adapter is the most thoroughly developed adapter because that is the platform the project author knows best. Unity Catalog is treated as the source of truth for governance *inside* a Databricks environment; nothing in Tessera contradicts that.
- **Snowflake.** The Snowflake adapter is built against the public surface of the Snowflake platform, as any partner integration would be. The project does not coordinate with Snowflake and does not exclude it.
- **Other platforms.** Adapters for other platforms (BigQuery, Redshift, on-premise warehouses, custom enforcement patterns) are first-class peers of the two named adapters. The IR layer is platform-neutral by design and the adapter contract treats them all the same.

This neutrality at the IR layer is structural: a project that privileges one platform in its canonical representation would defeat the point of the project, which is to make policy meaning portable.

## Contributing

Contributions are welcome under the project's current skunkworks model with three caveats:

- **The ADRs are authoritative.** Contributions that conflict with a recorded decision should propose a new ADR first; the implementation follows.
- **The IR layer stays platform-neutral.** Pull requests that introduce platform-specific concepts into the vocabulary or IR will be redirected to the relevant adapter.
- **Honesty over coverage.** It is better to declare that an adapter cannot enforce a concept than to silently approximate it. The diagnostic and extraction reports are the mechanism for this.

## License

Apache License 2.0. See `LICENSE` for the full text and `DECISIONS.md` ADR-009 for the rationale.

## Contact

Project maintained by Brice Giesbrecht ([@bgiesbrecht](https://github.com/bgiesbrecht)). Issues and discussions on the repository are the preferred channel; the project's skunkworks posture (ADR-002) means responses are best-effort and not on behalf of any employer.

---

*Tessera is a small token. Two halves, held by different parties, that match when brought together. That is the project.*
