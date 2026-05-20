"""Snowflake → UC migration end-to-end:

    1. Discover deployed policies on BRICETEST.TESSERA via SnowflakeAdapter.discover.
    2. Extract each into Tessera IR via SnowflakeAdapter.extract.
    3. Validate extracted IRs against schema + SHACL.
    4. Emit equivalent Databricks DDL via UnityCatalogAdapter.emit, using bindings
       that map Snowflake-side identifiers to their Databricks counterparts.
    5. Print the resulting DDL — the SQL that would be run on Databricks to
       reproduce the policies on Unity Catalog.

If a Databricks SDK session is available and unblocked, the script can also
apply the DDL and verify behavior; that step is deferred to a follow-up.
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

    # Bindings that translate Snowflake identifiers to Databricks identifiers
    # for the migration. The Snowflake side used UPPER_CASE roles and database
    # qualifiers; Databricks uses lowercase group names + the bg_rls_demo catalog.
    uc_config = AdapterConfig(
        identity_bindings={
            "group:bg_rls_demo_all_priority_ops":   "bg_rls_demo_all_priority_ops",
            "group:bg_rls_demo_high_priority_ops":  "bg_rls_demo_high_priority_ops",
            "group:public":                         "account users",
        },
        resource_bindings={
            "table:BRICETEST.TESSERA.SNOW_ORDERS":           "bg_rls_demo.tpch.orders",
            "table:BRICETEST.TESSERA.SNOW_ORDERS_RLS_ACL":   "bg_rls_demo.tpch.orders_rls_acl",
            "column:BRICETEST.TESSERA.SNOW_ORDERS.o_clerk":  "bg_rls_demo.tpch.orders.o_clerk",
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

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
