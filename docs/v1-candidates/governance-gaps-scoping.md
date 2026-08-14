# Governance-gap scoping — audit logging (#19), retention (#21), AI governance (#25)

**Status:** Design document. Articulates the design surface for the three in-scope gaps the 2026-05-19 governance survey identified (`docs/handoffs/2026-05-19-governance-gaps-handoff.md`); **commits to no spec changes.** ADRs and spec implementation follow once the design settles, per the `abac-and-attribute-axes.md` precedent.
**Companion issues:** [#19](https://github.com/bgiesbrecht/tessera/issues/19) audit-logging obligation vocabulary, [#21](https://github.com/bgiesbrecht/tessera/issues/21) retention/deletion, [#25](https://github.com/bgiesbrecht/tessera/issues/25) AI-governance axes.
**Related ADRs:** ADR-001 (no runtime engine — the boundary all three press against), ADR-005 (standards reuse), ADR-016 (transformation parameterization), ADR-018–021 (attribute axes / scoped attachment), ADR-027 (descriptive, not prescriptive).

---

## §1. The shared thread: these three test the enforcement edge

The existing policy kinds (row visibility, column masking, access grants) each compile to a *declarative platform primitive* — a row filter, a masking policy, a GRANT. That is what makes "Tessera compiles to platform-native enforcement" (ADR-001) true for them.

These three gaps are different, and honesty requires saying so up front: **current data platforms have thin, default-on, or entirely advisory native enforcement for all three.**

- **Audit logging** is largely *account-wide and default-on* — Databricks `system.access.audit`, Snowflake `ACCESS_HISTORY` already record access without a per-object policy. A per-policy "audit this" obligation is often an *assertion that the platform already satisfies*, not a switch Tessera flips.
- **Retention/deletion** has *no clean declarative primitive*. Snowflake `DATA_RETENTION_TIME_IN_DAYS` is Time-Travel retention (how far back you can query), **not** a "delete after N" policy; Databricks Delta `VACUUM` is history cleanup, not record expiry. Real retention/deletion is a *scheduled job* (`DELETE WHERE ts < …`), an operational artifact, not a policy object.
- **AI-use restrictions** (no-training, no-automated-decision) have *no platform enforcement at all* — no data-platform primitive stops a model from training on a tagged column. Enforcement lives in ML pipelines that choose to honor the classification.

So the value Tessera adds here is **portable expression of the requirement plus honest capability reporting**, more than one-to-one lowering to a native primitive. This is consistent with the project's posture (ADR-027: describe, don't invent) as long as the capability profiles state plainly, per platform, whether the obligation is *enforced*, *asserted-satisfied*, *emitted as an operational job*, or *advisory only*. The recurring design move for all three: model the *meaning* (what must be logged / retained / restricted), let the adapter map to whatever the platform offers, and never claim enforcement the platform does not provide.

None of the three requires Tessera to *run* anything (the ADR-001 line holds): it expresses obligations and constraints that compile to platform configuration, native primitives where they exist, or a described operational artifact where they don't.

---

## §2. Audit logging — refine the `AuditLog` obligation (#19) — _implemented (ADR-030, 2026-08-14)_

**Shipped** in v0 per ADR-030: `auditFields` / `auditSink` / `auditRetention` on the `AuditLog` obligation, with worked example `spec/v0/examples/audit-obligation-sensitive-read.*`. Expression-first (no adapter emission yet — see the honest-limitation note below, which the ADR carries forward). The design below stands as the record.

**Today (pre-ADR-030).** `tessera:AuditLog` is a bare `Obligation` subclass: "record the access event to a named audit destination." No structure — it can't say *what* to record or *to what category of sink*.

**The refinement.** Give the audit obligation a small, semantic parameter set — the *content and character* of the required record, not a log format:

- `auditFields` — which semantic fields must be captured: `principal`, `resource`, `action`, `timestamp`, `purpose`, `outcome`. (Meaning, not column names.)
- `auditSink` — a *category* of destination (`platform-native`, `external-siem`, `immutable-store`), bound to a concrete target by adapter configuration (ADR-021 pattern), never a platform table name in the policy file.
- `auditRetention` — optionally, how long the audit record itself must persist (which is really a retention constraint on the log; see §3 — worth cross-referencing, not duplicating).

**Meaning-vs-mechanism.** Tessera says "this access must be recorded capturing principal/resource/purpose/outcome, to an immutable sink." The adapter maps that to the platform's audit facility (enable `ACCESS_HISTORY`, route `system.access.audit`, or emit a config assertion). Tessera does not model log rotation, SIEM wiring, or storage.

**The honest limitation, foregrounded.** On platforms that audit account-wide by default, an audit obligation is frequently *"the platform already does this"* — the adapter's emission is an assertion/diagnostic that the required fields are covered, not a new mechanism. That is still valuable: it makes the requirement explicit and portable, and it lets a capability profile confirm coverage or flag a gap (e.g., a platform that doesn't capture `purpose`). But the capability profile must say `asserted-satisfied` rather than `enforced` where that is the truth.

**Shape.** This is the architecturally simplest of the three — an obligation-vocabulary refinement within the existing `Obligation` hierarchy, no new policy kind. **One ADR.**

---

## §3. Retention & deletion — a `RetentionConstraint` policy kind (#21)

_Implemented (ADR-031, 2026-08-14): `RetentionConstraint`, expression-first — option 2/3 hybrid (first-class policy kind carrying the full intent, but not emitted; the emittable delete-after job is a deferred, opt-in increment). Worked example `spec/v0/examples/retention-delete-after-policy.*`. §6.1 resolved. The analysis below stands as the record._

The survey flagged this as the most urgent (GDPR Art. 5(1)(e), CCPA, HIPAA all cite it) — and it is also the one with the most design tension. Two decisions are genuinely the author's to make (§6).

**The two-directional core.** Retention pulls two opposite ways, and the IR must distinguish them because they are different obligations:

- **Delete-after (minimization).** "Personal data must be deleted N days after collection." The driver is privacy minimization; the failure mode is keeping data too long.
- **Retain-for (preservation).** "Financial records must be kept at least 7 years." The driver is legal preservation; the failure mode is deleting too soon.

A single "retention period" field cannot capture both — the same number means opposite obligations. The IR needs `retentionDirection` (`delete-after` | `retain-for`), a `retentionPeriod` (ISO-8601 duration), a `retentionBasis` (the event the clock starts from — a timestamp column or a lifecycle event), and a terminal `action` (`delete` | `anonymize` | `archive`).

**The scope-and-mechanism tension (flag for the author).** Neither Databricks nor Snowflake has a declarative "delete records older than N" policy object. Enforcement is an operational job. So a `RetentionConstraint` would lower to:

- Snowflake: at best `DATA_RETENTION_TIME_IN_DAYS` — but that's Time-Travel, a *different* concept; it does **not** implement delete-after. So mostly: an emitted scheduled `DELETE`/`TRUNCATE` task, or a described job.
- Databricks: a scheduled job / DLT expectation / `DELETE` + `VACUUM`; no native declarative retention policy.

This is the crux: retention is **data-lifecycle governance, not access-decision governance**, and its enforcement is operational rather than a declarative platform policy. That presses harder on ADR-001 and on Tessera's scope than anything to date — Tessera would be emitting (or describing) an operational job, not attaching a policy. Three framings are possible, and this is a posture call:

1. **Full policy kind**, adapters emit scheduled-task DDL where the platform allows and a described-job artifact otherwise (capability profile honest about "operational-job, not enforced-policy").
2. **Narrower**: model only *delete-after with a basis column*, the one shape that maps to an emittable scheduled `DELETE`; defer archive/anonymize.
3. **Reframe as an obligation** rather than a policy kind — a retention *obligation* attached to a resource, emitted as a documented requirement, explicitly not something Tessera enforces.

**Shape.** A new `PolicyConstraint` subclass (`RetentionConstraint`) plus the direction/basis/action vocabulary — **one or two ADRs**, gated on the §6 scope decision. Given the operational-enforcement reality, option 2 (narrow, emittable) is the lowest-risk first cut; option 3 is the most posture-conservative.

---

## §4. AI governance — new attribute axes (#25) — _implemented (ADR-029, 2026-08-13)_

This is the cleanest fit: it extends the ADR-018 attribute-axis framework, no new policy kind. **Shipped** in v0 per ADR-029: axes `trainingEligibility` and `automatedDecision` in `ontology.ttl` / `context.jsonld` / `shapes.ttl`, worked example `spec/v0/examples/ai-governance-training-mask-policy.*` (validates and emits masking DDL on both adapters, keyed off the axis). The design below stands as the record.

**The axes.** AI-use restrictions are *properties of the data* (the §1 three-category test in `abac-and-attribute-axes.md`: data attribute vs request condition vs principal property → these are data attributes), so they are attribute axes:

- `trainingEligibility` — e.g. `NoTraining`, `TrainingWithConsent`, `TrainingAllowed`. "May this data be used to train models?"
- `automatedDecision` — e.g. `NoAutomatedDecision`, `ADMWithHumanReview`. "May this data drive automated decisions?" (GDPR Art. 22.)

Both are flat axes in the ADR-018 sense (independent enumeration members; no natural subsumption hierarchy), declared like `dataSubject`/`regulatoryRegime`. Adopters extend with their own values under their namespace (per ADR-028: bare = Tessera, prefix = adopter).

**The honest limitation, foregrounded.** No data-platform primitive enforces "no training." A governed tag records the classification; a *data platform* cannot stop a downstream ML job from reading and training on it. So the capability profile is `advisory` here: the axes make the restriction explicit, portable, and *composable with access controls* — the real enforcement leverage is indirect. For example, `trainingEligibility: NoTraining` composes with the existing masking/access machinery: "mask columns tagged NoTraining to the ML-service principal" is an enforceable ColumnVisibility policy that *uses* the axis. That composition — an AI-governance axis driving an ordinary access policy — is where these axes get teeth on today's platforms, and is worth a worked example.

**Shape.** Additive axes in `ontology.ttl` / `context.jsonld` / `schema.json` following the ADR-018 pattern (and the ADR-028 `@vocab` mechanics, so bare values resolve). **One ADR.**

---

## §5. Sequencing and ADR map

Priority follows the survey's regulatory-urgency hint, adjusted for design risk:

| Gap | Kind of change | Design risk | ADR(s) | Suggested order |
|---|---|---|---|---|
| **#25 AI axes** | additive attribute axes (ADR-018 pattern) | low | 1 | first — lowest risk, exercises the composition-with-access story |
| **#19 audit** | obligation-vocabulary refinement | low–moderate (honest "asserted-satisfied" framing) | 1 | second |
| **#21 retention** | new policy kind + operational-enforcement question | high (scope/posture) | 1–2, gated on §6 | third — needs the scope decision first |

Doing #25 first is deliberate: it validates the "express-then-compose" pattern that #19 and #21 also lean on, and it is the least likely to require a posture conversation.

---

## §6. Open questions for the author

1. **Is retention (#21) in scope as a policy *kind*, and if so which framing?** The survey said in-scope, but retention is data-lifecycle, not access, and its enforcement is operational (a scheduled job), which presses on ADR-001 harder than anything so far. Choose: (1) full policy kind with job emission, (2) narrow delete-after-with-basis-column only, or (3) reframe as a non-enforced obligation. My lean: (2) as the first cut — it is the one shape that maps to an emittable primitive and keeps the enforcement claim honest.
2. **Audit `auditRetention` — model here or via the retention vocabulary?** Retention of the *audit log* is itself a retention constraint. Cross-reference #21 rather than duplicate; decide once #21's shape settles.
3. **Do the AI axes need enforcement beyond classification, or is compose-with-access enough for v0?** My lean: classification + the composition example is the right v0 scope; the axes are honestly advisory on their own, and the enforcement leverage is via the access machinery that already exists.
4. **Capability-profile vocabulary for thin enforcement.** All three need capability levels beyond SUPPORTED/PARTIAL/UNSUPPORTED to be honest — e.g. `asserted-satisfied`, `operational-job`, `advisory`. Worth a small capability-vocabulary addition (its own ADR) so the profiles don't overclaim.
