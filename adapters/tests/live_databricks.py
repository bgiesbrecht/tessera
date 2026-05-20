"""Live integration test: emit row-visibility policy and verify on Databricks.

Run from the repo root with the .venv interpreter:
    .venv/bin/python -m adapters.tests.live_databricks

The script:
    1. Loads spec/v0/examples/group-row-visibility-policy-a.jsonld.
    2. Emits Unity Catalog DDL via UnityCatalogAdapter with explicit bindings.
    3. Executes the DDL against acme.tpch.orders.
    4. Verifies row counts under the current user (whose group membership controls
       what the row filter returns).
"""

from __future__ import annotations

import json
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

from adapters.contract.types import AdapterConfig
from adapters.unity_catalog import UnityCatalogAdapter


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = REPO_ROOT / "spec" / "v0" / "examples"

PROFILE = "adb-984752964297111"
WAREHOUSE_ID = "148ccb90800933a1"   # "Shared Endpoint" — currently RUNNING
TARGET_TABLE = "acme.tpch.orders"


def run_sql(w: WorkspaceClient, sql: str):
    resp = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID, statement=sql, wait_timeout="30s",
    )
    while resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
        resp = w.statement_execution.get_statement(resp.statement_id)
    if resp.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"SQL failed: {resp.status.error}")
    return resp.result.data_array if resp.result else None


def main() -> None:
    policy = json.loads((EXAMPLES / "group-row-visibility-policy-a.jsonld").read_text())

    config = AdapterConfig(
        identity_bindings={
            "group:acme_all_priority_ops": "acme_all_priority_ops",
            "group:acme_high_priority_ops": "acme_high_priority_ops",
            "group:account-users": "account users",   # Databricks built-in
        },
        resource_bindings={
            "table:acme.tpch.orders": TARGET_TABLE,
        },
    )
    result = UnityCatalogAdapter(config=config).emit(policy)

    print("=== Diagnostics ===")
    for d in result.diagnostics:
        print(f"  [{d.severity.value}] {d.code}: {d.message}")
    print()
    print("=== Statements ===")
    for s in result.statements:
        print(s)
        print()

    if result.has_errors:
        raise SystemExit("emission errors; refusing to execute")

    w = WorkspaceClient(profile=PROFILE)

    # Drop any existing row filter to avoid the multiple-policy conflict observed
    # in earlier ABAC exercises. The function reference is the bound row-filter UDF.
    print("Detaching any existing row filter…")
    try:
        run_sql(w, f"ALTER TABLE {TARGET_TABLE} DROP ROW FILTER")
    except Exception as e:
        print(f"  (no existing filter to drop: {str(e).splitlines()[0]})")

    for stmt in result.statements:
        print(">>", stmt.splitlines()[0])
        run_sql(w, stmt)

    print()
    print("=== Verification: row counts under current user ===")
    data = run_sql(
        w, f"SELECT o_orderpriority, COUNT(*) FROM {TARGET_TABLE} GROUP BY 1 ORDER BY 1"
    )
    total = sum(int(row[1]) for row in (data or []))
    print(f"  total visible: {total}")
    for row in (data or []):
        print(f"    {row[0]}: {row[1]}")

    # Membership probe so the row count is interpretable.
    membership = run_sql(
        w,
        "SELECT "
        "is_account_group_member('acme_all_priority_ops') AS all_priority, "
        "is_account_group_member('acme_high_priority_ops') AS high_priority, "
        "is_account_group_member('account users') AS account_users",
    )
    if membership:
        print(f"  caller membership: {membership[0]}")


if __name__ == "__main__":
    main()
