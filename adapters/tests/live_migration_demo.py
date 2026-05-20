"""Repeatable Snowflake → Unity Catalog migration demo.

Provisions a fresh Snowflake schema, deploys three Tessera policies on it via
the SnowflakeAdapter, then runs the full discover → extract → emit → deploy →
verify cycle against a fresh Databricks schema. End-to-end migration via the
Tessera IR pivot, with both source and target as clean slates so the
demonstration isn't muddied by state from prior exercises.

Run with:
    .venv/bin/python -m adapters.tests.live_migration_demo

Re-runnable: drops and recreates the demo schemas on each invocation.

To tear down (drops both schemas and exits):
    .venv/bin/python -m adapters.tests.live_migration_demo --cleanup

Identifier constants below — adjust if you want to target different account /
catalog names. The three source-policy YAMLs come from `spec/v0/examples/`;
they are Databricks-shaped by default and get rebound via the adapter config
to point at the fresh schemas on each platform.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import snowflake.connector
import jsonschema
from rdflib import Graph
from pyshacl import validate as shacl_validate

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from adapters.contract.types import AdapterConfig, DiagnosticSeverity
from adapters.snowflake import SnowflakeAdapter
from adapters.unity_catalog import UnityCatalogAdapter


# ---------------------------------------------------------------------------
# Identifiers — change here if you want different schemas / accounts / etc.
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "spec" / "v0" / "schema.json"
SHAPES_PATH = REPO_ROOT / "spec" / "v0" / "shapes.ttl"
ONTOLOGY_PATH = REPO_ROOT / "spec" / "v0" / "ontology.ttl"
CONTEXT_PATH = REPO_ROOT / "spec" / "v0" / "context.jsonld"
EXAMPLES = REPO_ROOT / "spec" / "v0" / "examples"
AUTH_PATH = Path.home() / "snowflake_auth.txt"

SNOWFLAKE_ACCOUNT   = "FBGQMMZ-DCC90967"
SNOWFLAKE_USER      = "BGIESBRECHT"
SNOWFLAKE_WAREHOUSE = "COMPUTE_WH"
SNOWFLAKE_DATABASE  = "BRICETEST"
SOURCE_SCHEMA       = "MIGRATION_DEMO"

DATABRICKS_PROFILE  = "adb-984752964297111"
DATABRICKS_WAREHOUSE = "148ccb90800933a1"
TARGET_CATALOG      = "bg_rls_demo"
TARGET_SCHEMA       = "migration_demo"

# Roles / groups used in the demo. These already exist on both platforms from
# prior worked exercises; the demo reuses them rather than provisioning fresh.
ROLE_HIGH_PRIORITY = "BG_RLS_DEMO_HIGH_PRIORITY_OPS"
ROLE_ALL_PRIORITY  = "BG_RLS_DEMO_ALL_PRIORITY_OPS"
GROUP_HIGH_PRIORITY = "bg_rls_demo_high_priority_ops"
GROUP_ALL_PRIORITY  = "bg_rls_demo_all_priority_ops"
GROUP_ACCOUNT_USERS = "account users"

# Caller identity to seed into the byDataset ACL on the target side.
DATABRICKS_USER_EMAIL = "brice.giesbrecht@databricks.com"


# Source policy YAMLs (Databricks-shaped IRs; the adapter bindings remap them
# to fresh schemas on each platform).
SOURCE_POLICIES = [
    EXAMPLES / "group-row-visibility-policy-a.tessera.yaml",
    EXAMPLES / "acl-row-visibility-policy.tessera.yaml",
    EXAMPLES / "column-mask-orders-clerk-policy.tessera.yaml",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fq_sf_table(name: str) -> str:
    return f"{SNOWFLAKE_DATABASE}.{SOURCE_SCHEMA}.{name}"


def fq_uc_table(name: str) -> str:
    return f"{TARGET_CATALOG}.{TARGET_SCHEMA}.{name}"


def section(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}\n")


def step(title: str) -> None:
    print(f"\n--- {title} ---")


def sf_connect():
    pw = AUTH_PATH.read_text().strip()
    conn = snowflake.connector.connect(
        account=SNOWFLAKE_ACCOUNT, user=SNOWFLAKE_USER, password=pw,
        warehouse=SNOWFLAKE_WAREHOUSE, database=SNOWFLAKE_DATABASE,
        role="ACCOUNTADMIN",
    )
    return conn


def db_runner():
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementState
    w = WorkspaceClient(profile=DATABRICKS_PROFILE)

    def run(sql: str, *, ignore_errors: bool = False):
        r = w.statement_execution.execute_statement(
            warehouse_id=DATABRICKS_WAREHOUSE, statement=sql, wait_timeout="30s",
        )
        while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
            r = w.statement_execution.get_statement(r.statement_id)
        if r.status.state != StatementState.SUCCEEDED:
            if ignore_errors:
                return None
            raise RuntimeError(f"SQL failed: {sql[:80]} -> {r.status.error}")
        return r.result.data_array if r.result else None

    return run


# ---------------------------------------------------------------------------
# Phase 1 — Provision Snowflake source schema
# ---------------------------------------------------------------------------

def provision_snowflake_source(cur) -> None:
    section("Phase 1 — Provision Snowflake source schema")

    step(f"Drop & recreate {SNOWFLAKE_DATABASE}.{SOURCE_SCHEMA}")
    cur.execute(f"DROP SCHEMA IF EXISTS {SNOWFLAKE_DATABASE}.{SOURCE_SCHEMA} CASCADE")
    cur.execute(f"CREATE SCHEMA {SNOWFLAKE_DATABASE}.{SOURCE_SCHEMA}")
    cur.execute(f"USE SCHEMA {SNOWFLAKE_DATABASE}.{SOURCE_SCHEMA}")

    step("Create demo tables (sampled from TPC-H)")
    for stmt in [
        f"CREATE TABLE {fq_sf_table('demo_orders')} AS "
        f"  SELECT * FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS SAMPLE (100000 ROWS)",
        # Add an `orderpriority` column (alias of `o_orderpriority`) so the
        # acl-row-visibility YAML's `resourceColumn: orderpriority` finds it
        # on the protected table. Surface of issue #13 (resourceColumn
        # conflation) — the IR field carries both the ACL column name AND
        # the protected column name; the demo aligns them by duplicating.
        f"CREATE TABLE {fq_sf_table('demo_orders_rls_acl')} AS "
        f"  SELECT *, O_ORDERPRIORITY AS orderpriority "
        f"  FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS SAMPLE (100000 ROWS)",
        f"CREATE TABLE {fq_sf_table('demo_rls_acl_mapping')} ("
        f"  USERNAME VARCHAR, CODE_NAME VARCHAR)",
        f"CREATE TABLE {fq_sf_table('demo_rls_priority_acl')} ("
        f"  CODE_NAME VARCHAR, ORDERPRIORITY VARCHAR)",
        f"INSERT INTO {fq_sf_table('demo_rls_priority_acl')} VALUES "
        f"  ('urgent_priority_ops', '1-URGENT'),"
        f"  ('high_priority_ops',   '2-HIGH'),"
        f"  ('standard_ops',        '3-MEDIUM'),"
        f"  ('standard_ops',        '4-NOT SPECIFIED'),"
        f"  ('standard_ops',        '5-LOW')",
        f"INSERT INTO {fq_sf_table('demo_rls_acl_mapping')} VALUES "
        f"  ('{SNOWFLAKE_USER}', 'urgent_priority_ops'),"
        f"  ('{SNOWFLAKE_USER}', 'high_priority_ops')",
    ]:
        cur.execute(stmt)
        print(f"  OK: {stmt[:80]}…")

    step("Grant access to demo roles")
    for role in (ROLE_HIGH_PRIORITY, ROLE_ALL_PRIORITY, "PUBLIC"):
        for stmt in [
            f"GRANT USAGE ON SCHEMA {SNOWFLAKE_DATABASE}.{SOURCE_SCHEMA} TO ROLE {role}",
            f"GRANT SELECT ON ALL TABLES IN SCHEMA {SNOWFLAKE_DATABASE}.{SOURCE_SCHEMA} TO ROLE {role}",
        ]:
            cur.execute(stmt)
    print("  OK")


# ---------------------------------------------------------------------------
# Phase 2 — Deploy three Tessera policies on Snowflake source
# ---------------------------------------------------------------------------

def deploy_source_policies(cur) -> None:
    section("Phase 2 — Deploy three Tessera policies on Snowflake source")

    # Bindings translate the Databricks-shaped IR (table:bg_rls_demo.tpch.orders
    # and groups:bg_rls_demo_*) to the fresh Snowflake schema's identifiers.
    sf_config = AdapterConfig(
        identity_bindings={
            f"group:{GROUP_ALL_PRIORITY}":  ROLE_ALL_PRIORITY,
            f"group:{GROUP_HIGH_PRIORITY}": ROLE_HIGH_PRIORITY,
            f"group:{GROUP_ACCOUNT_USERS}": "PUBLIC",
            "group:account-users":          "PUBLIC",
            "group:orders_full_access":     ROLE_HIGH_PRIORITY,  # same role used as the privileged group
        },
        resource_bindings={
            "table:bg_rls_demo.tpch.orders":               fq_sf_table("demo_orders"),
            "table:bg_rls_demo.tpch.orders_rls_acl":       fq_sf_table("demo_orders_rls_acl"),
            "table:bg_rls_demo.tpch.rls_acl_mapping":      fq_sf_table("demo_rls_acl_mapping"),
            "table:bg_rls_demo.tpch.rls_priority_acl":     fq_sf_table("demo_rls_priority_acl"),
            "column:bg_rls_demo.tpch.orders.o_clerk":      f"{fq_sf_table('demo_orders')}.o_clerk",
        },
    )
    sf = SnowflakeAdapter(config=sf_config)

    from tools.converter import yaml_to_jsonld
    for yaml_path in SOURCE_POLICIES:
        step(f"Emit + apply: {yaml_path.name}")
        policy = yaml_to_jsonld(yaml_path)
        result = sf.emit(policy)
        for d in result.diagnostics:
            print(f"  [{d.severity.value}] {d.code}: {d.message[:140]}")
        if result.has_errors:
            print("  EMISSION ERRORS; skipping")
            continue
        for stmt in result.statements:
            head = stmt.splitlines()[0]
            try:
                cur.execute(stmt)
                print(f"  OK: {head[:100]}")
            except Exception as e:
                print(f"  FAIL: {head[:100]}\n       -> {str(e).splitlines()[0][:200]}")


# ---------------------------------------------------------------------------
# Phase 3 — Discover deployed policies on the Snowflake source
# Phase 4 — Extract each into Tessera IR; validate
# ---------------------------------------------------------------------------

def discover_and_extract(cur) -> list[dict]:
    section("Phase 3 — Discover policies on fresh Snowflake source")

    sf = SnowflakeAdapter(config=AdapterConfig(extras={
        "discover_database": SNOWFLAKE_DATABASE,
        "discover_schema":   SOURCE_SCHEMA,
        "snowflake_cursor":  cur,
    }))
    disc = sf.discover()
    for d in disc.diagnostics:
        print(f"  [{d.severity.value}] {d.code}: {d.message[:140]}")
    for art in disc.artifacts:
        attach = "; ".join(
            f"{a.get('REF_ENTITY_NAME')}"
            + (f".{a.get('REF_COLUMN_NAME')}" if a.get('REF_COLUMN_NAME') else "")
            for a in art["attachments"]
        )
        print(f"  • [{art['kind']}] {art['name']}  →  {attach or '<no attachments>'}")

    section("Phase 4 — Extract each into Tessera IR; validate")

    schema = json.loads(SCHEMA_PATH.read_text())
    shapes = Graph(); shapes.parse(str(SHAPES_PATH), format="turtle")
    onto   = Graph(); onto.parse(str(ONTOLOGY_PATH), format="turtle")
    local_ctx = f"file://{CONTEXT_PATH.resolve()}"

    extracted: list[dict] = []
    for art in disc.artifacts:
        r = sf.extract(art)
        step(art["name"])
        print(f"  confidence: {r.confidence}")
        for d in r.diagnostics:
            print(f"  [{d.severity.value}] {d.code}: {d.message[:140]}")
        if r.policy is None:
            print("  (no policy extracted)")
            continue
        try:
            jsonschema.validate(r.policy, schema)
            schema_ok = "OK"
        except jsonschema.ValidationError as e:
            schema_ok = f"FAIL: {e.message[:140]}"
        try:
            tmp_doc = dict(r.policy); tmp_doc["@context"] = local_ctx
            with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonld", delete=False) as tf:
                json.dump(tmp_doc, tf); tmp = tf.name
            data = Graph(); data.parse(tmp, format="json-ld")
            conforms, _, msg = shacl_validate(
                data_graph=data, shacl_graph=shapes, ont_graph=onto, inference="none")
            shacl_ok = "OK" if conforms else f"FAIL: {msg[:140]}"
        except Exception as e:
            shacl_ok = f"FAIL: {e}"
        print(f"  schema: {schema_ok}")
        print(f"  shacl:  {shacl_ok}")
        extracted.append(r.policy)
    return extracted


# ---------------------------------------------------------------------------
# Phase 5 — Provision Databricks target schema
# Phase 6 — Emit UC DDL with rebinding
# Phase 7 — Deploy UC DDL on Databricks
# ---------------------------------------------------------------------------

def provision_uc_target_and_deploy(extracted: list[dict]) -> list[tuple[str, list[str]]]:
    run = db_runner()
    section("Phase 5 — Provision Databricks target schema")

    step(f"Drop & recreate {TARGET_CATALOG}.{TARGET_SCHEMA}")
    try:
        run(f"DROP SCHEMA IF EXISTS {TARGET_CATALOG}.{TARGET_SCHEMA} CASCADE")
    except Exception:
        pass
    run(f"CREATE CATALOG IF NOT EXISTS {TARGET_CATALOG}")
    run(f"CREATE SCHEMA IF NOT EXISTS {TARGET_CATALOG}.{TARGET_SCHEMA}")

    step("Create demo tables (sampled from TPC-H)")
    for stmt in [
        f"CREATE TABLE {fq_uc_table('demo_orders')} AS "
        f"  SELECT * FROM samples.tpch.orders LIMIT 100000",
        # Mirror the Snowflake-side schema: add an `orderpriority` column
        # alongside o_orderpriority so the migrated row filter finds it.
        f"CREATE TABLE {fq_uc_table('demo_orders_rls_acl')} AS "
        f"  SELECT *, o_orderpriority AS orderpriority "
        f"  FROM samples.tpch.orders LIMIT 100000",
        f"CREATE TABLE {fq_uc_table('demo_rls_acl_mapping')} ("
        f"  username STRING, code_name STRING)",
        f"INSERT INTO {fq_uc_table('demo_rls_acl_mapping')} VALUES "
        f"  ('{DATABRICKS_USER_EMAIL}', 'urgent_priority_ops'),"
        f"  ('{DATABRICKS_USER_EMAIL}', 'high_priority_ops')",
        f"CREATE TABLE {fq_uc_table('demo_rls_priority_acl')} ("
        f"  code_name STRING, orderpriority STRING)",
        f"INSERT INTO {fq_uc_table('demo_rls_priority_acl')} VALUES "
        f"  ('urgent_priority_ops', '1-URGENT'),"
        f"  ('high_priority_ops',   '2-HIGH'),"
        f"  ('standard_ops',        '3-MEDIUM'),"
        f"  ('standard_ops',        '4-NOT SPECIFIED'),"
        f"  ('standard_ops',        '5-LOW')",
    ]:
        run(stmt)
        print(f"  OK: {stmt[:80]}…")

    section("Phase 6 — Emit UC DDL from extracted Tessera IR")

    # Bindings map the Snowflake-side identifiers (as carried by the extracted IR)
    # to their Databricks-side counterparts in the fresh target schema.
    uc_config = AdapterConfig(
        identity_bindings={
            f"group:{ROLE_HIGH_PRIORITY.lower()}": GROUP_HIGH_PRIORITY,
            f"group:{ROLE_ALL_PRIORITY.lower()}":  GROUP_ALL_PRIORITY,
            "group:public":                        GROUP_ACCOUNT_USERS,
        },
        resource_bindings={
            f"table:{fq_sf_table('demo_orders')}":          fq_uc_table("demo_orders"),
            f"table:{fq_sf_table('demo_orders_rls_acl')}":  fq_uc_table("demo_orders_rls_acl"),
            f"table:{fq_sf_table('demo_rls_acl_mapping')}": fq_uc_table("demo_rls_acl_mapping"),
            f"table:{fq_sf_table('demo_rls_priority_acl')}":fq_uc_table("demo_rls_priority_acl"),
            f"column:{fq_sf_table('demo_orders')}.o_clerk": f"{fq_uc_table('demo_orders')}.o_clerk",
        },
    )
    uc = UnityCatalogAdapter(config=uc_config)

    stmt_batches: list[tuple[str, list[str]]] = []
    for policy in extracted:
        step(policy["@id"])
        em = uc.emit(policy)
        for d in em.diagnostics:
            print(f"  [{d.severity.value}] {d.code}: {d.message[:140]}")
        if em.has_errors:
            print("  EMISSION ERRORS; skipping")
            continue
        for s in em.statements:
            head = s.splitlines()[0]
            print(f"  emit: {head[:100]}")
        stmt_batches.append((policy["@id"], em.statements))

    section("Phase 7 — Deploy UC DDL on Databricks")
    for policy_id, statements in stmt_batches:
        step(policy_id)
        for stmt in statements:
            head = stmt.splitlines()[0]
            try:
                run(stmt)
                print(f"  OK: {head[:100]}")
            except RuntimeError as e:
                print(f"  FAIL: {head[:100]}\n       -> {str(e).splitlines()[0][:200]}")

    return stmt_batches


# ---------------------------------------------------------------------------
# Phase 8 — Verify behavior on Databricks target
# ---------------------------------------------------------------------------

def verify_on_databricks() -> None:
    section("Phase 8 — Verify behavior on Databricks target")
    run = db_runner()

    step(f"Row counts on {fq_uc_table('demo_orders')} (group row-vis applies)")
    rows = run(f"SELECT o_orderpriority, COUNT(*) FROM {fq_uc_table('demo_orders')} "
               f"GROUP BY 1 ORDER BY 1")
    total = sum(int(r[1]) for r in (rows or []))
    print(f"  total visible: {total}")
    for r in rows or []: print(f"    {r[0]}: {r[1]}")

    step(f"Row counts on {fq_uc_table('demo_orders_rls_acl')} (byDataset RLS applies)")
    rows = run(f"SELECT o_orderpriority, COUNT(*) FROM {fq_uc_table('demo_orders_rls_acl')} "
               f"GROUP BY 1 ORDER BY 1")
    total = sum(int(r[1]) for r in (rows or []))
    print(f"  total visible: {total}")
    for r in rows or []: print(f"    {r[0]}: {r[1]}")

    step(f"Distinct o_clerk on {fq_uc_table('demo_orders')} (mask applies unless in group)")
    rows = run(f"SELECT DISTINCT o_clerk FROM {fq_uc_table('demo_orders')} LIMIT 5")
    for r in rows or []: print(f"    {r[0]}")

    step("Membership probe")
    rows = run(
        f"SELECT is_account_group_member('{GROUP_ALL_PRIORITY}') AS all_priority, "
        f"       is_account_group_member('{GROUP_HIGH_PRIORITY}') AS high_priority, "
        f"       is_account_group_member('{GROUP_ACCOUNT_USERS}') AS account_users"
    )
    if rows: print(f"  {rows[0]}")


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def cleanup() -> None:
    section("Cleanup — drop demo schemas on both platforms")

    # Snowflake
    try:
        conn = sf_connect(); cur = conn.cursor()
        cur.execute(f"DROP SCHEMA IF EXISTS {SNOWFLAKE_DATABASE}.{SOURCE_SCHEMA} CASCADE")
        print(f"  Snowflake: dropped {SNOWFLAKE_DATABASE}.{SOURCE_SCHEMA}")
        cur.close(); conn.close()
    except Exception as e:
        print(f"  Snowflake: cleanup failed -> {e}")

    # Databricks
    try:
        run = db_runner()
        run(f"DROP SCHEMA IF EXISTS {TARGET_CATALOG}.{TARGET_SCHEMA} CASCADE")
        print(f"  Databricks: dropped {TARGET_CATALOG}.{TARGET_SCHEMA}")
    except Exception as e:
        print(f"  Databricks: cleanup failed -> {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description="Snowflake → UC migration demo.")
    p.add_argument("--cleanup", action="store_true", help="Drop demo schemas and exit.")
    args = p.parse_args()

    if args.cleanup:
        cleanup()
        return 0

    conn = sf_connect()
    cur = conn.cursor()
    try:
        provision_snowflake_source(cur)
        deploy_source_policies(cur)
        extracted = discover_and_extract(cur)
    finally:
        cur.close()
        conn.close()

    if not extracted:
        print("\n(no policies extracted — aborting before Databricks side)")
        return 1

    provision_uc_target_and_deploy(extracted)
    verify_on_databricks()

    print("\nDone. Re-run safely; use --cleanup to drop schemas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
