# ABAC Support and Attribute Axes — Scoping Document

**Status:** Design document. Lands in v0 per ADR-017 (immutability bar suspended until external dependency).
**Companion ADRs:** ADR-013 (default-handling), ADR-014 (policy container), ADR-015 (ordered first-match), ADR-016 (transformation parameterization), ADR-017 (suspended immutability).
**Filed under `docs/v1-candidates/`** by historical convention from when v1-vs-v0 was still a live question; the directory name predates ADR-017 and is not updated immediately to avoid churn. Future scoping documents may live in a renamed directory.

---

## §1. The principle: meaning, not mechanism

Tessera expresses *what is being decided about the data*, not *how the platform records the attribute that drives the decision*.

A policy that says "redact columns containing PII unless the user is in the data stewards group" is the same policy whether the underlying platform identifies PII columns via:

- Governed tags (Databricks ABAC).
- Object tags (Snowflake).
- A separate classification metadata table (a custom enforcement pattern).
- Column naming conventions (a brittle but real legacy approach).
- Schema-level metadata in a JSON sidecar (an emerging pattern in some lakehouses).

The policy is *about PII*. The platform's mechanism for identifying PII columns is an implementation detail. Tessera models PII as a semantic attribute of the data; the adapter handles how that attribute is recognized on its target platform.

### Three categories of property

Working through the ABAC design surfaces a related distinction that the IR needs to keep clean. Policies reference three structurally different kinds of property:

- **Properties of the data.** Sensitivity, data subject, regulatory regime, business domain. These are facts *about the data* — they hold regardless of who is reading, why, or when. Tessera models these as **attribute axes** on resources (§2).
- **Properties of the access request.** Purpose of access, time of request, jurisdiction the request originates from. These are facts *about a specific invocation* — they vary per query. Tessera models these as **conditions** in the existing condition algebra (`purpose-in`, `located-in`, `time-window`).
- **Properties of the principal.** Group membership, identity, role assignments. Tessera models these via **principal selectors** (`byIdentity`, `byComposition`, etc.).

This distinction matters because it determines where new vocabulary lands when policy needs grow. Purpose is a property of an access request, not a property of the data — the same data can be accessed for different purposes by different requests. Forcing purpose into an attribute axis on data would conflate "what this data is" with "what this access is for." Conversely, sensitivity is a property of the data, not of the request — every access to a PII column is to PII regardless of who asks or why. Forcing sensitivity into the condition algebra would lose the static-property nature.

The existing `purpose-in` condition operator therefore stays as a condition, not promoted to an axis. The four ABAC additions in §2–§5 concern only properties of the first category.

### What this rules out

The framework does *not* introduce a `Tag` class into the IR. A `Tag` class would model the platform mechanism, not the meaning. We previously avoided this kind of leak in the timing-disclosure conversation (where "timing categories" were considered for IR-level enumeration and rejected because they were per-mechanism vocabulary); the same logic applies here.

The framework does *not* model coordination labels — `team: fraud-ops`, `cost-center: 12345`, `environment: production` — as data attributes. These are operational metadata about ownership and accounting. They may correspond to principal attributes (a user's team) or to scope attributes (a catalog's environment), but they are not properties of the data the policy protects. Policies that gate on team membership do so via principal selectors, not via data-attribute selectors.

### What this enables

If Tessera models meaning rather than mechanism:

- The same policy file is portable across Databricks (governed tags), Snowflake (object tags), and custom-pattern adapters (classification tables).
- The Databricks adapter's tag taxonomy is a *configuration* concern, not a policy concern.
- A policy author writing for Tessera does not need to know which platform will enforce the policy.
- Platforms that change their tag mechanisms (Databricks ABAC is recent; it may evolve) do not invalidate existing policies — only the adapter's emission needs to keep up.

---

## §2. AttributeAxis: orthogonal semantic dimensions

The existing `Classification` hierarchy handles the single-axis hierarchical case well. `PII ⊂ PersonalData ⊂ RegulatedData` is a clean hierarchy. A column either is or is not PII; if it is PII, it is a subtype of PersonalData; the hierarchy carries useful inference.

What the existing hierarchy does not handle is *orthogonal* dimensions. A column may simultaneously be:

- *Sensitivity:* PII (specifically email).
- *Data subject:* EU resident.
- *Regulatory regime:* GDPR.
- *Business domain:* customer relationship management.

These are four independent axes. Each axis has its own value vocabulary. A column has zero or one value per axis. Forcing them into one hierarchy produces combinatorial class names like `MarketingTeamGDPREmailPII` that age badly.

### The addition

A new concept, **`tessera:AttributeAxis`**, names an independent semantic dimension. Each existing classification is refactored to declare which axis it belongs to.

Each axis declares its own structural type. Some axes carry hierarchical relationships between values; others are flat enumerations:

- **Hierarchical axis.** Values form a subsumption hierarchy. `sensitivity: PIIEmail` implies `sensitivity: PII` by subclassing. SHACL shapes and the schema expect class-hierarchy references on this axis.
- **Flat axis.** Values are independent enumeration members. `dataSubject: EUResident` does not subsume anything; `dataSubject: USResident` is a sibling, not a parent or child. The schema expects scalar value references on this axis.

The distinction is per-axis because the underlying domain dictates it: sensitivity has natural taxonomic structure, regulatory regimes do not. Declaring the type up front lets validators reject malformed references early.

### Proposed v0 axes

Drawn from real ABAC use cases and aligned with W3C DPV where possible:

| Axis | Structural type | Example values | Notes |
|---|---|---|---|
| `sensitivity` | Hierarchical | PII ⊂ PersonalData ⊂ RegulatedData; PIIEmail ⊂ PII; Public, Confidential as siblings | The existing classification hierarchy lives here. Backward-compatible. Aligned with DPV `PersonalDataCategory`. |
| `dataSubject` | Flat | EUResident, USResident, Employee, Customer, Minor | Aligned with DPV `DataSubject`. Subsumption between, e.g., Minor and Customer is a real-world question the v0 vocabulary does not commit to. |
| `regulatoryRegime` | Flat | GDPR, HIPAA, PCI-DSS, SOX, CCPA | Regulations do not subsume each other; they overlap in scope but are independent. |
| `businessDomain` | Flat (adopter may extend hierarchically) | CRM, Finance, HR, Engineering, Marketing | Organizational classification. v0 declares it flat; adopters who model org hierarchies may declare a hierarchical extension under their own namespace. |

The number of axes intentionally stays small in v0. Adopters extend with their own axes by declaring new `AttributeAxis` individuals (analogous to how the closed condition algebra has well-known operators with adopter-declared extensions). Each adopter-declared axis declares its own structural type.

### How resources carry attributes

A resource (catalog, schema, table, column) carries zero or more attribute *assignments*. Each assignment names an axis and a value. The same resource may have:

```yaml
attributes:
  sensitivity: PII
  dataSubject: EUResident
  regulatoryRegime: GDPR
  businessDomain: CRM
```

Hierarchical inference applies only within hierarchical axes: if `sensitivity: PIIEmail` is asserted, the resource is also `sensitivity: PII` by subsumption. On flat axes, no such inference holds — `dataSubject: EUResident` does not imply any other `dataSubject` value.

### Why this is right shape, not over-engineering

The four axes above correspond to the four most common policy distinctions across the platforms surveyed:

- Databricks ABAC tutorials and examples consistently reference data sensitivity (`pii`), data subject (`location`, `eu`), regulatory regime (often implicit), and business domain (`team`, `department`).
- Snowflake tag examples follow the same pattern (the documented use case in the Snowflake quickstart uses `PII`, `FINANCIAL` as values).
- W3C DPV models these dimensions as separate vocabularies, not as one hierarchy.

The framework is recognizing a structure that already exists in practice, not inventing one. The risk of over-engineering is bounded because the axes are *adopter-extensible* — a v0 with four named axes is a starting point, not a closed set.

---

## §3. Scoped policy attachment

Tessera v0 attaches policies to specific resources via `appliesTo`. A policy says "this applies to `acme.tpch.orders`." This is fine for table-specific policies but does not express ABAC's defining behavior.

ABAC's defining behavior: a policy attaches at a *level* in the hierarchy (catalog, schema, or table) and *automatically applies* to anything within that scope matching its conditions. A single policy can protect every PII column in a catalog without enumerating tables.

### The addition

A new concept, **`tessera:Scope`**, expresses the level at which a policy attaches. A policy with a scope applies to every resource within that scope that matches its selectors.

```yaml
- "@type": Policy
  appliesTo:
    selector: byScope
    scope: catalog:bg_data
    matching:
      attributes:
        sensitivity: PII
```

The above attaches the policy at the catalog level; it applies to every column in every table in the catalog tagged with sensitivity PII.

Scope kinds for v0 are inferred from the resource IRI's namespace prefix:

- `catalog:` → applies to all schemas, tables, and columns in the catalog.
- `schema:` → applies to all tables and columns in the schema.
- `table:` → applies to all columns in the table.
- `column:` → applies only to the specific column. (Equivalent to today's `byIdentity` selector pointing at a column.)

Inferring the kind from the resource prefix avoids redundancy. The Tessera context defines these prefixes; adapters use them consistently for emission and extraction. If an adapter needs the kind explicit for downstream tooling, it can synthesize it from the resource IRI without help from the policy file.

Inheritance through scope is *implicit and downward*. A policy at catalog scope applies to schemas, tables, and columns within. The adapter handles platform-specific inheritance details (Databricks does not propagate tags from table to column by default; Snowflake does propagate tags from table to columns — but these are mechanism differences, not policy differences).

### Scope exclusion is distinct from principal exclusion

Two kinds of "exclusion" appear in ABAC patterns, and they are structurally different. The IR keeps them separate:

- **Scope exclusion** — *what resources the policy applies to.* "Attach at catalog scope, except for one schema and one table within it." The exclusion narrows the resource set.
- **Principal exclusion** — *who the policy affects.* "Apply to `account users` except `data-stewards`." The exclusion narrows the principal set; the policy still applies to the same resources.

Principal exclusion is already handled by the existing principal selectors (`byComposition` with `match: not` is the canonical form, and the v1 candidates already address whether more concise forms are needed). The policy container's ordered first-match (ADR-015) further enables expressing principal exclusion via rule ordering.

Scope exclusion is new with `byScope` and needs its own mechanism. The straightforward addition is an optional `except` list on the scope selector:

```yaml
appliesTo:
  selector: byScope
  scope: catalog:bg_data
  except:
    - schema:bg_data.sandbox
    - table:bg_data.metrics.staging_only
  matching:
    attributes:
      sensitivity: PII
```

Whether this v0 addition includes `except` is a design choice for ADR-019 — it's small enough to include up front, but it's also possible to defer until a worked exercise drives it. The straightforward path is including it: Snowflake and Databricks ABAC both support scope-level exclusion patterns, and a v0 that omits it would force a follow-on amendment soon after.

### The relationship to `appliesTo`

The existing `appliesTo` field carries a selector. The selector can be `byIdentity` (today's behavior — points at a specific resource), `byClassification` (now refactored to use attribute axes), `byDataset` (existing data-driven selection), or `byScope` (new). The `byScope` selector is the addition; the others continue to work.

A policy with `byScope` selection plus attribute-matching conditions is an ABAC policy in Tessera terms. A policy with `byIdentity` selection is a table-specific policy. Both shapes remain valid.

---

## §4. Composable attribute selectors

The existing `byClassification` selector matches resources whose classification is a specific class. With orthogonal axes, the selector evolves: match resources whose attributes meet specified conditions across one or more axes, composed with conjunction, disjunction, and negation.

### Reuse `byComposition`'s shape, don't invent a parallel one

The existing `byComposition` selector composes principal selectors via `match: and|or|not` over a `criteria` list. The same algebra applies to attribute matching, and the design should use the same shape rather than introduce a parallel one. Three different shapes for what is one algebraic concept would be a maintenance smell that propagates into schema, SHACL, and adapter code.

The canonical form for composed attribute selection:

```yaml
matching:
  match: and
  criteria:
    - attribute:
        axis: sensitivity
        value: PII
    - attribute:
        axis: dataSubject
        value: EUResident
```

Each leaf criterion names an axis and a value. `match: and` requires all to hold; `match: or` requires any; `match: not` negates a single criterion (or a single composed criterion).

Composition nests:

```yaml
matching:
  match: or
  criteria:
    - attribute:
        axis: sensitivity
        value: PII
    - match: and
      criteria:
        - attribute:
            axis: regulatoryRegime
            value: GDPR
        - attribute:
            axis: dataSubject
            value: EUResident
```

The above matches resources where `sensitivity=PII` OR (`regulatoryRegime=GDPR` AND `dataSubject=EUResident`).

### Implicit conjunction as syntactic sugar

The most common case is conjunction over a small number of attributes. The verbose canonical form is noise for that case. The IR therefore accepts an implicit-AND shortcut:

```yaml
matching:
  attributes:
    sensitivity: PII
    dataSubject: EUResident
```

This is sugar that desugars to the canonical form with `match: and`. The converter, the schema, and adapters all treat it as equivalent. The shortcut exists because policies authored against the canonical form for two-attribute conjunctions would read significantly worse than they need to.

### What this corresponds to on each platform

- **Databricks** emits `has_tag` / `has_tag_value` predicates inside `MATCH COLUMNS` (or the equivalent at row level). The composition algebra maps directly: `match: and` → SQL `AND`, `match: or` → SQL `OR`, `match: not` → SQL `NOT`. The tag taxonomy mapping (§5) handles the translation from `attribute.axis: sensitivity, value: PII` to a concrete `has_tag` or `has_tag_value` call.
- **Snowflake** emits explicit `SYSTEM$GET_TAG_ON_CURRENT_*` calls inside policy bodies, or attaches the policy to the appropriate tag via `ALTER TAG SET MASKING POLICY` for the simple single-attribute cases. The composition algebra translates to SQL conditional logic in the policy body.
- **Custom-pattern adapters** emit JOIN conditions against their classification tables.

The point of capturing the composition algebra at the IR level is that the algebra is the same across platforms; only the surface syntax differs.

---

## §5. Adapter configuration mappings (tag-taxonomy as one instance)

§2 through §4 add to the IR. §5 is structurally different: it specifies *adapter configuration shape*, not IR vocabulary. The reason it belongs in this scoping document is that ABAC support requires it, but the underlying pattern is broader than ABAC and worth establishing as a general framework rather than as a one-off for tags.

### The pattern

Adapters need to translate between platform-specific identifiers and Tessera's semantic vocabulary. The translation is per-environment because adopters use different naming conventions, different tag taxonomies, different principal identity systems. The mapping is bidirectional: emission lowers Tessera identifiers to platform-specific ones; extraction lifts platform-specific identifiers back to Tessera ones.

Tessera has had one instance of this pattern from the beginning: **identity binding** (ADR-002, where the project's customer-enablement posture acknowledged that Databricks principals are mapped to Tessera principal IRIs via per-environment configuration). ABAC adds a second instance: **tag taxonomy mapping** (Databricks governed tag keys/values mapped to Tessera attribute axes/values). More instances are likely as the framework grows: classification name mapping, group hierarchy mapping, possibly more.

Rather than treating each instance as a one-off, ADR-021 (planned) establishes the **adapter configuration mapping pattern** as the general shape, with tag-taxonomy mapping as its first concrete application. Future instances follow the same pattern.

### Shape of the pattern

An adapter configuration mapping declares pairings between platform-specific identifiers and Tessera's semantic identifiers. The pairing is grouped by *kind* (the type of identifier being mapped) and the kind determines what fields the platform-specific side carries:

```yaml
# adapters/unity-catalog/configuration.yaml (illustrative)

identityBindings:
  - tesseraPrincipal: group:data-stewards
    platformGroup: bg_data_stewards
  - tesseraPrincipal: user:brice@databricks.com
    platformUser: brice.giesbrecht@databricks.com

tagTaxonomy:
  - axis: sensitivity
    axisValue: PII
    tagKey: classification
    tagValue: pii
  - axis: sensitivity
    axisValue: PIIEmail
    tagKey: pii
    tagValue: email
  - axis: dataSubject
    axisValue: EUResident
    tagKey: region
    tagValue: EMEA
  - axis: regulatoryRegime
    axisValue: GDPR
    tagKey: regulation
    tagValue: gdpr
```

The Snowflake adapter's configuration uses the same structural shape with platform-specific fields:

```yaml
# adapters/snowflake/configuration.yaml (illustrative)

tagTaxonomy:
  - axis: sensitivity
    axisValue: PII
    tagSchema: governance
    tagName: classification
    tagValue: PII
  - axis: dataSubject
    axisValue: EUResident
    tagSchema: governance
    tagName: data_region
    tagValue: EU
```

The pattern is the same; the platform-specific identifier fields differ per adapter.

### Default behavior on unmapped identifiers

During extraction, the adapter may encounter a platform-specific identifier that is not in the configuration mapping — a tag whose key/value pair has no Tessera axis/value equivalent, a principal IRI not in identity-binding. ADR-021 specifies three configurable behaviors, with **strict as the default**:

- **Strict (default).** Unmapped identifier is an extraction error. The adapter refuses to lift the policy into the IR without an explicit mapping. The IR stays clean of unknown attributes. Adopters configuring strict accept that they must declare all their tag and identity mappings before extraction runs.
- **Permissive.** Unmapped identifier is lifted onto a synthetic axis or principal namespace (e.g., `unknown:tagKey` for a tag whose key isn't mapped) with confidence marker `low`. The IR carries the information but the policy semantics are not validated. Useful during migration when not all tags are yet mapped.
- **Pass-through.** Unmapped identifier is lifted into the IR with the platform-specific identifier carried verbatim and confidence `low`. This preserves round-trip fidelity at the cost of IR cleanliness. Useful for diagnostic scenarios where the goal is to see what's in the platform rather than to produce a portable policy.

The default is strict because it keeps the IR honest by default; opt-in to looser semantics requires explicit configuration. This matches the framework's broader "honesty over completeness" disposition.

### Why this is configuration, not policy

Putting these mappings in the policy file would violate the §1 principle — the policy would carry mechanism. A policy that says `sensitivity: PII` should mean the same thing on every platform; the policy author should not need to know whether the Databricks adapter expects this to emit as `has_tag('pii')`, `has_tag_value('classification', 'pii')`, or `has_tag('data_class')` with allowed value `PII`.

The mapping is per-adapter, per-environment. Different customers running the Databricks adapter may have different tag taxonomies; the policy file does not change.

---

## §6. Worked sketches for the two target platforms

These are design-time sketches, not implementations. The Databricks SQL syntax has been verified (§9 Stage 1 task 1, completed 2026-05-18) against current Databricks ABAC documentation; the corrected syntax appears below. The Snowflake sketch is qualitative; no Snowflake adapter is planned for the immediate v0 work and the sketch's role is to show that the design accommodates Snowflake's mechanism, not to specify the emission concretely.

### Sketch: column masking on Databricks ABAC

A policy expressed in Tessera's vocabulary using the revised algebra:

```yaml
"@type": Policy
"@id": policy:redact-pii-email
policyKind: ColumnVisibility
appliesTo:
  selector: byScope
  scope: catalog:bg_data
  matching:
    attributes:
      sensitivity: PIIEmail
rules:
  - principal:
      selector: byIdentity
      resource: group:data-stewards
    effect: allow
  - principal:
      selector: byIdentity
      resource: group:account-users
    effect: transform
    transformation:
      type: Redact
      replacement: 'redacted'
defaultStrategy: explicit-baseline-group
baselineGroup: "account users"
```

Note the policy file contains no platform-specific tag references. The `sensitivity: PIIEmail` attribute is a Tessera-level semantic identifier; the Databricks adapter resolves it to a platform-specific `has_tag_value` call via its configuration mapping.

The Databricks adapter, given this policy and a taxonomy mapping where `sensitivity:PIIEmail` maps to `has_tag_value('pii', 'email')`, would emit (verified syntax):

```sql
-- The masking UDF. Takes the matched column value (and optionally additional
-- arguments via USING COLUMNS) and returns a value castable to the column's
-- type. For a literal-redaction policy, the function ignores its input.
CREATE FUNCTION fn_redact_pii_email(val STRING) RETURNS STRING
  RETURN 'redacted';

-- The policy itself. Attached at catalog scope; MATCH COLUMNS identifies
-- the columns the policy applies to via tag predicates; ON COLUMN names
-- which matched column (by alias) receives the masking function.
CREATE POLICY redact_pii_email
  ON CATALOG bg_data
  COLUMN MASK fn_redact_pii_email
    TO `account users`
    EXCEPT `data-stewards`
    FOR TABLES
    MATCH COLUMNS has_tag_value('pii', 'email') AS pii_email_col
    ON COLUMN pii_email_col;
```

The clause ordering follows the verified Databricks syntax: `COLUMN MASK → TO → [EXCEPT] → FOR TABLES → [WHEN] → MATCH COLUMNS ... AS alias → ON COLUMN alias → [USING COLUMNS]`. Three details the sketch carries that the earlier version did not:

- **`FOR TABLES` clause** is required between the principal binding and the column-matching clauses.
- **`AS alias` on `MATCH COLUMNS`** names the matched column set so the `ON COLUMN` clause can reference it. The alias is policy-local; it does not have to match any actual column name in the protected tables.
- **`ON COLUMN alias`** identifies which matched column receives the mask. The alias links back to the `MATCH COLUMNS` clause.

The `has_tag` and `has_tag_value` built-ins take literal key (and optionally value) strings; no wildcard or pattern-matching syntax is documented. To match any column tagged with a given key regardless of value, use `has_tag('pii')`; to match every column unconditionally, use `MATCH COLUMNS TRUE`. The composition algebra from §4 maps directly: `match: and` → SQL `AND` over `has_tag*` predicates, `match: or` → `OR`, `match: not` → `NOT`.

The structural shape — policy-attached-at-scope, principal binding via `TO`/`EXCEPT`, tag-based selection via `MATCH COLUMNS` with aliasing, masking via `COLUMN MASK` + `ON COLUMN` — is what the design must support. The verification confirmed all of this; the only adjustments needed were the missing `FOR TABLES`, the aliasing requirement, and an explicit UDF definition.

### Sketch: extraction from existing Databricks ABAC

A Databricks deployment has the ABAC policy above. The Databricks adapter, with the same configuration mapping, extracts:

- Recognizes the tag predicate → maps to `attributes.sensitivity: PIIEmail` via the tag-taxonomy mapping.
- Recognizes `TO 'account users' EXCEPT 'data-stewards'` → maps to two rules with appropriate principal selectors.
- Recognizes `COLUMN MASK fn_redact_pii_email` → emits a `Transformation` of type `Redact` if the UDF body is recognizable; otherwise lifts as `type: Custom` with the UDF reference and confidence `medium`.

The extraction produces a Tessera policy with the structure shown. Extraction confidence is `high` for the parts the mapping covers cleanly, `medium` for parts where the UDF body requires interpretation, `low` for parts where the tag is not in the mapping (per §5's strict default, this would actually fail extraction rather than producing a `low`-confidence result).

### Sketch: column masking on Snowflake (design-time only, no implementation)

The same Tessera policy emitted to a hypothetical Snowflake adapter would produce a tag-based masking policy. The Snowflake mechanism is to define a masking policy, then `ALTER TAG SET MASKING POLICY` to bind it to a tag. The Snowflake adapter, with its own configuration mapping where `sensitivity:PIIEmail` maps to a specific Snowflake tag, would produce DDL of roughly this shape:

```sql
-- ⚠ design-time sketch; no Snowflake adapter exists yet
CREATE MASKING POLICY redact_pii_email
  AS (val STRING) RETURNS STRING ->
    CASE
      WHEN CURRENT_ROLE() IN ('DATA_STEWARDS') THEN val
      ELSE 'redacted'
    END;

ALTER TAG governance.pii SET MASKING POLICY redact_pii_email;
```

The same policy IR, two different platform emissions. The semantic content — "redact PIIEmail-tagged columns unless the user is a data steward" — is preserved. The implementation differs per platform mechanism.

Confirming this sketch concretely would require building a Snowflake adapter, which is future work. The point here is that the policy file does not change between Databricks and Snowflake emission; only the adapter and its configuration do.

---

## §7. v0 disposition

Per ADR-017, the immutability bar is suspended until external dependency. All four additions in §2 through §5 land in v0:

- `AttributeAxis` concept and the refactored `Classification` system.
- `Scope` concept and the `byScope` selector.
- Composable attribute selectors (using the `byComposition` algebra over attribute leaves).
- Adapter configuration mapping pattern (tag taxonomy as one instance; identity binding as another).

The work is captured in subsequent ADRs:

- **ADR-018 (planned)** — AttributeAxis and the Classification refactor.
- **ADR-019 (planned)** — Scoped policy attachment via `byScope`, including scope-exclusion via `except`. Explicitly does *not* prescribe a cross-policy combining algorithm (see §8 Q3); that decision is deferred until the worked exercise produces evidence.
- **ADR-020 (planned)** — Composable attribute matching reusing the `byComposition` algebra.
- **ADR-021 (planned)** — Adapter configuration mapping pattern, with tag taxonomy and identity binding as the first two instances.

These could potentially fold into fewer ADRs if cohesion suggests it, but the §7 precedent (ADR-014 / ADR-015) argues for keeping structurally distinct decisions decomposed.

### Why four ADRs instead of one

Each addition is structurally distinct:

- §2 changes the classification *shape*.
- §3 adds a new selector and a new resource-set concept.
- §4 changes the *algebra* over selectors (reuses `byComposition`'s pattern but extends its domain).
- §5 is *adapter contract*, not IR.

A single ADR conflating these would lose the distinction. Following the ADR-014 / ADR-015 precedent, keeping these decomposed serves the historical record.

---

## §8. Open questions and follow-on work

**Q1. Should `purpose` move from "purpose-binding via condition" to "purpose as an attribute axis"? — Resolved: stays as a condition.**

Purpose is a property of an access request, not a property of the data. The same data can be accessed for different purposes by different requests; treating it as a data attribute would conflate "what this data is" with "what this access is for." The existing `purpose-in` condition operator stays as the canonical mechanism, and the three-category framing in §1 ("data attribute / request condition / principal property") captures the structural distinction so the question doesn't resurface.

This resolution does not preclude per-resource declarations of *which purposes are permitted for this data*, if a future exercise drives that need. That would be a different concept — a kind of resource-level capability or contract — and not the same as making purpose an attribute axis. Out of scope for ABAC v0; revisit if evidence demands.

**Q2. What is the relationship between `attributes:` on a resource and `Classification` references that pre-date this work?**

The existing `Classification` system is preserved. The refactor moves classifications onto axes (`Classification: PII` becomes `attributes.sensitivity: PII`), but existing files referencing classifications without an axis should still validate. The schema needs to handle both shapes during the v0 lifecycle, possibly with a deprecation note on the bare-classification form. ADR-018 specifies the backward-compat behavior.

**Q3. How does the ABAC policy structure interact with the policy container's combining algebra (ADR-015)? — Targeted by the worked exercise.**

This is the most consequential open question. ADR-015 specifies first-match within a single policy. ABAC's defining behavior is that *multiple policies* can attach at overlapping scopes, and their combined effect depends on cross-policy resolution rules. Snowflake has explicit ordering (row access first, then masking; single column can't be in both signatures). Databricks ABAC evaluates dynamically with its own rules. ADR-015 does not speak to either.

Three resolution paths the worked exercise (§9) should help discriminate between:

- **α — Tessera ignores cross-policy combination.** Policies are evaluated independently per platform conventions. Adapters handle platform-specific combining; Tessera doesn't model it. The IR cannot represent the intent of "this should take precedence when both apply."
- **β — Tessera adopts a single cross-policy combining algorithm.** Names one (deny-overrides, permit-overrides, declared priority) and requires adapters to enforce it. Commits to a position that may not match Databricks or Snowflake's native semantics.
- **γ — Tessera declares cross-policy combining as adapter-configurable.** The IR doesn't pick; each adapter declares its combining semantics in its capability profile. Policies depending on a specific algorithm declare that as a capability requirement.

The exercise designed in §9 should include a multi-policy case explicitly — two ABAC policies attached to overlapping scopes with different attribute matchers and different effects, designed to put them in tension. What Databricks does, what the customer would want it to do, and whether they match are all observable. The result discriminates between α, β, and γ.

ADR-019 (scoped attachment) deliberately does *not* prescribe a cross-policy combining algorithm. That decision is held until the exercise produces evidence.

**Q4. Does the `byScope` selector need an exclusion facility?**

§3 of this document includes `except` on the scope selector in the design. The question is whether to include it in the v0 addition or defer until evidence demands it. The straightforward answer is to include it, because both Snowflake and Databricks ABAC support scope-level exclusion patterns and a v0 that omits it would force a follow-on amendment quickly. ADR-019 includes the `except` facility unless the worked exercise reveals a reason to defer.

**Q5. What about coordination labels that are governance-relevant — like a tag that records "data classification reviewer"?**

If a tag is used as a record of a governance decision (who reviewed, when), it is metadata about the policy, not a property of the data. Falls under provenance (ADR-007 partially), not under attributes. Worth being explicit about so the distinction holds: the §1 three-category framing identifies what counts as a data attribute; classifications-of-the-policy-process are a fourth category that Tessera handles via provenance, not via attribute axes.

---

## §9. Recommended next steps

The path from here to landed spec changes runs through three stages: pre-ADR verification, ADR drafting, then a worked exercise that validates the design before spec changes land.

### Stage 1 — pre-ADR verification (small focused tasks)

One task should complete before ADRs are drafted:

1. **Verify the Databricks ABAC DDL syntax** against current reference documentation. ✓ **Completed 2026-05-18.** The verification confirmed the structural design holds but corrected three details in the §6 sketch: the `FOR TABLES` clause is required between `EXCEPT` and `MATCH COLUMNS`; `MATCH COLUMNS` requires an `AS alias` that the `ON COLUMN alias` clause then references; the masking UDF takes the column value as its first argument and returns a value castable to the column type. The `has_tag` / `has_tag_value` built-ins take literal arguments (no wildcards documented); the composition algebra in §4 maps directly to SQL `AND`/`OR`/`NOT`. The §6 sketch has been updated with the verified syntax. No impact on §2–§5 design.

   Sources consulted: [Create and manage ABAC policies](https://docs.databricks.com/aws/en/data-governance/unity-catalog/abac/policies), [Attribute-based access control in Unity Catalog](https://docs.databricks.com/aws/en/data-governance/unity-catalog/abac), [Core concepts for ABAC](https://docs.databricks.com/aws/en/data-governance/unity-catalog/abac/core-concepts).

2. (Q1 is resolved in §8 above; this slot was previously for that resolution.)

### Stage 2 — ADR drafting

After Stage 1, draft the ABAC ADRs against the revised scoping document:

- **ADR-018 — AttributeAxis and the Classification refactor.** Introduces the axis concept, declares the four v0 axes with their structural types (hierarchical vs flat), specifies the axis-extensibility convention, and handles the backward-compat relationship to existing classifications per §8 Q2.
- **ADR-019 — Scoped policy attachment via `byScope`.** Introduces the `Scope` concept, the resource-IRI-prefix-based kind inference, the implicit-downward inheritance semantics, and (likely) the `except` facility per §8 Q4. Explicitly does *not* prescribe cross-policy combining (held until §9 Stage 3 produces evidence).
- **ADR-020 — Composable attribute matching.** Reuses the `byComposition` algebra (`match: and|or|not`, `criteria: [...]`) over attribute leaves; specifies the implicit-AND shortcut as syntactic sugar; aligns with the existing principal-selector composition pattern.
- **ADR-021 — Adapter configuration mapping pattern.** Establishes the general pattern for per-environment mapping between platform-specific identifiers and Tessera semantic identifiers. Specifies the strict default with permissive and pass-through as configurable alternatives. Names tag taxonomy and identity binding as the first two instances; future instances follow the same shape.

These four could fold into fewer ADRs if cohesion suggests it, but the §7 precedent (ADR-014 / ADR-015 as separate decisions for policy container and combining algebra) argues for keeping structurally distinct decisions decomposed.

### Stage 3 — worked exercise (validates the design before spec changes land)

A column-masking exercise driven by a `sensitivity` attribute, designed to surface §8 Q3 (cross-policy combination) if possible.

The exercise's shape:

- **Phase 1 inputs.** Tag a column in the test notebook with a governed tag corresponding to `sensitivity: PIIClerk` (or similar — the actual tag name is the customer's choice; the Tessera attribute axis is Tessera's choice). Construct a second ABAC policy attached to the same catalog scope with a different attribute matcher and a different effect, designed to overlap with the first policy on at least some columns. The conflict is intentional — the question is what happens.
- **Phase 2 derivation.** Express both policies in Tessera's vocabulary, run the Databricks adapter sketch to produce the emitted DDL, observe what each policy produces independently and what they produce together.
- **Phase 3 verification and comparison.** Observe what Databricks actually does when both policies are applied to the same column. Compare against the Tessera-level expectations. The result either confirms a specific cross-policy resolution semantics (which then informs whether ADR-019 should adopt α, β, or γ) or surfaces that Tessera's view is platform-specific and the IR cannot express it portably.

The user (Brice) needs to construct the ABAC examples in the test notebook to enable Phase 3. The notebook does not currently use ABAC; this is an explicit prerequisite for the exercise.

### Stage 4 — spec changes land

After the exercise runs and the ADRs are drafted with its findings incorporated, the spec changes land:

- `spec/v0/ontology.ttl` — `AttributeAxis`, `Scope`, `byScope`, attribute-matching shape, adapter-configuration vocabulary.
- `spec/v0/context.jsonld` — short names for the new terms.
- `spec/v0/schema.json` — structural validation including per-axis hierarchy expectations.
- `docs/technical-design-v0.2.md` §4 — incorporates scope, attribute axes, composable matching, and the configuration-mapping pattern.
- `spec/v0/examples/` — the worked-exercise artifacts produced in Stage 3.

The exercise either confirms the design or surfaces something the scoping document missed. Either outcome is cheaper before ADRs publish and the spec changes land than after.
