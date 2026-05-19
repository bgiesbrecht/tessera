"""Live integration test: emit row-visibility policy and verify on Snowflake.

Run from the repo root with the .venv interpreter:
    .venv/bin/python -m adapters.tests.live_snowflake

The script:
    1. Loads spec/v0/examples/group-row-visibility-policy-a.jsonld.
    2. Emits Snowflake DDL via SnowflakeAdapter with explicit identity/resource bindings.
    3. Executes the DDL against BRICETEST.TESSERA.SNOW_ORDERS.
    4. Probes the resulting policy by activating different roles and counting rows.
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
TARGET_TABLE = f"{DATABASE}.{SCHEMA}.SNOW_ORDERS"


def main() -> None:
    policy = json.loads((EXAMPLES / "group-row-visibility-policy-a.jsonld").read_text())

    # Identity binding keys match the IR PrincipalRef IRIs verbatim. The worked-example
    # JSON-LD uses `group:` prefixes for these refs; the binding maps each to the
    # corresponding Snowflake role name.
    config = AdapterConfig(
        identity_bindings={
            "group:bg_rls_demo_all_priority_ops": "BG_RLS_DEMO_ALL_PRIORITY_OPS",
            "group:bg_rls_demo_high_priority_ops": "BG_RLS_DEMO_HIGH_PRIORITY_OPS",
            "group:account-users": "PUBLIC",
        },
        resource_bindings={
            "table:bg_rls_demo.tpch.orders": TARGET_TABLE,
        },
    )
    result = SnowflakeAdapter(config=config).emit(policy)

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

    pw = AUTH.read_text().strip()
    conn = snowflake.connector.connect(
        account=ACCOUNT, user=USER, password=pw,
        warehouse=WAREHOUSE, database=DATABASE, schema=SCHEMA, role="ACCOUNTADMIN",
    )
    cur = conn.cursor()

    # Detach any existing policy so we can re-apply cleanly.
    cur.execute(f"SHOW ROW ACCESS POLICIES IN SCHEMA {DATABASE}.{SCHEMA}")
    existing = [r[1] for r in cur.fetchall()]
    for name in existing:
        try:
            cur.execute(
                f"ALTER TABLE {TARGET_TABLE} DROP ROW ACCESS POLICY {DATABASE}.{SCHEMA}.{name}"
            )
        except Exception:
            pass

    for stmt in result.statements:
        print(">>", stmt.splitlines()[0])
        cur.execute(stmt)

    # GRANT APPLY on the policy so the roles can read through it.
    policy_objs = [s for s in result.statements if "ROW ACCESS POLICY" in s and s.startswith("CREATE")]
    if policy_objs:
        first_line = policy_objs[0].splitlines()[0]
        # CREATE OR REPLACE ROW ACCESS POLICY <schema-qualified-name>
        policy_name = first_line.split("ROW ACCESS POLICY", 1)[1].strip()
        for role in ("BG_RLS_DEMO_ALL_PRIORITY_OPS", "BG_RLS_DEMO_HIGH_PRIORITY_OPS", "PUBLIC"):
            cur.execute(f"GRANT APPLY ON ROW ACCESS POLICY {policy_name} TO ROLE {role}")

    # Snowflake activates secondary roles per session. With the default of ALL,
    # `IS_ROLE_IN_SESSION(...)` returns true for every role granted to the user,
    # regardless of which role is set as primary via USE ROLE — defeating the
    # row-access policy's intended discrimination during testing. Disable secondary
    # roles for the probe so each USE ROLE actually exercises that role alone.
    cur.execute("USE SECONDARY ROLES NONE")

    print()
    print("=== Verification: row counts per active role (secondary roles disabled) ===")
    for role in ("PUBLIC", "BG_RLS_DEMO_HIGH_PRIORITY_OPS", "BG_RLS_DEMO_ALL_PRIORITY_OPS", "ACCOUNTADMIN"):
        try:
            cur.execute(f"USE ROLE {role}")
            cur.execute("USE WAREHOUSE COMPUTE_WH")
            cur.execute(
                f"SELECT O_ORDERPRIORITY, COUNT(*) FROM {TARGET_TABLE} GROUP BY 1 ORDER BY 1"
            )
            rows = cur.fetchall()
            total = sum(r[1] for r in rows)
            print(f"  active role = {role}: {total} rows visible")
            for r in rows:
                print(f"    {r[0]}: {r[1]}")
        except Exception as e:
            print(f"  active role = {role}: ERROR {str(e).splitlines()[0]}")
            # Reset to ACCOUNTADMIN so the next iteration can USE ROLE
            cur.execute("USE ROLE ACCOUNTADMIN")
            cur.execute("USE SECONDARY ROLES NONE")

    cur.execute("USE ROLE ACCOUNTADMIN")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
