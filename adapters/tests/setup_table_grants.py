"""Idempotent setup for the table-grants exercise.

Run from the repo root with the .venv interpreter:
    .venv/bin/python -m adapters.tests.setup_table_grants

The script:
    1. Creates BG_RLS_DEMO catalog and TPCH / TPCH_STAGING schemas if absent.
    2. Creates an initial table in TPCH_STAGING (for the propagation test in
       Scenario B; Phase 3 adds another table mid-exercise to verify forward
       propagation).
    3. Creates a no-op UDF compute_customer_ltv (for Scenario C).
    4. Recreates bg_rls_demo.tpch.orders if missing (re-using sample TPCH data).
    5. Drops any pre-existing grants on the three target objects so the
       exercise can re-apply cleanly.

Group creation is NOT scripted; account-level group membership requires
console access. Brice provisions groups manually.
"""

from __future__ import annotations

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState


PROFILE = "adb-984752964297111"
WAREHOUSE_ID = "148ccb90800933a1"


def run_sql(w: WorkspaceClient, sql: str, ignore_errors: bool = False) -> list | None:
    r = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID, statement=sql, wait_timeout="30s",
    )
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        if ignore_errors:
            return None
        raise RuntimeError(f"SQL failed: {sql[:80]}... -> {r.status.error}")
    return r.result.data_array if r.result else None


def main() -> None:
    w = WorkspaceClient(profile=PROFILE)

    print("=== Catalog / schemas ===")
    for stmt in [
        "CREATE CATALOG IF NOT EXISTS bg_rls_demo",
        "CREATE SCHEMA IF NOT EXISTS bg_rls_demo.tpch",
        "CREATE SCHEMA IF NOT EXISTS bg_rls_demo.tpch_staging",
    ]:
        run_sql(w, stmt)
        print(f"  OK: {stmt}")

    print()
    print("=== Tables ===")
    # Scenario A target. CREATE TABLE IF NOT EXISTS ... AS SELECT is valid in
    # Databricks SQL and skips the CTAS body if the table already exists.
    run_sql(
        w,
        "CREATE TABLE IF NOT EXISTS bg_rls_demo.tpch.orders AS SELECT * FROM samples.tpch.orders",
    )
    print("  ensured: bg_rls_demo.tpch.orders")

    # Scenario B target — initial table in the staging schema.
    run_sql(
        w,
        "CREATE TABLE IF NOT EXISTS bg_rls_demo.tpch_staging.initial_table "
        "AS SELECT * FROM samples.tpch.orders LIMIT 100",
    )
    print("  ensured: bg_rls_demo.tpch_staging.initial_table")

    print()
    print("=== Scenario C function ===")
    # No-op SQL UDF for Scenario C. Returns a fixed value; signature exists for
    # the test to call. CREATE OR REPLACE so re-runs are idempotent.
    run_sql(
        w,
        "CREATE OR REPLACE FUNCTION bg_rls_demo.tpch.compute_customer_ltv("
        "  customer_key BIGINT"
        ") RETURNS DOUBLE "
        "RETURN 0.0",
    )
    print("  OK: bg_rls_demo.tpch.compute_customer_ltv")

    print()
    print("=== Pre-clean any existing grants on the targets (idempotent re-runs) ===")
    # Best-effort revokes; the GRANT statements in Phase 3 will re-apply cleanly.
    revokes = [
        "REVOKE SELECT ON TABLE bg_rls_demo.tpch.orders FROM `bg_rls_demo_marketing_analytics`",
        "REVOKE SELECT ON SCHEMA bg_rls_demo.tpch_staging FROM `bg_rls_demo_data_engineering`",
        "REVOKE USE SCHEMA ON SCHEMA bg_rls_demo.tpch_staging FROM `bg_rls_demo_data_engineering`",
        "REVOKE EXECUTE ON FUNCTION bg_rls_demo.tpch.compute_customer_ltv "
        "  FROM `bg_rls_demo_marketing_analytics`",
    ]
    for stmt in revokes:
        run_sql(w, stmt, ignore_errors=True)
        print(f"  pre-clean: {stmt[:80]}...")

    print()
    print("=== Group provisioning note ===")
    print("  This script does NOT create account-level groups.")
    print("  Manual step required (Brice): create or confirm the following groups exist")
    print("  and that you are a member of them as appropriate for the test scenarios:")
    print("    - bg_rls_demo_marketing_analytics")
    print("    - bg_rls_demo_data_engineering")
    print()
    print("  Group propagation lag is 2-4 minutes after membership changes.")


if __name__ == "__main__":
    main()
