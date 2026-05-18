# Federated Governance Policy — Problem Statement & Solution Recommendation

**Status:** Draft for stakeholder review
**Audience:** Data platform leadership, governance and security stakeholders, architecture review
**Purpose:** Establish a shared understanding of the problem and an agreed direction before any technical specification or implementation work begins.

---

## Part 1 — Problem Statement

### 1.1 Context

Modern data platforms — Snowflake, Databricks, and others — each provide rich, native mechanisms for enforcing data governance: row-level security, column masking, access grants, tag-based policies, and cross-account sharing. These mechanisms are deeply integrated with each platform's query engine, identity model, and catalog. Individually, they are fit for purpose.

The difficulty arises when an organization operates across more than one platform. The *business rules* an organization needs to enforce — who can see what data, under what circumstances, for what purpose, with what obligations — are platform-independent. The *mechanisms* available to enforce them are not. Two platforms with the same governance intent will encode it in different SQL, different catalog objects, different identity primitives, and different runtime behaviors.

A further complication: many organizations have, over time, built their own enforcement patterns that predate or sit alongside native platform mechanisms. ACL tables joined into views, middleware that injects predicates, BI-tool row contexts, application-layer interceptors. These patterns are no less real as policy than native constructs — and in many enterprises, they hold the majority of the actual access logic.

### 1.2 The problem in plain terms

Organizations that operate across multiple data platforms, or that wish to migrate between them, currently have no portable way to express, review, transport, or reconcile their data governance policies. Each policy must be authored, maintained, and audited separately in each platform's native form, and the *intent* behind those policies — the business rule the policy was meant to enforce — is lost in the translation to platform-specific code.

### 1.3 Concrete harms this produces

- **Migration cost.** Moving a workload from Snowflake to Databricks, or the reverse, requires manually rewriting every access policy, row filter, and masking rule. The work is tedious, error-prone, and the resulting policies must be re-audited from scratch.
- **Drift between platforms.** When the same business rule exists in two places, the implementations diverge over time. Reconciling them — proving they enforce the same thing — is a manual, expert-led exercise.
- **Loss of intent.** Native policy code captures *what* is enforced but not *why*. A masking rule attached to a column has no machine-readable record that it exists because the column is PII, that the exception for fraud investigators reflects a specific business purpose, or that the rule originated from a particular regulation. Reviewers and auditors must reconstruct intent from code, comments, and institutional memory.
- **Inability to reason across platforms.** Questions like "show me every place where PII is accessible without a logged audit obligation" cannot be answered uniformly. Each platform must be queried separately, in its own terms, by someone fluent in that platform.
- **Custom enforcement patterns are invisible.** Where governance is enforced via homegrown patterns — ACL tables, view layers, middleware — there is no shared vocabulary in which those patterns and native platform policies can be compared.
- **Reluctance to migrate or modernize.** The cumulative effect of the above is that organizations defer platform changes, defer adoption of better native governance features, and defer harmonization of policy across the enterprise — not because the changes are technically infeasible but because the policy-translation cost is unbounded.

### 1.4 Who is affected

- **Data platform engineers** who must implement and maintain policies in each platform.
- **Data governance and security teams** who must verify that policies meet stated intent, and that intent is consistent across platforms.
- **Compliance and audit functions** that must produce evidence of effective controls and explain *why* controls exist.
- **Business stakeholders** whose intent is encoded — and frequently lost — somewhere between their original requirement and the platform DDL that implements it.
- **Architecture and platform-strategy leadership** for whom platform choice is currently constrained by migration cost rather than fit.

### 1.5 Why existing approaches do not solve this

Several adjacent solutions exist, each addressing a slice of the problem but not the whole:

- **Catalog and lineage tools** describe data but generally do not encode enforceable policy. They surface what exists, not what is permitted.
- **Cross-platform policy engines** (typically runtime gateways) impose policy from outside the platform, which introduces a new chokepoint, conflicts with platform-native performance, and is often politically difficult to adopt.
- **Manual translation playbooks** exist within consultancies and internal teams, but are knowledge in heads rather than tooling, do not scale, and produce no durable artifact that can be reviewed or re-applied.
- **Existing policy languages** (XACML, ODRL, Rego, Cedar) solve parts of the abstract problem but are not connected to the specific concerns of data-platform governance: classification-driven policies, masking and row-filtering as first-class concepts, integration with platform tag systems, and round-tripping with native DDL.

The gap is specifically: a *portable, intent-preserving representation of data-platform governance policies*, with tooling that can both extract from and emit to the platforms (native and custom) where those policies actually run.

### 1.6 Goals

The effort succeeds if it produces all of the following:

1. **A portable representation of data governance policies** that captures intent — including classification, purpose, principal, conditions, transformations, and obligations — independent of any specific platform's mechanisms.
2. **A vocabulary of governance concepts** grounded in established standards where possible, such that the same concept (PII, purpose, jurisdiction, masking) means the same thing across platforms and across organizations.
3. **The ability to extract existing policy from a platform into the portable representation**, including from custom enforcement patterns, with explicit confidence indicators where extraction involves inference.
4. **The ability to emit policy from the portable representation into a target platform's native or custom mechanisms**, with a clear and honest report of which parts are fully enforced, partially enforced, or unsupported on that target.
5. **A human-reviewable artifact** for each policy, suitable for version control, pull-request review, and audit.
6. **An extensibility model** that allows organizations to integrate their own enforcement patterns without forking the specification.

### 1.7 Non-goals

To keep scope honest, the following are explicitly out of scope for the initial effort:

- **A runtime policy enforcement engine.** The project compiles to native enforcement; it does not run as a query-time gateway.
- **Data quality, lineage, retention, or contract policies.** These are adjacent and important, but each is its own problem and conflating them slows all of them down. Reserved for future extension.
- **Identity federation.** The project assumes some form of identity reference exists and provides a binding mechanism; it does not solve the cross-platform identity problem itself.
- **Encryption, key management, differential privacy, anonymization techniques.** Adjacent; assumed to be provided by other systems.
- **Universal coverage on day one.** The initial scope is Snowflake and Databricks, with the explicit expectation that other platforms and custom patterns will follow through the same extension model.

### 1.8 Success criteria

The effort is successful when:

- An organization can extract its existing governance policies from Snowflake (whether native or custom-pattern) and from Databricks into the portable representation, with each extracted policy clearly labeled by extraction confidence.
- The portable representation can be reviewed by governance stakeholders as a primary artifact, not as a secondary translation of "the real policy."
- The same portable representation can be emitted to a different target platform such that the resulting native enforcement is behaviorally equivalent within a documented and accepted set of trade-offs.
- The custom enforcement pattern of at least one real customer is supported through the extension mechanism, without requiring changes to the core specification.
- Stakeholders — engineers, security, compliance, leadership — agree the artifact captures their intent and can be used as the basis for cross-platform governance discussions.

### 1.9 Constraints and principles

The work is bound by the following:

- **Intent over mechanism.** The representation captures what a policy is meant to achieve, not the specific code that achieves it on any one platform.
- **Honesty over completeness.** Where translation is lossy, the loss must be visible and explicit, not silently papered over.
- **Extensibility from the start.** No assumption that the initial set of platforms or patterns is the final set. The extension surface is a first-class part of the design.
- **Reuse over invention.** Where established standards (ontologies, policy vocabularies, identity conventions) cover part of the problem, the project adopts them rather than inventing parallels.
- **Reviewability.** Every artifact the project produces is designed to be read, diffed, and discussed by humans who are not the original author.

---

## Part 2 — Solution Recommendation

### 2.1 Recommended approach

The recommended approach is to define a **portable, intent-preserving representation of data governance policies**, supported by an **extensible adapter model** that connects the portable representation to the specific platforms and patterns where policies are actually enforced. The core of the project is the representation and its surrounding vocabulary; the adapters are the means by which the representation meets the real world.

This is a single direction with two complementary halves: the *what* (the portable representation and its vocabulary) and the *how* (the adapters that move policy between the representation and real systems).

### 2.2 Core elements of the approach

#### A vocabulary of governance concepts

A shared definition of the entities involved in data governance — principals, resources, classifications, purposes, jurisdictions, conditions, obligations, transformations, and the kinds of policy that connect them. This vocabulary is the agreement that makes everything else possible: it is what allows "PII" or "purpose of access" to mean the same thing in two different platforms and two different organizations. Where existing standards cover parts of this vocabulary, they are adopted directly.

#### A portable representation of policies

A canonical form in which a policy can be expressed, reviewed, stored, and exchanged independently of any specific platform. This form is the durable artifact of the project. It is what gets checked into version control, reviewed in pull requests, presented to auditors, and used as input to migration and reconciliation tasks. It is designed to be machine-processable but also human-readable enough that a governance stakeholder can read a policy and understand what it does.

#### Adapters as the bridge to real systems

Each platform or enforcement pattern is connected to the portable representation through an adapter. An adapter has two responsibilities: **extraction** — reading what exists in a platform and lifting it into the portable representation — and **emission** — taking a policy from the portable representation and producing the native artifacts that enforce it.

Adapters are first-class. The project ships with adapters for Snowflake-native and Databricks-native enforcement at minimum. Custom enforcement patterns — such as the ACL-table-and-view pattern used by some customers — are supported through additional adapters, authored against a stable adapter contract. An organization that has a custom pattern can connect it to the portable representation by writing an adapter for it; the rest of the system works unchanged.

#### A capability and confidence model

Different adapters have different capabilities. A given target platform may support some governance concepts natively, approximate others, and not support others at all. The project does not pretend otherwise. Each adapter declares what it can and cannot enforce, and emission produces an explicit report of which parts of each policy are fully enforced, partially enforced, or unsupported on the target.

Similarly, extraction is not always certain. Inferring intent from native DDL or from a custom pattern often requires reasoning about names, comments, and structure. Extraction produces policies labeled with a confidence indicator so that reviewers know where to focus their attention.

#### A human-friendly authoring surface

In addition to the portable representation, the project provides a human-oriented way to author and review policies. This authoring surface is designed for the people who actually write and maintain governance rules — data engineers, security professionals, governance leads — and is deliberately separate from the machine-readable representation that the adapters consume. The authoring surface is a projection of the representation, not a replacement for it.

### 2.3 How this addresses the stated problem

| Stated harm | How the approach addresses it |
|---|---|
| Migration cost | Extraction lifts existing policies into a portable form; emission re-projects them onto the target platform, with explicit reporting of gaps. The work that remains is reviewing and resolving the gaps, not hand-translating the whole. |
| Drift between platforms | The portable representation becomes the single source of truth (or the reconciliation target, depending on the organization's operating model), and divergence between platforms becomes visible and diffable rather than implicit. |
| Loss of intent | Concepts like classification, purpose, jurisdiction, and obligation are first-class in the representation, not buried in DDL. Intent is captured because the vocabulary makes it expressible. |
| Inability to reason across platforms | A policy in the portable form is the same policy regardless of where it is enforced. Cross-platform queries, audits, and reviews operate on the representation, not on each platform's native catalog. |
| Custom enforcement patterns are invisible | The adapter model treats custom patterns as peers of native platform mechanisms. Once an adapter exists, policies enforced by a custom pattern are as visible and portable as any other. |
| Reluctance to migrate or modernize | The cost calculus changes. Migration becomes a review-and-emit exercise with known trade-offs, not an open-ended translation project. |

### 2.4 What this approach explicitly avoids

- **It is not a runtime policy enforcement engine.** It compiles to and from the platforms that already do enforcement well; it does not insert itself into the query path.
- **It is not a universal policy language.** It is scoped to data-platform governance and is intentionally narrower than general-purpose authorization languages. Narrowness is a feature.
- **It does not require organizations to abandon their existing enforcement patterns.** Adapters allow current patterns to continue running while becoming visible and portable.
- **It does not claim lossless translation between platforms.** Where loss occurs, it is named and reported; equivalence is a property to be demonstrated, not assumed.
- **It does not depend on a single vendor or platform.** The vocabulary and representation are platform-neutral by design; adapters are the only platform-specific surface.

### 2.5 Operating models the approach supports

The approach is compatible with more than one way of working, and the choice is left to the adopting organization:

- **Portable representation as source of truth.** Policies are authored in the portable form, checked into version control, and pushed to platforms through emission. The platforms are downstream of the representation.
- **Platforms as source of truth, representation as reconciliation layer.** Policies continue to be maintained in platform-native form; the representation is produced by extraction and used for review, comparison, and reporting.
- **Hybrid.** Some policies are authored centrally and pushed; others remain platform-native and are extracted on a schedule. The representation reflects the union.

The choice of operating model is a stakeholder decision and should be made deliberately. It affects governance processes, tooling deployment, and ownership boundaries more than it affects the technical design.

### 2.6 What it will take to demonstrate the approach

A credible demonstration of the recommended approach involves the following, in roughly the following order:

1. **An agreed vocabulary** for the initial scope of governance concepts.
2. **A defined portable representation** that uses that vocabulary.
3. **One end-to-end adapter pair** — extraction and emission — for a chosen first platform.
4. **A second adapter pair** for a different platform, with a worked round-trip showing behavioral equivalence within stated trade-offs.
5. **A custom-pattern adapter** for at least one real-world non-native enforcement pattern, demonstrating that the extension model holds.
6. **A reviewable corpus** of real policies — extracted, represented, re-emitted, and reviewed by stakeholders — showing that the artifacts are useful, not just internally consistent.

Each of these steps produces an artifact that can be evaluated independently, so the approach can be validated incrementally rather than only at the end.

### 2.7 Open questions for stakeholders

These are decisions that should be made before, or early in, the work. They are not technical questions that the implementation will answer; they are choices that shape what the implementation is *for*.

1. **Scope of policy types.** Should the initial scope be access policies only, or include sharing, retention, and other adjacent kinds? The recommendation is access-only for the first iteration, with reserved space for the rest.
2. **Operating model.** Will the portable representation be treated as source of truth, as reconciliation layer, or as a hybrid? This choice shapes governance processes more than it shapes design.
3. **Primary authoring audience.** Who writes policies in the new system — data engineers, governance professionals, business stakeholders? Different audiences imply different authoring surfaces.
4. **Standards posture.** Is this an internal capability, an open specification, or eventually a candidate for standards-body adoption? The choice affects governance, IP, and how aggressively to align with existing standards bodies.
5. **Custom-pattern strategy.** When a customer or business unit has a custom enforcement pattern, does the project build the adapter, or is adapter authorship a customer responsibility supported by a documented contract? The recommendation is that the project builds the first few to learn what the contract needs to be, then opens it.
6. **Source-of-truth ownership.** Even within "portable representation as source of truth," who owns the representation — central platform team, governance organization, federated per data product? This is a Data Mesh question more than a technical one and should be settled before the tooling lands in production.

---

## Part 3 — What this document is not

This document deliberately does not contain:

- A specification of the vocabulary or representation in technical form.
- A definition of the adapter contract.
- A description of the authoring surface's syntax.
- An implementation plan, timeline, or resourcing proposal.

Those follow from agreement on this document. The intent here is to ground the work in a shared problem and a shared direction so that subsequent technical drafts can be evaluated against stated goals rather than against shifting assumptions.

---

*End of draft. Next step: stakeholder review and resolution of the open questions in §2.7, after which the technical specification can resume from the previous draft with the adapter model and custom-pattern support incorporated as first-class concerns.*
