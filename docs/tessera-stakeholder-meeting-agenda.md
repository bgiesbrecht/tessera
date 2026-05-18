# Federated Governance Policy — Stakeholder Decision Meeting

**Meeting purpose:** Resolve the six open decisions in the Problem Statement & Recommendation document so that technical specification work can proceed against a fixed set of constraints.

**Meeting type:** Decision meeting, not discussion meeting. Each item below has a named decision, a recommended position, and an owner. Items either resolve in the meeting or are explicitly deferred with a named follow-up.

**Duration:** 90 minutes.
**Format:** In person preferred; hybrid acceptable. Camera on for remote attendees.

---

## Pre-read

Attendees must have read, before the meeting:

1. **Executive Summary** (one page) — `tessera-executive-summary.md`
2. **Problem Statement & Solution Recommendation** (full) — `tessera-problem-and-recommendation.md`

Specifically, attendees should arrive having formed an opinion on §2.7 of the full document. The meeting assumes the framing in §1 and §2 is broadly agreed; if an attendee disagrees with the framing itself, they should flag that to the chair at least 24 hours before the meeting so it can be addressed first.

---

## Attendees and roles

| Role | Responsibility in meeting |
|---|---|
| **Chair** | Keeps to time, calls each decision, names follow-ups |
| **Decision owner (per item)** | Has authority to commit on that decision, or to defer with a named timeline |
| **Scribe** | Records decisions, deferrals, owners, and dates in the decision log |
| **Technical lead** | Answers feasibility questions; does not advocate for a position |
| **Stakeholder representatives** | Governance, security, compliance, platform engineering, architecture |

The Chair and Technical Lead should not be the same person. The Chair's job is process; the Technical Lead's job is content.

---

## Ground rules

- Each agenda item has a recommended position. If the recommendation is accepted, the item resolves quickly. If not, discussion is bounded by the time box.
- "Decide now with reservations" is preferred to "defer." Reservations are recorded; the decision still holds.
- Any attendee may invoke a deferral, but must name the specific thing that would need to be true for the decision to resolve, and a date by which that thing will be known.
- Technical implementation questions are out of scope. The Technical Lead may answer factual feasibility questions but the meeting does not design solutions.

---

## Agenda

### Opening — 5 minutes

Chair frames the meeting: this is a decision meeting on six items; the framing of the problem is assumed agreed; the goal is to leave with as many of the six resolved as possible.

Any objections to the framing itself are taken first or deferred to a separate session.

---

### Item 1 — Scope of policy types — 10 minutes

**Decision owner:** Governance lead

**Question:** Does the initial scope cover access policies only (allow/deny, row filters, column masks, sharing), or does it extend to retention, lifecycle, quality, or data-contract policies?

**Recommended position:** Access policies only for the first iteration, with reserved structural space in the representation for the others. Reasons: each non-access category is its own problem domain; conflating them slows all of them down; access policy alone is enough to deliver the migration and reconciliation value.

**Decision needed:** Confirm access-only scope, or specify which additional categories must be in scope and accept the corresponding extension to timeline.

**Failure mode if not decided:** Scope creep during specification. Engineers will guess and the guesses will conflict.

---

### Item 2 — Operating model — 20 minutes

**Decision owner:** Platform leadership (jointly with Governance)

**Question:** Is the portable representation the source of truth (policies authored centrally, pushed to platforms), the reconciliation layer (platforms remain authoritative, representation is extracted), or a hybrid?

**Recommended position:** Defer the final choice but commit to *supporting both* in the design. The representation must be authorable as a primary artifact and producible from extraction. Organizations adopting the system choose their operating model; the system does not impose one. The technical implication is that round-tripping is a first-class requirement, which it already is.

**Decision needed:** Confirm "support both, organization chooses" as the design constraint, or commit to a single model and document the reasoning.

**Why this is the longest item:** This decision has the largest downstream consequences for governance processes, tooling deployment, and ownership boundaries — but is also the one most prone to being decided implicitly rather than deliberately. Worth the 20 minutes.

**Failure mode if not decided:** Each implementation choice gets re-litigated through this lens. Adapter design, deployment topology, and change-management workflow all depend on it.

---

### Item 3 — Primary authoring audience — 10 minutes

**Decision owner:** Governance lead

**Question:** Who is the primary author of policies in the new system — data engineers, governance professionals, or business stakeholders?

**Recommended position:** Data engineers as primary authors; governance professionals as primary reviewers; business stakeholders as the source of intent that engineers encode. The authoring surface is designed for engineers (familiar with code and version control); review tooling is designed for governance and audit (familiar with policy semantics but not necessarily code).

**Decision needed:** Confirm the primary/reviewer/source split, or specify a different model.

**Failure mode if not decided:** The authoring surface is designed for the wrong audience and is either too technical for governance or too informal for engineering rigor.

---

### Item 4 — Standards posture — 10 minutes

**Decision owner:** Architecture leadership

**Question:** Is this project an internal capability, an open specification we publish, or a candidate for standards-body adoption (CNCF, W3C, or a Data Mesh-aligned body)?

**Recommended position:** Open specification from day one; standards-body submission deferred until the specification has been validated against multiple real organizations. Reasons: open specification creates the credibility needed for adoption by customers and partners; standards-body work is premature without that validation; internal-only is a strictly worse position than open, given the network effects of a portable representation.

**Decision needed:** Confirm "open specification, defer standards body," or commit to internal-only with rationale, or commit to immediate standards-body engagement with named target.

**Failure mode if not decided:** Governance and IP choices made implicitly through engineering decisions (license headers, repository location, contribution model) rather than deliberately.

---

### Item 5 — Custom-pattern strategy — 10 minutes

**Decision owner:** Engineering leadership (jointly with Customer Engineering)

**Question:** When a customer or business unit has a custom enforcement pattern (such as ACL-table-and-view), does the project team build the adapter, or is adapter authorship a customer responsibility supported by a documented contract?

**Recommended position:** Project builds the first two or three custom-pattern adapters as paid engagements, then publishes the adapter contract and supports community/customer authorship for subsequent patterns. Reasons: the first few adapters teach the project what the contract needs to be; opening contribution before the contract is stable produces churn; doing all of them indefinitely does not scale.

**Decision needed:** Confirm "build first, open later," or commit to "open from day one" or "always build."

**Failure mode if not decided:** Customer engagements proceed without a clear engagement model, and the adapter contract is shaped by accident rather than design.

---

### Item 6 — Source-of-truth ownership — 15 minutes

**Decision owner:** Platform leadership (jointly with Data Mesh / Governance leads)

**Question:** Who within an adopting organization owns the portable representation and its evolution — a central platform team, the governance organization, or a federated model with one owner per data product?

**Recommended position:** This is the question the project cannot answer for adopters; it is an organizational design decision specific to each adopter. The project's responsibility is to ensure the representation and tooling support all three ownership models without preferring one. For the project's *own* governance, federated ownership of the specification (with a central editor function) mirrors the Data Mesh philosophy the work is grounded in.

**Decision needed:** Confirm "project supports all three ownership models, organizations choose their own," and separately decide the project's own internal governance model.

**Why this is grouped with Item 2:** Items 2 and 6 are the two questions most likely to be conflated and most important not to conflate. Item 2 is about *where the policy lives*; Item 6 is about *who owns it*. They interact but they are not the same question.

**Failure mode if not decided:** The project either prescribes an ownership model (which adopters resist) or stays silent (which leaves adopters without guidance and produces inconsistent rollouts).

---

### Closing — 10 minutes

**Decision log review.** Scribe reads back each decision, deferral, owner, and date. Attendees confirm or correct in real time. The recorded decisions are the meeting's output; anything not recorded did not happen.

**Follow-ups named.** For each deferred item: what would need to be true for the decision to resolve, by when, by whom.

**Next milestone.** Confirm the date by which the revised technical design will be circulated, given the decisions made today.

---

## Decision log template

| # | Decision item | Outcome (decided / deferred) | Position | Owner | Reservations / follow-up | Date resolved or due |
|---|---|---|---|---|---|---|
| 1 | Scope of policy types | | | | | |
| 2 | Operating model | | | | | |
| 3 | Primary authoring audience | | | | | |
| 4 | Standards posture | | | | | |
| 5 | Custom-pattern strategy | | | | | |
| 6 | Source-of-truth ownership | | | | | |

---

## Anti-patterns to watch for

The Chair should call out, in real time, the following meeting failure modes, which are common in decisions of this kind:

- **Solutioning the technical implementation.** "How would the adapter handle…" is out of scope. Refer to the Technical Lead for feasibility only.
- **Re-opening the framing.** If §1 of the full document is contested, that conversation belongs in a separate session. The meeting assumes framing is agreed.
- **Decision by exhaustion.** A decision reached because the time box expired and one position was the last spoken is not a decision. Use the "decide now with reservations" pattern instead.
- **Implicit deferral.** "Let's come back to this" without a named follow-up is a deferral pretending not to be one. Every deferral gets an owner and a date.
- **Conflating items 2 and 6.** Where policy lives is not the same question as who owns it.

---

## After the meeting

Within 48 hours, the scribe circulates the decision log to all attendees and one level above each decision owner. Decisions are considered final 5 business days after circulation unless an attendee escalates in writing.

The technical design draft proceeds against the decisions as recorded, not against the meeting discussion.
