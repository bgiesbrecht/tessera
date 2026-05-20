# Diagnostic Report — ABAC Column Mask (Policies A & B)

**Companion artifacts:**
- `abac-column-mask-policy-a.tessera.yaml` / `.jsonld` (Redact)
- `abac-column-mask-policy-b.tessera.yaml` / `.jsonld` (Hash)
- `abac-column-mask.databricks.sql`
- `abac-column-mask.comparison.md` (Phase 3 stub)

**Inputs:** `docs/exercises/abac-column-mask-inputs.md`
**Exercise framing:** `docs/worked-example-exercise.md` — canonical three-phase mode (blind derivation preserved; Brice has not shared the existing implementation).
**Spec version:** v0 with the ABAC additions (ADRs 018–021) **prefigured** but not yet implemented in the spec files. Stage 4 spec changes follow this exercise.
**Target platform:** Databricks Unity Catalog (ABAC mechanism per ADRs 018–019 and Stage 1 syntax verification).

This diagnostic is the honest accounting required by §2.4 of the exercise framing: which elements of each policy are fully enforced, which are partially enforced, which are unenforced — plus the v0 IR gaps the exercise surfaces and the per-mechanism timing disclosure.

---

## 1. Summary

The Tessera-derived policies express the ABAC column-mask intent using the post-ABAC vocabulary (`byScope` + `matching.attributes` + `defaultStrategy: negated-complement` + ColumnVis `defaultBranch` carrying the transformation). The SQL emission uses the verified Databricks ABAC DDL form: `CREATE POLICY ... ON CATALOG ... COLUMN MASK ... TO ... EXCEPT ... FOR TABLES MATCH COLUMNS has_tag_value(...) AS alias ON COLUMN alias`.

The exercise's substantive output is **not** yet observable — it requires deploying both policies and querying as a non-privileged principal to surface the cross-policy combination behavior (ADR-019's deferred α/β/γ decision). That observation lives in the Phase 3 comparison document. Phase 2 establishes that the design *can be expressed*; Phase 3 establishes what *happens* when both are deployed.

Three structural findings worth recording from the Phase 2 derivation itself, independent of any Phase 3 observation:

1. The current `spec/v0/schema.json` does not yet support `byScope` or the `matching` shape. The Phase 2 JSON-LD therefore does NOT validate against the current schema. This is expected — the schema update is part of Stage 4. (§4.1)
2. The `appliesTo.matching` block uses ADR-020's implicit-AND shortcut (`attributes: { sensitivity: PIIClerk }`); a single-attribute case desugars trivially to the canonical `match: and / criteria: [{attribute: ...}]` form. The shortcut is the intended ergonomic shape. (§4.2)
3. The `GRANT EXECUTE` emission pattern from the prior column-mask exercise carries forward here. The IR still does not formally declare grants (v1 candidate issue #10 `policy-execute-grants` remains the right place). The Tessera-derived SQL emits the grants defensively. (§4.3)

---

## 2. Per-element enforcement

| Policy element | Category | Notes |
|---|---|---|
| Scoped attachment (`byScope` at `catalog:acme`) | **Fully enforced** | `CREATE POLICY ... ON CATALOG acme` attaches at the catalog level; Databricks ABAC propagates to all descendants matching the predicate. |
| Attribute matching (`sensitivity: PIIClerk`) | **Fully enforced via taxonomy mapping** | Translates to `has_tag_value('abac_column', 'clerk')` per the configured tag-taxonomy mapping (ADR-021). The mapping is per-environment adapter configuration, not in the policy file. |
| Principal binding (`acme_all_priority_ops` privileged) | **Fully enforced** | `TO account users EXCEPT acme_all_priority_ops` in the DDL. Members of the privileged group bypass the mask; everyone else hits it. |
| `defaultStrategy: negated-complement` | **Fully enforced (structurally)** | The Databricks ABAC `TO account users EXCEPT group` form is structurally negated-complement: the policy applies to the universal set minus the exception. The Tessera `defaultStrategy` declaration matches the emission. |
| Policy A — Redact with literal 'CLERK-REDACTED' | **Fully enforced** | UDF returns the literal unconditionally; ABAC invokes it for non-privileged principals. |
| Policy B — Hash with sha256 | **Fully enforced** | UDF returns `sha2(val, 256)`; same evaluation path. |
| `effect: allow` on the privileged rule | **Fully enforced via EXCEPT clause** | Members of the privileged group are exempted from the policy via the EXCEPT clause; they see the original column value (Databricks bypasses the mask entirely for excepted principals). |
| `effect: transform` on the defaultBranch | **Fully enforced via the UDF + COLUMN MASK binding** | The UDF is the transformation; ABAC invokes it for every matched column for every non-exempted principal. |
| `capabilityRequirements` (scoped attachment / axis matching / taxonomy mapping) | **Declared, validated by adapter capability profile (when built)** | The Databricks adapter would declare support for all three. |
| Provenance metadata | **Partially enforced** | Tessera `provenance.notes` exists; Databricks DDL has a `COMMENT` clause that carries part of it (the policy ID). Full provenance lives in the YAML, not the platform. |

---

## 3. Per-mechanism timing disclosure (per technical-design §5.2)

Two timing characteristics are relevant to this ABAC mechanism:

1. **Account-group membership cache.** Same 2–4 minute propagation observed in the prior group-row-visibility exercise. Affects when changes to `acme_all_priority_ops` take effect on the ABAC policy's `EXCEPT` evaluation. Not new; recorded for completeness.

2. **Tag-binding cache (potentially new).** Databricks ABAC may cache the `has_tag_value` evaluations for some interval to avoid repeated metastore lookups. The propagation behavior of tag changes — adding a new column tag, removing one, retagging a column — is a separate timing characteristic. Phase 3 observation should measure this; if it differs from the account-group cache window, it is a per-mechanism timing finding that the Databricks adapter's capability profile should declare separately.

The framework's role (per ADR-016 § 5.2 of the technical design) is to require these disclosures; the adapter's role is to declare them concretely. This exercise contributes the first observation of the tag-binding cache characteristic, even if Phase 2 itself cannot measure it.

---

## 4. v0 / spec gaps surfaced by this exercise

### 4.1 Schema does not yet recognize `byScope` or `matching`

The current `spec/v0/schema.json` was updated post-ADR-014/016/022 but **not** post-ADRs 018–021 — those spec changes are gated on this exercise. The Phase 2 JSON-LD artifacts therefore reference `selector: byScope`, `appliesTo.matching`, `appliesTo.scope`, and `appliesTo.matching.attributes` — none of which the schema currently knows about. The validator will reject the documents.

This is **expected**. The exercise's role is to validate the design; if the design holds, Stage 4 lands the schema additions and the artifacts validate. The Phase 3 comparison document will record either (a) successful schema update + clean validation as a confirmation of the design, or (b) any design adjustments the exercise surfaces.

### 4.2 The `matching` block uses the implicit-AND shortcut (ADR-020)

Both policies use the single-attribute shorthand:

```yaml
matching:
  attributes:
    sensitivity: PIIClerk
```

ADR-020 specifies this desugars to the canonical:

```yaml
matching:
  match: and
  criteria:
    - attribute:
        axis: sensitivity
        value: PIIClerk
```

For a single attribute, the implicit-AND form is equivalent to a one-element `criteria` list. The exercise demonstrates that the shortcut is the intended authoring form for simple cases. The canonical form is used in artifacts when more than one attribute appears, or when explicit `match: or` / `match: not` is needed.

The schema (Stage 4) should accept both shapes and the converter should normalize to canonical for internal processing.

### 4.3 `GRANT EXECUTE` still implicit in the IR

The Tessera-derived SQL emits `GRANT EXECUTE ON FUNCTION ... TO account users` for both UDFs, but the IR has no place to declare this. The Phase 2 artifact does not record the grants; only the SQL emission does. This is the same finding from the prior column-mask exercise and from the row-visibility exercises; it remains tracked as v1-candidate issue #10 `policy-execute-grants`.

The exercise does not resolve this; it just reaffirms that the gap persists wherever transformations are involved.

### 4.4 Capability requirements: declared but not yet validated

The artifacts declare three capability requirements (`scoped-policy-attachment`, `attribute-axis-matching`, `tag-taxonomy-mapping`). These names are not yet vocabulary — they exist as machine-readable strings that the adapter capability profile will eventually match against. The Databricks adapter (when built) would declare which capabilities it supports.

Until the adapter exists, these are decorative. Stage 4 should formalize the capability vocabulary or accept that capability strings are adopter-defined per ADR-021's adapter-configuration framing.

---

## 5. The substantive observation Phase 3 produces

The Phase 3 comparison document is currently a stub. After deployment, it captures:

- What Databricks does for a principal **in** `acme_all_priority_ops` (predicted: pass-through, both policies have the same EXCEPT, so both bypass — the principal sees the real clerk value).
- What Databricks does for a principal **not** in `acme_all_priority_ops` — the substantive observation. Both Policy A and Policy B apply; both transformations are defined; what value does Databricks return?
  - **α candidate observation**: Databricks deterministically picks one (e.g., by policy creation order, alphabetical name, or some other rule). The principal sees either `'CLERK-REDACTED'` or `sha2(clerk_value, 256)` deterministically.
  - **β candidate observation**: Databricks blends the two somehow (unlikely but possible — e.g., applying both transformations in sequence). The principal sees `sha2('CLERK-REDACTED', 256)` or similar chained result.
  - **γ candidate observation**: Databricks refuses to attach both policies, or rejects the configuration at policy-evaluation time with an error. The composition is not supported.

Whichever result emerges, ADR-019's α/β/γ choice has empirical grounding. A follow-on ADR records the choice the platform observation justifies.

A secondary observation worth measuring: **policy attachment ordering**. Does it matter whether Policy A is created before Policy B, or vice versa? If yes, ADR-019 needs to address ordering semantics. Phase 3 should deploy in both orders to test.

---

## 6. Disqualifying-divergence checklist (per inputs §7.3)

| Requirement | Status |
|---|---|
| Use verified ABAC DDL form | ✓ — `CREATE POLICY … ON CATALOG … COLUMN MASK … TO … EXCEPT … FOR TABLES MATCH COLUMNS … AS … ON COLUMN …` matches the Stage 1 verification. |
| Reference `acme_all_priority_ops` verbatim | ✓ — in both policies' EXCEPT clauses. |
| Map `sensitivity: PIIClerk` to `has_tag_value('abac_column', 'clerk')` | ✓ — for both policies. |
| Attach both at catalog scope `acme` | ✓ — both `ON CATALOG acme`. |

---

## 7. Findings summary

| Finding | Category | Recommended action |
|---|---|---|
| Schema doesn't yet support `byScope` / `matching` (§4.1) | **Stage 4 spec update** | Update `schema.json` and `ontology.ttl`/`context.jsonld` per ADRs 018–021's Consequences sections after Phase 3 validates the design. |
| Cross-policy combination behavior (§5) | **Phase 3 observation pending** | Deploy both policies; query as non-privileged user; record the result. |
| Tag-binding cache timing (§3) | **Phase 3 observation pending** | Modify a tag during the verification run; observe propagation lag. |
| GRANT EXECUTE not in IR (§4.3) | **Existing v1 candidate** | Tracked as issue #10; this exercise reinforces. |
| Implicit-AND shortcut working (§4.2) | **Design validation** | Confirms ADR-020's syntactic-sugar design. Schema must accept both shapes. |

The exercise is structurally complete pending the Phase 3 deployment + observation.
