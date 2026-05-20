# Getting started — ACL-driven row access and column masking

This tutorial walks you through writing two real Tessera policies for a situation many teams already have: **an ACL mapping table that decides who sees which rows, plus a column that should be masked unless the caller is in a privileged group**. By the end you'll have two `.tessera.yaml` files, you'll have seen what Tessera produces from them on Databricks and on Snowflake, and you'll know how to deploy and verify each one.

No knowledge of RDF, JSON-LD, or semantic-web tooling is assumed. If you can read YAML and you've used SQL to write a row filter or a masking policy before, you have everything you need.

---

## Who this is for

You're a data engineer, security engineer, or governance practitioner. You probably already have:

- One or more tables in production that need access control.
- An ACL mapping table somewhere — maybe two tables linked by a codename — that decides which principals get which rows.
- At least one column where the value should be redacted for most callers but visible to a privileged team (compliance, ops leadership, internal audit, etc.).
- Either Databricks, Snowflake, or both. Bonus if you're trying to make the same policy enforce identically across both.

If that's you, read on. If you're new to data governance entirely, the [evaluating page](../evaluating.md) is a better starting point.

---

## The scenario

You run an order management system on TPC-H-shaped tables. Your customer service team needs row-level access to orders, but the rules are nuanced:

- **CSR row access is controlled by an ACL mapping table.** Some CSRs handle urgent orders (priorities 1 and 2), some handle standard orders (priorities 3-5), some handle both. The mapping is in a table, not in group membership, so it can change without re-granting platform permissions.
- **The `o_clerk` column (the internal employee who handled the order) is sensitive.** CSRs don't need to know who internally processed an order. Operations leadership does. So `o_clerk` should be redacted for most callers but visible to anyone in the `orders_full_access` group.

Two policies. Two patterns. They co-exist on the same table.

### What the policies need to do

**Policy 1 — Row visibility.** A CSR sees a row in `orders` if and only if the ACL mapping tables grant them access to that row's `o_orderpriority` value. Principals with no ACL entry see no rows.

**Policy 2 — Column masking.** Anyone reading `orders` sees `'CLERK-REDACTED'` for the `o_clerk` column **unless** they're a member of the `orders_full_access` group, in which case they see the real value.

Together, the policies form a layered access model: row visibility limits *which* rows you see, column masking shapes *what* you see of each row.

---

## What you'll need

- A YAML editor.
- Python 3.11+ with the Tessera repo cloned and a venv ready (`pip install -r requirements.txt` once that file exists; for now `pip install jsonschema rdflib pyshacl databricks-sdk snowflake-connector-python` covers it).
- A target platform — Databricks workspace **or** Snowflake account, ideally both.
- The ability to create tables, groups (or roles on Snowflake), and run admin SQL.

You do **not** need:

- Familiarity with RDF, JSON-LD, OWL, or SHACL.
- A Tessera CLI (none exists yet — deployment is library-shaped Python).
- A separate Tessera runtime — Tessera produces platform-native SQL; the platform enforces.

---

## Step 1 — Set up your sample data

Pick whichever platform is convenient; the tutorial works against either or both. The Tessera repo includes setup snippets you can adapt. The table schemas below match what the existing worked examples in `spec/v0/examples/` use.

### Databricks

```sql
-- Catalog + schema
CREATE CATALOG IF NOT EXISTS acme;
CREATE SCHEMA IF NOT EXISTS acme.tpch;

-- Protected table (TPC-H orders)
CREATE TABLE IF NOT EXISTS acme.tpch.orders
AS SELECT * FROM samples.tpch.orders;

-- ACL mapping tables — two-table indirection via "codenames"
CREATE TABLE acme.tpch.rls_acl_mapping (
  username  STRING,
  code_name STRING
);

CREATE TABLE acme.tpch.rls_priority_acl (
  code_name      STRING,
  orderpriority  STRING
);

-- Seed data — for behavioral verification
INSERT INTO acme.tpch.rls_priority_acl VALUES
  ('urgent_priority_ops', '1-URGENT'),
  ('high_priority_ops',   '2-HIGH'),
  ('standard_ops',        '3-MEDIUM'),
  ('standard_ops',        '4-NOT SPECIFIED'),
  ('standard_ops',        '5-LOW');

INSERT INTO acme.tpch.rls_acl_mapping VALUES
  ('you@yourcompany.com', 'urgent_priority_ops'),
  ('you@yourcompany.com', 'high_priority_ops');
```

Make sure you've also created an account-level group `orders_full_access` for the column-mask exception, and have at least one identity assigned to it (or not, depending on which side of the policy you want to test).

### Snowflake

```sql
USE ROLE ACCOUNTADMIN;
CREATE DATABASE IF NOT EXISTS ACME;
CREATE SCHEMA  IF NOT EXISTS ACME.TESSERA;
USE SCHEMA ACME.TESSERA;

CREATE TABLE SNOW_ORDERS AS
  SELECT * FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS;

CREATE TABLE RLS_ACL_MAPPING (
  USERNAME  VARCHAR,
  CODE_NAME VARCHAR
);

CREATE TABLE RLS_PRIORITY_ACL (
  CODE_NAME       VARCHAR,
  O_ORDERPRIORITY VARCHAR
);

INSERT INTO RLS_PRIORITY_ACL VALUES
  ('urgent_priority_ops', '1-URGENT'),
  ('high_priority_ops',   '2-HIGH'),
  ('standard_ops',        '3-MEDIUM'),
  ('standard_ops',        '4-NOT SPECIFIED'),
  ('standard_ops',        '5-LOW');

INSERT INTO RLS_ACL_MAPPING VALUES
  ('YOUR_SNOWFLAKE_USERNAME', 'urgent_priority_ops'),
  ('YOUR_SNOWFLAKE_USERNAME', 'high_priority_ops');

-- Custom role for the column-mask exception
CREATE ROLE IF NOT EXISTS ORDERS_FULL_ACCESS;
GRANT ROLE ORDERS_FULL_ACCESS TO USER YOUR_SNOWFLAKE_USERNAME;
```

Replace `YOUR_SNOWFLAKE_USERNAME` and `you@yourcompany.com` with real identifiers from your environment.

**A note on Snowflake users.** Snowflake folds unquoted identifiers to uppercase. Your `CURRENT_USER()` value typically lands uppercase (e.g., `BGIESBRECHT` not `bgiesbrecht`). Store ACL usernames the same way.

---

## Step 2 — Write Policy 1: ACL-driven row visibility

Create `policies/csr-row-access.tessera.yaml`. This policy says: "look up the caller in the ACL mapping table; the priorities they're authorized for determine which rows they see."

```yaml
policy:
  id: csr-row-access
  version: 1.0.0
  kind: RowVisibilityConstraint
  description: |
    A CSR sees rows of orders whose o_orderpriority is granted to them via
    the two-table ACL join (rls_acl_mapping -> rls_priority_acl).
    Principals not in the ACL mapping see no rows (fail-closed).

  appliesTo:
    selector: byIdentity
    resource: table:acme.tpch.orders

  action: Read
  defaultStrategy: none      # principals matching no rule see nothing

  rules:
    - principal:
        selector: byDataset
        dataset:
          type: PrincipalSetFromTable
          table: acme.tpch.rls_acl_mapping
          principalColumn: username
          resourceColumn: code_name
      condition:
        op: exists-in-dataset
        operands:
          - type: ResourceSetFromTable
            table: acme.tpch.rls_priority_acl
            principalColumn: code_name
            resourceColumn: o_orderpriority
      effect: keep-matching-rows
```

### What this is saying, line by line

- **`kind: RowVisibilityConstraint`** — this policy gates row visibility, not column values.
- **`appliesTo`** — which resource the policy attaches to. The selector `byIdentity` means "attach to this specific table by name."
- **`action: Read`** — the action being governed.
- **`defaultStrategy: none`** — fail-closed. A principal who doesn't match the rule sees nothing.
- **`rules`** — what to do for matching principals. Just one rule here.
  - **`principal.selector: byDataset`** — the set of principals authorized by this rule isn't a single group; it's computed at query time by looking up the caller in a mapping table.
  - **`PrincipalSetFromTable`** — the mapping table itself. `principalColumn: username` says "match the caller against this column"; `resourceColumn: code_name` says "the rows you find produce codenames."
  - **`condition: op: exists-in-dataset`** — additionally, the row in `orders` must have its `o_orderpriority` value present in the second ACL table (joined by codename).
  - **`ResourceSetFromTable`** — the second ACL table, joined by `code_name`. The `resourceColumn` is the column on the protected table whose value must match.
  - **`effect: keep-matching-rows`** — when this rule matches, the row stays visible.

### Why `byDataset` here

You could try to express this with `byIdentity` against groups, but every change to which CSRs can see which priorities would require platform-side group membership updates. Putting the mapping in a table means it can change without re-granting permissions. This is the [data-driven entitlement pattern Snowflake documents for mapping tables](https://docs.snowflake.com/en/user-guide/security-row-using): the platform-native equivalent gates on `CURRENT_USER()` against the mapping table. (For role-discrimination scenarios, Snowflake recommends `IS_ROLE_IN_SESSION` instead — Tessera's `byIdentity`. See [authoring.md § Snowflake authoring guidance](../authoring.md#snowflake-authoring-guidance) for the selector-fit decision.)

---

## Step 3 — Write Policy 2: column mask with group exception

Create `policies/orders-clerk-mask.tessera.yaml`. This policy says: "show `o_clerk` redacted for everyone, except members of `orders_full_access` who see the real value."

```yaml
policy:
  id: orders-clerk-mask
  version: 1.0.0
  kind: ColumnVisibilityConstraint
  description: |
    The o_clerk column shows the literal 'CLERK-REDACTED' for all callers
    EXCEPT members of orders_full_access, who see the real value.

  appliesTo:
    selector: byIdentity
    resource: column:acme.tpch.orders.o_clerk

  action: Read
  defaultStrategy: negated-complement   # "explicit rule + ELSE for everyone else"

  rules:
    - principal:
        selector: byIdentity
        resource: group:orders_full_access
      effect: allow                     # see the real value

  defaultBranch:
    effect: transform                   # apply a transformation
    transformation:
      type: Redact
      replacement: "CLERK-REDACTED"
```

### What this is saying

- **`kind: ColumnVisibilityConstraint`** — this policy gates a column's value, not row visibility.
- **`appliesTo.resource: column:...`** — the column being protected. The `column:` prefix is a Tessera convention for identifying a column by its fully-qualified name.
- **`defaultStrategy: negated-complement`** — there's one explicit rule (members of the privileged group), and a `defaultBranch` for everyone else.
- **`rules[0]`** — members of `orders_full_access` see the real value (`effect: allow`).
- **`defaultBranch`** — non-members get the transformation: replace the column value with `'CLERK-REDACTED'`.

### Why `Redact` and not `Mask` or `Hash`

`Redact` substitutes a fixed string. Other transformations available in v0:

- `Mask` — replaces characters with a mask character, optionally preserving a prefix/suffix (e.g., `XXXX1234` for the last four digits of a card number).
- `Hash` — replaces with a cryptographic hash.
- `Tokenize` and `Bucketize` — declared but parameter shapes are deferred to a future version.

For a "make the value obviously redacted" intent, `Redact` is the cleanest choice. If you needed reversible pseudonymization, `Hash` with a deterministic salt is the usual move.

---

## Step 4 — Convert YAML to canonical form, then validate

The validators read canonical JSON-LD. The Tessera converter handles the YAML → JSON-LD step:

```bash
.venv/bin/python -m tools.converter policies/csr-row-access.tessera.yaml \
    --out policies/csr-row-access.jsonld

.venv/bin/python -m tools.converter policies/orders-clerk-mask.tessera.yaml \
    --out policies/orders-clerk-mask.jsonld
```

Each invocation reads one YAML file and writes its canonical JSON-LD counterpart. The converter handles the mechanical mapping (envelope unwrap, `id → @id` with `policy:` prefix, `kind → policyKind`, `type → @type` for typed entities, canonical `@context` injection). Use the JSON-LD outputs for everything downstream — validation, adapter emission, deployment.

The converter's library entry points are also available if you'd rather drive it from Python:

```python
from tools.converter import yaml_to_jsonld, convert_file
convert_file('policies/csr-row-access.tessera.yaml',
             'policies/csr-row-access.jsonld')
```

Now run the two-layer validator. You don't need to know what the layers are conceptually; you do need to run them so structural mistakes are caught before deployment.

```python
import json
from pathlib import Path
import jsonschema
from rdflib import Graph
from pyshacl import validate

schema = json.loads(Path('spec/v0/schema.json').read_text())
shapes = Graph(); shapes.parse('spec/v0/shapes.ttl', format='turtle')
onto   = Graph(); onto.parse('spec/v0/ontology.ttl', format='turtle')

def validate_policy(jsonld_path: Path) -> None:
    doc = json.loads(jsonld_path.read_text())

    # Layer 1: structural well-formedness
    jsonschema.validate(doc, schema)

    # Layer 2: semantic well-formedness (vocabulary checks, etc.)
    data = Graph(); data.parse(str(jsonld_path), format='json-ld')
    conforms, _, msg = validate(
        data_graph=data, shacl_graph=shapes, ont_graph=onto, inference='none')
    if not conforms:
        raise RuntimeError(msg)

    print(f"{jsonld_path.name}: OK")

validate_policy(Path('policies/csr-row-access.jsonld'))
validate_policy(Path('policies/orders-clerk-mask.jsonld'))
```

If either policy is malformed (a required field missing, an enum value typo, a structural issue), one of the validators will tell you which line. Fix the YAML, re-run the converter, re-run the validators until both pass.

**On YAML as source of truth.** YAML is the form you author and edit. JSON-LD is the form tooling consumes. Don't hand-edit the JSON-LD — re-run the converter from the YAML. Comment preservation in YAML round-trips is a deferred feature (the converter uses `ruamel.yaml` from the start so this lands cleanly later); for now, treat YAML comments as authoring documentation that doesn't survive to the canonical form.

---

## Step 5 — See what Tessera produces for each platform

Tessera's job is to translate your policy intent into platform-native enforcement. You don't run a Tessera service in production — you run an adapter that emits SQL, then you deploy the SQL the way you'd deploy any other SQL.

```python
import json
from adapters.contract.types import AdapterConfig
from adapters.unity_catalog import UnityCatalogAdapter
from adapters.snowflake import SnowflakeAdapter

# Configure once per environment — what your platform calls things
uc_config = AdapterConfig(
    identity_bindings={
        'group:orders_full_access': 'orders_full_access',
    },
)
sf_config = AdapterConfig(
    identity_bindings={
        'group:orders_full_access': 'ORDERS_FULL_ACCESS',
    },
    resource_bindings={
        'table:acme.tpch.orders':
            'ACME.TESSERA.SNOW_ORDERS',
        'column:acme.tpch.orders.o_clerk':
            'ACME.TESSERA.SNOW_ORDERS.O_CLERK',
    },
)

# Policy 1
csr = json.loads(open('policies/csr-row-access.jsonld').read())
uc_result = UnityCatalogAdapter(config=uc_config).emit(csr)
sf_result = SnowflakeAdapter(config=sf_config).emit(csr)
print("--- Databricks (CSR row access) ---")
for s in uc_result.statements: print(s); print()
print("--- Snowflake (CSR row access) ---")
for s in sf_result.statements: print(s); print()
```

For Policy 1 (the byDataset row visibility) you'll see something like:

**Databricks** — a row-filter UDF that joins the ACL tables and an `ALTER TABLE ... SET ROW FILTER ON (o_orderpriority)`.

**Snowflake** — a `CREATE ROW ACCESS POLICY ... -> EXISTS (... CURRENT_USER() ...)` and an `ALTER TABLE ... ADD ROW ACCESS POLICY ... ON (O_ORDERPRIORITY)`. Note the policy gates on `CURRENT_USER()` against your mapping table; this is the data-driven entitlement pattern Snowflake documents for mapping tables, and it's a structural fit because your policy decision is "which codenames does this user have" rather than "does this user have role X."

For Policy 2 (the column mask):

**Databricks** — a `CREATE FUNCTION` that returns `o_clerk` when `is_account_group_member('orders_full_access')` is true and `'CLERK-REDACTED'` otherwise, plus an `ALTER TABLE ... ALTER COLUMN o_clerk SET MASK ...`.

**Snowflake** — a `CREATE MASKING POLICY ... -> CASE WHEN IS_ROLE_IN_SESSION('ORDERS_FULL_ACCESS') THEN o_clerk ELSE 'CLERK-REDACTED' END` and an `ALTER TABLE ... MODIFY COLUMN O_CLERK SET MASKING POLICY ...`.

**The same YAML produces both.** That's the value proposition: one source of policy intent, two platform-native enforcements.

---

## Step 6 — Deploy

Tessera produces SQL strings. Execute them with whatever deployment tooling you already use (CI/CD, Terraform, a notebook, dbt). The examples below use the platform SDKs directly for clarity.

### Databricks

```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

w = WorkspaceClient(profile='your-workspace-profile')
WH = 'your-warehouse-id'

def run(sql: str):
    r = w.statement_execution.execute_statement(
        warehouse_id=WH, statement=sql, wait_timeout='30s')
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(r.status.error)
    return r.result.data_array if r.result else None

# If you're re-applying, you may need to drop the previous attachment first.
# run('ALTER TABLE acme.tpch.orders DROP ROW FILTER')
# run('ALTER TABLE acme.tpch.orders ALTER COLUMN o_clerk DROP MASK')

for stmt in uc_result.statements:   # Policy 1
    run(stmt)
for stmt in mask_uc_result.statements:   # Policy 2 (emit similarly)
    run(stmt)
```

### Snowflake

```python
import snowflake.connector
conn = snowflake.connector.connect(
    account='YOUR_ACCOUNT', user='YOUR_USER', password='...',
    warehouse='YOUR_WAREHOUSE', database='ACME', schema='TESSERA',
    role='ACCOUNTADMIN',
)
cur = conn.cursor()

# If re-applying:
# cur.execute('ALTER TABLE ACME.TESSERA.SNOW_ORDERS '
#             'DROP ROW ACCESS POLICY ...')
# cur.execute('ALTER TABLE ACME.TESSERA.SNOW_ORDERS '
#             'MODIFY COLUMN O_CLERK UNSET MASKING POLICY')

for stmt in sf_result.statements:        # Policy 1
    cur.execute(stmt)
for stmt in mask_sf_result.statements:   # Policy 2
    cur.execute(stmt)
```

**Snowflake operator note.** This scenario's Policy 1 uses `byDataset` because the underlying decision is data-driven entitlement (which codenames does this CSR have access to). The Snowflake emission gates on `CURRENT_USER()` against your mapping table, which is orthogonal to role activation — so `DEFAULT_SECONDARY_ROLES = ('ALL')` (Snowflake's default since 2024) doesn't affect this policy either way. The role-activation question only arises for `IS_ROLE_IN_SESSION`-based (i.e., `byIdentity`) policies; full discussion in [operating.md](../operating.md). For when `byIdentity` is the right choice instead, see [authoring.md § Snowflake authoring guidance](../authoring.md#snowflake-authoring-guidance).

---

## Step 7 — Verify behavior

The point of policies is enforcement, so check that yours actually fires.

### Policy 1 (row visibility) — three scenarios

| Scenario | Setup | What you should see |
|---|---|---|
| 1 | Seed data as-is (you're in `urgent_priority_ops` and `high_priority_ops`) | Only `1-URGENT` and `2-HIGH` rows |
| 2 | Add an `(you, 'standard_ops')` row to the mapping table | All five priorities |
| 3 | Remove all your mapping rows | Zero rows |

Run as your own user:

```sql
SELECT o_orderpriority, COUNT(*) FROM acme.tpch.orders
GROUP BY 1 ORDER BY 1;
```

After each scenario change, re-run the query. No re-grant needed; the policy reads the ACL tables at query time.

### Policy 2 (column mask) — two paths

If you're in `orders_full_access`:

```sql
SELECT DISTINCT o_clerk FROM acme.tpch.orders LIMIT 3;
-- Expect: real Clerk#0000XXXXX values
```

If you're not:

```sql
SELECT DISTINCT o_clerk FROM acme.tpch.orders LIMIT 3;
-- Expect: 'CLERK-REDACTED' (single distinct value)
```

To switch sides, add/remove yourself from the group on the platform admin console. Note that on Databricks, account-group membership changes can take 2–4 minutes to propagate; on Snowflake, role grants take effect at the next session.

### Stacking both policies

The two policies operate on different surfaces (rows vs. column values), so they compose naturally. With both applied: you see only the rows you're ACL'd for, and within those rows, `o_clerk` is either real or redacted depending on `orders_full_access` membership.

---

## Common variations

### My ACL table has different column names

Change `principalColumn` and `resourceColumn` in the `PrincipalSetFromTable` and `ResourceSetFromTable` blocks. The columns must exist on the named tables, but the names are up to you. The IR validates the structure, not the column names — your platform will reject the emitted DDL if the columns don't exist.

### I want the mask to apply to multiple columns

Each `ColumnVisibilityConstraint` policy targets one column. For multiple columns under the same masking intent, write one policy per column with the same `rules` and `defaultBranch`. A future ABAC-driven variant lets you write a single policy that attaches to any column tagged a particular way — see the existing exercises under `spec/v0/examples/abac-column-mask-*` for the shape, though full adapter support is still in progress.

### I want everyone except a specific group to see the value, with no other condition

That's exactly Policy 2's shape — one rule for the privileged group, `defaultBranch` for everyone else. Just substitute your group name in `principal.resource`.

### My priorities or codenames need to change over time

You don't update the Tessera policy. You update the ACL tables. The policy reads them at query time — that's the whole point of `byDataset`. Audit log shows the policy text is stable; the access semantics evolve with the data.

### What if I need both `byDataset` row visibility AND ABAC-driven column masking?

That's a fine combination. The IR supports both shapes. Adapter coverage today: `byDataset` row visibility works on Databricks and Snowflake; ABAC-driven column masking is implemented on Databricks (for the explicit policyKind shape) and queued for Snowflake. If you need it now, write the policy and the validators will accept it; emission diagnostics will tell you what's missing on a particular adapter.

### What if I'm authoring policies for Databricks only and don't care about Snowflake?

Tessera still works. You'll just never invoke the Snowflake adapter. The value proposition Tessera delivers in single-platform scenarios is the validation pipeline + the cross-customer-portability of the YAML format. If neither matters to you, Unity Catalog's native DDL is also fine.

---

## Where to go from here

- **More authoring patterns** — [authoring.md](../authoring.md) covers attribute axes, ABAC scoping, condition operators, transformations.
- **Per-platform deployment depth** — [operating.md](../operating.md) has the operator checklists, including the Snowflake `DEFAULT_SECONDARY_ROLES` discussion if your policies need role discrimination.
- **The worked-example library** — `spec/v0/examples/` has eight completed exercises with all artifacts (YAML, canonical form, target SQL, diagnostics). They're the most concrete reference for what's actually possible.
- **The conceptual tutorial** — [tutorial.md](../tutorial.md) walks the group-row-visibility example end to end, with more attention to what's happening at each step.
- **Issues and discussions** — `https://github.com/bgiesbrecht/tessera/issues` is where active gaps and design questions live. The governance-gap survey issues (#16–#25) are a good map of what's known to be in/out of scope today.

If you got two YAML files validating and you saw the platform DDL emit cleanly: you've done the thing. The rest is iteration on your real corpus.
