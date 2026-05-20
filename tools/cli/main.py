"""Tessera CLI — unified command surface over the converter + adapters.

Subcommands:

    validate  <file>                          — JSON Schema + SHACL on a YAML or JSON-LD policy
    convert   <file> [--out PATH]             — YAML → JSON-LD
    emit      <file> --adapter NAME [--config bindings.yaml]
                                              — produce platform DDL
    discover  --adapter NAME [scope args]     — inventory deployed policies
    extract   --adapter NAME [scope args] [--name N]
                                              — discover + lift each (or one) artifact to IR
    reconcile --adapter NAME [scope args] --intended PATH
                                              — diff intended IR against deployed state

Platform connection details:

    Databricks   — pass `--profile <profile>` and `--warehouse-id <id>`, or set
                   TESSERA_DB_PROFILE and TESSERA_DB_WAREHOUSE in the environment.
                   The Databricks SDK handles the auth.

    Snowflake    — pass `--account`, `--user`, `--warehouse`, `--database`, and
                   `--auth-file`, or set TESSERA_SF_* env vars. The auth file
                   contents are read as the password.

Bindings file format (YAML), passed via `--config`:

    identity_bindings:
      "group:foo": "FOO_ROLE"
    resource_bindings:
      "table:src.s.t": "tgt.s.t"
    tag_taxonomy:
      ["sensitivityAxis", "PII"]: ["classification", "pii"]
    extras:
      warehouse: COMPUTE_WH

All subcommands print structured output. Use `--json` to get machine-readable
output where it applies; otherwise the format is human-friendly.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

# Resolve the repo root so spec files are findable regardless of cwd.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

SCHEMA_PATH = REPO_ROOT / "spec" / "v0" / "schema.json"
SHAPES_PATH = REPO_ROOT / "spec" / "v0" / "shapes.ttl"
ONTOLOGY_PATH = REPO_ROOT / "spec" / "v0" / "ontology.ttl"
CONTEXT_PATH = REPO_ROOT / "spec" / "v0" / "context.jsonld"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_policy_dict(path: str | Path) -> dict[str, Any]:
    """Read a policy file. If it's a `.tessera.yaml`, convert to JSON-LD; if
    it's a `.jsonld` (or `.json`), load directly."""
    p = Path(path)
    if str(p).endswith(".tessera.yaml") or p.suffix in (".yaml", ".yml"):
        from tools.converter import yaml_to_jsonld
        return yaml_to_jsonld(p)
    return json.loads(p.read_text())


def _load_bindings_config(config_path: str | None) -> "AdapterConfig":
    from adapters.contract.types import AdapterConfig
    if not config_path:
        return AdapterConfig()
    from ruamel.yaml import YAML
    yaml = YAML(typ="safe")
    data = yaml.load(Path(config_path).read_text()) or {}
    return AdapterConfig(
        identity_bindings=data.get("identity_bindings", {}) or {},
        resource_bindings=data.get("resource_bindings", {}) or {},
        tag_taxonomy={
            tuple(k): tuple(v) for k, v in (data.get("tag_taxonomy", {}) or {}).items()
        },
        extras=data.get("extras", {}) or {},
    )


def _print_diagnostics(diagnostics: list[Any], *, prefix: str = "  ") -> int:
    """Print diagnostics; return count of ERROR-severity ones."""
    errs = 0
    for d in diagnostics:
        sev = d.severity.value
        if sev == "error":
            errs += 1
        print(f"{prefix}[{sev}] {d.code}: {d.message}")
    return errs


def _build_adapter(name: str, config) -> Any:
    if name in ("unity-catalog", "uc", "databricks"):
        from adapters.unity_catalog import UnityCatalogAdapter
        return UnityCatalogAdapter(config=config)
    if name in ("snowflake", "sf"):
        from adapters.snowflake import SnowflakeAdapter
        return SnowflakeAdapter(config=config)
    raise SystemExit(f"error: unknown adapter {name!r}; expected unity-catalog or snowflake")


def _attach_databricks_sql(config, profile: str | None, warehouse: str | None):
    """Mutate config.extras to include a `run_sql` callable for UC discover/reconcile."""
    profile = profile or os.environ.get("TESSERA_DB_PROFILE")
    warehouse = warehouse or os.environ.get("TESSERA_DB_WAREHOUSE")
    if not (profile and warehouse):
        raise SystemExit(
            "error: Databricks connection needs --profile and --warehouse-id "
            "(or TESSERA_DB_PROFILE and TESSERA_DB_WAREHOUSE env vars)."
        )
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementState
    w = WorkspaceClient(profile=profile)

    def run_sql(sql: str):
        r = w.statement_execution.execute_statement(
            warehouse_id=warehouse, statement=sql, wait_timeout="30s",
        )
        while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
            r = w.statement_execution.get_statement(r.statement_id)
        if r.status.state != StatementState.SUCCEEDED:
            raise RuntimeError(f"SQL failed: {sql[:80]} -> {r.status.error}")
        return r.result.data_array if r.result else None

    config.extras["run_sql"] = run_sql


def _attach_snowflake_cursor(config, *, account, user, warehouse, database, auth_file):
    account   = account   or os.environ.get("TESSERA_SF_ACCOUNT")
    user      = user      or os.environ.get("TESSERA_SF_USER")
    warehouse = warehouse or os.environ.get("TESSERA_SF_WAREHOUSE")
    database  = database  or os.environ.get("TESSERA_SF_DATABASE")
    auth_file = auth_file or os.environ.get("TESSERA_SF_AUTH_FILE") or str(Path.home() / "snowflake_auth.txt")
    missing = [k for k, v in {
        "--account": account, "--user": user, "--warehouse": warehouse, "--database": database,
    }.items() if not v]
    if missing:
        raise SystemExit(
            f"error: Snowflake connection missing {', '.join(missing)} "
            f"(or set TESSERA_SF_ACCOUNT/USER/WAREHOUSE/DATABASE)."
        )
    pw = Path(auth_file).read_text().strip()
    import snowflake.connector
    conn = snowflake.connector.connect(
        account=account, user=user, password=pw,
        warehouse=warehouse, database=database, role="ACCOUNTADMIN",
    )
    cur = conn.cursor()
    config.extras["snowflake_cursor"] = cur
    return conn, cur


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_validate(args: argparse.Namespace) -> int:
    import jsonschema
    from rdflib import Graph
    from pyshacl import validate as shacl_validate

    doc = _load_policy_dict(args.file)
    schema = json.loads(SCHEMA_PATH.read_text())
    try:
        jsonschema.validate(doc, schema)
        print(f"schema: OK")
    except jsonschema.ValidationError as e:
        print(f"schema: FAIL — {e.message}")
        return 2

    shapes = Graph(); shapes.parse(str(SHAPES_PATH), format="turtle")
    onto = Graph(); onto.parse(str(ONTOLOGY_PATH), format="turtle")
    local_ctx = f"file://{CONTEXT_PATH.resolve()}"
    doc_with_ctx = dict(doc); doc_with_ctx["@context"] = local_ctx
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonld", delete=False) as tf:
        json.dump(doc_with_ctx, tf); tmp = tf.name
    data = Graph(); data.parse(tmp, format="json-ld")
    conforms, _, msg = shacl_validate(
        data_graph=data, shacl_graph=shapes, ont_graph=onto, inference="none")
    if not conforms:
        print(f"shacl: FAIL\n{msg}")
        return 2
    print(f"shacl: OK")
    print(f"\n{args.file}: validates clean.")
    return 0


def cmd_convert(args: argparse.Namespace) -> int:
    from tools.converter import yaml_to_jsonld
    doc = yaml_to_jsonld(args.file)
    payload = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        Path(args.out).write_text(payload)
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(payload)
    return 0


def cmd_emit(args: argparse.Namespace) -> int:
    policy = _load_policy_dict(args.file)
    config = _load_bindings_config(args.config)
    adapter = _build_adapter(args.adapter, config)
    result = adapter.emit(policy)

    if args.json:
        payload = {
            "policy_id": result.policy_id,
            "target_artifacts": result.target_artifacts,
            "statements": result.statements,
            "diagnostics": [
                {"severity": d.severity.value, "code": d.code, "message": d.message,
                 "location": d.location}
                for d in result.diagnostics
            ],
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        if result.diagnostics:
            print("Diagnostics:")
            _print_diagnostics(result.diagnostics)
            print()
        print("Statements:")
        for s in result.statements:
            print(s)
            print()
    return 1 if result.has_errors else 0


def cmd_discover(args: argparse.Namespace) -> int:
    config = _load_bindings_config(args.config)
    adapter = _build_adapter(args.adapter, config)
    sf_conn = None
    # Backfill scope args from env vars where applicable.
    catalog  = args.catalog  or os.environ.get("TESSERA_DB_CATALOG")
    schema   = args.schema   or os.environ.get("TESSERA_DB_SCHEMA") or os.environ.get("TESSERA_SF_SCHEMA")
    database = args.database or os.environ.get("TESSERA_SF_DATABASE")

    if args.adapter in ("unity-catalog", "uc", "databricks"):
        _attach_databricks_sql(config, args.profile, args.warehouse_id)
        if not catalog or not schema:
            raise SystemExit("error: --catalog and --schema are required for unity-catalog discover.")
        result = adapter.discover(catalog=catalog, schema=schema)
    else:
        sf_conn, _ = _attach_snowflake_cursor(
            config, account=args.account, user=args.user,
            warehouse=args.warehouse, database=database, auth_file=args.auth_file,
        )
        if not database or not schema:
            raise SystemExit("error: --database and --schema are required for snowflake discover.")
        result = adapter.discover(database=database, schema=schema)

    try:
        if args.json:
            payload = {
                "artifacts": result.artifacts,
                "diagnostics": [
                    {"severity": d.severity.value, "code": d.code, "message": d.message}
                    for d in result.diagnostics
                ],
            }
            sys.stdout.write(json.dumps(payload, indent=2, default=str) + "\n")
        else:
            if result.diagnostics:
                print("Diagnostics:")
                _print_diagnostics(result.diagnostics)
                print()
            print(f"Discovered {len(result.artifacts)} artifact(s):")
            for art in result.artifacts:
                attach = art.get("attachments") or [{}]
                a = attach[0]
                target = a.get("REF_ENTITY_NAME") or "<no attachment>"
                col = a.get("REF_COLUMN_NAME")
                if col:
                    target += f".{col}"
                print(f"  • [{art.get('kind')}] {art.get('fq_name') or art.get('name')}  →  {target}")
    finally:
        if sf_conn is not None:
            sf_conn.close()
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    config = _load_bindings_config(args.config)
    adapter = _build_adapter(args.adapter, config)
    sf_conn = None

    catalog  = args.catalog  or os.environ.get("TESSERA_DB_CATALOG")
    schema   = args.schema   or os.environ.get("TESSERA_DB_SCHEMA") or os.environ.get("TESSERA_SF_SCHEMA")
    database = args.database or os.environ.get("TESSERA_SF_DATABASE")

    if args.adapter in ("unity-catalog", "uc", "databricks"):
        _attach_databricks_sql(config, args.profile, args.warehouse_id)
        disc = adapter.discover(catalog=catalog, schema=schema)
    else:
        sf_conn, _ = _attach_snowflake_cursor(
            config, account=args.account, user=args.user,
            warehouse=args.warehouse, database=database, auth_file=args.auth_file,
        )
        disc = adapter.discover(database=database, schema=schema)

    try:
        if disc.diagnostics:
            _print_diagnostics(disc.diagnostics, prefix="discover: ")
        artifacts = disc.artifacts
        if args.name:
            artifacts = [a for a in disc.artifacts if args.name in (a.get("name", ""), a.get("fq_name", ""))]
            if not artifacts:
                print(f"error: no artifact named {args.name!r} found.", file=sys.stderr)
                return 2

        extracted: list[dict] = []
        for art in artifacts:
            r = adapter.extract(art)
            if r.policy:
                extracted.append(r.policy)
            if r.diagnostics:
                _print_diagnostics(r.diagnostics, prefix=f"extract({art.get('name')}): ")

        if args.out:
            for i, policy in enumerate(extracted):
                outname = Path(args.out) / f"{policy['@id'].split(':')[-1]}.jsonld"
                outname.parent.mkdir(parents=True, exist_ok=True)
                outname.write_text(json.dumps(policy, indent=2) + "\n")
                print(f"wrote {outname}")
        else:
            sys.stdout.write(json.dumps(extracted, indent=2, default=str) + "\n")
    finally:
        if sf_conn is not None:
            sf_conn.close()
    return 0


def cmd_reconcile(args: argparse.Namespace) -> int:
    config = _load_bindings_config(args.config)
    adapter = _build_adapter(args.adapter, config)
    sf_conn = None

    # Load the intended corpus
    intended_path = Path(args.intended)
    intended: list[dict] = []
    if intended_path.is_dir():
        candidates = list(intended_path.glob("*.jsonld")) + list(intended_path.glob("*.tessera.yaml"))
    else:
        candidates = [intended_path]
    for p in candidates:
        intended.append(_load_policy_dict(p))
    print(f"loaded {len(intended)} intended policies from {args.intended}")

    catalog  = args.catalog  or os.environ.get("TESSERA_DB_CATALOG")
    schema   = args.schema   or os.environ.get("TESSERA_DB_SCHEMA") or os.environ.get("TESSERA_SF_SCHEMA")
    database = args.database or os.environ.get("TESSERA_SF_DATABASE")

    if args.adapter in ("unity-catalog", "uc", "databricks"):
        _attach_databricks_sql(config, args.profile, args.warehouse_id)
        result = adapter.reconcile(intended, catalog=catalog, schema=schema)
    else:
        sf_conn, _ = _attach_snowflake_cursor(
            config, account=args.account, user=args.user,
            warehouse=args.warehouse, database=database, auth_file=args.auth_file,
        )
        result = adapter.reconcile(intended, database=database, schema=schema)

    try:
        print()
        print(f"Additions:     {len(result.additions)}")
        for a in result.additions:
            print(f"  + {a['key']}")
        print(f"Removals:      {len(result.removals)}")
        for r_ in result.removals:
            print(f"  - {r_['key']}")
        print(f"Modifications: {len(result.modifications)}")
        for m in result.modifications:
            print(f"  ~ {m['key']}: diff fields = {list(m['diff'].keys())}")
        if result.diagnostics:
            print(f"\nDiagnostics: {len(result.diagnostics)}")
            _print_diagnostics(result.diagnostics)
    finally:
        if sf_conn is not None:
            sf_conn.close()
    return 0


# ---------------------------------------------------------------------------
# Argparse wiring
# ---------------------------------------------------------------------------


def _add_databricks_conn_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", help="Databricks SDK profile name (or TESSERA_DB_PROFILE).")
    parser.add_argument("--warehouse-id", help="Databricks SQL warehouse id (or TESSERA_DB_WAREHOUSE).")


def _add_snowflake_conn_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--account",   help="Snowflake account locator (or TESSERA_SF_ACCOUNT).")
    parser.add_argument("--user",      help="Snowflake user (or TESSERA_SF_USER).")
    parser.add_argument("--warehouse", help="Snowflake warehouse (or TESSERA_SF_WAREHOUSE).")
    parser.add_argument("--auth-file", help="Path to file containing Snowflake password (or TESSERA_SF_AUTH_FILE; default ~/snowflake_auth.txt).")


def _add_scope_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--catalog",  help="Databricks catalog (UC adapter only).")
    parser.add_argument("--schema",   help="Databricks schema / Snowflake schema.")
    parser.add_argument("--database", help="Snowflake database (Snowflake adapter only).")


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tessera",
        description="Tessera CLI — convert, validate, emit, discover, extract, reconcile.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # validate
    v = sub.add_parser("validate", help="JSON Schema + SHACL on a policy file.")
    v.add_argument("file", help="Path to a .tessera.yaml or .jsonld file.")
    v.set_defaults(func=cmd_validate)

    # convert
    c = sub.add_parser("convert", help="YAML → JSON-LD.")
    c.add_argument("file", help="Path to a .tessera.yaml file.")
    c.add_argument("--out", help="Write JSON-LD here; default stdout.")
    c.set_defaults(func=cmd_convert)

    # emit
    e = sub.add_parser("emit", help="Produce platform DDL for a policy.")
    e.add_argument("file", help="Path to a .tessera.yaml or .jsonld file.")
    e.add_argument("--adapter", required=True, choices=["unity-catalog", "uc", "databricks", "snowflake", "sf"])
    e.add_argument("--config", help="Bindings YAML (identity_bindings, resource_bindings, tag_taxonomy, extras).")
    e.add_argument("--json", action="store_true", help="Emit machine-readable JSON to stdout.")
    e.set_defaults(func=cmd_emit)

    # discover
    d = sub.add_parser("discover", help="Inventory deployed policies on a platform.")
    d.add_argument("--adapter", required=True, choices=["unity-catalog", "uc", "databricks", "snowflake", "sf"])
    d.add_argument("--config", help="Bindings YAML.")
    d.add_argument("--json", action="store_true", help="Emit machine-readable JSON to stdout.")
    _add_databricks_conn_args(d)
    _add_snowflake_conn_args(d)
    _add_scope_args(d)
    d.set_defaults(func=cmd_discover)

    # extract
    x = sub.add_parser("extract", help="Discover then lift each artifact to Tessera IR.")
    x.add_argument("--adapter", required=True, choices=["unity-catalog", "uc", "databricks", "snowflake", "sf"])
    x.add_argument("--name", help="Extract only an artifact whose name matches (substring).")
    x.add_argument("--out", help="Write each extracted IR as <name>.jsonld in this directory; default stdout JSON.")
    x.add_argument("--config", help="Bindings YAML.")
    _add_databricks_conn_args(x)
    _add_snowflake_conn_args(x)
    _add_scope_args(x)
    x.set_defaults(func=cmd_extract)

    # reconcile
    r = sub.add_parser("reconcile", help="Diff intended IR (file or directory) against deployed state.")
    r.add_argument("--adapter", required=True, choices=["unity-catalog", "uc", "databricks", "snowflake", "sf"])
    r.add_argument("--intended", required=True, help="Path to an intended-IR file or directory of .tessera.yaml / .jsonld files.")
    r.add_argument("--config", help="Bindings YAML.")
    _add_databricks_conn_args(r)
    _add_snowflake_conn_args(r)
    _add_scope_args(r)
    r.set_defaults(func=cmd_reconcile)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
