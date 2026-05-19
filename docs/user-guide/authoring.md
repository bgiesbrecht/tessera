# Authoring policies

This page is the authoring reference. It assumes you've worked through [`tutorial.md`](./tutorial.md). Where the tutorial walked one policy end to end, this page covers the vocabulary you'll reach for when writing policies of your own.

The canonical form is JSON-LD (ADR-004), but you author in YAML (`.tessera.yaml` files). The YAML maps mechanically to JSON-LD via the JSON-LD context at `spec/v0/context.jsonld`. A converter tool that handles this round-trip with comment preservation is queued; for now, the two forms are maintained side by side.

## Top-level structure — the Policy container

Every multi-rule policy is a `Policy` container (ADR-014). Single-rule policies can use a freestanding `PolicyConstraint` at the document root, but `Policy` is the recommended shape for everything.

```yaml
policy:
  id: example-policy                       # Short name; expands to policy:example-policy IRI
  version: 1.0.0
  kind: RowVisibilityConstraint | ColumnVisibilityConstraint
  description: |
    Plain-language description; lands in rdfs:comment.

  appliesTo: { selector: …, resource: … }  # What the policy is attached to (§ Selectors)
  action: Read | Write | Delete | Share | Sample | Aggregate

  defaultStrategy: explicit-baseline-group | negated-complement | none
  baselineGroup: group:…                   # Required iff explicit-baseline-group
  defaultBranch:                            # Required iff negated-complement
    effect: …
    transformation: …

  rules:
    - principal: …
      condition: …                          # Optional
      effect: …
      transformation: …                     # Required iff effect: transform

  capabilityRequirements: [list of strings] # Optional; for adapter-emission diagnostics
  provenance: { extractedFrom: …, notes: … } # Optional
```

**Rules evaluate top-to-bottom (ADR-015).** The first rule whose `principal` selector and `condition` (if any) match wins; subsequent rules don't evaluate. If no rule matches, `defaultStrategy` controls the fallback.

**`defaultStrategy` says what to do for principals matching no rule:**

| Strategy | Semantics | Requires |
|---|---|---|
| `explicit-baseline-group` | A named group sees the policy's baseline behavior; principals outside the group see nothing | `baselineGroup: group:…` |
| `negated-complement` | A fallback branch applies to everyone matching no rule | `defaultBranch: {effect, transformation}` |
| `none` | Fail-closed: no rule match ⇒ no access | — |

The choice is *intent*, not just observable behavior. Two policies that produce the same query results may carry different `defaultStrategy` values — and the difference is real, captured for downstream tooling and audit.

## Selectors

A selector identifies a set of resources or principals. Tessera has five:

### `byIdentity` — direct IRI reference

```yaml
appliesTo:
  selector: byIdentity
  resource: table:bg_rls_demo.tpch.orders

principal:
  selector: byIdentity
  resource: group:bg_rls_demo_high_priority_ops
```

The simplest selector. The IRI is platform-neutral; the adapter resolves it via `identity_bindings` (for principals) or `resource_bindings` (for resources) — see [`operating.md`](./operating.md).

### `byClassification` — semantic-attribute reference

```yaml
appliesTo:
  selector: byClassification
  classification: classification:PII
```

Selects everything carrying the named classification. The classification IRI must resolve to a `tessera:Classification` subclass in the ontology (the SHACL shapes enforce this).

### `byDataset` — data-driven principal set

```yaml
principal:
  selector: byDataset
  dataset:
    type: PrincipalSetFromTable
    table: catalog.schema.acl_mapping
    principalColumn: username
    resourceColumn: code_name
```

The principal set is computed at query time by joining a mapping table. Used for ACL-table patterns (the Databricks `acl-row-visibility-*` and Snowflake `snowflake-byDataset-row-visibility-*` exercises). Also the **recommended Snowflake authoring pattern** for non-trivial row-access policies — see § Snowflake authoring guidance below.

### `byScope` — ABAC scoped attachment

```yaml
appliesTo:
  selector: byScope
  scope: catalog:bg_rls_demo
  except:
    - schema:bg_rls_demo.sandbox
  matching:
    attributes:
      sensitivity: PII
      dataSubject: EUResident
```

Attaches a policy to a scope (catalog, schema, table, column) with optional `matching` criteria over attribute axes (ADR-019, ADR-020). The `except` facility excludes sub-scopes. The `matching` block supports both a shorthand (`attributes:` map = implicit AND) and a canonical form (`match: and|or|not, criteria: [...]`).

### `byComposition` — predicate algebra

```yaml
appliesTo:
  selector: byComposition
  criteria:
    match: and
    criteria:
      - selector: byClassification
        classification: classification:PII
      - selector: byDataset
        dataset: { … }
```

Combines other selectors with `and`/`or`/`not`. Used when no single selector kind expresses the intent.

## Conditions

Per-rule predicate, optional. Limits when the rule applies. Eleven operators:

| Operator | Meaning |
|---|---|
| `and`, `or`, `not` | Logical composition |
| `eq`, `lt`, `gt` | Scalar comparison |
| `in` | Membership in a fixed value list |
| `purpose-in` | Match against the session's claimed purpose-of-use (PROHL-style) |
| `located-in` | Match against session jurisdiction attribute |
| `time-window` | Match against time-of-day / day-of-week / date range |
| `consent-granted` | Per-subject consent record check |
| `exists-in-dataset` | Existence of a matching row in a `ResourceSetFromTable` |

Example:

```yaml
condition:
  op: and
  operands:
    - { op: in, operands: [column:t.priority], values: ['1-URGENT', '2-HIGH'] }
    - { op: purpose-in, values: ['fraud-investigation', 'audit'] }
```

Not all adapters implement all operators. The adapter's capability profile declares which it supports; emission diagnostics flag unsupported operators.

## Effects

Per-rule outcome:

| Effect | Meaning |
|---|---|
| `allow` | Grant access (used in non-visibility contexts) |
| `deny` | Refuse access |
| `transform` | Replace the value with a transformation output. Requires `transformation:`. |
| `keep-matching-rows` | (Row visibility) Include matching rows |
| `drop-matching-rows` | (Row visibility) Exclude matching rows |

**Effect-driven transformation constraint (ADR-022):** `transformation` is required if and only if `effect: transform`. The schema enforces this — a `RowVisibilityConstraint` rule with `effect: keep-matching-rows` cannot carry a `transformation`, and a `ColumnVisibilityConstraint` rule with `effect: transform` must carry one.

## Transformations

Carried as a structured `TransformationInstance` (ADR-016). Five well-known types:

```yaml
# Replace value with a fixed string
transformation:
  type: Redact
  replacement: "CLERK-REDACTED"

# Replace value with masked form
transformation:
  type: Mask
  maskChar: "X"
  preserveFirst: 0
  preserveLast: 4

# Replace with hash of value
transformation:
  type: Hash
  algorithm: sha256

# Replace with tokenized value (parameter shape deferred)
transformation:
  type: Tokenize

# Replace with bucketed value (parameter shape deferred)
transformation:
  type: Bucketize
```

Per-transformation parameters are validated by the JSON Schema. `Redact` requires `replacement`; `Mask` rejects `replacement` (it has `maskChar`/`preserveFirst`/`preserveLast`); `Hash` rejects `replacement` (it has `algorithm`).

## Attribute axes (ABAC)

Tessera models attributes via the `AttributeAxis` class (ADR-018). Four well-known axes in v0:

| Axis | Type | Example values |
|---|---|---|
| `sensitivity` | Hierarchical | `Public`, `Internal`, `Confidential`, `Restricted`, `PII`, … |
| `dataSubject` | Flat | `EUResident`, `USResident`, `Employee`, `Customer`, `Minor` |
| `regulatoryRegime` | Flat | `GDPR`, `HIPAA`, `PCI_DSS`, `SOX`, `CCPA` |
| `businessDomain` | Flat | `CRM`, `Finance`, `HR`, `Engineering`, `MarketingDomain` |

Each axis is itself extensible — adopters can introduce additional values in their own namespace. The hierarchical `sensitivity` axis additionally supports subsumption (`PII` ⊑ `Confidential`); flat axes treat values as discrete IRIs.

Use attribute axes in:
- `appliesTo` with `byScope` + `matching:` (apply policy to all PII columns in catalog X)
- `appliesTo` with `byClassification` (apply to whatever is labeled PII)
- `principal` selectors via `byClassification` (rare; supported)

## Snowflake authoring guidance

For non-trivial Snowflake row-access policies, **prefer `byDataset` over `byIdentity`** for the principal selector. This recommendation has two parts: a Snowflake-side reason and a Tessera-side reason that align.

### Snowflake reason

Snowflake's documentation recommends a mapping-table pattern for non-trivial row-access policies (Snowflake docs, *Use row access policies — Mapping table placement*). The reason is operational: gating the policy body on `CURRENT_USER()` against an authorization table is unaffected by the `DEFAULT_SECONDARY_ROLES` setting, whereas gating on `IS_ROLE_IN_SESSION` is subject to it.

Since 2024 (BCR-1692), Snowflake's default for new users is `DEFAULT_SECONDARY_ROLES = ('ALL')`. With ALL active, `IS_ROLE_IN_SESSION(X)` returns true for every role granted to the user, regardless of which role is primary via `USE ROLE`. Policies that rely on `IS_ROLE_IN_SESSION` to discriminate between roles silently fail to discriminate. The mapping-table pattern sidesteps this entirely.

### Tessera reason

Tessera's `byDataset` selector with `PrincipalSetFromTable` lowers structurally to exactly that mapping-table pattern. The IR shape is the same as the Databricks ACL exercise — the platform divergence is purely in adapter emission. By authoring with `byDataset`, you get:

- Snowflake-secondary-roles immunity by construction.
- Role-taxonomy changes update the ACL table, not the policy DDL.
- The same IR runs on Databricks (where the adapter joins the ACL table in a row-filter UDF body) and on Snowflake (where the adapter joins the ACL table in a row-access policy body).

### Recommended Snowflake `byDataset` shape

```yaml
policy:
  id: example
  kind: RowVisibilityConstraint
  appliesTo: { selector: byIdentity, resource: table:DB.SCHEMA.PROTECTED }
  action: Read
  defaultStrategy: none
  rules:
    - principal:
        selector: byDataset
        dataset:
          type: PrincipalSetFromTable
          table: DB.SCHEMA.ACL_USER_TO_CODENAME
          principalColumn: USERNAME       # matched against CURRENT_USER()
          resourceColumn: CODE_NAME
      condition:
        op: exists-in-dataset
        operands:
          - type: ResourceSetFromTable
            table: DB.SCHEMA.ACL_CODENAME_TO_VALUE
            principalColumn: CODE_NAME
            resourceColumn: PROTECTED_COLUMN_NAME    # see caveat below
      effect: keep-matching-rows
```

**Caveat — `resourceColumn` is currently conflated** (v1 candidate; see `spec/v0/examples/snowflake-byDataset-row-visibility.diagnostic.md` §3). For the policy to emit cleanly on Snowflake, the `resourceColumn` of the `ResourceSetFromTable` must match the column name on the protected table that the row-access policy binds to. v1 may split this into separate `aclColumn` + `boundColumn` fields. For now, name the columns to match.

When `byIdentity` is acceptable for Snowflake:
- The policy is single-rule and gates on `PUBLIC` only (no role discrimination needed).
- Your environment has `DEFAULT_SECONDARY_ROLES` explicitly set per user.
- The policy is for a controlled context where the secondary-roles-immunity property isn't load-bearing.

## When to use which selector

| Want to express | Selector |
|---|---|
| "this specific table / specific group" | `byIdentity` |
| "anything tagged PII / Confidential" | `byClassification` |
| "membership determined by a join against an ACL table" | `byDataset` (Snowflake-preferred; see above) |
| "everything in catalog X, except sandbox schema" with optional attribute matching | `byScope` |
| "PII AND in CRM domain, NOT in test schema" | `byComposition` |

## Worked-example library

`spec/v0/examples/` holds seven completed exercises spanning the design surface. Read them when authoring something similar:

| Example | Demonstrates |
|---|---|
| `group-row-visibility-*` | Multi-group row visibility via ordered first-match |
| `acl-row-visibility-*` | `byDataset` + `PrincipalSetFromTable` on Databricks |
| `column-mask-orders-clerk-*` | Single `TransformationInstance` (Redact) |
| `abac-column-mask-*` | ABAC scoping via `byScope` + tag-driven masking |
| `abac-row-filter-priority-*` | ABAC scoping with multi-branch row filter |
| `snowflake-byDataset-row-visibility-*` | The recommended Snowflake pattern, end to end |

Each carries a `.diagnostic.md` that records findings, gaps, and platform-specific behaviors.

## What's not in v0

- **Tokenize / Bucketize parameter shapes.** The types exist; the parameter schemas are deferred to v1.
- **A formal "preferred algorithm" annotation** for cross-policy combination. Tessera doesn't pick; the adapter declares platform behavior (ADR-023, γ-with-refinement).
- **A DSL.** Deferred per ADR-006 until the IR is stable through real corpus exposure.
- **Two-axis attribute matching** (table-level via `WHEN` + column-level via `MATCH COLUMNS`). v1 candidate, issue #12.
- **Match-modifier declarations on `PrincipalSetFromTable`** (case-insensitive match, whitespace normalization). v1 candidate, surfaced by the Databricks ACL exercise.

If you're authoring something that hits one of these gaps, surface it; the v0-suspended-immutability framing (ADR-017) means v0 admits additions while no external consumer exists.
