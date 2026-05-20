# Evaluating Tessera

This page is for decision-makers — security, data architecture, governance leadership — assessing whether Tessera fits a real estate. It is deliberately direct about scope, non-goals, and limitations.

## What Tessera is

Tessera is a portable representation of data governance policy. It lets organizations running multiple data platforms (typically Databricks alongside Snowflake) express *what* their access policies *mean* once, in a vocabulary that is independent of any platform, and translate that meaning into native enforcement on each platform via adapters.

The value proposition is **semantic interoperability of policy**: an agreement that "PII," "fraud investigation purpose," "EU residency," and "audit-log obligation" mean the same thing wherever they are enforced.

Concretely:
- One `.tessera.yaml` file defines the intent.
- Adapters lower that intent to platform-native enforcement (Unity Catalog DDL on Databricks; row-access policies and masking policies on Snowflake).
- The same intent runs everywhere; the adapter handles the platform-specific mechanism.

## What Tessera is not

These are not edge-case clarifications. They are load-bearing scope decisions, documented in ADRs and consistently held:

- **Not a runtime policy engine.** Tessera compiles to platform-native enforcement; it does not insert into the query path. There is no Tessera service that evaluates policies at request time. (ADR-001 disclaims this category.)
- **Not operational interoperability.** Policy behavior when data physically moves between platforms (Delta Sharing, Iceberg, replication) is reserved space. Out of scope for v0.
- **Not a universal authorization language.** Scope is data-platform governance specifically. Not for application authz, not for API gateways, not for OS-level access control.
- **Not a substitute for Unity Catalog inside Databricks-only shops.** If you run only Databricks, Unity Catalog already does what you need. Tessera adds value precisely when policy must mean the same thing on Unity Catalog AND somewhere else.
- **Not a standards-body submission.** Tessera draws semantic alignment from ODRL, DPV, and adjacent vocabularies (ADR-005) but does not seek formal standardization. It is engineering posture: skunkworks, customer-driven, ADR-disciplined (ADR-002).
- **Not a Databricks product.** It is an Anthropic / Databricks Field Engineering project led by Brice Giesbrecht. It does not have a Databricks product roadmap, formal SLAs, or commercial commitments.
- **Not prescriptive about authoring style.** Tessera represents policy intent; it does not invent cross-platform authoring recommendations the platforms themselves do not document. Where Snowflake or Databricks recommends a pattern, Tessera surfaces and cites that recommendation. Where they don't, Tessera describes what each shape represents and lets you choose. (ADR-027.)

## When Tessera fits

The strongest fit is an organization with:

- **Multiple data platforms** — at least one of which is Databricks (the adapter Tessera leans into first) and at least one other (Snowflake, custom Spark+ACL, BigQuery on the roadmap).
- **Real policy ambiguity** — different teams or platforms have arrived at semantically equivalent policies via different mechanisms (governed tags vs object tags vs classification tables) and the inconsistency is costing audit time, migration time, or policy-drift incidents.
- **An engineering culture that values explicit decision records** — Tessera is opinionated about ADR discipline, capability profiles as documents, and diagnostic surfaces as first-class artifacts. Organizations that prefer black-box tooling will find the surface area heavy.

Weaker fit:

- **Single-platform Databricks shops.** Use Unity Catalog directly. Tessera adds friction without value.
- **Pure Snowflake shops.** Snowflake's native policy primitives plus their documented mapping-table pattern cover most needs. Tessera adds value here only if there is a credible second-platform plan.
- **Real-time policy enforcement requirements.** Tessera is compile-to-DDL; if the requirement is runtime evaluation at request time, the project is misaligned.

## The hardest concession

Tessera does not contest Unity Catalog's role inside Databricks. Unity Catalog is the source of truth for governance inside the Databricks platform; Tessera operates between governance estates. This concession is irreducible and load-bearing. Documents or framings that contradict it produce internal Databricks friction the project cannot survive.

If your evaluation hinges on Tessera replacing Unity Catalog — or being preferred to it for Databricks-internal policy — the answer is no. Tessera is for the gap between estates, not within an estate.

## Honest limitations as of 2026-05-19

These are not roadmap items; they are the current state. Read them before committing.

**The v0 IR has known gaps:**
- Tokenize / Bucketize parameter shapes are deferred to v1.
- Two-axis attribute matching (issue #12) is not modeled.
- `PrincipalSetFromTable` does not formally split ACL-column-name from protected-column-name (one of the v1 candidates surfaced by the Snowflake byDataset exercise).
- Match-modifier declarations on `byDataset` selectors (case-insensitive match, whitespace normalization) are not modeled.

The v0 immutability bar is suspended (ADR-017) until external dependency exists, so these gaps remain addressable. But they are gaps today.

**The adapter scaffolds are first cuts:**
- Databricks: emits row-visibility for `byIdentity`. Column visibility, ABAC, `byDataset`, and other selector kinds are stubbed with diagnostics.
- Snowflake: emits row-visibility for `byIdentity` and `byDataset`. Column visibility, ABAC, and other selector kinds are stubbed with diagnostics.
- Discovery, extraction, reconciliation are stubbed across both adapters. The contract defines them; the implementations don't yet exist.

**Tooling is incomplete:**
- YAML → JSON-LD converter exists (v1, 2026-05-20). Reverse direction (JSON-LD → YAML) is deferred. Comment preservation in YAML round-trips is also deferred; the converter uses `ruamel.yaml` from the start so the feature can land cleanly later.
- No CLI. Library-shaped Python only.
- No formal `verify` mode for deployment-time configuration checks (e.g., "this principal binding maps to a role that doesn't exist on the target," "the target column type doesn't match the policy's expected type").

**The customer engagement backing v0 is one real ACL-pattern shop.** ADR-003's reference customer — a Snowflake shop with hundreds of ACL-table-based policies — drove the design discipline (adapter-first, `byDataset` first-class, capability profiles as artifacts). Other customer corpora may strain the design in ways v0 hasn't yet absorbed.

## Decision framework

Three questions in order:

1. **Does your estate have at least two data platforms where the same policy must mean the same thing?** If no, stop here; use the platforms' native primitives.

2. **Is policy ambiguity / drift between platforms a real cost — audit failures, migration friction, governance incidents?** If no, the engineering overhead of adopting Tessera is not justified by the value it adds. Revisit when the cost materializes.

3. **Can your engineering culture absorb explicit ADR discipline, capability-profile reading, and diagnostic-surface engagement?** Tessera does not present a unified abstraction over platforms; it presents an honest cross-platform vocabulary with explicit per-platform translation. Teams expecting black-box governance will find the surface area heavy.

If all three are yes, Tessera is likely a fit. Start with [`tutorial.md`](./tutorial.md) and the worked examples in `spec/v0/examples/`.

## How Tessera compares

| Surface | Tessera | Platform-native (UC / Snowflake) | Runtime engines (OPA, Cedar) | Standards (ODRL, DPV) |
|---|---|---|---|---|
| Where it lives | Compile-time, between authoring and platform DDL | Inside each platform's catalog | At request time, in the query path | Vocabulary specifications |
| What it produces | Platform-native DDL via adapter | Platform DDL directly | Allow / deny decisions per request | No artifacts; vocabulary only |
| Cross-platform fidelity | Yes; that's the point | No (each platform's vocabulary) | No (each engine's policy language) | Partial (vocabulary alignment, no enforcement) |
| Runtime overhead | Zero (DDL is the runtime) | Zero (native primitives) | Per-request evaluation cost | N/A |
| Integration with native platform tooling | Strong (emits DDL the platform validates) | Strong (it *is* the platform) | Weak; bypasses platform primitives | None directly |
| Maturity | First-cut scaffolds; one customer corpus; ADRs disciplined | Mature, production-grade | Mature (OPA), emerging (Cedar) | Mature vocabularies; not enforcement |

Tessera's positioning: compile-time portability between platforms, leaning into each platform's native enforcement. Not a runtime engine. Not a standards effort. Not a replacement for native primitives.

## What to read next

- [`tutorial.md`](./tutorial.md) — concrete end-to-end if you want to see what Tessera actually does.
- `docs/executive-summary.md` — one-page leadership brief.
- `docs/problem-and-recommendation.md` — stakeholder framing.
- `DECISIONS.md` — every significant decision recorded. ADRs 001–027.
- `docs/technical-design-v0.2.md` — spec-level reference.
- `spec/v0/examples/` — seven completed worked exercises with full artifacts and diagnostic findings.
