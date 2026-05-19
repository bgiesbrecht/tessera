# Diagnostic — Snowflake `byDataset` Row-Visibility Exercise

**Phase 2 + Phase 3 deliverable.** Verifies that the IR's `byDataset` selector + `PrincipalSetFromTable` class lower to a Snowflake row-access policy whose body is a correlated `EXISTS` over two ACL tables. Companion to `docs/exercises/snowflake-byDataset-row-visibility-inputs.md`.

## 1. Per-element enforcement

| IR element | Lowered to | Platform fidelity |
|---|---|---|
| `policyKind: RowVisibilityConstraint` | `CREATE ROW ACCESS POLICY ... AS (col VARCHAR) RETURNS BOOLEAN -> ...` | Exact |
| `appliesTo: {selector: byIdentity, resource: table:...}` | `ALTER TABLE <table> ADD ROW ACCESS POLICY ... ON (col)` | Exact |
| `defaultStrategy: none` | No fallback clause in the policy body; rows hidden by default for non-matching users | Exact (Snowflake row-access policy evaluates to FALSE → row hidden) |
| `rules[0].principal: {selector: byDataset, dataset: PrincipalSetFromTable}` | `EXISTS (SELECT 1 FROM <mapping_table> m WHERE m.<principal_col> = CURRENT_USER() ...)` | Exact (the `principal_col` is the IR's `principalColumn` field) |
| `rules[0].condition: {op: exists-in-dataset, operands: [ResourceSetFromTable]}` | `JOIN <resource_acl_table> p ON m.<resource_col> = p.<principal_col> AND p.<resource_col> = POLICY_INPUT_VALUE` | Exact, with one IR finding (§3) |
| `rules[0].effect: keep-matching-rows` | Policy body returns TRUE for matching rows | Exact |

## 2. Behavioral verification (Phase 3)

Live execution against `BRICETEST.TESSERA.SNOW_ORDERS_RLS_ACL` (1.5M rows from TPC-H), as user `BGIESBRECHT`:

| Scenario | Setup | Expected | Observed | Pass |
|---|---|---|---|---|
| 1 | Seed: `BGIESBRECHT` ∈ {`urgent_priority_ops`, `high_priority_ops`} | Sees `1-URGENT`, `2-HIGH` only | 600,434 rows; 1-URGENT: 300,343 + 2-HIGH: 300,091 | ✅ |
| 2 | Add `('BGIESBRECHT', 'standard_ops')` to mapping | Sees all five priorities | 1,500,000 rows across all five | ✅ |
| 3 | Remove all `BGIESBRECHT` mapping rows | Sees zero rows | 0 rows | ✅ |
| 4a | Seed restored; `USE SECONDARY ROLES NONE` | Sees 1-URGENT + 2-HIGH | 600,434 rows | ✅ |
| 4b | Seed restored; `USE SECONDARY ROLES ALL` | Identical to 4a (secondary-roles immune) | 600,434 rows | ✅ |

**Scenario 4 is the key empirical claim**: the same protected table, same user, same seed data — row counts identical across `USE SECONDARY ROLES NONE` and `ALL`. The byDataset pattern gates on `CURRENT_USER()`, which is unaffected by `DEFAULT_SECONDARY_ROLES` or `USE SECONDARY ROLES`. This is the structural reason Snowflake's documentation recommends mapping-table authorization for non-trivial row-access policies, and the reason Tessera's `byDataset` selector aligns with that recommendation.

## 3. v0 IR finding — `resourceColumn` is conflated

The IR's `ResourceSetFromTable.resourceColumn` field carries one identifier that must serve two distinct roles:

1. The column name on the **ACL table** that the `EXISTS` subquery reads (`p.<resourceColumn>`).
2. The column name on the **protected table** that the `ALTER TABLE ... ON (<col>)` clause binds to the policy parameter.

These two columns are *usually* the same name by convention (the ACL mirrors the protected table's column), but the IR has no formal mechanism requiring or expressing this alignment. The exercise's seed data initially used `ORDERPRIORITY` for the ACL column and `O_ORDERPRIORITY` for the protected column — distinct names — which caused the emitted `ALTER TABLE ... ON (ORDERPRIORITY)` clause to fail with `invalid identifier 'ORDERPRIORITY'`. The exercise resolved this by renaming the ACL column to match the protected column (`O_ORDERPRIORITY`).

**Disposition.** v1 candidate. The IR should either:

- Split `resourceColumn` into `aclColumn` (the ACL table's column) + `boundColumn` (the protected table's column), OR
- Add an explicit `boundColumn` field on the policy or `appliesTo` clause naming the column the row-access policy attaches to.

The Databricks ACL exercise had the same latent gap; it manifested only as adapter emission needing to *know* the column name, which the worked-example artifact baked in by convention. The Snowflake exercise made the gap visible because the platform validates the ON-clause column at policy creation. File as a new issue alongside the existing v1 candidates from the Databricks ACL exercise (#7–#11).

## 4. Other findings

**4.1 — Parameter-name collision.** The emitted row-access policy parameter is named `POLICY_INPUT_VALUE` rather than a column-derived name. This is required to avoid Snowflake resolving a bare identifier in the policy body to a column reference instead of the parameter, which would degenerate the predicate to `col = col` (always TRUE). The adapter's implementation pins this name; if Snowflake ever changes its identifier-resolution rules, the implementation continues to work because the alias is decoupled from any column name.

**4.2 — Capability profile update.** The Snowflake adapter's `DATASET_DRIVEN_PRINCIPALS` capability moves from `PARTIAL` to `PARTIAL (RowVisibility supported; ColumnVisibility still pending)` with a sharper rationale. The capability profile is updated in `adapters/snowflake/capability.py`.

**4.3 — No identity-binding required.** Unlike the role-based parity test (`live_snowflake.py`), this exercise required no `identity_bindings` entries in `AdapterConfig`. The principal binding comes from the ACL data itself (`'BGIESBRECHT'` in `RLS_ACL_MAPPING.USERNAME`), not from the IR's `principal:` IRIs. This is part of what makes the byDataset pattern operationally simpler — role taxonomy changes update the ACL table, not the policy DDL.

**4.4 — Failure modes confirmed.** Empty ACL mapping (scenario 3) produces zero rows. The `EXISTS` clause is fail-closed by construction; no implicit `ELSE` branch exists in the policy body. ACL table unavailability would produce the same fail-closed behavior (subquery cannot evaluate ⇒ predicate FALSE ⇒ row hidden), though this exercise did not test the unavailable-table case.

## 5. Cross-platform comparison

Same IR (`spec/v0/examples/snowflake-byDataset-row-visibility-policy.jsonld` ↔ `spec/v0/examples/acl-row-visibility-policy.jsonld`); divergent platform DDL:

| Aspect | Databricks (acl-row-visibility) | Snowflake (this exercise) |
|---|---|---|
| Policy primitive | UDF + row filter attach | Row-access policy + table attach |
| DDL form | `CREATE FUNCTION ... AS FILTER ... ; ALTER TABLE ... SET ROW FILTER ... ON (col)` | `CREATE ROW ACCESS POLICY ... -> ...; ALTER TABLE ... ADD ROW ACCESS POLICY ... ON (col)` |
| Principal function | `current_user()` (email) | `CURRENT_USER()` (login name) |
| Case sensitivity | Adapter emits `lower(trim(...))` normalization (per Databricks ACL exercise) | Relies on Snowflake's identifier folding (uppercase by default) |
| ACL column-name convention | Diverges between ACL (`orderpriority`) and protected (`o_orderpriority`); adapter handles | Required to align (`O_ORDERPRIORITY` in both) for emission to succeed |
| Secondary-roles / multi-role gotcha | N/A (Databricks groups are flat) | Immune by design — `CURRENT_USER()` ignores role activation |

The structural alignment of `byDataset` + `PrincipalSetFromTable` with Snowflake's recommended mapping-table pattern is now empirically validated, not merely argued.

## 6. What this exercise does NOT cover

- **ColumnVisibility via `byDataset`.** Out of scope; the Snowflake adapter still warns `UNIMPLEMENTED_POLICY_KIND` for `ColumnVisibilityConstraint`.
- **ABAC + `byDataset`.** Untested combination.
- **Multi-policy stacking.** Snowflake permits multiple row-access policies on a table; ADR-023's γ-with-refinement framing has been validated on Databricks but not yet on Snowflake.
- **Permission column.** The IR's `byDataset` selector supports an optional `permissionColumn` + `permissionValue`; this exercise used implicit-read semantics. The permission-column variant has not been emitted on Snowflake.

These are follow-up exercise candidates if needed.

## 7. Disposition

- **Adapter implementation:** `adapters/snowflake/emission.py` now handles `byDataset` row-visibility. Other policyKinds remain stubbed.
- **IR finding:** `resourceColumn` conflation logged as a v1 candidate; not in scope for v0 corrections.
- **User documentation:** Phase 3 verification grounds the recommendation that `byDataset` + mapping-table is the Tessera-author-preferred Snowflake pattern for non-trivial row-access policies. The user-guide authoring section can present this with empirical backing.
