# Running Tessera — End-to-End Demonstration

*Captured 2026-06-12 against Tessera `0.6.3`. Every command and output block below is a verbatim transcript from a real run on this repository — nothing is illustrative.*

This document shows the full offline pipeline: **author a policy in YAML → convert to canonical JSON-LD → validate (JSON Schema + SHACL) → emit platform-native enforcement DDL for two different platforms from the same intermediate representation.**

This demonstrates the core claim: *one policy, expressed once, lowered into the native enforcement mechanism of each platform by a per-platform adapter.* The same input produces a Databricks row-filter function and a Snowflake row-access policy.

---

## 0. Environment

The repo ships a `.venv` with the required dependencies. No build, no install step.

```text
$ .venv/bin/python --version
Python 3.13.7

$ .venv/bin/pip list | grep -iE "jsonschema|rdflib|ruamel|pyshacl|databricks-sdk|snowflake-connector"
databricks-sdk             0.109.0
jsonschema                 4.26.0
jsonschema-specifications  2025.9.1
pyshacl                    0.31.0
rdflib                     7.6.0
ruamel.yaml                0.19.1
snowflake-connector-python 4.5.0
```

The CLI surface:

```text
$ .venv/bin/python -m tools.cli.main --help
usage: tessera [-h] {validate,convert,emit,discover,extract,reconcile} ...

Tessera CLI — convert, validate, emit, discover, extract, reconcile.

positional arguments:
  {validate,convert,emit,discover,extract,reconcile}
    validate            JSON Schema + SHACL on a policy file.
    convert             YAML → JSON-LD.
    emit                Produce platform DDL for a policy.
    discover            Inventory deployed policies on a platform.
    extract             Discover then lift each artifact to Tessera IR.
    reconcile           Diff intended IR (file or directory) against deployed
                        state.
```

> `discover`, `extract`, and `reconcile` require live platform credentials and return structured *NOT_IMPLEMENTED* diagnostics for unsupported paths. The demonstration below uses the fully offline path: `convert`, `validate`, `emit`.

---

## 1. The policy, authored in YAML

This is the practitioner-facing form — what a customer or engineer writes and reviews. It expresses a three-branch row-visibility rule on `acme.tpch.orders`, driven by group membership, evaluated first-match (ADR-015).

```yaml
"@context": https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld
"@type": Policy
"@id": policy:group-row-visibility-policy-a
version: 1.0.0
policyKind: RowVisibilityConstraint
description: >
  Three-branch row visibility on acme.tpch.orders driven by group
  memberships. Default visibility (priorities 3-5) grounded in explicit
  membership in the Databricks universal group `account users`.

appliesTo:
  selector: byIdentity
  resource: table:acme.tpch.orders

action: Read

defaultStrategy: explicit-baseline-group
baselineGroup: "account users"

rules:
  # Rule A1 — "all priority ops" group sees every row.
  - principal:
      selector: byIdentity
      resource: group:acme_all_priority_ops
    effect: keep-matching-rows

  # Rule A2 — "high priority ops" group sees the high-priority rows.
  - principal:
      selector: byIdentity
      resource: group:acme_high_priority_ops
    effect: keep-matching-rows
    condition:
      op: in
      operands:
        - column:acme.tpch.orders.o_orderpriority
      values: ["1-URGENT", "2-HIGH"]

  # Rule A3 — baseline (`account users`) sees the lower-priority rows.
  - principal:
      selector: byIdentity
      resource: group:account-users
    effect: keep-matching-rows
    condition:
      op: in
      operands:
        - column:acme.tpch.orders.o_orderpriority
      values: ["3-MEDIUM", "4-NOT SPECIFIED", "5-LOW"]
```

*(Comments and provenance trimmed for the doc; the full file is at `spec/v0/examples/group-row-visibility-policy-a.tessera.yaml`.)*

---

## 2. Convert YAML → canonical JSON-LD

```text
$ .venv/bin/python -m tools.converter \
    spec/v0/examples/group-row-visibility-policy-a.tessera.yaml
```

```json
{
  "@context": "https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld",
  "@type": "Policy",
  "@id": "policy:group-row-visibility-policy-a",
  "version": "1.0.0",
  "policyKind": "RowVisibilityConstraint",
  "description": "Three-branch row visibility on acme.tpch.orders driven by group memberships. Default visibility (priorities 3-5) grounded in explicit membership in the Databricks universal group `account users`.",
  "appliesTo": {
    "selector": "byIdentity",
    "resource": "table:acme.tpch.orders"
  },
  "action": "Read",
  "defaultStrategy": "explicit-baseline-group",
  "baselineGroup": "account users",
  "rules": [
    {
      "principal": { "selector": "byIdentity", "resource": "group:acme_all_priority_ops" },
      "effect": "keep-matching-rows"
    },
    {
      "principal": { "selector": "byIdentity", "resource": "group:acme_high_priority_ops" },
      "effect": "keep-matching-rows",
      "condition": {
        "op": "in",
        "operands": ["column:acme.tpch.orders.o_orderpriority"],
        "values": ["1-URGENT", "2-HIGH"]
      }
    },
    {
      "principal": { "selector": "byIdentity", "resource": "group:account-users" },
      "effect": "keep-matching-rows",
      "condition": {
        "op": "in",
        "operands": ["column:acme.tpch.orders.o_orderpriority"],
        "values": ["3-MEDIUM", "4-NOT SPECIFIED", "5-LOW"]
      }
    }
  ]
}
```

---

## 3. Validate (JSON Schema + SHACL)

Structural validation (JSON Schema 2020-12) and semantic validation (SHACL shapes) run together:

```text
$ .venv/bin/python -m tools.cli.main validate \
    spec/v0/examples/group-row-visibility-policy-a.jsonld
schema: OK
shacl: OK

spec/v0/examples/group-row-visibility-policy-a.jsonld: validates clean.
```

---

## 4. Emit — the same policy, two platforms

The **identical** JSON-LD IR is lowered by two independent adapters into each platform's native enforcement mechanism.

### 4a. Databricks (Unity Catalog)

```text
$ .venv/bin/python -m tools.cli.main emit \
    spec/v0/examples/group-row-visibility-policy-a.jsonld --adapter uc
```

```sql
-- Statements:
CREATE OR REPLACE FUNCTION acme.tpch.orders__group_row_visibility_policy_a_filter(o_orderpriority STRING)
RETURNS BOOLEAN
RETURN
        is_account_group_member('acme_all_priority_ops')
        OR (is_account_group_member('acme_high_priority_ops') AND o_orderpriority IN ('1-URGENT', '2-HIGH'))
        OR (is_account_group_member('account-users') AND o_orderpriority IN ('3-MEDIUM', '4-NOT SPECIFIED', '5-LOW'));

ALTER TABLE acme.tpch.orders SET ROW FILTER acme.tpch.orders__group_row_visibility_policy_a_filter ON (o_orderpriority);
```

Databricks mechanism: a SQL UDF + `SET ROW FILTER`, principal binding via `is_account_group_member(...)`.

### 4b. Snowflake

```text
$ .venv/bin/python -m tools.cli.main emit \
    spec/v0/examples/group-row-visibility-policy-a.jsonld --adapter sf
```

```text
Diagnostics:
  [warning] UNBOUND_PRINCIPAL: rule 0: principal 'group:acme_all_priority_ops' has no identity_bindings entry. Snowflake roles are case-sensitive; without an explicit binding the adapter falls back to the IR slug, which may not resolve.
  [warning] UNBOUND_PRINCIPAL: rule 1: principal 'group:acme_high_priority_ops' has no identity_bindings entry. ...
  [warning] UNBOUND_PRINCIPAL: rule 2: principal 'group:account-users' has no identity_bindings entry. ...
```

```sql
-- Statements:
CREATE OR REPLACE ROW ACCESS POLICY acme.tpch.group_row_visibility_policy_a_rap
AS (o_orderpriority VARCHAR) RETURNS BOOLEAN ->
        IS_ROLE_IN_SESSION('ACME_ALL_PRIORITY_OPS')
        OR (IS_ROLE_IN_SESSION('ACME_HIGH_PRIORITY_OPS') AND o_orderpriority IN ('1-URGENT', '2-HIGH'))
        OR (IS_ROLE_IN_SESSION('ACCOUNT-USERS') AND o_orderpriority IN ('3-MEDIUM', '4-NOT SPECIFIED', '5-LOW'));

ALTER TABLE acme.tpch.orders ADD ROW ACCESS POLICY acme.tpch.group_row_visibility_policy_a_rap ON (o_orderpriority);
```

Snowflake mechanism: a `ROW ACCESS POLICY` object + `ADD ROW ACCESS POLICY`, principal binding via `IS_ROLE_IN_SESSION(...)`.

**What changed and what didn't.** The policy *meaning* — three branches, the same priority predicates, first-match order — is identical. The *mechanism* is entirely different: UDF vs. policy object, `is_account_group_member` vs. `IS_ROLE_IN_SESSION`, group slug vs. upper-cased role name. The diagnostics are first-class output: the Snowflake adapter flags that role names are case-sensitive and no explicit identity binding was configured, so it fell back to the IR slug. The adapter surfaces a real deployment risk rather than failing silently.

---

## 5. Breadth check — ABAC column mask on Databricks

To show the pipeline isn't limited to one policy shape, here is an attribute-based (ABAC) column-mask policy emitted for Databricks. It masks columns *by semantic attribute* (`sensitivity: PIIClerk`) rather than by name — meaning over mechanism (ADR-018–021).

```text
$ .venv/bin/python -m tools.cli.main emit \
    spec/v0/examples/abac-column-mask-policy-a.jsonld --adapter uc
```

```text
Diagnostics:
  [warning] UNBOUND_TAG_ATTRIBUTE: matching attribute ('sensitivity', 'PIIClerk') has no tag_taxonomy entry; falling back to has_tag_value('sensitivity', 'PIIClerk'). Configure config.tag_taxonomy for production.
  [info] ABAC_FUNCTION_SCHEMA_INFERRED: Function schema inferred as 'acme.tpch'; override via config.extras['abac_function_schema'] for production deployments.
```

```sql
-- Statements:
CREATE OR REPLACE FUNCTION acme.tpch.tessera__abac_column_mask_clerk_redact__mask(val STRING)
RETURNS STRING
RETURN 'CLERK-REDACTED';

GRANT EXECUTE ON FUNCTION acme.tpch.tessera__abac_column_mask_clerk_redact__mask TO `account users`;

CREATE OR REPLACE POLICY tessera__abac_column_mask_clerk_redact
  ON CATALOG acme
  COMMENT 'Tessera ABAC column mask — policy:abac-column-mask-clerk-redact'
  COLUMN MASK acme.tpch.tessera__abac_column_mask_clerk_redact__mask
    TO `account users`
    EXCEPT `acme_all_priority_ops`
    FOR TABLES
    MATCH COLUMNS has_tag_value('sensitivity', 'PIIClerk') AS PIIClerk
    ON COLUMN PIIClerk;
```

This is the modern Databricks ABAC pattern (`CREATE POLICY ... COLUMN MASK ... MATCH COLUMNS`), driven entirely from the semantic attribute carried in the IR.

---

## What this run demonstrates

| Step | Command | What it proves |
|------|---------|----------------|
| Convert | `python -m tools.converter <yaml>` | Practitioner YAML lowers cleanly to canonical JSON-LD. |
| Validate | `tools.cli.main validate <jsonld>` | Both structural (JSON Schema) and semantic (SHACL) layers pass. |
| Emit (UC) | `... emit <jsonld> --adapter uc` | Same IR → Databricks-native row filter / column mask. |
| Emit (SF) | `... emit <jsonld> --adapter sf` | Same IR → Snowflake-native row access policy. |
| Diagnostics | (in emit output) | Adapters surface deployment risks as structured, first-class output. |

**One policy. Two platforms. Native enforcement on each, plus honest diagnostics — produced entirely offline with no platform connection.**

---

## Notes for anyone re-running this

- All commands are run from the repo root with the bundled interpreter: `.venv/bin/python ...`.
- The offline path (`convert`, `validate`, `emit`) needs no credentials.
- The `discover` / `extract` / `reconcile` paths, and the `adapters/tests/live_*.py` scripts, require a live Databricks workspace and/or Snowflake account.
- Adapters never execute DDL. They return statements and diagnostics; the caller owns execution, dry-run, retry, and audit. This is deliberate (the project compiles to native enforcement; it is not a runtime engine).
- The committed `pytest` suites (`tools/converter/tests/`, `adapters/tests/test_parity.py`) require `pip install pytest`, which is not currently in the bundled `.venv`.
