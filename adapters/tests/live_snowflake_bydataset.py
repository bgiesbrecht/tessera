"""Live integration test: byDataset row visibility on Snowflake.

This is the Phase 3 verification for the Snowflake byDataset exercise. It:
    1. Sets up the protected table and ACL mapping tables in BRICETEST.TESSERA.
    2. Seeds the ACL data per docs/exercises/snowflake-byDataset-row-visibility-inputs.md §2.8.
    3. Emits Snowflake DDL via SnowflakeAdapter from spec/v0/examples/snowflake-byDataset-row-visibility-policy.jsonld.
    4. Applies the row-access policy.
    5. Verifies the four scenarios from the brief, including the secondary-roles-immunity scenario.
"""

from __future__ import annotations

import json
from pathlib import Path

import snowflake.connector

from adapters.contract.types import AdapterConfig
from adapters.snowflake import SnowflakeAdapter


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = REPO_ROOT / "spec" / "v0" / "examples"
AUTH = REPO_ROOT / "snowflake_auth.txt"

ACCOUNT = "FBGQMMZ-DCC90967"
USER = "BGIESBRECHT"
WAREHOUSE = "COMPUTE_WH"
DATABASE = "BRICETEST"
SCHEMA = "TESSERA"

PROTECTED_TABLE = f"{DATABASE}.{SCHEMA}.SNOW_ORDERS_RLS_ACL"
MAPPING_TABLE = f"{DATABASE}.{SCHEMA}.RLS_ACL_MAPPING"
PRIORITY_ACL_TABLE = f"{DATABASE}.{SCHEMA}.RLS_PRIORITY_ACL"


def main() -> None:
    pw = AUTH.read_text().strip()
    conn = snowflake.connector.connect(
        account=ACCOUNT, user=USER, password=pw,
        warehouse=WAREHOUSE, database=DATABASE, schema=SCHEMA, role="ACCOUNTADMIN",
    )
    cur = conn.cursor()

    print("=== Setup: protected table + ACL tables + seed data ===")
    # Drop any pre-existing test artifacts so re-runs are clean.
    try:
        cur.execute(
            f"ALTER TABLE {PROTECTED_TABLE} DROP ROW ACCESS POLICY "
            f"{DATABASE}.{SCHEMA}.snowflake_byDataset_row_visibility_rap"
        )
    except Exception:
        pass
    for stmt in [
        f"DROP ROW ACCESS POLICY IF EXISTS {DATABASE}.{SCHEMA}.snowflake_byDataset_row_visibility_rap",
        f"DROP TABLE IF EXISTS {PROTECTED_TABLE}",
        f"DROP TABLE IF EXISTS {MAPPING_TABLE}",
        f"DROP TABLE IF EXISTS {PRIORITY_ACL_TABLE}",
        f"CREATE TABLE {PROTECTED_TABLE} AS SELECT * FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS",
        f"CREATE TABLE {MAPPING_TABLE} (USERNAME VARCHAR, CODE_NAME VARCHAR)",
        f"CREATE TABLE {PRIORITY_ACL_TABLE} (CODE_NAME VARCHAR, O_ORDERPRIORITY VARCHAR)",
        f"INSERT INTO {PRIORITY_ACL_TABLE} VALUES "
        "('urgent_priority_ops', '1-URGENT'), "
        "('high_priority_ops', '2-HIGH'), "
        "('standard_ops', '3-MEDIUM'), "
        "('standard_ops', '4-NOT SPECIFIED'), "
        "('standard_ops', '5-LOW')",
        f"INSERT INTO {MAPPING_TABLE} VALUES "
        "('BGIESBRECHT', 'urgent_priority_ops'), "
        "('BGIESBRECHT', 'high_priority_ops')",
    ]:
        try:
            cur.execute(stmt)
        except Exception as e:
            print(f"  skip: {stmt[:60]}... -> {str(e).splitlines()[0]}")
    print("  setup complete")

    print()
    print("=== Emit DDL via adapter ===")
    policy = json.loads(
        (EXAMPLES / "snowflake-byDataset-row-visibility-policy.jsonld").read_text()
    )
    result = SnowflakeAdapter(AdapterConfig()).emit(policy)
    for d in result.diagnostics:
        print(f"  [{d.severity.value}] {d.code}: {d.message[:120]}")
    for s in result.statements:
        print(s)
        print()
    if result.has_errors:
        raise SystemExit("emission errors; refusing to execute")

    print("=== Apply DDL ===")
    for stmt in result.statements:
        print(">>", stmt.splitlines()[0])
        cur.execute(stmt)

    def count_priorities() -> dict[str, int]:
        cur.execute(
            f"SELECT O_ORDERPRIORITY, COUNT(*) FROM {PROTECTED_TABLE} GROUP BY 1 ORDER BY 1"
        )
        return {row[0]: int(row[1]) for row in cur.fetchall()}

    def scenario(label: str) -> None:
        counts = count_priorities()
        total = sum(counts.values())
        print(f"  {label}: total={total} visible")
        for k, v in counts.items():
            print(f"    {k}: {v}")

    print()
    print("=== Scenario 1: seed data as-is — BGIESBRECHT sees 1-URGENT + 2-HIGH only ===")
    cur.execute("USE SECONDARY ROLES NONE")
    scenario("scenario 1")

    print()
    print("=== Scenario 2: add ('BGIESBRECHT', 'standard_ops') ⇒ all five priorities ===")
    cur.execute(f"INSERT INTO {MAPPING_TABLE} VALUES ('BGIESBRECHT', 'standard_ops')")
    scenario("scenario 2")

    print()
    print("=== Scenario 3: remove all BGIESBRECHT entries ⇒ zero rows ===")
    cur.execute(f"DELETE FROM {MAPPING_TABLE} WHERE USERNAME = 'BGIESBRECHT'")
    scenario("scenario 3")

    print()
    print("=== Scenario 4: restore seed, verify secondary-roles immunity ===")
    cur.execute(f"DELETE FROM {MAPPING_TABLE}")
    cur.execute(
        f"INSERT INTO {MAPPING_TABLE} VALUES "
        "('BGIESBRECHT', 'urgent_priority_ops'), "
        "('BGIESBRECHT', 'high_priority_ops')"
    )
    cur.execute("USE SECONDARY ROLES NONE")
    scenario("scenario 4a (USE SECONDARY ROLES NONE)")
    cur.execute("USE SECONDARY ROLES ALL")
    scenario("scenario 4b (USE SECONDARY ROLES ALL)")

    cur.execute("USE SECONDARY ROLES NONE")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
