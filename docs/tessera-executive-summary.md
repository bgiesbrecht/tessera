# Federated Governance Policy — Executive Summary

**One-page brief.** A customer-enablement initiative for joint Databricks–Snowflake environments. Full problem statement and recommendation available separately.

---

## The customer problem we are responding to

Many of our customers run Databricks alongside Snowflake. Some did this by design — different platforms for different workloads — and some inherited the configuration through acquisition. In nearly all cases, consolidation is not on the near-term roadmap, and the multi-platform estate is the steady state.

These customers face a governance problem that neither platform can solve alone. The same business rules — who can see what data, under what conditions, for what purpose — must be enforced in two places, in two different mechanisms, with no shared artifact that says what the policy actually is. The intent behind each rule, expressed once by a governance team, has to be hand-translated twice into platform-specific code. Over time the two implementations drift, audits have to be conducted separately in each platform's terms, and migrations between workloads become expensive enough that customers defer governance modernization rather than face the translation cost.

This problem is structural to multi-platform environments. It cannot be solved by either platform improving its own governance — Unity Catalog is the right answer inside Databricks, and Snowflake's governance is the right answer inside Snowflake. The gap is not inside either platform; it is between them.

## What we propose to build

A portable, intent-preserving representation of governance policies, expressed in a shared vocabulary, that can be translated to Unity Catalog and to Snowflake-native enforcement through purpose-built adapters. Customers who run both platforms get a single artifact — reviewable, version-controlled, auditable — that expresses what they want enforced. The adapters do the work of translating that artifact into the native mechanisms each platform actually uses to enforce it.

The shared meaning lives in the portable representation. The platform-specific mechanics live in the adapters. This is **semantic interoperability of policy**: an agreement that "PII," "fraud investigation purpose," "EU residency," and "audit-log obligation" mean the same thing wherever they are enforced.

## What this is, and is not, with respect to Unity Catalog

Unity Catalog is the source of truth for governance inside a Databricks environment. This project does not change that. For customers running Databricks alone, this project is not relevant — Unity Catalog already does what they need.

This project is for customers running Databricks alongside another platform, where the question is not "what is the source of truth inside Databricks" but "how do we express policy intent in a way that both platforms can honor consistently." The portable representation is the lingua franca *between* governance estates. Inside the Databricks estate, Unity Catalog remains authoritative; the portable representation describes what Unity Catalog should enforce and what its peer system on the other platform should enforce equivalently. The adapter from the portable representation to Unity Catalog is rich and treats Unity Catalog as a first-class target.

This is a customer-enablement initiative, not a standards effort. We are not proposing that the industry adopt a new governance standard. We are proposing to give customers who run multi-platform environments a tool that solves a real and continuous problem they face today.

## What this delivers

| Today, for multi-platform customers | With this approach |
|---|---|
| The same business rule is encoded twice, in Unity Catalog and in Snowflake, and drifts over time | One policy artifact expresses intent; Unity Catalog and Snowflake each enforce a translation of it |
| Cross-platform consistency is an expert-led, manual exercise | Divergence is diffable against the shared artifact |
| Policy intent is reconstructed from DDL, comments, and tribal knowledge | Intent is captured directly, in standard vocabulary |
| Audits are conducted per platform, in platform-specific terms | Audits operate on the portable artifact, with platform-specific evidence attached |
| Custom enforcement patterns (ACL tables, view layers) are opaque to enterprise governance | Custom patterns are first-class peers of native platform mechanisms |
| Migration between workloads is an open-ended manual project | Migration is a special case of the same capability |

## What this is, precisely

The project delivers **semantic interoperability of policy**: a shared meaning for governance concepts across platforms, expressed in a portable representation and connected to platform-specific enforcement through adapters.

It is adjacent to, but does not deliver:

- **Operational interoperability** — policy behavior on data that physically moves between platforms (Delta Sharing into Snowflake, federated queries, Iceberg tables read by both). The representation provides the foundation; end-to-end behavior depends on platform-specific mechanisms evolving on their own timelines. We reserve space for this and follow developments closely.
- **Runtime interoperability** — a query-time gateway imposing a single authorization decision across platforms. This is a different product category with different trade-offs, and the project does not pursue it.

Being explicit about these boundaries is part of the value. We are scoping to the problem we can solve well.

## How this relates to Databricks strategy

Honestly: this is a skunkworks initiative. It is motivated by customers we work with who have the multi-platform governance problem today and have no answer to it. It is not an official Databricks product, it is not positioned as a standards play, and it does not propose that Databricks cede any ground on Unity Catalog being the source of truth for Databricks governance.

What it does propose is that we provide tooling — open or shared with customers who need it — that lets those customers express policy intent portably and translate it into Unity Catalog with full fidelity. If the project is useful, customers benefit and Databricks looks like the vendor that helped them. If it stalls, no official commitment has been made.

The strategic posture is principled cooperation: we build this because customers need it, we build it in a way that does not privilege Databricks at the representational layer (privileging the platform there would defeat the point of the project), and the Unity Catalog adapter is the most thoroughly developed adapter because that is the platform we know best. We do not coordinate with Snowflake on this; we do not exclude them either. Their adapter is built against the public surface of their platform, as any partner integration would be.

## Why this is achievable

The pattern is proven in adjacent domains. Healthcare standards bodies have done exactly this for clinical logic: a shared representation, grounded in a standardized vocabulary, translated to multiple execution environments. The technical building blocks for governance — policy vocabularies, ontology standards, modern authorization languages — exist and can be reused rather than reinvented. The scope is deliberately narrow: data-platform governance, not universal authorization.

## What we are asking for

This brief is to inform leadership of the work and to align on three questions:

1. **Strategic posture toward the work.** Permission to continue as a skunkworks effort, with the understanding that the project is customer-facing and does not represent an official Databricks position. Clarity on whether the work can be shared with specific customers, open-sourced under an individual or team affiliation, or must remain internal.
2. **Standards posture.** Whether the eventual artifact is shared as open documentation, contributed to a neutral body, or kept as customer-engagement tooling. The default is the third; the first two require explicit conversation.
3. **Relationship to Unity Catalog.** Confirmation that the framing — Unity Catalog as the source of truth inside Databricks, the portable representation as the lingua franca between estates — is acceptable as the public stance of the work.

## What success looks like

- Joint Databricks–Snowflake customers expressing governance policy once, in the portable representation, with Unity Catalog and Snowflake each enforcing equivalent translations — and with the trade-offs of each translation explicit and reviewable.
- Customers treating the portable artifact as the authoritative statement of cross-platform policy, while continuing to treat Unity Catalog as authoritative inside their Databricks estate.
- At least one real customer's custom enforcement pattern supported through the adapter model, demonstrating that the framework extends beyond the two big platforms.
- Cross-platform consistency demonstrated by diff, not by expert assertion — usable as the basis for audit, migration, and steady-state operation.

## Next step

A focused conversation on the three questions above, to confirm the work can proceed as scoped. With those settled, the technical specification and the first customer engagement can proceed against a clear set of constraints.
