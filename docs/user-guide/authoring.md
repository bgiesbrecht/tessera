# Authoring policies

This page is the authoring reference. It assumes you've worked through [`tutorial.md`](./tutorial.md). Where the tutorial walked one policy end to end, this page covers the vocabulary you'll reach for when writing policies of your own.

The canonical form is JSON-LD (ADR-004), but you author in YAML (`.tessera.yaml` files). The YAML maps mechanically to JSON-LD via the JSON-LD context at `spec/v0/context.jsonld`. A v1 converter is available — run `python -m tools.converter <file.tessera.yaml> --out <file.jsonld>` or call `from tools.converter import yaml_to_jsonld` from Python. The converter handles envelope-form YAML (the practitioner shape `policy: { id, kind, ... }`) and JSON-LD-shaped YAML alike. Comment preservation in YAML round-trips and the reverse direction (JSON-LD → YAML) are deferred to v2.

## A note on this page's voice (ADR-027)

This reference is **descriptive**, not prescriptive. It describes what each selector, effect, and transformation represents — and where a platform's own documentation makes a recommendation (e.g., Snowflake on `IS_ROLE_IN_SESSION` vs. mapping tables for different scenarios), this page cites it. It does not synthesize cross-platform authoring recommendations Tessera has no authoritative basis to make. *That which can be defined can be represented*: the IR's job is to represent whatever well-defined intent you want to express, faithfully across platforms. Where the IR can't yet represent something definable, that's a gap to file an issue against — not a constraint on you. See ADR-027 for the full reasoning.

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
  resource: table:acme.tpch.orders

principal:
  selector: byIdentity
  resource: group:acme_high_priority_ops
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

The principal set is computed at query time by joining a mapping table. Used for ACL-table patterns (the Databricks `acl-row-visibility-*` and Snowflake `snowflake-byDataset-row-visibility-*` exercises). On Snowflake, this is the pattern documented for data-driven entitlement — see § Snowflake authoring guidance below for when it fits and when `byIdentity` fits instead.

### `byScope` — ABAC scoped attachment

```yaml
appliesTo:
  selector: byScope
  scope: catalog:acme
  except:
    - schema:acme.sandbox
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

Pick the selector that matches what the policy actually decides — **not** policy complexity. Snowflake's [Use row access policies](https://docs.snowflake.com/en/user-guide/security-row-using) documents three patterns and recommends different ones for different scenarios. Earlier versions of this guide framed `byDataset` as Snowflake's blanket preferred pattern for "non-trivial" policies; that framing was wrong and is corrected here.

### Role-discrimination → `byIdentity`

When the policy decision is *"does this user have role X?"*, Snowflake explicitly recommends `IS_ROLE_IN_SESSION`:

> "If role activation and role hierarchy are important, Snowflake recommends that the policy conditions use the IS_ROLE_IN_SESSION function for account roles and the IS_DATABASE_ROLE_IN_SESSION function for database roles."
> — [Use row access policies](https://docs.snowflake.com/en/user-guide/security-row-using)

Tessera's `byIdentity` lowers to `IS_ROLE_IN_SESSION` on Snowflake, matching that recommendation. Snowflake's `DEFAULT_SECONDARY_ROLES = ('ALL')` default (BCR-1692, rolled out 2024) is **consistent with** this emission rather than a defeat condition: secondary roles activate, `IS_ROLE_IN_SESSION` sees them, permission-scope semantics hold. The platform default and the adapter's emission align. (ADR-024's postscript and [`operating.md`](./operating.md) § Role-discrimination semantics record this correction.)

If your policy author intends *primary-role-only* semantics — "only when explicitly acting as role X" — that is a different intent the IR does not currently express. Tracked as issue [#14](https://github.com/bgiesbrecht/tessera/issues/14).

### Data-driven entitlement → `byDataset`

When the policy decision is *"does this ACL/mapping table assign this user to these rows?"*, Snowflake documents the mapping-table pattern as the canonical fit:

> "A row access policy condition can reference a mapping table to filter the query result set... For example, use a mapping table to determine the revenue values a sales manager can see in a specified sales region."
> — [Use row access policies](https://docs.snowflake.com/en/user-guide/security-row-using)

This is the real Tessera customer engagement (ADR-003): hundreds of policies expressed as ACL rows. Tessera's `byDataset` selector with `PrincipalSetFromTable` lowers to this pattern. The policy body gates on `CURRENT_USER()` against the ACL, which is orthogonal to role activation — so `DEFAULT_SECONDARY_ROLES` is not part of the design question. Same IR runs on both platforms; only the adapter emission differs.

Snowflake's performance caveat:

> "using mapping tables may result in decreased performance compared to the more simple example."
> — [Use row access policies](https://docs.snowflake.com/en/user-guide/security-row-using)

The documented optimization for high-volume protected tables is wrapping the lookup in a memoizable function:

> "To increase query performance on the policy-protected table, replace the mapping table lookup subquery in the EXISTS clause with a memoizable function."
> — [Use row access policies](https://docs.snowflake.com/en/user-guide/security-row-using)

Tessera's emit path currently produces the plain EXISTS form; memoization is a queued optimization, not a v0 requirement.

### Simple cases → simple patterns

For straightforward decisions, Snowflake favors simple patterns over mapping tables on performance grounds:

> "The advantage of simple policies like this is that there is a negligible performance cost for Snowflake to evaluate these policies to return query results compared to using row access policies with mapping tables."
> — [Use row access policies](https://docs.snowflake.com/en/user-guide/security-row-using)

A single-rule Tessera `byIdentity` policy lowers to one of these simple patterns. Complexity by itself is not a reason to reach for `byDataset`.

### `byDataset` shape on Snowflake

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

## When to use which selector

| Want to express | Selector |
|---|---|
| "this specific table / specific group" | `byIdentity` |
| "anything tagged PII / Confidential" | `byClassification` |
| "membership determined by a join against an ACL table" | `byDataset` (data-driven entitlement; see § Snowflake authoring guidance) |
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
| `snowflake-byDataset-row-visibility-*` | The Snowflake mapping-table pattern for data-driven entitlement, end to end |

Each carries a `.diagnostic.md` that records findings, gaps, and platform-specific behaviors.

## What's not in v0

- **Tokenize / Bucketize parameter shapes.** The types exist; the parameter schemas are deferred to v1.
- **A formal "preferred algorithm" annotation** for cross-policy combination. Tessera doesn't pick; the adapter declares platform behavior (ADR-023, γ-with-refinement).
- **A DSL.** Deferred per ADR-006 until the IR is stable through real corpus exposure.
- **Two-axis attribute matching** (table-level via `WHEN` + column-level via `MATCH COLUMNS`). v1 candidate, issue #12.
- **Match-modifier declarations on `PrincipalSetFromTable`** (case-insensitive match, whitespace normalization). v1 candidate, surfaced by the Databricks ACL exercise.

If you're authoring something that hits one of these gaps, surface it; the v0-suspended-immutability framing (ADR-017) means v0 admits additions while no external consumer exists.
