# Design sketch — `tessera:Policy` container

**Status:** Decision-grade sketch. Not yet an ADR. Resolves enough structural questions to make the backport-vs-hold call (§5); finer design work proceeds after that decision.

**Scope:** This sketch covers issues [#1 policy-container](https://github.com/bgiesbrecht/tessera/issues/1), [#2 default-branch-predicate](https://github.com/bgiesbrecht/tessera/issues/2), and partly [#3 principal-in-group-condition](https://github.com/bgiesbrecht/tessera/issues/3) — the three v1 candidates surfaced by the first worked example. The combining-algebra question from ADR-007 is also resolved here as a side effect.

**Reading order:** §1 → §5 in order. §5 is the load-bearing decision.

---

## 1. The proposed `tessera:Policy` shape

### 1.1 Recommended shape (Option B — container of constraints)

```yaml
"@context": https://bgiesbrecht.github.io/tessera/spec/v1/context.jsonld   # or v0 if backported
"@type": Policy
"@id": policy:group-row-visibility-policy-a
version: 1.0.0
description: >
  Three-branch row visibility on acme.tpch.orders, default grounded
  in explicit membership in `account users`.
kind: RowVisibility

appliesTo:
  selector: byIdentity
  resource: table:acme.tpch.orders

defaultStrategy: explicit-baseline-group
baselineGroup: "account users"

rules:
  # Rule 1 — most permissive
  - principal: { selector: byIdentity, resource: group:acme_all_priority_ops }
    effect: keep-matching-rows
    # No condition: rule matches every row for principals in this group.

  # Rule 2 — restrictive
  - principal: { selector: byIdentity, resource: group:acme_high_priority_ops }
    effect: keep-matching-rows
    condition:
      op: in
      operands: [column:acme.tpch.orders.o_orderpriority]
      values: ["1-URGENT", "2-HIGH"]

  # Rule 3 — baseline (the rule keyed off baselineGroup; framework recognizes
  # this as the default branch under explicit-baseline-group)
  - principal: { selector: byIdentity, resource: group:account-users }
    effect: keep-matching-rows
    condition:
      op: in
      operands: [column:acme.tpch.orders.o_orderpriority]
      values: ["3-MEDIUM", "4-NOT SPECIFIED", "5-LOW"]

provenance:
  notes: …
```

**Key changes from v0:**

- New top-level class `tessera:Policy`. Acts as a container holding `rules` plus policy-wide metadata.
- `kind` discriminator selects the policy domain (RowVisibility, AccessControl, ColumnVisibility, Distribution). Each kind constrains the legal rule sub-shape — e.g., RowVisibility rules cannot carry transformations; ColumnVisibility rules must.
- `appliesTo` moves from per-constraint to Policy-level. All rules share the same resource scope. (Single-resource-per-Policy is the v1 invariant; cross-resource policies are out of scope here.)
- `defaultStrategy` and `baselineGroup` move from per-constraint to Policy-level. Duplication across `@graph` members disappears.
- `defaultBranch` is a new Policy-level field; see §3.
- `rules` is an **ordered array**; ordering matters for combining (see §2).
- Each rule is a slimmer object: `principal`, optional `condition`, `effect`, plus kind-appropriate fields (`transformation` for ColumnVisibility). No `@type` per rule needed — the kind discriminator on Policy determines it.

### 1.2 Alternative considered (Option A — Policy as new sibling, existing constraints retired)

The alternative would deprecate `RowVisibilityConstraint`, `AccessConstraint`, etc. as top-level classes and replace them with `tessera:Policy` + `kind` discriminator. Each "rule" sub-object would become the primary structural unit; the existing constraint classes would survive only as discriminator values for `kind`.

**Why I prefer Option B:**

- **Backward compatibility.** A v0 single-constraint policy artifact remains a valid Tessera document. Migration is opt-in (rewrite as Policy when multi-branch is needed). Option A requires rewriting every existing artifact.
- **Lower disruption.** The existing constraint classes carry semantics adapters already know how to translate. Option B reuses them; Option A retires them and re-introduces them under a different structural role.
- **The shape difference is small.** Under Option B, single-rule policies can be written either as a standalone constraint (the v0 shape) or as a Policy with a one-element `rules` array (the v1 shape). Both are valid; the converter handles both. Multi-rule policies REQUIRE the Policy shape.

### 1.3 Sub-question: per-rule fields

Each rule in `rules` has:

- `principal` — required. Per-rule. Determines who the rule applies to.
- `condition` — optional. Per-rule. Predicates over the row (for RowVisibility) or other policy-domain attributes.
- `effect` — required. Per-rule. For RowVisibility kind, must be `keep-matching-rows` or `drop-matching-rows`. For other kinds, the legal effects vary.
- Kind-specific extras: `transformation` for ColumnVisibility; possibly `action` if per-rule actions are needed.

The `action` field is the open question here. Most worked examples have a single action per policy (`Read` for visibility policies). I'd put `action` at Policy level by default, with the option for v1.1 to push it to per-rule if multi-action policies prove needed. This keeps the rule object small.

### 1.4 Ontology and context impact

- New class `tessera:Policy` in the ontology, subclass of `tessera:Entity` (not `tessera:PolicyConstraint` — Policy contains constraints, doesn't refine the constraint concept).
- New property `tessera:rules` with domain `tessera:Policy` and range `rdf:List` of constraint references.
- New property `tessera:policyKind` with domain `tessera:Policy` and range the existing constraint class hierarchy.
- New property `tessera:defaultBranch` (see §3).
- Existing properties `tessera:defaultStrategy`, `tessera:baselineGroup`, `tessera:appliesTo` extend their domain to include `tessera:Policy`.
- Context: add short names for the new terms; preserve existing short names.

---

## 2. Combining algebra

### 2.1 Decision: ordered first-match

When multiple rules exist on a Policy, they are evaluated **in order**. The **first matching rule wins**: its `effect` and any row-predicate apply. Subsequent rules are not evaluated.

This is XACML's "first-applicable" combining algorithm.

### 2.2 Why first-match

- **Mirrors natural emission.** The CASE/WHEN/ELSE SQL shape that adapters already produce for row visibility is exactly first-match semantics.
- **Predictable.** The author knows what will happen by reading rules top to bottom.
- **Handles overlapping principals cleanly.** If a principal is in both `all_priority_ops` and `high_priority_ops`, the rule ordered first applies. The policy author makes the precedence explicit by ordering rules.
- **Composes with `defaultStrategy` cleanly.** For `explicit-baseline-group`, the baseline rule is last (catches everyone in the universal group after restrictive rules have been checked). For `negated-complement`, no explicit baseline rule; if no rule matches, `defaultBranch` applies. For `none`, no rule matches → fail-closed.

### 2.3 Alternatives considered

- **Union semantics** ("any matching rule's effect = keep is OR'd together"): defensible for additive permission models, but breaks down when rules have different row predicates. The first worked example would not work cleanly under union — a principal in `all_priority_ops` AND `high_priority_ops` would see the union of {all rows} and {1-URGENT, 2-HIGH rows} = all rows, which happens to be correct here, but the model doesn't generalize.
- **Priority field per rule** (XACML "deny-overrides" / "permit-overrides"): more flexible but adds a per-rule field. Not needed for the worked example; can be added in v1.x if a corpus exposes the need.
- **Declared combining algorithm per Policy**: most flexible. Punted to v1.x as an extension; v1 only supports first-match, with a `combiningAlgorithm` field potentially added later if needed.

### 2.4 Resolves ADR-007 open question

ADR-007 tracks "Obligation enforcement model" and adjacent open questions about combining. This sketch resolves the combining-algorithm question for Policies: **first-match, ordered**. A new ADR formally records this (whether ADR-014 if backported or a v1 ADR if held).

---

## 3. `defaultBranch` sketch

### 3.1 Purpose

When `defaultStrategy: negated-complement`, the IR has no place to carry the default-branch row predicate. v0 worked around this by expressing the default as a `byComposition` / `match: not` rule. `defaultBranch` is the explicit field.

### 3.2 Shape

```yaml
"@type": Policy
defaultStrategy: negated-complement
rules:
  - principal: { selector: byIdentity, resource: group:acme_all_priority_ops }
    effect: keep-matching-rows
  - principal: { selector: byIdentity, resource: group:acme_high_priority_ops }
    condition: { op: in, operands: [column:...], values: ["1-URGENT", "2-HIGH"] }
    effect: keep-matching-rows
defaultBranch:
  effect: keep-matching-rows
  condition:
    op: in
    operands: [column:...]
    values: ["3-MEDIUM", "4-NOT SPECIFIED", "5-LOW"]
```

A `defaultBranch` is a slimmer rule:
- No `principal` (it applies by being the default — i.e., to principals matching no other rule)
- `effect` required
- `condition` optional (no condition = keep all rows for default principals)

### 3.3 When `defaultBranch` is legal vs. illegal

| `defaultStrategy` | `defaultBranch` field |
|---|---|
| `explicit-baseline-group` | **Forbidden.** The baseline rule (one of the entries in `rules`, keyed off `baselineGroup`) serves the default role. Adding `defaultBranch` would be ambiguous. |
| `negated-complement` | **Required.** Without it, the policy has no place to declare what non-matchers see. |
| `none` | **Forbidden.** `none` means fail-closed; non-matchers see nothing. A `defaultBranch` contradicts that. |
| Omitted (= `none`) | **Forbidden.** Same as `none`. |

These constraints are enforceable via JSON Schema (`if/then/else` over `defaultStrategy`).

### 3.4 Eliminates the v0 workaround

The `byComposition` / `match: not` "default rule" used in `group-row-visibility-policy-b.tessera.yaml` becomes unnecessary. The default predicate moves to its proper home.

---

## 4. `principal-in-group` post-container

### 4.1 The container obviates the common case

Once policies have ordered rules with per-rule principal selectors, "principal in group X" is naturally expressed as a rule's principal:

```yaml
rules:
  - principal: { selector: byIdentity, resource: group:audit_reviewers }
    effect: keep-matching-rows
    condition: { op: time-window, values: [quarterly-review-window] }
```

This reads as: "for principals in `audit_reviewers`, during the quarterly review window, keep matching rows." The principal selector handles membership; the condition handles the time gate. No new condition operator needed.

### 4.2 The remaining case

There's still a case the container does not handle cleanly: **complex condition combinations where group membership appears inside a disjunction**.

Example: "Keep rows when (the principal is in `compliance_reviewers` AND consent is granted) OR (the principal is in `auditors` AND located in the EU)."

With first-match rules, this requires two rules. That's correct but it loses the OR's structural unity — a reader sees two rules and has to assemble the disjunction mentally.

If the disjunction is a common shape in real policies, the condition algebra needs `principal-in-group` (or `principal-in-set`) so that one rule can carry the full OR in its condition. If the disjunction is rare, two rules suffice.

### 4.3 Recommendation

**Defer `principal-in-group` until corpus exposure demonstrates the need.** The container resolves the urgent case; the conjunction-in-one-rule case is real but not yet exercised by any artifact in the project. Issue #3 stays open as a deferred v1 candidate, but is not a blocker for the v1 cut.

---

## 5. Backport to v0 (ADR-014) or hold for v1?

### 5.1 The question

The structural change in §1–§4 is significant: a new top-level class, new properties, restructured shape for multi-branch policies. Two paths:

- **Backport.** Treat this as a v0 correction (parallel to ADR-013's `defaultStrategy` addition). Publish v0 with the container present. No external consumer has built against v0 yet; the window for v0 corrections is still open per ADR-013's reasoning.
- **Hold.** Publish v0 as currently designed (multi-branch via `@graph` workaround). Cut v1 with the container when other v1 candidates accumulate. v0 artifacts remain valid for v0; v1 is a parallel-URL namespace.

### 5.2 Case for backport

- **The cost is bounded and known.** The work in §1–§4 is concrete enough to estimate: one ontology revision, one context revision, one JSON Schema revision, one technical-design update, two ADRs (ADR-014 plus the combining-algebra ADR from §2.4), and a revision of the worked-example artifacts to use the new shape. Probably 4–8 hours of focused work.
- **Avoids compounding cost.** Every tool built between now and a hypothetical v1 cut would encode the `@graph` workaround: the JSON Schema does already; the SHACL shapes would; the converter would; the Databricks adapter would. Each of those would need revision at v1. Backporting now caps that at zero.
- **The principle is right.** The container is the shape the framework actually wants. v0 with the workaround is a temporary embarrassment. Releasing v0 with a known structural defect because "we'll fix it in v1" is the kind of compromise the project's voice consistently rejects.
- **ADR-013 precedent.** ADR-013 backported a similar pre-publication correction (`defaultStrategy`/`baselineGroup`) for the same reasons. The precedent is the project's stated policy: pre-publication corrections allowed until external consumers exist.
- **External consumer status.** None today. The window remains open.

### 5.3 Case for hold

- **Two backports signal churn.** ADR-013 was one pre-publication correction; ADR-014 would be a second. A reader might reasonably wonder how many more are coming. "v0 is stable" becomes harder to claim.
- **v0 is supposed to stabilize.** The project's posture is "ship less and label it correctly." Holding the line on what v0 includes — even when later additions look attractive — is part of stabilization.
- **The workaround is documented.** The diagnostic explicitly surfaces the multi-branch gap. A future reader picking up v0 artifacts knows the workaround is a workaround, not a permanent design.
- **The work is real.** Even at 4–8 hours, it's work that delays other priorities (SHACL shapes, converter, first adapter scaffolding).

### 5.4 Recommendation: backport

Backport. ADR-014.

Three reasons that together tip the balance:

1. **The workaround is structural, not cosmetic.** Compare to other corrections that might come up — say, renaming a vocabulary term, or adjusting a label. Those would be cosmetic and could reasonably hold for v1. The container change reaches into how policies are written, validated, emitted, and reasoned about. It's the wrong shape for the framework to publish.

2. **The cost of holding compounds.** Every v0 artifact built on the workaround is rework at v1 cut. Backporting caps the cost; holding accumulates it. The math only gets worse from here.

3. **The "two backports" objection is weaker than it looks.** ADR-013 backported a property addition; ADR-014 would backport a structural correction. Both are pre-publication. Both are responses to what the first worked example surfaced. A future reader who sees both will likely see them as *the project taking its first worked example seriously* — which is the right read.

The case for hold isn't wrong, but it's a case for being conservative; backporting is the case for being honest. The project's voice consistently chooses honest over conservative.

### 5.5 If backport: what ADR-014 says

ADR-014 records:

1. The decision: introduce `tessera:Policy` container, ordered rules, first-match combining, `defaultBranch` field, in v0 before publication.
2. Why now: ADR-013 precedent, no external consumer, structural correction not cosmetic.
3. What changes: ontology, context, schema, technical design, worked-example artifacts.
4. Migration: v0 artifacts already in the repo (the worked example) get rewritten to the new shape. The `@graph` workaround is deprecated but remains parseable for a transition window — the converter understands both shapes during v0.
5. What this resolves: issues #1, #2, partly #3; ADR-007's combining-algebra question.

### 5.6 If hold: what the documented decision says

A short note appended to the technical design (or a new ADR-014-hold recording the decision) saying:

- v0 publishes with the `@graph` workaround as the known multi-branch shape.
- Issues #1, #2, #3 remain open as v1 candidates.
- The v1 cut will introduce the container with the design sketched here.
- Customers and adapters built against v0 should expect that multi-branch policies will require migration at v1.

This is honest; it just optimizes for stabilization over correctness.

---

## 6. Open sub-questions (for design work after the decision)

These are real questions but not blockers for the backport decision. Listed so they're not lost.

- **Single-rule policies under Option B.** When a multi-branch shape is unnecessary, can authors still write a bare `RowVisibilityConstraint` at top level? Recommendation: yes (backward compat). The converter and validators accept both. Tools normalize to Policy form for internal processing.
- **Migration tooling.** Should the v0 → v1 (or v0 pre-backport → v0 post-backport) migration be mechanical? The artifacts in `spec/v0/examples/` are small enough to migrate by hand; real customer corpora would benefit from a converter mode.
- **JSON-LD `@graph` deprecation.** Does the framework continue to accept `@graph` of constraints as a multi-branch shape? Recommendation: for a v0 transition window, yes (the converter normalizes to Policy form). For v1, no. Customers who write `@graph` shapes after v1 are writing v0-shaped policies and should opt into v0.
- **Capability profile entries for the new fields.** Adapters declare support for `defaultStrategy`, `defaultBranch`, `Policy` itself, etc. The capability-profile vocabulary needs new entries.

These are tracked in the ADR-014 implementation work if backport happens, or in v1 design work if hold.

---

## 7. What this sketch is and isn't

This is a **decision-grade sketch**. It is enough to:

- Answer the §5 backport-vs-hold question.
- Inform follow-on ADR drafting (ADR-014 in the backport path).
- Identify the work items required to implement either path.

It is **not**:

- A finished ontology revision. The actual Turtle text for `tessera:Policy`, `tessera:rules`, etc. is implementation work that follows the decision.
- A finished JSON Schema revision. Schema design follows.
- A finished SHACL shapes draft. Shapes design follows.
- A migration guide. Customer-facing migration notes follow.
- An adapter contract revision. Adapter-side capability profile changes follow.

If the decision is backport, these become the work plan. If hold, they become the v1 plan.
