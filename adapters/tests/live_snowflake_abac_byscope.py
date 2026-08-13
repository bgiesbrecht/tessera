"""Live verification: ABAC byScope emission on Snowflake (issue #31).

Verifies that the tag-based masking / row-access DDL the adapter emits actually
enforces on a real Snowflake account. Run from the repo root with the .venv:

    .venv/bin/python -m adapters.tests.live_snowflake_abac_byscope [--keep]

Requires a *billed* Snowflake account with a runnable warehouse; the password is
read from ./snowflake_auth.txt (repo root). Set ACCOUNT/USER/WAREHOUSE below to
your account.

Live-verified 2026-08-13 on a fresh Enterprise account: both paths enforce as
expected (column mask redacts for non-privileged roles; row filter shows the
per-role priority slices). Two mechanism facts, discovered live and now baked
into the adapter / this script:
  * Column masking tags the COLUMN; row access tags the TABLE. (Snowflake
    applies a tag-based row-access policy to objects carrying the tag; a
    column-level tag does not trigger it.)
  * The `ALTER TAG ... SET ROW ACCESS POLICY ... ON (<col> <type>)` clause must
    name the real discriminator column (the emitter derives it from the matching
    attribute value); it binds positionally to the policy predicate.

The script is self-contained: it creates the roles, database, schema, test
table, and tags it needs, and drops them on exit (unless --keep).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import snowflake.connector

from adapters.contract.types import AdapterConfig
from adapters.snowflake import SnowflakeAdapter


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = REPO_ROOT / "spec" / "v0" / "examples"
AUTH = REPO_ROOT / "snowflake_auth.txt"

ACCOUNT = "XOPZIEO-ZO85767"
USER = "BRICEGDB02"
WAREHOUSE = "COMPUTE_WH"

DB, SCHEMA = "TESSERA_VERIFY", "ABAC"
FQ = f"{DB}.{SCHEMA}"
TABLE = f"{FQ}.ABAC_VERIFY_ORDERS"
COL_TAG = f"{FQ}.TESSERA_ABAC_COL"   # tags O_CLERK → drives the column mask
ROW_TAG = f"{FQ}.TESSERA_ABAC_ROW"   # tags the TABLE → drives the row filter
CREATED_ROLES = ("ACME_ALL_PRIORITY_OPS", "ACME_HIGH_PRIORITY_OPS")
ROLES = CREATED_ROLES + ("PUBLIC",)


def _x(cur, sql: str, quiet: bool = True):
    if not quiet:
        print(">>", sql.splitlines()[0][:96])
    cur.execute(sql)
    return cur.fetchall()


def _setup(cur) -> None:
    print("=== setup: db / schema / roles / table / tags ===")
    _x(cur, f"USE WAREHOUSE {WAREHOUSE}")
    _x(cur, f"CREATE DATABASE IF NOT EXISTS {DB}")
    _x(cur, f"CREATE SCHEMA IF NOT EXISTS {FQ}")
    for r in CREATED_ROLES:
        _x(cur, f"CREATE ROLE IF NOT EXISTS {r}")
        _x(cur, f"GRANT ROLE {r} TO USER {USER}")
    # The discriminator column is named to match the row policy's matching value
    # ('orderpriority'); the adapter emits ON (orderpriority VARCHAR).
    _x(cur, f"""CREATE OR REPLACE TABLE {TABLE} AS
        SELECT O_ORDERKEY, O_CLERK, O_ORDERPRIORITY AS orderpriority, O_TOTALPRICE
        FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS SAMPLE (2000 ROWS)""")
    _x(cur, f"CREATE TAG IF NOT EXISTS {COL_TAG}")
    _x(cur, f"CREATE TAG IF NOT EXISTS {ROW_TAG}")
    _x(cur, f"ALTER TABLE {TABLE} ALTER COLUMN O_CLERK SET TAG {COL_TAG} = 'clerk'")  # column-level
    _x(cur, f"ALTER TABLE {TABLE} SET TAG {ROW_TAG} = 'orderpriority'")               # TABLE-level
    for r in ROLES:
        for g in (f"GRANT USAGE ON DATABASE {DB} TO ROLE {r}",
                  f"GRANT USAGE ON SCHEMA {FQ} TO ROLE {r}",
                  f"GRANT USAGE ON WAREHOUSE {WAREHOUSE} TO ROLE {r}",
                  f"GRANT SELECT ON TABLE {TABLE} TO ROLE {r}"):
            _x(cur, g)


def _emit_apply(cur, fname: str, config: AdapterConfig) -> None:
    print(f"\n=== emit + apply: {fname} ===")
    result = SnowflakeAdapter(config=config).emit(json.loads((EXAMPLES / fname).read_text()))
    for d in result.diagnostics:
        print(f"   [{d.severity.value}] {d.code}: {d.message}")
    if result.has_errors:
        raise SystemExit("emission errors; refusing to execute")
    for stmt in result.statements:
        print(stmt)
        _x(cur, stmt)


def _use(cur, role: str) -> None:
    cur.execute(f"USE ROLE {role}")
    cur.execute(f"USE WAREHOUSE {WAREHOUSE}")
    cur.execute("USE SECONDARY ROLES NONE")


def _verify(cur) -> None:
    print("\n=== VERIFY column mask (O_CLERK) ===")
    for role in ("ACME_ALL_PRIORITY_OPS", "PUBLIC"):
        _use(cur, role)
        sample = [c[0] for c in _x(cur, f"SELECT DISTINCT O_CLERK FROM {TABLE} LIMIT 3")]
        expect = "real values" if role == "ACME_ALL_PRIORITY_OPS" else "'CLERK-REDACTED'"
        print(f"  {role}: {sample}   (expect {expect})")

    print("\n=== VERIFY row filter (orderpriority) ===")
    expect = {"ACME_ALL_PRIORITY_OPS": "all", "ACME_HIGH_PRIORITY_OPS": "1-URGENT/2-HIGH",
              "PUBLIC": "3-MEDIUM/4-NOT SPECIFIED/5-LOW"}
    for role in ROLES:
        _use(cur, role)
        rows = _x(cur, f"SELECT orderpriority, COUNT(*) FROM {TABLE} GROUP BY 1 ORDER BY 1")
        print(f"  {role}: total={sum(r[1] for r in rows)} -> "
              f"{dict((r[0], r[1]) for r in rows)}   (expect {expect[role]})")


def _cleanup(cur) -> None:
    print("\n=== cleanup ===")
    cur.execute("USE ROLE ACCOUNTADMIN")
    cur.execute(f"USE WAREHOUSE {WAREHOUSE}")
    _x(cur, f"DROP DATABASE IF EXISTS {DB}")  # cascades: table, tags, policies
    for r in CREATED_ROLES:
        _x(cur, f"DROP ROLE IF EXISTS {r}")
    print("   done.")


def main() -> None:
    keep = "--keep" in sys.argv
    conn = snowflake.connector.connect(
        account=ACCOUNT, user=USER, password=AUTH.read_text().strip(),
        role="ACCOUNTADMIN", warehouse=WAREHOUSE,
    )
    cur = conn.cursor()
    try:
        _setup(cur)
        _emit_apply(cur, "abac-column-mask-policy-a.jsonld", AdapterConfig(
            identity_bindings={"group:acme_all_priority_ops": "ACME_ALL_PRIORITY_OPS"},
            tag_taxonomy={("sensitivity", "acme:PIIClerk"): (COL_TAG, "clerk")},
            extras={"abac_policy_schema": FQ}))
        _emit_apply(cur, "abac-row-filter-priority.jsonld", AdapterConfig(
            identity_bindings={"group:acme_all_priority_ops": "ACME_ALL_PRIORITY_OPS",
                               "group:acme_high_priority_ops": "ACME_HIGH_PRIORITY_OPS"},
            tag_taxonomy={("acme:rowDiscriminator", "orderpriority"): (ROW_TAG, "orderpriority")},
            extras={"abac_policy_schema": FQ}))
        _verify(cur)
    finally:
        if keep:
            print("\n(--keep) leaving test objects in place.")
        else:
            _cleanup(cur)
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
