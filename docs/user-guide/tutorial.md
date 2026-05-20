# Tutorial — Tessera end to end

This tutorial walks through a single policy from authoring to deployment on both Databricks and Snowflake. The artifacts produced here exist in the repo as completed exercises; you can follow along by reading them, or rerun the live scripts against your own platforms.

**What you'll do, in order:**
1. Understand the policy intent in plain English.
2. Write the policy in `.tessera.yaml`.
3. Convert to the canonical JSON-LD form via the converter (`python -m tools.converter ...`).
4. Validate against the JSON Schema and SHACL shapes.
5. Configure an adapter (identity bindings, resource bindings).
6. Emit DDL through the adapter.
7. Deploy and verify on the target platform.
8. Repeat 5–7 for the second target platform.

The policy used throughout is **group-driven row visibility on a TPC-H orders table**: members of one group see everything, members of another group see only urgent/high-priority orders, everyone else sees only routine-priority orders.

This is the `group-row-visibility-policy-a` worked example. All file paths in this tutorial are relative to the repo root.

---

## 1. Policy intent

Plain English, no platform vocabulary:

> Members of `bg_rls_demo_all_priority_ops` see all order rows. Members of `bg_rls_demo_high_priority_ops` see only orders with priority `1-URGENT` or `2-HIGH`. Everyone else (the catch-all `account-users` group on Databricks; `PUBLIC` on Snowflake) sees only orders with priority `3-MEDIUM`, `4-NOT SPECIFIED`, or `5-LOW`. A user belonging to none of these groups sees nothing.

The IR's job is to express this intent **once**, in a form that lowers to platform-native enforcement on Databricks (a row filter on the table) and on Snowflake (a row-access policy on the table). The platforms don't need to know each other's vocabulary; the adapter does the translation.

---

## 2. Authoring — the `.tessera.yaml`

Open `spec/v0/examples/group-row-visibility-policy-a.tessera.yaml`. The structure:

```yaml
policy:
  id: group-row-visibility-policy-a
  version: 1.0.0
  kind: RowVisibilityConstraint           # The policy gates row visibility, not column values

  appliesTo:                              # Which resource the policy is attached to
    selector: byIdentity
    resource: table:bg_rls_demo.tpch.orders

  action: Read                            # The action being governed (Read, Write, Delete, …)

  defaultStrategy: explicit-baseline-group # What happens to principals matching no rule

  rules:
    - principal:                          # Who this rule applies to
        selector: byIdentity
        resource: group:bg_rls_demo_all_priority_ops
      effect: keep-matching-rows          # No condition ⇒ keep all rows for this principal

    - principal:
        selector: byIdentity
        resource: group:bg_rls_demo_high_priority_ops
      condition:
        op: in
        operands: [column:bg_rls_demo.tpch.orders.o_orderpriority]
        values: ['1-URGENT', '2-HIGH']
      effect: keep-matching-rows

    - principal:
        selector: byIdentity
        resource: group:account-users
      condition:
        op: in
        operands: [column:bg_rls_demo.tpch.orders.o_orderpriority]
        values: ['3-MEDIUM', '4-NOT SPECIFIED', '5-LOW']
      effect: keep-matching-rows
```

**Key shapes:**

- **`Policy` container** — one top-level shape carrying metadata (`appliesTo`, `action`, `defaultStrategy`) plus an ordered `rules` list. See ADR-014.
- **Ordered first-match combining** — rules evaluate top-to-bottom; the first matching rule wins (ADR-015). If no rule matches, `defaultStrategy` controls the fallback.
- **`byIdentity` selectors** — both for the resource (`table:...`) and for principals (`group:...`). The IR uses platform-neutral IRIs; the adapter resolves them.
- **`in` condition** — single-operand membership test against a fixed list of values. Other operators: `eq`, `lt`, `gt`, `purpose-in`, `located-in`, `time-window`, `consent-granted`, `exists-in-dataset`.

For the full authoring vocabulary, see [`authoring.md`](./authoring.md).

---

## 3. Mental model — JSON-LD canonical form

YAML is what you write; JSON-LD is what the system reasons over. The conversion is mechanical (mapping keys, expanding short names to IRIs via the spec's `context.jsonld`). A v1 converter handles this — `python -m tools.converter <file.tessera.yaml> --out <file.jsonld>` or the library function `tools.converter.yaml_to_jsonld()`. Comment preservation in YAML round-trips and JSON-LD → YAML are deferred to v2.

For now, the JSON-LD is hand-maintained alongside the YAML. Look at `spec/v0/examples/group-row-visibility-policy-a.jsonld` for the canonical form of the policy above. The shape is similar; the IRIs are explicit and the `@context` line at the top declares the vocabulary namespace.

You'll generally do all your reading and writing in YAML. The validators and adapters consume the JSON-LD.

---

## 4. Validation

Two layers, in order:

### 4a. JSON Schema — structural validation

```python
import json, jsonschema
schema = json.loads(open('spec/v0/schema.json').read())
doc = json.loads(open('spec/v0/examples/group-row-visibility-policy-a.jsonld').read())
jsonschema.validate(doc, schema)   # raises ValidationError on structural issues
```

The schema enforces:
- Required fields per policy kind.
- Conditional dependencies (e.g., `baselineGroup` is required iff `defaultStrategy: explicit-baseline-group`; `transformation` is required iff `effect: transform`).
- Enum-valued fields (action, selector kind, effect, condition operator).
- Type structure of nested objects.

If the schema reports clean, the JSON-LD is structurally well-formed.

### 4b. SHACL shapes — semantic validation

```python
from rdflib import Graph
from pyshacl import validate
shapes = Graph(); shapes.parse('spec/v0/shapes.ttl', format='turtle')
onto = Graph(); onto.parse('spec/v0/ontology.ttl', format='turtle')
data = Graph(); data.parse('spec/v0/examples/group-row-visibility-policy-a.jsonld', format='json-ld')
conforms, _, msg = validate(data, shacl_graph=shapes, ont_graph=onto, inference='none')
```

SHACL covers what JSON Schema cannot:
- Closed vocabulary checks against IRI values (axis references resolve to known `AttributeAxis` instances; classifications resolve to known classifications).
- Node-shape composition via `sh:node` (since JSON-LD doesn't assert `@type` on blank nodes).
- Type-aware value checking that the schema's enum machinery can't express.

Both layers should pass before you hand a policy to an adapter.

---

## 5. Adapter configuration

The adapter takes the platform-neutral IR and lowers it to platform-native DDL. To do that, it needs to know how Tessera's IRIs map to your platform's identifiers. This is configuration, not policy content.

```python
from adapters.contract.types import AdapterConfig

config = AdapterConfig(
    identity_bindings={
        # IR PrincipalRef IRI → platform principal identifier
        'group:bg_rls_demo_all_priority_ops': 'bg_rls_demo_all_priority_ops',
        'group:bg_rls_demo_high_priority_ops': 'bg_rls_demo_high_priority_ops',
        'group:account-users': 'account users',
    },
    resource_bindings={
        # IR ResourceRef IRI → platform-qualified table identifier
        'table:bg_rls_demo.tpch.orders': 'bg_rls_demo.tpch.orders',
    },
)
```

The same IR can target different platforms by swapping the config — same `identity_bindings` keys (the IRIs), different values (the platform identifiers). See [`operating.md`](./operating.md) for the full configuration surface (including `tag_taxonomy` for ABAC).

---

## 6. Emission — Databricks

```python
import json
from adapters.unity_catalog import UnityCatalogAdapter

policy = json.loads(open('spec/v0/examples/group-row-visibility-policy-a.jsonld').read())
result = UnityCatalogAdapter(config=config).emit(policy)

for d in result.diagnostics:
    print(f"[{d.severity.value}] {d.code}: {d.message}")
for stmt in result.statements:
    print(stmt)
```

For this policy, the adapter emits:

```sql
CREATE OR REPLACE FUNCTION bg_rls_demo.tpch.orders__group_row_visibility_policy_a_filter(
  o_orderpriority STRING
) RETURNS BOOLEAN
RETURN
        is_account_group_member('bg_rls_demo_all_priority_ops')
        OR (is_account_group_member('bg_rls_demo_high_priority_ops')
            AND o_orderpriority IN ('1-URGENT', '2-HIGH'))
        OR (is_account_group_member('account users')
            AND o_orderpriority IN ('3-MEDIUM', '4-NOT SPECIFIED', '5-LOW'));

ALTER TABLE bg_rls_demo.tpch.orders
  SET ROW FILTER bg_rls_demo.tpch.orders__group_row_visibility_policy_a_filter
  ON (o_orderpriority);
```

The adapter never executes. The `result.statements` is a list of DDL; running them is the caller's responsibility. The full runnable script is `adapters/tests/live_databricks.py`.

**Deployment on Databricks via the SDK:**

```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

w = WorkspaceClient(profile='your-profile')
for stmt in result.statements:
    r = w.statement_execution.execute_statement(
        warehouse_id='your-warehouse-id', statement=stmt, wait_timeout='30s',
    )
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        r = w.statement_execution.get_statement(r.statement_id)
    assert r.status.state == StatementState.SUCCEEDED, r.status.error
```

**Verification.** After deployment, query the table as different users and confirm the row counts match the policy intent. On the live test we ran (`adapters/tests/live_databricks.py`), the caller was a member of `account users` only; they saw 4,499,708 rows (priorities 3, 4, 5 — the third branch of the policy).

---

## 7. Emission — Snowflake

Swap the adapter and the config. The IR is unchanged.

```python
from adapters.snowflake import SnowflakeAdapter

snowflake_config = AdapterConfig(
    identity_bindings={
        'group:bg_rls_demo_all_priority_ops': 'BG_RLS_DEMO_ALL_PRIORITY_OPS',
        'group:bg_rls_demo_high_priority_ops': 'BG_RLS_DEMO_HIGH_PRIORITY_OPS',
        'group:account-users': 'PUBLIC',
    },
    resource_bindings={
        'table:bg_rls_demo.tpch.orders': 'BRICETEST.TESSERA.SNOW_ORDERS',
    },
)
result = SnowflakeAdapter(config=snowflake_config).emit(policy)
```

The Snowflake adapter emits:

```sql
CREATE OR REPLACE ROW ACCESS POLICY BRICETEST.TESSERA.group_row_visibility_policy_a_rap
AS (o_orderpriority VARCHAR) RETURNS BOOLEAN ->
        IS_ROLE_IN_SESSION('BG_RLS_DEMO_ALL_PRIORITY_OPS')
        OR (IS_ROLE_IN_SESSION('BG_RLS_DEMO_HIGH_PRIORITY_OPS')
            AND o_orderpriority IN ('1-URGENT', '2-HIGH'))
        OR (IS_ROLE_IN_SESSION('PUBLIC')
            AND o_orderpriority IN ('3-MEDIUM', '4-NOT SPECIFIED', '5-LOW'));

ALTER TABLE BRICETEST.TESSERA.SNOW_ORDERS
  ADD ROW ACCESS POLICY BRICETEST.TESSERA.group_row_visibility_policy_a_rap
  ON (o_orderpriority);
```

Same IR; platform-divergent DDL. Note the differences:
- `is_account_group_member` → `IS_ROLE_IN_SESSION` — Databricks groups, Snowflake roles.
- `SET ROW FILTER` → `ADD ROW ACCESS POLICY` — different DDL primitives for the same concept.
- Table identifier resolved through `resource_bindings` to a Snowflake-qualified name.

**The Snowflake authoring intent question** that this policy hits: `IS_ROLE_IN_SESSION` is what [Snowflake recommends](https://docs.snowflake.com/en/user-guide/security-row-using) for role-discrimination policies — "If role activation and role hierarchy are important, Snowflake recommends that the policy conditions use the IS_ROLE_IN_SESSION function..." With `DEFAULT_SECONDARY_ROLES = ('ALL')` (Snowflake's default since 2024 per BCR-1692), every granted role is session-active, so the predicate sees them all. This is consistent with `IS_ROLE_IN_SESSION`'s permission-scope semantics, not a defeat of them. If your policy is actually doing data-driven entitlement rather than role discrimination, see § 8 below for the `byDataset` pattern. [`operating.md`](./operating.md) covers the operator-side configuration question in detail.

**Deployment on Snowflake via the connector:**

```python
import snowflake.connector
conn = snowflake.connector.connect(
    account='YOUR_ACCOUNT', user='YOUR_USER', password='...',
    warehouse='COMPUTE_WH', database='BRICETEST', schema='TESSERA',
)
cur = conn.cursor()
for stmt in result.statements:
    cur.execute(stmt)
```

**Verification.** The live test (`adapters/tests/live_snowflake.py`) verifies the four role configurations and confirms `IS_ROLE_IN_SESSION`'s hierarchical behavior — see [`operating.md`](./operating.md).

---

## 8. Data-driven entitlement on Snowflake — `byDataset`

When the policy decision is "which rows is *this user* assigned to" rather than "does this user have role X," the right Tessera selector is `byDataset` (Snowflake side) and `PrincipalSetFromTable` (the principal set is computed from a join, not enumerated as role names). [Snowflake documents this as the mapping-table pattern](https://docs.snowflake.com/en/user-guide/security-row-using): the policy body gates on `CURRENT_USER()` against an authorization table, which is orthogonal to role activation. (Note Snowflake's performance caveat in the same doc: "using mapping tables may result in decreased performance compared to the more simple example.")

Tessera's `byDataset` selector with `PrincipalSetFromTable` IS that pattern. The IR is identical to the custom-ACL pattern from the `acl-row-visibility` exercise:

```yaml
rules:
  - principal:
      selector: byDataset
      dataset:
        type: PrincipalSetFromTable
        table: BRICETEST.TESSERA.RLS_ACL_MAPPING
        principalColumn: USERNAME
        resourceColumn: CODE_NAME
    condition:
      op: exists-in-dataset
      operands:
        - type: ResourceSetFromTable
          table: BRICETEST.TESSERA.RLS_PRIORITY_ACL
          principalColumn: CODE_NAME
          resourceColumn: O_ORDERPRIORITY
    effect: keep-matching-rows
```

The Snowflake adapter lowers this to:

```sql
CREATE OR REPLACE ROW ACCESS POLICY ...
AS (POLICY_INPUT_VALUE VARCHAR) RETURNS BOOLEAN ->
        EXISTS (
            SELECT 1
            FROM BRICETEST.TESSERA.RLS_ACL_MAPPING m
            JOIN BRICETEST.TESSERA.RLS_PRIORITY_ACL p
              ON m.CODE_NAME = p.CODE_NAME
            WHERE m.USERNAME = CURRENT_USER()
              AND p.O_ORDERPRIORITY = POLICY_INPUT_VALUE
        );
```

**This pattern was empirically verified** on 2026-05-19 against `BRICETEST.TESSERA`. The full exercise (Phase 1 brief, Phase 2 IR + adapter emission, Phase 3 live verification) is at `docs/exercises/snowflake-byDataset-row-visibility-inputs.md` and `spec/v0/examples/snowflake-byDataset-row-visibility.diagnostic.md`. The key verification: row counts under `USE SECONDARY ROLES NONE` and `USE SECONDARY ROLES ALL` are identical, because `CURRENT_USER()` ignores role activation. See [`authoring.md`](./authoring.md) for when to use `byDataset` vs `byIdentity`.

---

## 9. Where to go from here

- **More authoring patterns** — `byClassification`, `byScope` for ABAC, `byComposition` for predicate algebra. [`authoring.md`](./authoring.md).
- **Per-platform operator playbooks** — Snowflake `DEFAULT_SECONDARY_ROLES`, Databricks group propagation lag, capability-profile interpretation. [`operating.md`](./operating.md).
- **The worked-example library** — `spec/v0/examples/` holds seven completed exercises, each with a `.tessera.yaml`, `.jsonld`, `.databricks.sql` or `.snowflake.sql`, and a `.diagnostic.md` explaining findings.
- **Decision rationale** — `DECISIONS.md` has all the ADRs. ADRs 013–024 cover the core IR shapes (Policy container, ABAC, adapter contract).
- **Spec reference** — `docs/technical-design-v0.2.md` is the authoritative spec; the user guide explains how to use it; the technical design explains what it is.
