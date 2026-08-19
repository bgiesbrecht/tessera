"""Live integration test: byDataset row visibility on Oracle (VPD).

Phase-3 verification for the Oracle adapter (ADR-033), the counterpart to
live_snowflake_bydataset.py. It:
    1. Sets up the protected table and the two ACL tables in the connecting schema.
    2. Seeds the ACL data (same shape as the Snowflake/UC exercises).
    3. Emits Oracle DDL via OracleAdapter from
       spec/v0/examples/acl-row-visibility-policy.jsonld.
    4. Applies the VPD policy function + DBMS_RLS.ADD_POLICY.
    5. Verifies visibility changes as ACL rows are added/removed.

Connection: reads the password from `oracle_auth.txt` at the repo root (gitignored,
never committed), and the user + DSN from TESSERA_ORA_USER / TESSERA_ORA_DSN (or the
constants below). Requires `pip install oracledb`. This script is gated on a real
Oracle instance; it is not part of the offline pytest suite.

Note on identifiers: the committed example targets acme.tpch.orders_rls_acl, which
the adapter maps to Oracle TPCH.ORDERS_RLS_ACL. This script overrides the object
binding to the connecting schema via AdapterConfig.resource_bindings so it runs in a
single user's schema without needing a TPCH schema.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import oracledb

from adapters.contract.types import AdapterConfig
from adapters.oracle import OracleAdapter


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = REPO_ROOT / "spec" / "v0" / "examples"
AUTH = REPO_ROOT / "oracle_auth.txt"

USER = os.environ.get("TESSERA_ORA_USER", "TESSERA")
DSN = os.environ.get("TESSERA_ORA_DSN", "localhost:1521/XEPDB1")
SCHEMA = USER.upper()

PROTECTED = f"{SCHEMA}.ORDERS_RLS_ACL"
MAPPING = f"{SCHEMA}.RLS_ACL_MAPPING"
PRIORITY_ACL = f"{SCHEMA}.RLS_PRIORITY_ACL"


def main() -> None:
    pw = AUTH.read_text().strip()
    conn = oracledb.connect(user=USER, password=pw, dsn=DSN)
    cur = conn.cursor()

    def run(sql: str, ignore: bool = False) -> None:
        try:
            cur.execute(sql)
        except Exception as e:  # noqa: BLE001
            if not ignore:
                raise
            print(f"  skip: {sql.splitlines()[0][:60]}... -> {str(e).splitlines()[0]}")

    print("=== Setup: protected table + ACL tables + seed ===")
    # DBMS_RLS policy must be dropped before the table.
    run(f"BEGIN DBMS_RLS.DROP_POLICY('{SCHEMA}','ORDERS_RLS_ACL','TESSERA_ACL_ROW_VISIBILITY'); "
        "EXCEPTION WHEN OTHERS THEN NULL; END;", ignore=True)
    for stmt in [
        f"DROP TABLE {PROTECTED}",
        f"DROP TABLE {MAPPING}",
        f"DROP TABLE {PRIORITY_ACL}",
    ]:
        run(stmt, ignore=True)
    for stmt in [
        f"CREATE TABLE {PROTECTED} (o_orderkey NUMBER, orderpriority VARCHAR2(20))",
        f"CREATE TABLE {MAPPING} (username VARCHAR2(100), code_name VARCHAR2(50))",
        f"CREATE TABLE {PRIORITY_ACL} (code_name VARCHAR2(50), orderpriority VARCHAR2(20))",
        f"INSERT INTO {PROTECTED} VALUES (1, '1-URGENT')",
        f"INSERT INTO {PROTECTED} VALUES (2, '2-HIGH')",
        f"INSERT INTO {PROTECTED} VALUES (3, '3-MEDIUM')",
        f"INSERT INTO {PROTECTED} VALUES (4, '4-NOT SPECIFIED')",
        f"INSERT INTO {PROTECTED} VALUES (5, '5-LOW')",
        f"INSERT INTO {PRIORITY_ACL} VALUES ('urgent_priority_ops', '1-URGENT')",
        f"INSERT INTO {PRIORITY_ACL} VALUES ('high_priority_ops', '2-HIGH')",
        f"INSERT INTO {PRIORITY_ACL} VALUES ('standard_ops', '3-MEDIUM')",
        f"INSERT INTO {PRIORITY_ACL} VALUES ('standard_ops', '4-NOT SPECIFIED')",
        f"INSERT INTO {PRIORITY_ACL} VALUES ('standard_ops', '5-LOW')",
        f"INSERT INTO {MAPPING} VALUES ('{USER}', 'urgent_priority_ops')",
        f"INSERT INTO {MAPPING} VALUES ('{USER}', 'high_priority_ops')",
    ]:
        run(stmt)
    conn.commit()
    print("  setup complete")

    print("\n=== Emit DDL via adapter ===")
    policy = json.loads((EXAMPLES / "acl-row-visibility-policy.jsonld").read_text())
    # Bind the Tessera table IRIs to this schema's objects.
    config = AdapterConfig(resource_bindings={
        "table:acme.tpch.orders_rls_acl": PROTECTED,
        "table:acme.tpch.rls_acl_mapping": MAPPING,
        "table:acme.tpch.rls_priority_acl": PRIORITY_ACL,
    })
    result = OracleAdapter(config).emit(policy)
    for d in result.diagnostics:
        print(f"  [{d.severity.value}] {d.code}: {d.message[:120]}")
    for s in result.statements:
        print(s + "\n")
    if result.has_errors:
        raise SystemExit("emission errors; refusing to execute")

    print("=== Apply DDL ===")
    for stmt in result.statements:
        # oracledb executes one statement at a time; strip the PL/SQL '/' terminator.
        body = stmt.rstrip().removesuffix("/").rstrip()
        print(">>", body.splitlines()[0])
        cur.execute(body)
    conn.commit()

    def visible() -> int:
        cur.execute(f"SELECT COUNT(*) FROM {PROTECTED}")
        return int(cur.fetchone()[0])

    print("\n=== Scenario 1: seed (urgent+high) ⇒ 2 rows visible ===")
    print("  visible:", visible())
    print("\n=== Scenario 2: add standard_ops ⇒ 5 rows ===")
    cur.execute(f"INSERT INTO {MAPPING} VALUES ('{USER}', 'standard_ops')"); conn.commit()
    print("  visible:", visible())
    print("\n=== Scenario 3: remove all mappings ⇒ 0 rows (fail-closed) ===")
    cur.execute(f"DELETE FROM {MAPPING} WHERE username = '{USER}'"); conn.commit()
    print("  visible:", visible())

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
