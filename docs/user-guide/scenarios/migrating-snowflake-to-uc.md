# Migration scenario — Snowflake → Unity Catalog via Tessera IR

This walkthrough takes three policies actually running on Snowflake — a role-based row-access policy, a mapping-table byDataset row-access policy, and a column masking policy — discovers them, extracts them into Tessera IR, emits equivalent Databricks DDL, deploys the DDL on Unity Catalog, and verifies behavioral equivalence. End to end, in one runnable script.

It is the answer to the question that motivated the project: *can the same governance intent enforce identically on two platforms, with the Tessera IR as the portable pivot?* For the three policy shapes here the answer is yes, with caveats this document calls out honestly.

---

## What's deployed on Snowflake before we start

Three policies on `BRICETEST.TESSERA`, deployed during the earlier worked exercises:

| Policy | Shape | Attached to | Body summary |
|---|---|---|---|
| `GROUP_ROW_VISIBILITY_POLICY_A_RAP` | Role-based row-access policy with multi-branch CASE | `SNOW_ORDERS.O_ORDERPRIORITY` | `IS_ROLE_IN_SESSION('ALL_PRIORITY_OPS') OR (IS_ROLE_IN_SESSION('HIGH_PRIORITY_OPS') AND o_orderpriority IN ('1-URGENT','2-HIGH')) OR (IS_ROLE_IN_SESSION('PUBLIC') AND o_orderpriority IN ('3-MEDIUM','4-NOT SPECIFIED','5-LOW'))` |
| `SNOWFLAKE_BYDATASET_ROW_VISIBILITY_RAP` | Mapping-table byDataset row-access policy | `SNOW_ORDERS_RLS_ACL.O_ORDERPRIORITY` | `EXISTS (SELECT 1 FROM RLS_ACL_MAPPING m JOIN RLS_PRIORITY_ACL p ON m.CODE_NAME = p.CODE_NAME WHERE m.USERNAME = CURRENT_USER() AND p.O_ORDERPRIORITY = <param>)` |
| `COLUMN_MASK_ORDERS_CLERK_MASK` | Role-based masking policy | `SNOW_ORDERS.O_CLERK` | `CASE WHEN IS_ROLE_IN_SESSION('BG_RLS_DEMO_HIGH_PRIORITY_OPS') THEN O_CLERK ELSE 'CLERK-REDACTED' END` |

Together they cover three distinct enforcement patterns. The migration has to handle all three.

---

## The five phases

The runnable script lives at `adapters/tests/live_snowflake_to_uc_migration.py`. Each phase is a step in the migration cycle.

### Phase 1 — Discover

```python
sf = SnowflakeAdapter(config=AdapterConfig(extras={
    "discover_database": "BRICETEST",
    "discover_schema":   "TESSERA",
    "snowflake_cursor":  cur,
}))
result = sf.discover()
```

`SnowflakeAdapter.discover()` walks `SHOW ROW ACCESS POLICIES`, `SHOW MASKING POLICIES`, and `INFORMATION_SCHEMA.POLICY_REFERENCES`, gathering each policy's body via `DESCRIBE` and its attachments. The result carries one artifact per policy:

```
• [row_access_policy] BRICETEST.TESSERA.GROUP_ROW_VISIBILITY_POLICY_A_RAP   → SNOW_ORDERS
• [row_access_policy] BRICETEST.TESSERA.SNOWFLAKE_BYDATASET_ROW_VISIBILITY_RAP → SNOW_ORDERS_RLS_ACL
• [masking_policy]    BRICETEST.TESSERA.COLUMN_MASK_ORDERS_CLERK_MASK         → SNOW_ORDERS.O_CLERK
```

### Phase 2 — Extract

```python
for art in result.artifacts:
    extraction = sf.extract(art)
    if extraction.policy:
        validate(extraction.policy)
```

`SnowflakeAdapter.extract(artifact)` lifts each discovered policy into Tessera IR. The extractor is pattern-driven: it recognizes three body shapes (the ones the worked exercises deployed):

- `EXISTS (SELECT 1 FROM <map> m JOIN <acl> p WHERE m.<user_col> = CURRENT_USER() ...)` → `byDataset` row visibility with `exists-in-dataset` condition.
- `IS_ROLE_IN_SESSION('X') OR (IS_ROLE_IN_SESSION('Y') AND <col> IN (...))` → multi-rule `byIdentity` row visibility.
- `CASE WHEN IS_ROLE_IN_SESSION('X') THEN col ELSE 'literal' END` → `byIdentity` column visibility with `Redact` defaultBranch.

Each extracted IR is validated against `spec/v0/schema.json` and `spec/v0/shapes.ttl`. All three pass cleanly with confidence ≥ 0.9.

A real production extractor would parse a SQL AST rather than regex over the body text. The pattern-driven extractor handles the shapes the project has deployed; broader coverage is a follow-up.

### Phase 3 — Emit

```python
uc = UnityCatalogAdapter(config=AdapterConfig(
    identity_bindings={ "group:bg_rls_demo_high_priority_ops": "bg_rls_demo_high_priority_ops", ... },
    resource_bindings={
        "table:BRICETEST.TESSERA.SNOW_ORDERS":            "bg_rls_demo.tpch.orders",
        "table:BRICETEST.TESSERA.SNOW_ORDERS_RLS_ACL":    "bg_rls_demo.tpch.orders_rls_acl",
        "column:BRICETEST.TESSERA.SNOW_ORDERS.o_clerk":   "bg_rls_demo.tpch.orders.o_clerk",
        "table:BRICETEST.TESSERA.RLS_ACL_MAPPING":        "bg_rls_demo.tpch.rls_acl_mapping",
        "table:BRICETEST.TESSERA.RLS_PRIORITY_ACL":       "bg_rls_demo.tpch.rls_priority_acl",
    },
))
for policy in extracted:
    uc_result = uc.emit(policy)
```

The Tessera IR is platform-neutral. The Unity Catalog adapter lowers it to Databricks DDL: row-filter UDFs + `ALTER TABLE ... SET ROW FILTER`, column-mask UDFs + `ALTER TABLE ... ALTER COLUMN ... SET MASK`. Identity and resource bindings translate Snowflake-side identifiers to their Databricks-side counterparts.

**Resource bindings cover both protected tables and data tables referenced inside policy bodies.** The byDataset policy's body reaches into the ACL mapping tables; those references get remapped via `resource_bindings` too (the IR carries the source-platform table name as data, the adapter looks up the binding via `table:<raw>` key). Without this, the emitted DDL would reference `BRICETEST.TESSERA.RLS_ACL_MAPPING` — a table Databricks can't see.

### Phase 4 — Deploy

The script provisions the data side of the migration alongside the policy DDL:

- The protected tables (`bg_rls_demo.tpch.orders`, `bg_rls_demo.tpch.orders_rls_acl`) are created from the Databricks TPC-H samples if absent.
- The ACL mapping data (`rls_acl_mapping`, `rls_priority_acl`) is created and seeded — the byDataset policy's body needs this data to exist on the target platform, not just on the source.
- Any existing row filter / column mask on the targets is dropped (idempotent re-run).
- The migrated DDL is applied via the Databricks SDK's Statement Execution API.

All three policies apply cleanly:

```
OK: CREATE OR REPLACE FUNCTION bg_rls_demo.tpch.orders__extracted_group_row_visibility_policy_a_filter(...)
OK: ALTER TABLE bg_rls_demo.tpch.orders SET ROW FILTER ...
OK: CREATE OR REPLACE FUNCTION bg_rls_demo.tpch.tessera__extracted_snowflake_bydataset_row_visibility__row_filter(...)
OK: ALTER TABLE bg_rls_demo.tpch.orders_rls_acl SET ROW FILTER ...
OK: CREATE OR REPLACE FUNCTION bg_rls_demo.tpch.tessera__extracted_column_mask_orders_clerk__mask(...)
OK: GRANT EXECUTE ON FUNCTION ... TO `account users`
OK: ALTER TABLE bg_rls_demo.tpch.orders ALTER COLUMN o_clerk SET MASK ...
```

### Phase 5 — Verify

The caller (`brice.giesbrecht@databricks.com`) has membership probe `[all_priority_ops=false, high_priority_ops=false, account_users=true]`. The ACL seed data maps this user to codenames `urgent_priority_ops` + `high_priority_ops`, which themselves map to priorities `1-URGENT` + `2-HIGH`.

| Probe | Result | Why |
|---|---|---|
| `SELECT o_orderpriority, COUNT(*) FROM orders GROUP BY 1` | 4,499,708 rows; priorities 3-MEDIUM / 4-NOT SPECIFIED / 5-LOW only | Multi-rule policy's third branch fires (caller is in `account users` only) |
| `SELECT o_orderpriority, COUNT(*) FROM orders_rls_acl GROUP BY 1` | 3,000,292 rows; priorities 1-URGENT (1,501,100) + 2-HIGH (1,499,192) | byDataset policy resolves the ACL chain: user → codenames → priorities |
| `SELECT DISTINCT o_clerk FROM orders LIMIT 5` | `CLERK-REDACTED` (single distinct value) | Mask applies because caller is not in `bg_rls_demo_high_priority_ops` |

All three policies enforce as their Snowflake-side originals would. The migration is behaviorally equivalent within the IR's scope.

---

## What the exercise surfaced

Two real findings landed as adapter improvements during this exercise:

### Resource bindings cover data tables, not just protected tables

The `byDataset` policy's body joins two ACL tables that aren't the protected table. The IR's `PrincipalSetFromTable.table` and `ResourceSetFromTable.table` are data references; they need remapping during migration just as much as the protected-table reference does.

The fix: the UC `byDataset` emission now consults `config.bind_resource(f"table:{raw}")` for these data-table references, falling back to the raw IR value if no binding exists. Migration tooling supplies the bindings; the adapter does the remap. No IR change required.

### Parameter naming collision in the row-filter UDF body

The byDataset emission initially named the function parameter after the IR's `resourceColumn` field — `O_ORDERPRIORITY` in this case. SQL is case-insensitive on identifiers, so the predicate `p.o_orderpriority = O_ORDERPRIORITY` inside the EXISTS subquery is ambiguous: Databricks resolves the bare identifier to the column reference (`p.o_orderpriority`), the predicate degenerates to `col = col`, and the row filter passes everything.

First deployment of the migration script showed all 7,500,000 rows visible — a hint the filter wasn't filtering. The fix is the same one the Snowflake adapter already had: pin a fixed parameter alias (`policy_input_value`) that doesn't collide with any column referenced in the body. The column-to-parameter bind happens positionally via `ALTER TABLE ... SET ROW FILTER ... ON (col)`.

Both findings landed as commits during this exercise — the cycle of *exercise drives improvement* working as the project's discipline intends.

---

## What the exercise does NOT cover

This is a worked migration of three policies, not a complete migration tooling story. Several real concerns sit outside scope:

- **Data migration.** The script provisions the ACL data on Databricks; a real migration would extract the data from Snowflake (`CREATE TABLE ... AS SELECT * FROM remote_snowflake_table` via a federation source, or an ETL pipeline). The Tessera IR doesn't model the data migration step; it carries the policy intent and the table references.
- **Identity migration.** Snowflake roles (`BG_RLS_DEMO_HIGH_PRIORITY_OPS`) and Databricks groups (`bg_rls_demo_high_priority_ops`) are not auto-provisioned. The script assumes the groups already exist on Databricks (they were created in earlier worked exercises). A real migration would inventory Snowflake roles, provision equivalent Databricks groups, and populate the bindings.
- **Schema migration.** This exercise reuses TPC-H sample tables on both platforms. A real migration would mirror the source schemas onto the target.
- **Reconciliation.** The adapter contract includes a `reconcile()` method (still stubbed); a real production cycle would compare deployed state to the IR and flag drift. This exercise applies in one direction without reconciliation.
- **Cross-platform extraction shapes.** The Snowflake extractor recognizes three body shapes — the ones the project's worked exercises deployed. Production extraction would need a SQL AST parser and broader pattern coverage.
- **Audit trail.** Each step is logged; a real cycle would emit structured logs for compliance review. The script's output goes to stdout.

What this exercise *does* demonstrate is that the **IR pivot works**: a Snowflake policy can be lifted into Tessera IR, that IR validates cleanly, and the same IR produces working Databricks DDL. The promise of the framework is empirically validated for these shapes.

---

## Running it yourself

```bash
# From the tessera repo root:
.venv/bin/python -m adapters.tests.live_snowflake_to_uc_migration
```

Prereqs:
- `pip install` already covers it (`databricks-sdk`, `snowflake-connector-python`, `ruamel.yaml`, the validators).
- A `~/snowflake_auth.txt` file with the Snowflake password (the file is local-only; never committed).
- A Databricks SDK profile that resolves to a workspace with `bg_rls_demo` provisioned (or change the constants at the top of the script).

The script is idempotent — re-running it drops existing attachments before re-applying the new DDL. Useful for exercising the adapter when emission paths or extraction heuristics change.

---

## Pointers

- **Adapter code**: `adapters/snowflake/discovery.py` (discover + extract), `adapters/unity_catalog/emission.py` (`_emit_row_visibility_by_dataset` and the column-mask helpers).
- **The worked-example shapes the extractor recognizes**: `spec/v0/examples/group-row-visibility-policy-a.tessera.yaml`, `spec/v0/examples/snowflake-byDataset-row-visibility-policy.tessera.yaml`, `spec/v0/examples/column-mask-orders-clerk-policy.tessera.yaml`.
- **The Databricks-target DDL the extractor produces**: the hand-derived companions in `spec/v0/examples/*.databricks.sql`; the adapter-emitted output matches structurally (modulo function names and the parameter-alias fix described above).
- **Adapter contract**: ADR-024 in `DECISIONS.md`.
- **Adapter configuration mapping pattern**: ADR-021 — including `identity_bindings` and `resource_bindings`.
- **The companion practitioner tutorial**: `docs/user-guide/scenarios/acl-and-masking.md` covers authoring the same shapes from scratch, rather than migrating them.
