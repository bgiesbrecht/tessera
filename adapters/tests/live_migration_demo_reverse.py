"""Repeatable Unity Catalog → Snowflake migration demo.

Mirror of `live_migration_demo.py` with source and target reversed:

    Source: Unity Catalog (Databricks) — `bg_rls_demo.reverse_demo`
    Target: Snowflake — `BRICETEST.REVERSE_DEMO`

Eight phases, idempotent re-run, --cleanup teardown — same shape as the
forward demo. Proves the IR pivot is symmetric: the same three Tessera
worked-example IRs deploy onto UC via `UnityCatalogAdapter.emit`, are
re-discovered + extracted via UC's `discover()`/`extract()` (landed in 0.5.0),
and re-emit onto Snowflake via `SnowflakeAdapter.emit`. End-to-end
verification confirms the migrated policies enforce on the Snowflake target.

Run with:
    .venv/bin/python -m adapters.tests.live_migration_demo_reverse

Re-runnable. To tear down:
    .venv/bin/python -m adapters.tests.live_migration_demo_reverse --cleanup
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

from adapters.contract.types import AdapterConfig
from adapters.snowflake import SnowflakeAdapter
from adapters.unity_catalog import UnityCatalogAdapter


# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "spec" / "v0" / "schema.json"
SHAPES_PATH = REPO_ROOT / "spec" / "v0" / "shapes.ttl"
ONTOLOGY_PATH = REPO_ROOT / "spec" / "v0" / "ontology.ttl"
CONTEXT_PATH = REPO_ROOT / "spec" / "v0" / "context.jsonld"
EXAMPLES = REPO_ROOT / "spec" / "v0" / "examples"
AUTH_PATH = Path.home() / "snowflake_auth.txt"

# UC SOURCE
DATABRICKS_PROFILE  = "adb-984752964297111"
DATABRICKS_WAREHOUSE = "148ccb90800933a1"
SOURCE_CATALOG      = "bg_rls_demo"
SOURCE_SCHEMA       = "reverse_demo"

# Snowflake TARGET
SNOWFLAKE_ACCOUNT   = "FBGQMMZ-DCC90967"
SNOWFLAKE_USER      = "BGIESBRECHT"
SNOWFLAKE_WAREHOUSE = "COMPUTE_WH"
SNOWFLAKE_DATABASE  = "BRICETEST"
TARGET_SCHEMA       = "REVERSE_DEMO"

# Identifiers
GROUP_ALL_PRIORITY  = "bg_rls_demo_all_priority_ops"
GROUP_HIGH_PRIORITY = "bg_rls_demo_high_priority_ops"
GROUP_ACCOUNT_USERS = "account users"
ROLE_ALL_PRIORITY   = "BG_RLS_DEMO_ALL_PRIORITY_OPS"
ROLE_HIGH_PRIORITY  = "BG_RLS_DEMO_HIGH_PRIORITY_OPS"

DATABRICKS_USER_EMAIL = "brice.giesbrecht@databricks.com"


SOURCE_POLICIES = [
    EXAMPLES / "group-row-visibility-policy-a.tessera.yaml",
    EXAMPLES / "acl-row-visibility-policy.tessera.yaml",
    EXAMPLES / "column-mask-orders-clerk-policy.tessera.yaml",
]


def fq_uc_table(name: str) -> str:
    return f"{SOURCE_CATALOG}.{SOURCE_SCHEMA}.{name}"


def fq_sf_table(name: str) -> str:
    return f"{SNOWFLAKE_DATABASE}.{TARGET_SCHEMA}.{name}"


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
# Phase 1 — Provision UC source schema
# ---------------------------------------------------------------------------


def provision_uc_source() -> None:
    section("Phase 1 — Provision Unity Catalog source schema")
    run = db_runner()

    step(f"Drop & recreate {SOURCE_CATALOG}.{SOURCE_SCHEMA}")
    run(f"DROP SCHEMA IF EXISTS {SOURCE_CATALOG}.{SOURCE_SCHEMA} CASCADE", ignore_errors=True)
    run(f"CREATE CATALOG IF NOT EXISTS {SOURCE_CATALOG}")
    run(f"CREATE SCHEMA {SOURCE_CATALOG}.{SOURCE_SCHEMA}")

    step("Create demo tables (sampled from TPC-H)")
    for stmt in [
        f"CREATE TABLE {fq_uc_table('demo_orders')} AS "
        f"  SELECT * FROM samples.tpch.orders LIMIT 100000",
        # Add `orderpriority` alias column to align with the byDataset YAML's
        # resourceColumn (same workaround as the forward demo; issue #13).
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


# ---------------------------------------------------------------------------
# Phase 2 — Deploy three Tessera policies on UC source
# ---------------------------------------------------------------------------


def deploy_uc_source_policies() -> None:
    section("Phase 2 — Deploy three Tessera policies on UC source")
    run = db_runner()

    uc_config = AdapterConfig(
        identity_bindings={
            f"group:{GROUP_ALL_PRIORITY}":  GROUP_ALL_PRIORITY,
            f"group:{GROUP_HIGH_PRIORITY}": GROUP_HIGH_PRIORITY,
            f"group:{GROUP_ACCOUNT_USERS}": GROUP_ACCOUNT_USERS,
            "group:account-users":          GROUP_ACCOUNT_USERS,
            "group:orders_full_access":     GROUP_HIGH_PRIORITY,
        },
        resource_bindings={
            "table:bg_rls_demo.tpch.orders":               fq_uc_table("demo_orders"),
            "table:bg_rls_demo.tpch.orders_rls_acl":       fq_uc_table("demo_orders_rls_acl"),
            "table:bg_rls_demo.tpch.rls_acl_mapping":      fq_uc_table("demo_rls_acl_mapping"),
            "table:bg_rls_demo.tpch.rls_priority_acl":     fq_uc_table("demo_rls_priority_acl"),
            "column:bg_rls_demo.tpch.orders.o_clerk":      f"{fq_uc_table('demo_orders')}.o_clerk",
        },
    )
    uc = UnityCatalogAdapter(config=uc_config)

    from tools.converter import yaml_to_jsonld
    for yaml_path in SOURCE_POLICIES:
        step(f"Emit + apply: {yaml_path.name}")
        policy = yaml_to_jsonld(yaml_path)
        result = uc.emit(policy)
        for d in result.diagnostics:
            print(f"  [{d.severity.value}] {d.code}: {d.message[:140]}")
        if result.has_errors:
            print("  EMISSION ERRORS; skipping")
            continue
        for stmt in result.statements:
            head = stmt.splitlines()[0]
            try:
                run(stmt)
                print(f"  OK: {head[:100]}")
            except Exception as e:
                print(f"  FAIL: {head[:100]}\n       -> {str(e).splitlines()[0][:200]}")


# ---------------------------------------------------------------------------
# Phase 3 — Discover deployed policies on UC source
# Phase 4 — Extract each into Tessera IR; validate
# ---------------------------------------------------------------------------


def discover_and_extract() -> list[dict]:
    section("Phase 3 — Discover policies on UC source")

    run = db_runner()
    uc = UnityCatalogAdapter(config=AdapterConfig(extras={
        "discover_catalog": SOURCE_CATALOG,
        "discover_schema":  SOURCE_SCHEMA,
        "run_sql":          run,
    }))
    disc = uc.discover()
    for d in disc.diagnostics:
        print(f"  [{d.severity.value}] {d.code}: {d.message[:140]}")
    for art in disc.artifacts:
        attach = art["attachments"][0]
        col = attach.get("REF_COLUMN_NAME") or ""
        print(f"  • [{art['kind']}] {art['name']} on {attach.get('REF_ENTITY_NAME')}"
              + (f".{col}" if col else ""))

    section("Phase 4 — Extract each into Tessera IR; validate")

    schema = json.loads(SCHEMA_PATH.read_text())
    shapes = Graph(); shapes.parse(str(SHAPES_PATH), format="turtle")
    onto   = Graph(); onto.parse(str(ONTOLOGY_PATH), format="turtle")
    local_ctx = f"file://{CONTEXT_PATH.resolve()}"

    extracted: list[dict] = []
    for art in disc.artifacts:
        r = uc.extract(art)
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
# Phase 5 — Provision Snowflake target schema
# Phase 6 — Emit Snowflake DDL
# Phase 7 — Deploy on Snowflake
# ---------------------------------------------------------------------------


def provision_snowflake_target_and_deploy(extracted: list[dict]) -> list[tuple[str, list[str]]]:
    section("Phase 5 — Provision Snowflake target schema")
    conn = sf_connect()
    cur = conn.cursor()
    try:
        step(f"Drop & recreate {SNOWFLAKE_DATABASE}.{TARGET_SCHEMA}")
        cur.execute(f"DROP SCHEMA IF EXISTS {SNOWFLAKE_DATABASE}.{TARGET_SCHEMA} CASCADE")
        cur.execute(f"CREATE SCHEMA {SNOWFLAKE_DATABASE}.{TARGET_SCHEMA}")
        cur.execute(f"USE SCHEMA {SNOWFLAKE_DATABASE}.{TARGET_SCHEMA}")

        step("Create demo tables (sampled from TPC-H) + ACL data")
        for stmt in [
            f"CREATE TABLE {fq_sf_table('demo_orders')} AS "
            f"  SELECT * FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS SAMPLE (100000 ROWS)",
            # Mirror the UC-side `orderpriority` alias column.
            f"CREATE TABLE {fq_sf_table('demo_orders_rls_acl')} AS "
            f"  SELECT *, O_ORDERPRIORITY AS orderpriority "
            f"  FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS SAMPLE (100000 ROWS)",
            f"CREATE TABLE {fq_sf_table('demo_rls_acl_mapping')} ("
            f"  USERNAME VARCHAR, CODE_NAME VARCHAR)",
            # Seed both the Databricks-email form (carried through from UC's
            # extracted ACL data) AND the Snowflake-username form (so calling
            # CURRENT_USER() resolves on Snowflake).
            f"INSERT INTO {fq_sf_table('demo_rls_acl_mapping')} VALUES "
            f"  ('{DATABRICKS_USER_EMAIL}', 'urgent_priority_ops'),"
            f"  ('{DATABRICKS_USER_EMAIL}', 'high_priority_ops'),"
            f"  ('{SNOWFLAKE_USER}', 'urgent_priority_ops'),"
            f"  ('{SNOWFLAKE_USER}', 'high_priority_ops')",
            f"CREATE TABLE {fq_sf_table('demo_rls_priority_acl')} ("
            f"  CODE_NAME VARCHAR, ORDERPRIORITY VARCHAR)",
            f"INSERT INTO {fq_sf_table('demo_rls_priority_acl')} VALUES "
            f"  ('urgent_priority_ops', '1-URGENT'),"
            f"  ('high_priority_ops',   '2-HIGH'),"
            f"  ('standard_ops',        '3-MEDIUM'),"
            f"  ('standard_ops',        '4-NOT SPECIFIED'),"
            f"  ('standard_ops',        '5-LOW')",
        ]:
            cur.execute(stmt)
            print(f"  OK: {stmt[:80]}…")

        step("Grant role access on target schema")
        for role in (ROLE_HIGH_PRIORITY, ROLE_ALL_PRIORITY, "PUBLIC"):
            cur.execute(f"GRANT USAGE ON SCHEMA {SNOWFLAKE_DATABASE}.{TARGET_SCHEMA} TO ROLE {role}")
            cur.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA {SNOWFLAKE_DATABASE}.{TARGET_SCHEMA} TO ROLE {role}")

        section("Phase 6 — Emit Snowflake DDL from extracted Tessera IR")

        sf_config = AdapterConfig(
            identity_bindings={
                # The UC-extracted IR carries `group:bg_rls_demo_*` lowercase.
                # Map each to its Snowflake role equivalent.
                f"group:{GROUP_ALL_PRIORITY}":  ROLE_ALL_PRIORITY,
                f"group:{GROUP_HIGH_PRIORITY}": ROLE_HIGH_PRIORITY,
                f"group:{GROUP_ACCOUNT_USERS}": "PUBLIC",
            },
            resource_bindings={
                # UC-extracted IR carries `table:bg_rls_demo.reverse_demo.*`.
                # Map each to the Snowflake target table.
                f"table:{fq_uc_table('demo_orders')}":            fq_sf_table("demo_orders"),
                f"table:{fq_uc_table('demo_orders_rls_acl')}":    fq_sf_table("demo_orders_rls_acl"),
                f"table:{fq_uc_table('demo_rls_acl_mapping')}":   fq_sf_table("demo_rls_acl_mapping"),
                f"table:{fq_uc_table('demo_rls_priority_acl')}":  fq_sf_table("demo_rls_priority_acl"),
                f"column:{fq_uc_table('demo_orders')}.o_clerk":   f"{fq_sf_table('demo_orders')}.o_clerk",
            },
        )
        sf = SnowflakeAdapter(config=sf_config)

        stmt_batches: list[tuple[str, list[str]]] = []
        for policy in extracted:
            step(policy["@id"])
            em = sf.emit(policy)
            for d in em.diagnostics:
                print(f"  [{d.severity.value}] {d.code}: {d.message[:140]}")
            if em.has_errors:
                print("  EMISSION ERRORS; skipping")
                continue
            for s in em.statements:
                head = s.splitlines()[0]
                print(f"  emit: {head[:100]}")
            stmt_batches.append((policy["@id"], em.statements))

        section("Phase 7 — Deploy Snowflake DDL")
        for policy_id, statements in stmt_batches:
            step(policy_id)
            for stmt in statements:
                head = stmt.splitlines()[0]
                try:
                    cur.execute(stmt)
                    print(f"  OK: {head[:100]}")
                except Exception as e:
                    print(f"  FAIL: {head[:100]}\n       -> {str(e).splitlines()[0][:200]}")
    finally:
        cur.close()
        conn.close()

    return stmt_batches


# ---------------------------------------------------------------------------
# Phase 8 — Verify behavior on Snowflake target
# ---------------------------------------------------------------------------


def verify_on_snowflake() -> None:
    section("Phase 8 — Verify behavior on Snowflake target")
    conn = sf_connect()
    cur = conn.cursor()
    try:
        # Defeat any default secondary roles; we want clean role discrimination.
        cur.execute("USE SECONDARY ROLES NONE")

        step(f"Row counts on {fq_sf_table('demo_orders')} (group row-vis applies)")
        cur.execute(f"SELECT o_orderpriority, COUNT(*) FROM {fq_sf_table('demo_orders')} "
                    f"GROUP BY 1 ORDER BY 1")
        rows = cur.fetchall()
        total = sum(int(r[1]) for r in rows)
        print(f"  total visible: {total}")
        for r in rows:
            print(f"    {r[0]}: {r[1]}")

        step(f"Row counts on {fq_sf_table('demo_orders_rls_acl')} (byDataset RLS applies)")
        cur.execute(f"SELECT o_orderpriority, COUNT(*) FROM {fq_sf_table('demo_orders_rls_acl')} "
                    f"GROUP BY 1 ORDER BY 1")
        rows = cur.fetchall()
        total = sum(int(r[1]) for r in rows)
        print(f"  total visible: {total}")
        for r in rows:
            print(f"    {r[0]}: {r[1]}")

        step(f"Distinct o_clerk on {fq_sf_table('demo_orders')} (mask applies unless in role)")
        cur.execute(f"SELECT DISTINCT o_clerk FROM {fq_sf_table('demo_orders')} LIMIT 5")
        for r in cur.fetchall():
            print(f"    {r[0]}")

        step("Active session info")
        cur.execute("SELECT CURRENT_USER(), CURRENT_ROLE()")
        print(f"  {cur.fetchone()}")
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def cleanup() -> None:
    section("Cleanup — drop demo schemas on both platforms")

    try:
        run = db_runner()
        run(f"DROP SCHEMA IF EXISTS {SOURCE_CATALOG}.{SOURCE_SCHEMA} CASCADE", ignore_errors=True)
        print(f"  Databricks: dropped {SOURCE_CATALOG}.{SOURCE_SCHEMA}")
    except Exception as e:
        print(f"  Databricks: cleanup failed -> {e}")

    try:
        conn = sf_connect(); cur = conn.cursor()
        cur.execute(f"DROP SCHEMA IF EXISTS {SNOWFLAKE_DATABASE}.{TARGET_SCHEMA} CASCADE")
        print(f"  Snowflake: dropped {SNOWFLAKE_DATABASE}.{TARGET_SCHEMA}")
        cur.close(); conn.close()
    except Exception as e:
        print(f"  Snowflake: cleanup failed -> {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description="Unity Catalog → Snowflake migration demo.")
    p.add_argument("--cleanup", action="store_true", help="Drop demo schemas and exit.")
    args = p.parse_args()

    if args.cleanup:
        cleanup()
        return 0

    provision_uc_source()
    deploy_uc_source_policies()
    extracted = discover_and_extract()

    if not extracted:
        print("\n(no policies extracted — aborting before Snowflake side)")
        return 1

    provision_snowflake_target_and_deploy(extracted)
    verify_on_snowflake()

    print("\nDone. Re-run safely; use --cleanup to drop schemas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
