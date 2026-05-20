# Handoff — Table-Level Grants Exercise

**For:** Claude Code
**Status:** Phase 1 inputs. Drafted by claude.ai (design partner), reviewed against the current spec by Claude Code, decisions on open questions recorded in §"Resolutions before Phase 2" below.
**Effective spec version:** v0, post-ADR-019 (canonical `byScope` attachment) and post-ADR-024 (adapter contract).

---

## Why this exercise

Six completed exercises so far have exercised row-visibility (group, ACL, ABAC, Snowflake-byDataset) and column masking. ABAC support landed in ADRs 018–021. What hasn't been exercised: **basic table-level grants** — the bread-and-butter "users in group X can read tables in schema Y" pattern that predates ABAC and is what most customers reach for first.

The exercise validates that Tessera expresses three progressively richer grant patterns cleanly. It also addresses open issue #10 (policy-execute-grants), which was surfaced during the row-visibility exercises but never directly exercised.

The framework's value proposition is **load-bearing on the simple cases as much as the complex ones**, because Tessera's primary driving activity is migration. If a customer is moving hundreds of grants between platforms, "use native DDL for the simple ones" defeats the framework — the operator has to translate manually and maintain two sources of truth. The IR must express the full corpus, simple and complex, or it cannot serve the migration use case.

This framing was sharpened in conversation 2026-05-19; the exercise's value is now understood as validating a load-bearing capability, not just demonstrating expressiveness on a simple case.

---

## Three scenarios, increasing in scope

### Scenario A: Single table read grant (simplest case)

**Business intent.** "The marketing analytics team needs to query our customer orders table for reporting. They should be able to read it but not modify it."

**Testable particulars.**
- Resource: `acme.tpch.orders`
- Principal: `acme_marketing_analytics` (account-level group; substituted as convenient for testing)
- Action: `Read`
- Effect: `allow`
- Default for non-members: not specified; the grant is purely affirmative. Principals not in the group fall through to whatever other policies or defaults apply.

**What this tests in the IR.**
- `byIdentity` resource selector pointing at a specific table.
- `byIdentity` principal selector pointing at a specific group.
- `action: Read` (the standard read action).
- `effect: allow` — the simplest effect, and the one that distinguishes affirmative grants from restriction policies.
- A single-rule Policy container with no `defaultStrategy` (because there's no default behavior to specify; the policy is purely affirmative).
- **The policyKind question:** is `RowVisibilityConstraint` the right shape for an affirmative grant, or does the IR need an `AccessGrantConstraint` distinct from restriction-shaped policies? Phase 2 should derive Scenario A both ways and let the diagnostic compare.

### Scenario B: Schema-level read grant with downward propagation

**Business intent.** "The data engineering team needs read access to every table in our staging schema, including tables that will be added later. We don't want to enumerate tables or update the grant every time a new table appears."

**Testable particulars.**
- Resource scope: schema `acme.tpch_staging` (substituted as convenient).
- Principal: `acme_data_engineering`
- Action: `Read`
- Effect: `allow`
- Downward propagation: the grant applies to all current and future tables in the schema. The Tessera framing of this is via `byScope` at schema level.

**What this tests in the IR.**
- `byScope` selector at schema level (ADR-019).
- The implicit-downward-inheritance semantics from ADR-019.
- `byScope` without an attached `matching` block — the "match every resource in scope" case. Verified at the JSON Schema layer (the `oneOf` branch for `byScope` requires `scope` but not `matching`); Phase 2 should confirm SHACL accepts it and document the semantics explicitly.

### Scenario C: Function execute grant

**Business intent.** "We've defined a function that computes customer lifetime value. Analysts in the marketing analytics team should be able to call this function in their queries; nobody else should be able to invoke it."

**Testable particulars.**
- Resource: a function `acme.tpch.compute_customer_ltv` (defined as a no-op in setup).
- Principal: `acme_marketing_analytics`
- Action: `Execute`
- Effect: `allow`

**What this tests in the IR.**
- Whether `Execute` is a valid action in the v0 vocabulary. **Verified prior to Phase 2: it was not in v0; it has been added** with semantic-only scope (see resolutions below). The exercise grounds the addition; the ADR documenting it lands alongside the diagnostic.
- Whether the resource selector cleanly handles functions as resources. The `function:` prefix is a new informal IRI convention; Phase 2 should adopt it and surface in the diagnostic.
- Open issue #10's "policy-execute-grants" finding — this scenario is the worked exercise that grounds it.

---

## Resolutions before Phase 2

The annotation legend in claude.ai's draft is resolved as follows:

- **Group names.** Use `acme_marketing_analytics` and `acme_data_engineering` for testing. Names don't matter for documentation; if testing prefers different names (existing groups), substitute freely. Document choices in the setup script.
- **Schema for Scenario B.** Use `acme.tpch_staging` (new; created in setup).
- **Function for Scenario C.** No-op SQL UDF: `RETURN 0` against an integer argument. Real computation isn't needed for behavioral verification.

Two design questions, resolved:

- **Execute action — add to v0 first, let exercise discover, or what?** Added prior to Phase 2 across `ontology.ttl`, `context.jsonld`, `schema.json`, `shapes.ttl`. Semantic-only scope (gating who can invoke business-logic resources); platform-mechanism uses of EXECUTE (UDFs as policy-enforcement vehicles, EXECUTE grants required to attach a UDF to a Tessera-emitted column-mask policy) remain **adapter scaffolding, not IR-modeled**. This boundary is the load-bearing finding the exercise records — Glean's enumeration of EXECUTE uses on Unity Catalog made the boundary visible.

- **`policyKind` for affirmative grants.** Open. Phase 2 should derive both forms (squeeze under `RowVisibilityConstraint` with `effect: allow`, and sketch what an `AccessGrantConstraint` would look like). Diagnostic compares; design decision deferred to a follow-up ADR after the comparison lands.

---

## What Phase 2 should produce

Per `docs/worked-example-exercise.md`, the standard artifact set, plus the new extraction-shape sketch:

- `spec/v0/examples/table-grants-scenario-a.tessera.yaml` + `.jsonld`
- `spec/v0/examples/table-grants-scenario-b.tessera.yaml` + `.jsonld`
- `spec/v0/examples/table-grants-scenario-c.tessera.yaml` + `.jsonld`
- `spec/v0/examples/table-grants.databricks.sql` (a single SQL file showing the Databricks emission for all three scenarios)
- `spec/v0/examples/table-grants.diagnostic.md` (per-element enforcement report covering all three scenarios; the `RowVisibilityConstraint` vs `AccessGrantConstraint` comparison; the `function:` IRI prefix finding; the extraction-shape sketch)

Plus, adjacent:

- `adapters/tests/setup_table_grants.py` — idempotent setup of groups, schema, function (run before Phase 3).
- An ADR documenting the `Execute` action addition with the semantic-vs-mechanism boundary.

## What Phase 3 should produce

After the Phase 2 artifacts are committed:

- `spec/v0/examples/table-grants.findings.md` — there is no existing implementation to compare against, so this is `findings.md` rather than `comparison.md`. Validates:
  - **Behavioral correctness.** Brice runs the emitted SQL in the workspace, exercises each grant scenario, confirms expected behavior.
  - **Framework fit.** Does the IR express each scenario cleanly? Does the `RowVisibilityConstraint` shoehorn feel awkward?
  - **Coverage of the underlying issue.** Specifically, does Scenario C resolve or sharpen open issue #10?
  - **Migration-shape validation.** A `SHOW GRANTS ON TABLE` row from the workspace, manually lowered to the IR shapes Phase 2 produced. This is the smallest possible extraction sketch; it validates that the IR shapes can carry what a migration would extract.

---

## Test scenarios for Phase 3 verification

For Scenario A (single table grant):

1. Brice in `acme_marketing_analytics`, queries `SELECT * FROM acme.tpch.orders` — should succeed.
2. Brice not in that group, queries the same — should fail (assuming no other policy grants access).
3. Brice in the group attempts `UPDATE acme.tpch.orders SET ... WHERE ...` — should fail (only Read is granted).

For Scenario B (schema-level grant with propagation):

1. Brice in `acme_data_engineering`, queries any existing table in `acme.tpch_staging` — should succeed.
2. Brice not in that group, queries the same — should fail.
3. **The propagation test.** Create a new table in the schema after the policy is applied. Brice in the group queries it — should succeed without any additional grant.

For Scenario C (function execute):

1. Brice in `acme_marketing_analytics`, calls `SELECT acme.tpch.compute_customer_ltv(123)` — should succeed.
2. Brice not in that group, calls the same — should fail.
3. Brice in the group attempts to redefine or drop the function — should fail (only Execute is granted).

---

## Workspace setup (handled in `adapters/tests/setup_table_grants.py`)

The setup script will idempotently:

- Create the groups at the account level (if Brice authorizes account-level group changes; otherwise the script provisions them as workspace-level).
- Create the schema `acme.tpch_staging` with at least one initial table.
- Create the function `acme.tpch.compute_customer_ltv` as a no-op SQL UDF.
- Print group memberships needed for the three scenarios; Brice toggles membership manually (the cached membership propagation lag of 2–4 minutes documented in technical-design §5.2 applies).

These prerequisites are not blockers for Phase 2 (Claude Code derives the Tessera artifacts without them existing).

---

## What this exercise does not cover

For deliberate scope-limiting:

- **No row-level or column-level constraints.** Exercised in prior rounds.
- **No multi-action grants in a single policy.** Scenario A grants only Read; B only Read; C only Execute. The question of whether the IR cleanly expresses `GRANT SELECT, USAGE ON SCHEMA foo TO group_x` is real but deferred. Phase 2 may surface it naturally if the policy container forces awkwardness; record as a finding.
- **No revocation semantics.** Tessera expresses what policies say, not the act of revoking.
- **No GRANT WITH GRANT OPTION semantics.** Delegating grant capability is a meta-policy concern that v0 does not address.
- **Full extraction implementation.** Phase 2 sketches what extraction would lower to (one `SHOW GRANTS` row as an example) but does not implement adapter discovery/extraction methods.

---

## Note on what this exercise might surface

Predictions worth recording before Phase 2 runs:

- **Scenario A** likely works cleanly under `RowVisibilityConstraint + effect: allow`. The IR has shaped equivalents.
- **Scenario B** likely works at the schema layer; the SHACL behavior for `byScope` without `matching` is the genuine open question.
- **Scenario C** definitely needs the `Execute` action (now added). The `function:` IRI prefix is a new informal convention worth surfacing.
- **The `policyKind` question** is likely to surface real awkwardness with `RowVisibilityConstraint`. The shape doesn't naturally communicate "this is an affirmative grant," and a future `AccessGrantConstraint` is a likely v0 addition.
- **The extraction sketch** is likely to surface that Tessera-IR is well-suited to lift `SHOW GRANTS` rows mechanically, validating the migration use case.

If predictions hold, exercise is meaningful validation. If they don't, the surprises are themselves the finding.
