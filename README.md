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
- **Not an official product of any vendor.** Tessera is a initiative to help solve a real and continuous governance problem. 
- **Not a universal authorization language.** Tessera is scoped to data-platform governance and is intentionally narrower than general-purpose authorization tools like Cedar or OPA. Narrowness is a feature.

## Who Tessera is for

Tessera is useful if you run data on more than one platform — typically Databricks alongside Snowflake — and you face one or more of these problems:

- The same governance rule has to be authored, maintained, and audited separately in each platform, and the two implementations drift over time.
- Migration of workloads between platforms is blocked or slowed by the cost of manually rewriting governance policies.
- Custom enforcement patterns (ACL tables, view layers, middleware) exist inside the organization and are not visible to enterprise governance because they don't fit either platform's native catalog.
- Auditors and reviewers cannot point to a single artifact that says what the policy actually is, independent of the code that enforces it.

If you run a single platform and that platform's governance meets your needs, Tessera is not for you.

## Status

Tessera is in early design. The specification is being drafted; reference adapters do not yet exist. The current focus is:

1. Stabilizing the vocabulary and intermediate representation.
2. Publishing the JSON-LD context as a stable, versioned reference.
3. Building the first end-to-end adapter (Unity Catalog) followed by the second (Snowflake-native).
4. Working through a real customer's custom enforcement pattern as the proving ground for adapter extensibility.

Expect breaking changes in everything until a v0.1 milestone is cut. After v0.1, the JSON-LD context is immutable per version; the YAML authoring form, the adapter contract, and the reference implementations follow normal semantic-versioning practice.

## Architecture in brief

```
              ┌─────────────────────────────────┐
              │     Authoring form (YAML)       │
              │ *.tessera.yaml, comments preserved│
              └─────────────────┬───────────────┘
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
├── DECISIONS.md                           ← decision log (ADRs)
├── docs/
│   ├── executive-summary.md               ← one-page brief
│   ├── problem-and-recommendation.md      ← stakeholder framing
│   ├── technical-design-v0.2.md           ← current technical spec
│   └── stakeholder-meeting-agenda.md      ← decision-meeting template
├── spec/
│   └── v0/
│       ├── context.jsonld                 ← JSON-LD context (v0, immutable)
│       ├── ontology.ttl                   ← OWL/Turtle ontology (v0, immutable)
│       ├── schema.json                    ← JSON Schema (planned)
│       └── shapes.ttl                     ← SHACL shapes (planned)
├── adapters/
│   ├── unity-catalog/                     ← planned
│   ├── snowflake/                         ← planned
│   └── custom-acl/                        ← planned, first customer engagement
└── tools/
    ├── converter/                         ← YAML ↔ JSON-LD (planned)
    └── linter/                            ← validation pipeline (planned)
```

Directories marked *planned* do not exist yet. The current artifact set is the documents under `docs/` and the context document under `spec/context/`.

## How to read the documents

In order, for a new contributor:

1. **`DECISIONS.md`** — read first, always. Every decision that shapes the project lives here as a numbered ADR. All other documents are consistent with these decisions; when they conflict, the ADRs win and the document gets fixed.
2. **`docs/executive-summary.md`** — the one-page version of what the project is and why.
3. **`docs/problem-and-recommendation.md`** — the stakeholder-facing framing of the problem and the proposed approach, written without code or technical specifics.
4. **`docs/technical-design-v0.2.md`** — the current technical specification. References the ADRs for foundational decisions; describes the architecture, vocabulary, IR, adapter contract, and reference implementation scope.
5. **`spec/v0/context.jsonld`** — the JSON-LD context document. The concrete vocabulary the rest of the spec builds on. Companion: `spec/v0/ontology.ttl`, the formal ontology in Turtle/OWL.

If you're trying to evaluate whether Tessera fits a specific environment, read 2 and 3 and stop. If you're trying to contribute to the spec or build an adapter, read all five.

## Foundational decisions

The project is grounded in seven recorded decisions (see `DECISIONS.md` for the full text and rationale):

- **ADR-001** Tessera's value proposition is semantic interoperability across platforms, not migration. Migration is a derived benefit.
- **ADR-002** Tessera is a skunkworks customer-enablement initiative. Unity Catalog remains the source of truth inside Databricks; Tessera operates between governance estates.
- **ADR-003** Adapters are the unifying abstraction. Native and custom enforcement patterns are peers, not core-and-extension.
- **ADR-004** JSON-LD is the canonical form of the intermediate representation; YAML is the primary authoring form.
- **ADR-005** The vocabulary reuses existing standards (W3C ODRL, W3C DPV, Cedar, XACML) where they fit, rather than reinventing them.
- **ADR-006** A custom DSL is deferred until the IR has stabilized through real corpus exposure and at least two adapter implementations. YAML is the authoring surface in the interim.
- **ADR-007** Several technical questions remain open and are tracked explicitly rather than resolved by default.

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
