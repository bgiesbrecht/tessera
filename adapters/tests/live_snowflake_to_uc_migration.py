"""Snowflake → UC migration end-to-end:

    1. Discover deployed policies on BRICETEST.TESSERA via SnowflakeAdapter.discover.
    2. Extract each into Tessera IR via SnowflakeAdapter.extract.
    3. Validate extracted IRs against schema + SHACL.
    4. Emit equivalent Databricks DDL via UnityCatalogAdapter.emit, using bindings
       that map Snowflake-side identifiers to their Databricks counterparts.
    5. Deploy the migrated DDL on Databricks (Phase 4) — provision prerequisite
       tables/ACL data, drop existing row filters and column masks on the
       targets, apply the new DDL.
    6. Verify behavior (Phase 5): confirm SHOW GRANTS / row counts / column
       values match the policy intent.
"""

from __future__ import annotations

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


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "spec" / "v0" / "schema.json"
SHAPES_PATH = REPO_ROOT / "spec" / "v0" / "shapes.ttl"
ONTOLOGY_PATH = REPO_ROOT / "spec" / "v0" / "ontology.ttl"
CONTEXT_PATH = REPO_ROOT / "spec" / "v0" / "context.jsonld"

AUTH_PATH = Path.home() / "snowflake_auth.txt"

ACCOUNT = "FBGQMMZ-DCC90967"
USER = "BGIESBRECHT"
WAREHOUSE = "COMPUTE_WH"
DATABASE = "BRICETEST"
SCHEMA = "TESSERA"


def main() -> None:
    schema = json.loads(SCHEMA_PATH.read_text())
    shapes = Graph(); shapes.parse(str(SHAPES_PATH), format="turtle")
    onto   = Graph(); onto.parse(str(ONTOLOGY_PATH), format="turtle")
    local_ctx = f"file://{CONTEXT_PATH.resolve()}"

    pw = AUTH_PATH.read_text().strip()
    conn = snowflake.connector.connect(
        account=ACCOUNT, user=USER, password=pw,
        warehouse=WAREHOUSE, database=DATABASE, schema=SCHEMA, role="ACCOUNTADMIN",
    )
    cur = conn.cursor()

    sf = SnowflakeAdapter(config=AdapterConfig(
        extras={
            "discover_database": DATABASE,
            "discover_schema": SCHEMA,
            "snowflake_cursor": cur,
        },
    ))

    print("=== Phase 1: discover deployed policies on BRICETEST.TESSERA ===\n")
    disc = sf.discover()
    for d in disc.diagnostics:
        print(f"  [{d.severity.value}] {d.code}: {d.message[:160]}")
    for art in disc.artifacts:
        attachments = "; ".join(
            f"{a.get('REF_ENTITY_NAME')}"
            + (f".{a.get('REF_COLUMN_NAME')}" if a.get('REF_COLUMN_NAME') else "")
            for a in art["attachments"]
        )
        print(f"  • [{art['kind']}] {art['fq_name']}  →  {attachments or '<no attachments>'}")
    print()

    # Bindings translate Snowflake-side identifiers to Databricks-side identifiers.
    # Includes the ACL mapping-table references (data tables) which the byDataset
    # policy's body reaches into — migration requires either remapping these
    # references or migrating the data; here we remap and migrate the data
    # alongside.
    uc_config = AdapterConfig(
        identity_bindings={
            "group:bg_rls_demo_all_priority_ops":   "bg_rls_demo_all_priority_ops",
            "group:bg_rls_demo_high_priority_ops":  "bg_rls_demo_high_priority_ops",
            "group:public":                         "account users",
        },
        resource_bindings={
            "table:BRICETEST.TESSERA.SNOW_ORDERS":            "bg_rls_demo.tpch.orders",
            "table:BRICETEST.TESSERA.SNOW_ORDERS_RLS_ACL":    "bg_rls_demo.tpch.orders_rls_acl",
            "column:BRICETEST.TESSERA.SNOW_ORDERS.o_clerk":   "bg_rls_demo.tpch.orders.o_clerk",
            # ACL data-table references inside the byDataset policy body
            "table:BRICETEST.TESSERA.RLS_ACL_MAPPING":        "bg_rls_demo.tpch.rls_acl_mapping",
            "table:BRICETEST.TESSERA.RLS_PRIORITY_ACL":       "bg_rls_demo.tpch.rls_priority_acl",
        },
    )
    uc = UnityCatalogAdapter(config=uc_config)

    print("=== Phase 2: extract each Snowflake policy to Tessera IR ===\n")
    extracted: list[dict] = []
    for art in disc.artifacts:
        r = sf.extract(art)
        print(f"--- {art['fq_name']} ---")
        print(f"  confidence: {r.confidence}")
        for d in r.diagnostics:
            print(f"  [{d.severity.value}] {d.code}: {d.message[:200]}")
        if r.policy is None:
            print("  (no policy extracted)\n")
            continue

        # Validate the extracted IR
        try:
            jsonschema.validate(r.policy, schema)
            schema_ok = "OK"
        except jsonschema.ValidationError as e:
            schema_ok = f"FAIL: {e.message[:160]}"
        # SHACL via JSON-LD round-trip through rdflib
        try:
            tmp_doc = dict(r.policy); tmp_doc["@context"] = local_ctx
            with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonld", delete=False) as tf:
                json.dump(tmp_doc, tf); tmp = tf.name
            data = Graph(); data.parse(tmp, format="json-ld")
            conforms, _, msg = shacl_validate(
                data_graph=data, shacl_graph=shapes, ont_graph=onto, inference="none")
            shacl_ok = "OK" if conforms else f"FAIL: {msg[:160]}"
        except Exception as e:
            shacl_ok = f"FAIL: {e}"
        print(f"  schema: {schema_ok}")
        print(f"  shacl:  {shacl_ok}")

        # Print IR (compact, skip @context)
        printed = {k: v for k, v in r.policy.items() if k != "@context"}
        print("  IR:", json.dumps(printed, indent=2)[:800])
        print()

        extracted.append(r.policy)

    print("=== Phase 3: emit Databricks DDL via UC adapter ===\n")
    all_uc_statements: list[tuple[str, list[str]]] = []
    for policy in extracted:
        em = uc.emit(policy)
        print(f"--- {policy['@id']} ---")
        for d in em.diagnostics:
            print(f"  [{d.severity.value}] {d.code}: {d.message[:160]}")
        if em.has_errors:
            print("  (emission errors; skipping statements)\n")
            continue
        for stmt in em.statements:
            print(stmt)
            print()
        all_uc_statements.append((policy["@id"], em.statements))

    cur.close()
    conn.close()

    print("\n=== Phase 4: deploy migrated DDL on Databricks ===\n")
    _deploy_on_databricks(all_uc_statements)


def _deploy_on_databricks(stmt_batches: list[tuple[str, list[str]]]) -> None:
    """Provision prereqs, drop existing attachments, apply the migrated DDL."""
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementState

    PROFILE = "adb-984752964297111"
    WAREHOUSE_ID = "148ccb90800933a1"
    w = WorkspaceClient(profile=PROFILE)

    def run(sql: str, *, ignore_errors: bool = False):
        r = w.statement_execution.execute_statement(
            warehouse_id=WAREHOUSE_ID, statement=sql, wait_timeout="30s",
        )
        while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
            r = w.statement_execution.get_statement(r.statement_id)
        if r.status.state != StatementState.SUCCEEDED:
            if ignore_errors:
                return None
            raise RuntimeError(f"SQL failed: {sql[:80]} -> {r.status.error}")
        return r.result.data_array if r.result else None

    print("Prereqs (idempotent provisioning) …")
    for stmt in [
        "CREATE CATALOG IF NOT EXISTS bg_rls_demo",
        "CREATE SCHEMA IF NOT EXISTS bg_rls_demo.tpch",
        "CREATE TABLE IF NOT EXISTS bg_rls_demo.tpch.orders AS "
        "  SELECT * FROM samples.tpch.orders",
        "CREATE OR REPLACE TABLE bg_rls_demo.tpch.orders_rls_acl AS "
        "  SELECT * FROM samples.tpch.orders",
        # Migrate the ACL mapping data from Snowflake to Databricks. The migration
        # tooling has to bring the data the policy body reaches into; the IR's
        # resource_bindings remap the references but the rows themselves need to
        # exist on the target platform.
        "CREATE OR REPLACE TABLE bg_rls_demo.tpch.rls_acl_mapping ("
        "  username STRING, code_name STRING)",
        "INSERT INTO bg_rls_demo.tpch.rls_acl_mapping VALUES "
        "  ('BGIESBRECHT', 'urgent_priority_ops'),"
        "  ('BGIESBRECHT', 'high_priority_ops'),"
        "  ('brice.giesbrecht@databricks.com', 'urgent_priority_ops'),"
        "  ('brice.giesbrecht@databricks.com', 'high_priority_ops')",
        "CREATE OR REPLACE TABLE bg_rls_demo.tpch.rls_priority_acl ("
        "  code_name STRING, o_orderpriority STRING)",
        "INSERT INTO bg_rls_demo.tpch.rls_priority_acl VALUES "
        "  ('urgent_priority_ops', '1-URGENT'),"
        "  ('high_priority_ops', '2-HIGH'),"
        "  ('standard_ops', '3-MEDIUM'),"
        "  ('standard_ops', '4-NOT SPECIFIED'),"
        "  ('standard_ops', '5-LOW')",
    ]:
        try:
            run(stmt)
            print(f"  OK: {stmt[:80]}…")
        except Exception as e:
            print(f"  FAIL: {stmt[:80]}… -> {str(e).splitlines()[0][:160]}")

    print("\nDrop any existing attachments on the targets …")
    for stmt in [
        "ALTER TABLE bg_rls_demo.tpch.orders DROP ROW FILTER",
        "ALTER TABLE bg_rls_demo.tpch.orders ALTER COLUMN o_clerk DROP MASK",
        "ALTER TABLE bg_rls_demo.tpch.orders_rls_acl DROP ROW FILTER",
    ]:
        run(stmt, ignore_errors=True)
        print(f"  attempted: {stmt}")

    print("\nApply migrated DDL …")
    for policy_id, statements in stmt_batches:
        print(f"  -- {policy_id} --")
        for stmt in statements:
            head = stmt.splitlines()[0]
            try:
                run(stmt)
                print(f"    OK: {head[:100]}")
            except RuntimeError as e:
                print(f"    FAIL: {head[:100]} -> {str(e).splitlines()[0][:200]}")

    print("\n=== Phase 5: verify behavior on Databricks ===\n")
    print("Row counts on bg_rls_demo.tpch.orders (was: ABAC-policy filtered):")
    try:
        rows = run("SELECT o_orderpriority, COUNT(*) FROM bg_rls_demo.tpch.orders GROUP BY 1 ORDER BY 1")
        for r in rows or []:
            print(f"  {r[0]}: {r[1]}")
    except Exception as e:
        print(f"  (query failed: {e})")

    print("\nRow counts on bg_rls_demo.tpch.orders_rls_acl (byDataset filter applied):")
    try:
        rows = run("SELECT o_orderpriority, COUNT(*) FROM bg_rls_demo.tpch.orders_rls_acl GROUP BY 1 ORDER BY 1")
        for r in rows or []:
            print(f"  {r[0]}: {r[1]}")
    except Exception as e:
        print(f"  (query failed: {e})")

    print("\nDistinct o_clerk on bg_rls_demo.tpch.orders (mask should hide values unless in group):")
    try:
        rows = run("SELECT DISTINCT o_clerk FROM bg_rls_demo.tpch.orders LIMIT 5")
        for r in rows or []:
            print(f"  {r[0]}")
    except Exception as e:
        print(f"  (query failed: {e})")

    print("\nMembership probe:")
    try:
        rows = run(
            "SELECT "
            "is_account_group_member('bg_rls_demo_all_priority_ops') AS all_priority, "
            "is_account_group_member('bg_rls_demo_high_priority_ops') AS high_priority, "
            "is_account_group_member('account users') AS account_users"
        )
        if rows:
            print(f"  {rows[0]}")
    except Exception as e:
        print(f"  (query failed: {e})")


if __name__ == "__main__":
    main()
