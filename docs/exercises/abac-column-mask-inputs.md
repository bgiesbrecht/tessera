# Phase 1 Inputs — ABAC Column-Masking Exercise

**For:** Claude Code.
**Companion documents:** `docs/worked-example-exercise.md`, `CLAUDE.md`, `DECISIONS.md`, `docs/v1-candidates/abac-and-attribute-axes.md` (the scoping document), and the prior worked examples.
**Status:** Phase 1 inputs for the ABAC scoping document's Stage 3 worked exercise. Brice's setup work in Databricks is the prerequisite (see §9).
**Effective spec version:** v0, post-ADR-022. ADRs 018–021 are filed but their spec changes (ontology, context, schema, technical-design §3–§4) **have not landed yet**. This exercise is the validation gate before those spec changes land.

---

## 0. Framing

**0.1 — Demo or production scope?**

Demo. Same `acme` environment as the prior three exercises.

**0.2 — Target platform**

Databricks Unity Catalog. This exercise specifically targets the **newer ABAC mechanism** (`CREATE POLICY ... ON CATALOG ... COLUMN MASK ... MATCH COLUMNS has_tag_value(...)`), not the per-column `SET MASK` form the prior column-mask exercise used. The verified syntax from §6 of the scoping document is the reference.

**0.3 — Scope of this exercise**

A **two-policy** ABAC column-masking exercise designed to surface the cross-policy combination question that ADR-019 deliberately deferred (the α/β/γ resolution paths in scoping doc §8 Q3).

Two policies attach at the same catalog scope (`acme`). They overlap on the `o_clerk` column intentionally. They specify different transformations. The question Stage 3 answers: what does Databricks ABAC actually do when both policies match? The answer discriminates between three resolution paths:

- **α** — Tessera ignores cross-policy combination; adapters defer to platform conventions.
- **β** — Tessera adopts a single algorithm (e.g., deny-overrides).
- **γ** — Tessera declares it adapter-configurable per capability profile.

---

## 1. The protected resource

**1.1 — Protected column**

`acme.tpch.orders_abac.o_clerk` (STRING). Same column as the prior column-mask exercise — re-tagged for ABAC.

**1.2 — Tag to apply**

A Databricks tag with key `abac_column` and value `clerk` is applied to the column. The mechanism (governed tag vs. ordinary column tag) is Brice's choice in §9 setup — both work with `has_tag_value`. The exercise prefers governed tags for the audit/integrity benefits, but ordinary tags suffice for the demo.

**1.3 — Existing classifications**

None on the column (apart from the ABAC tag added above). The prior column-mask exercise's `mask_order_clerk` UDF and the `tessera__column_mask_orders_clerk__mask` UDF both still exist in the workspace; neither uses ABAC and they should be detached before the ABAC policies attach, to avoid stacking masks unpredictably.

---

## 2. The attribute axis and tag taxonomy

**2.1 — Tessera axis**

`sensitivity` (existing hierarchical axis from ADR-018).

**2.2 — Tessera value**

`PIIClerk`. New value under the `sensitivity` axis, subsumed by `PII` per the hierarchy (`PIIClerk ⊂ PII ⊂ PersonalData`). Mirrors the existing `PIIEmail` naming convention.

For the worked example, `PIIClerk` is declared in the Tessera namespace (`tessera:PIIClerk`). In a production deployment, an adopter would declare it under their own namespace (e.g., `bg:PIIClerk`) per ADR-018's adopter-extensibility convention. The exercise uses the Tessera namespace for simplicity; the artifact's `provenance.notes` calls this out.

**2.3 — Taxonomy mapping (per ADR-021)**

```yaml
# Adapter configuration mapping (Databricks)
tagTaxonomy:
  - axis: sensitivity
    axisValue: PIIClerk
    tagKey: abac_column
    tagValue: clerk
  - axis: sensitivity
    axisValue: PII
    tagKey: abac_column
    tagValue: '*'   # any value on the abac_column key implies the broader PII parent
    # The wildcard above is illustrative — Databricks' has_tag_value does NOT support
    # wildcards (verified Stage 1). The actual emission for the broader match uses
    # has_tag('abac_column') (key-only predicate). See Policy B sketch in §6.
```

The mapping is bidirectional: emission lowers `sensitivity: PIIClerk` to `has_tag_value('abac_column', 'clerk')`; extraction lifts the tag back to the axis value.

---

## 3. The principal model

**3.1 — Privileged group**

`acme_all_priority_ops`. Members see the unredacted `o_clerk` value. Reused from the group row-visibility exercise so no new group is needed.

**3.2 — Default principals**

Every account user not in `acme_all_priority_ops` falls into the default branch of each policy and sees the policy's transformed value.

**3.3 — Group hierarchy**

`is_account_group_member` handles direct and indirect membership. Same caching behavior as the prior exercises (2–4 minute propagation lag).

---

## 4. The two policies

### 4.1 Policy A — specific PIIClerk redact

```yaml
"@type": Policy
"@id": policy:abac-column-mask-clerk-redact
policyKind: ColumnVisibilityConstraint
appliesTo:
  selector: byScope
  scope: catalog:acme
  matching:
    attributes:
      sensitivity: PIIClerk
action: Read
defaultStrategy: negated-complement
rules:
  - principal:
      selector: byIdentity
      resource: group:acme_all_priority_ops
    effect: allow
defaultBranch:
  effect: transform
  transformation:
    type: Redact
    replacement: 'CLERK-REDACTED'
```

Policy A matches the **specific** `sensitivity: PIIClerk` attribute. Members of `acme_all_priority_ops` pass through; everyone else sees `'CLERK-REDACTED'`.

### 4.2 Policy B — same matcher, hash transformation

```yaml
"@type": Policy
"@id": policy:abac-column-mask-clerk-hash
policyKind: ColumnVisibilityConstraint
appliesTo:
  selector: byScope
  scope: catalog:acme
  matching:
    attributes:
      sensitivity: PIIClerk
action: Read
defaultStrategy: negated-complement
rules:
  - principal:
      selector: byIdentity
      resource: group:acme_all_priority_ops
    effect: allow
defaultBranch:
  effect: transform
  transformation:
    type: Hash
    algorithm: sha256
```

Policy B matches the **same** `sensitivity: PIIClerk` attribute as Policy A. The two policies target an identical set of columns. Members of `acme_all_priority_ops` pass through; everyone else sees a SHA-256 hash.

### 4.3 The deliberate overlap

For a principal **not** in `acme_all_priority_ops`, both policies match `o_clerk` and want to apply different transformations:

- Policy A: replace with literal `'CLERK-REDACTED'`.
- Policy B: replace with `sha256(o_clerk)`.

The matching predicate is identical between the two policies — the conflict is **pure-overlap, different effect**, the cleanest possible shape for surfacing cross-policy combination. What Databricks ABAC actually does when both policies are attached and both apply to the same column is what Stage 3 observes. The observation discriminates among ADR-019's three resolution paths:

- If Databricks picks one deterministically (some priority rule), we have evidence for α (defer to platform) or β (Tessera adopts the same rule).
- If Databricks blends or chains them, we have a different observation that may require a different design.
- If Databricks rejects the configuration (refuses to attach both policies), we learn a constraint on what Tessera can express.

An earlier draft of this exercise had Policy B match the broader hierarchical parent (`sensitivity: PII`) to also exercise the hierarchical-subsumption emission question. That mixed two findings into one exercise — the cross-policy combination question and the hierarchical-emission question. The simpler shape above isolates the cross-policy question; hierarchical-emission becomes a follow-on exercise if needed.

---

## 5. Edge cases

**5.1 — Brice in `acme_all_priority_ops`**

Pass-through for both policies. `o_clerk` shows real clerk values regardless of which policy is "in effect."

**5.2 — Brice not in `acme_all_priority_ops`**

The cross-policy combination case. Observe and record what Databricks emits.

**5.3 — Mid-session group changes**

Subject to the same 2–4 minute account-group cache lag observed in the prior exercises. Not a new finding for this exercise; recorded once in the diagnostic.

**5.4 — Column tagged with the specific tag value**

`o_clerk` is tagged `abac_column=clerk`, which (in the Tessera vocabulary, after taxonomy mapping) corresponds to `sensitivity: PIIClerk`. Both policies match this column.

**5.5 — Columns not tagged**

Other columns in `acme.tpch.orders_abac` (`o_orderkey`, `o_orderstatus`, etc.) are not tagged with `abac_column = clerk`; neither policy matches them; they remain visible. Note: `o_orderpriority` is separately tagged `abac_column = orderpriority` for a hypothetical row-filter follow-on exercise; neither column-mask policy in this exercise matches it.

---

## 6. Non-functional requirements

Not applicable for the demo. Standard ABAC policy evaluation overhead per query.

---

## 7. What success looks like

**7.1 — Behavioral verification criteria**

Two scenarios against `acme.tpch.orders_abac.o_clerk`:

| Scenario | Setup | Expected `o_clerk` |
|---|---|---|
| 1 | Brice in `acme_all_priority_ops`, both ABAC policies attached | Real clerk values (both policies' allow branch wins for him) |
| 2 | Brice not in `acme_all_priority_ops`, both ABAC policies attached | **Observation, not prediction.** What Databricks returns answers the cross-policy combination question. |

Scenario 2 is the substantive observation. There is no a-priori expected value; the result discriminates between α/β/γ.

**7.2 — Acceptable divergences**

Tessera-derived emission may differ from any future canonical emission in function names, header comments, and SQL formatting. The structural shape (policy at catalog scope, MATCH COLUMNS predicate, COLUMN MASK with EXCEPT) must match the verified Databricks ABAC syntax.

**7.3 — Disqualifying divergences**

The Tessera derivation must:

- Use the verified ABAC DDL form (`CREATE POLICY ... ON CATALOG ... COLUMN MASK fn TO ... EXCEPT ... FOR TABLES MATCH COLUMNS ... AS alias ON COLUMN alias`).
- Reference `acme_all_priority_ops` verbatim.
- Map `sensitivity: PIIClerk` to `has_tag_value('abac_column', 'clerk')` for **both** Policy A and Policy B (same matching predicate; the policies differ only in their transformation).
- Both policies must attach at catalog scope `acme`.

---

## 8. Anticipated findings

The exercise is structurally designed to surface findings, not to validate a hypothesis. Anticipated:

**8.1 — Cross-policy combination (ADR-019's α/β/γ).** This is the load-bearing observation. Scenario 7.1.2 reveals what Databricks does; the result drives a follow-on ADR (number TBD) that picks among α/β/γ.

**8.2 — Hierarchical-axis match in adapter configuration (deferred to follow-on exercise).** A policy matching a hierarchical *parent* (e.g., `sensitivity: PII`) should emit a predicate that matches all subclasses (`PIIEmail`, `PIIClerk`, etc.). On Databricks this likely translates to `has_tag('abac_column')` rather than per-value predicates, and the tag-taxonomy mapping (ADR-021) needs to either (a) enumerate the subclasses or (b) describe subsumption explicitly. This exercise originally included Policy B matching `sensitivity: PII` to surface this finding, but the design was simplified to isolate the cross-policy combination question. The hierarchical-subsumption finding remains a tracked follow-on; it will be exercised by an exercise that uses two different specific values (e.g., one policy matching `PIIClerk`, another matching `PIIEmail`, with a third policy matching the parent `PII` — observing how all three compose).

**8.3 — Adapter capability profile for ABAC support.** The Databricks adapter (when built) declares which ABAC concepts it supports. This exercise informs that capability profile.

**8.4 — Possible new finding from Scenario 7.1.2.** The exercise may surface something I haven't anticipated. That's its purpose.

---

## 9. Setup steps Brice executed before Phase 2 starts

**Status: completed 2026-05-19 on workspace `adb-984752964297111.11.azuredatabricks.net`** (Azure Databricks, different from the AWS `e2-demo-field-eng` workspace the prior exercises used). State at handoff:

- Catalog `acme` and schema `tpch` exist.
- Dedicated table `acme.tpch.orders_abac` created (TPC-H orders shape, 4.5M rows, managed Delta) — separate from `orders` to keep the ABAC exercise isolated from the prior column-mask exercise's table.
- Column `o_clerk` tagged `abac_column = clerk`. Column `o_orderpriority` separately tagged `abac_column = orderpriority` (reserved for a row-filter follow-on exercise; not used here).
- Two prior ABAC policies (`orders_clerk_mask`, `orders_priority_rls`) that Brice had set up earlier were dropped at the start of this Phase 2 work to give the derivation a clean state to attach into. **Brice has not shared the policy DDL or the function bodies for the existing impl** — this preserves the blind-derivation property of the exercise framework. Phase 3 comparison happens after Phase 2 artifacts are committed.
- Brice's group membership in `acme_all_priority_ops` is **not** currently asserted (live `is_account_group_member` check returns false). Scenario 1 verification (pass-through) requires re-adding membership and waiting out the standard 2–4 minute cache propagation lag.

The original setup steps are preserved below as historical record of what the brief asked for:

1. Create the `abac_column` tag (governed tag preferred; account admin).
2. Apply to column: `ALTER TABLE acme.tpch.orders_abac ALTER COLUMN o_clerk SET TAGS ('abac_column' = 'clerk');`
3. (Not applicable in practice — `orders_abac` is a fresh table; no prior masks to detach.)
4. Re-add `brice.giesbrecht@databricks.com` to `acme_all_priority_ops` for Scenario 1 testing (still pending; not blocking Phase 2 authoring).
5. Verify with `SELECT * FROM acme.information_schema.column_tags WHERE table_name = 'orders_abac'` and `SELECT is_account_group_member('acme_all_priority_ops')`.

---

## 10. Phase 2 deliverables

After §9 setup completes, Phase 2 produces (all under `spec/v0/examples/`):

- `abac-column-mask-policy-a.tessera.yaml` / `.jsonld` — Policy A (specific PIIClerk redact).
- `abac-column-mask-policy-b.tessera.yaml` / `.jsonld` — Policy B (broader PII hash).
- `abac-column-mask.databricks.sql` — Both policies' DDL emission (CREATE POLICY ... ON CATALOG form per verified Stage 1 syntax).
- `abac-column-mask.diagnostic.md` — Per-element enforcement; v0 IR gaps; the cross-policy combination question framed and observed.
- `abac-column-mask.comparison.md` — Phase 3 comparison against the deployed-DDL behavior (no prior implementation to compare against, since the existing notebook does not use ABAC; the comparison is between the Tessera-emitted DDL and the runtime behavior).

Because the spec changes for ADRs 018–021 haven't landed yet, the Phase 2 artifacts will use the vocabulary as if those changes were in place (i.e., the canonical post-ABAC shape). The Phase 2 artifacts thus serve double duty: they validate the design and they prefigure the eventual Stage 4 ontology/context/schema changes.

If Phase 2 surfaces problems with the design that the scoping document missed, the scoping document is revised before ADRs 018–021's spec changes land. This is the exercise's most important property.

**Note on blind-derivation.** Unlike the prior column-mask exercise (`column-mask-orders-clerk-*`, which collapsed to single-pass / combined-input because Brice shared the existing SQL up front), this ABAC exercise preserves the canonical three-phase structure. Brice has set up the existing implementation but has explicitly not shared its details; Claude Code derives Phase 2 strictly from this inputs document. The existing implementation's DDL is shared only after Phase 2 artifacts are committed, enabling a true Phase 3 comparison. A planned row-filter follow-on exercise will use the same framing.
