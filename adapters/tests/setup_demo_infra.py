"""Idempotent provisioning for the Tessera worked-example infrastructure.

Creates the catalog / schema / group / role / table state the worked
examples and the migration demo expect to find on each platform.

Re-runnable: every step is `CREATE ... IF NOT EXISTS` or equivalent.

Run from the repo root:
    .venv/bin/python -m adapters.tests.setup_demo_infra                  # both platforms
    .venv/bin/python -m adapters.tests.setup_demo_infra --platform databricks
    .venv/bin/python -m adapters.tests.setup_demo_infra --platform snowflake

What this provisions:

  Databricks (catalog `acme` must already exist):
    Schemas:    acme.tpch, acme.tpch_staging
    Tables:     acme.tpch.orders                ← samples.tpch.orders
                acme.tpch.orders_rls_acl        ← samples.tpch.orders
                acme.tpch.orders_abac           ← samples.tpch.orders
                acme.tpch.rls_acl_mapping       (USERNAME, CODE_NAME)
                acme.tpch.rls_priority_acl      (CODE_NAME, O_ORDERPRIORITY)
                acme.tpch_staging.initial_table ← samples.tpch.orders LIMIT 100
    Function:   acme.tpch.compute_customer_ltv (no-op UDF)
    Groups:     NOT provisioned by this script — Unity Catalog GRANT
                requires account-level groups, and the workspace SDK
                creates only WorkspaceGroup-typed groups (visible to
                SHOW GROUPS but rejected by GRANT with
                PRINCIPAL_DOES_NOT_EXIST). Provision at:
                  https://accounts.cloud.databricks.com → Groups
                The script prints the exact list to create.

  Snowflake (no pre-existing state needed):
    Database:   ACME
    Schema:     ACME.TESSERA
    Tables:     ACME.TESSERA.SNOW_ORDERS          ← SAMPLE_DATA.TPCH_SF1.ORDERS
                ACME.TESSERA.SNOW_ORDERS_RLS_ACL  ← SAMPLE_DATA.TPCH_SF1.ORDERS
                ACME.TESSERA.RLS_ACL_MAPPING       (USERNAME, CODE_NAME)
                ACME.TESSERA.RLS_PRIORITY_ACL      (CODE_NAME, O_ORDERPRIORITY)
    Roles:      ACME_ALL_PRIORITY_OPS, ACME_HIGH_PRIORITY_OPS,
                ORDERS_FULL_ACCESS  (empty by default)

Group / role membership is intentionally NOT provisioned by this script.
Adding members is a separate operational decision (and requires
account-admin in Databricks, ACCOUNTADMIN in Snowflake).

Seed ACL data is NOT inserted by this script either — the live-test
scripts that need ACL seed rows insert them at runtime
(see `live_snowflake_bydataset.py`).

Lessons learned during 0.6.2 provisioning (2026-05-20):

  - **Databricks groups must be account-level AND assigned to the
    workspace.** Workspace SDK `groups.create()` makes
    `WorkspaceGroup`-typed groups, which appear in `SHOW GROUPS` but
    fail UC `GRANT` with `PRINCIPAL_DOES_NOT_EXIST`. This script no
    longer attempts group creation; it prints the manual step
    instead. AccountClient + an account-admin profile would let us
    automate this; that enhancement is queued, not implemented.
  - **Which workspace matters.** A Databricks account can have many
    workspaces (Azure + AWS, prod + dev, etc.). Account-level groups
    must be explicitly assigned to the workspace your SDK profile
    targets (`adb-984752964297111.11.azuredatabricks.net` for this
    repo). Creating groups in the right account but the wrong
    workspace produces the same `PRINCIPAL_DOES_NOT_EXIST` failure
    as not creating them at all.
  - **The CREATE TABLE IF NOT EXISTS AS SELECT pattern is safe to
    re-run** but skips the SELECT body if the table already exists.
    First run gets the seed data; subsequent runs are no-ops.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Databricks setup
# ---------------------------------------------------------------------------

DATABRICKS_PROFILE = "adb-984752964297111"
DATABRICKS_WAREHOUSE = "148ccb90800933a1"
DATABRICKS_GROUPS = [
    "acme_all_priority_ops",
    "acme_high_priority_ops",
    "acme_marketing_analytics",
    "acme_data_engineering",
    "orders_full_access",
]


def _run_sql_databricks(w, sql: str, ignore_errors: bool = False):
    from databricks.sdk.service.sql import StatementState

    r = w.statement_execution.execute_statement(
        warehouse_id=DATABRICKS_WAREHOUSE, statement=sql, wait_timeout="30s",
    )
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(0.5)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        if ignore_errors:
            return None
        raise RuntimeError(f"SQL failed: {sql[:80]}... -> {r.status.error}")
    return r.result.data_array if r.result else None


def setup_databricks() -> None:
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.errors import ResourceAlreadyExists

    print("=" * 70)
    print("DATABRICKS")
    print("=" * 70)

    w = WorkspaceClient(profile=DATABRICKS_PROFILE)

    print()
    print("--- Catalog / schemas ---")
    # Catalog `acme` is expected to exist (Brice created it). We still try to
    # ensure it, so the script is self-contained if catalog was dropped.
    for stmt in [
        "CREATE CATALOG IF NOT EXISTS acme",
        "CREATE SCHEMA IF NOT EXISTS acme.tpch",
        "CREATE SCHEMA IF NOT EXISTS acme.tpch_staging",
    ]:
        _run_sql_databricks(w, stmt)
        print(f"  OK: {stmt}")

    print()
    print("--- Tables (TPC-H derived) ---")
    tables = {
        "acme.tpch.orders":
            "CREATE TABLE IF NOT EXISTS acme.tpch.orders "
            "AS SELECT * FROM samples.tpch.orders",
        "acme.tpch.orders_rls_acl":
            "CREATE TABLE IF NOT EXISTS acme.tpch.orders_rls_acl "
            "AS SELECT * FROM samples.tpch.orders",
        "acme.tpch.orders_abac":
            "CREATE TABLE IF NOT EXISTS acme.tpch.orders_abac "
            "AS SELECT * FROM samples.tpch.orders",
        "acme.tpch_staging.initial_table":
            "CREATE TABLE IF NOT EXISTS acme.tpch_staging.initial_table "
            "AS SELECT * FROM samples.tpch.orders LIMIT 100",
    }
    for name, sql in tables.items():
        _run_sql_databricks(w, sql)
        print(f"  ensured: {name}")

    print()
    print("--- ACL tables (empty) ---")
    for stmt in [
        "CREATE TABLE IF NOT EXISTS acme.tpch.rls_acl_mapping "
        "(USERNAME STRING, CODE_NAME STRING)",
        "CREATE TABLE IF NOT EXISTS acme.tpch.rls_priority_acl "
        "(CODE_NAME STRING, O_ORDERPRIORITY STRING)",
    ]:
        _run_sql_databricks(w, stmt)
        print(f"  OK: {stmt.split(' (')[0]}")

    print()
    print("--- Functions ---")
    _run_sql_databricks(
        w,
        "CREATE OR REPLACE FUNCTION acme.tpch.compute_customer_ltv("
        "  customer_key BIGINT"
        ") RETURNS DOUBLE RETURN 0.0",
    )
    print("  OK: acme.tpch.compute_customer_ltv")

    print()
    print("--- Groups: MANUAL PROVISIONING REQUIRED ---")
    print("  Unity Catalog GRANT requires *account-level* groups, not workspace-local")
    print("  groups. The workspace SDK's groups.create() makes WorkspaceGroup-typed")
    print("  groups, which are visible to SHOW GROUPS but fail GRANT with")
    print("  PRINCIPAL_DOES_NOT_EXIST. This script does NOT create groups for that")
    print("  reason — provision them at account level instead:")
    print()
    print("    https://accounts.cloud.databricks.com  →  User management  →  Groups")
    print()
    print("  Groups to create (empty; assign membership as needed):")
    for group_name in DATABRICKS_GROUPS:
        print(f"    - {group_name}")
    print()
    print("  After creating each group, assign it to the workspace (Workspaces →")
    print("  your workspace → Permissions → Groups → Add).")
    print()
    print("  If you have an account-admin Databricks SDK profile configured,")
    print("  AccountClient.groups.create() can do this programmatically — that")
    print("  enhancement is a future increment to this script.")

    print()
    print("--- Databricks setup complete ---")


# ---------------------------------------------------------------------------
# Snowflake setup
# ---------------------------------------------------------------------------

SNOWFLAKE_ACCOUNT = "FBGQMMZ-DCC90967"
SNOWFLAKE_USER = "BGIESBRECHT"
SNOWFLAKE_WAREHOUSE = "COMPUTE_WH"
SNOWFLAKE_AUTH = Path.home() / "snowflake_auth.txt"
SNOWFLAKE_ROLES = [
    "ACME_ALL_PRIORITY_OPS",
    "ACME_HIGH_PRIORITY_OPS",
    "ORDERS_FULL_ACCESS",
]


def setup_snowflake() -> None:
    import snowflake.connector

    print("=" * 70)
    print("SNOWFLAKE")
    print("=" * 70)

    if not SNOWFLAKE_AUTH.exists():
        print(f"  ERROR: {SNOWFLAKE_AUTH} not found")
        return

    pw = SNOWFLAKE_AUTH.read_text().strip()
    conn = snowflake.connector.connect(
        account=SNOWFLAKE_ACCOUNT, user=SNOWFLAKE_USER, password=pw,
        warehouse=SNOWFLAKE_WAREHOUSE, role="ACCOUNTADMIN",
    )
    cur = conn.cursor()

    print()
    print("--- Database / schema ---")
    for stmt in [
        "CREATE DATABASE IF NOT EXISTS ACME",
        "USE DATABASE ACME",
        "CREATE SCHEMA IF NOT EXISTS ACME.TESSERA",
        "USE SCHEMA ACME.TESSERA",
    ]:
        cur.execute(stmt)
        print(f"  OK: {stmt}")

    print()
    print("--- Roles (empty) ---")
    for role in SNOWFLAKE_ROLES:
        cur.execute(f"CREATE ROLE IF NOT EXISTS {role}")
        print(f"  ensured: {role}")

    print()
    print("--- Tables (TPC-H derived) ---")
    # SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS is the standard 1.5M-row sample.
    for table, source in [
        ("SNOW_ORDERS", "SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS"),
        ("SNOW_ORDERS_RLS_ACL", "SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS"),
    ]:
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS ACME.TESSERA.{table} AS "
            f"SELECT * FROM {source}"
        )
        print(f"  ensured: ACME.TESSERA.{table}")

    print()
    print("--- ACL tables (empty) ---")
    for stmt in [
        "CREATE TABLE IF NOT EXISTS ACME.TESSERA.RLS_ACL_MAPPING "
        "(USERNAME VARCHAR, CODE_NAME VARCHAR)",
        "CREATE TABLE IF NOT EXISTS ACME.TESSERA.RLS_PRIORITY_ACL "
        "(CODE_NAME VARCHAR, O_ORDERPRIORITY VARCHAR)",
    ]:
        cur.execute(stmt)
        print(f"  OK: {stmt.split(' (')[0]}")

    print()
    print("--- Snowflake setup complete ---")

    cur.close()
    conn.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--platform", choices=["databricks", "snowflake", "all"], default="all",
        help="Which platform to provision (default: all).",
    )
    args = parser.parse_args()

    if args.platform in ("databricks", "all"):
        setup_databricks()
    if args.platform in ("snowflake", "all"):
        print()
        setup_snowflake()

    print()
    print("=" * 70)
    print("Setup complete. Group / role membership is empty — assign as needed.")
    print("=" * 70)


if __name__ == "__main__":
    main()
