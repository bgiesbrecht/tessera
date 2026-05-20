# Operating Tessera

This page is for engineers wiring Tessera into a deployment pipeline. It assumes you understand the IR vocabulary at the level of [`authoring.md`](./authoring.md) and have run through [`tutorial.md`](./tutorial.md).

## The adapter contract

Tessera defines a four-responsibility contract (ADR-024) implemented by every platform adapter:

1. **Emit** — lower an IR policy to platform-native DDL/SQL statements. Implemented in current adapters.
2. **Discover** — inventory policy-bearing artifacts on the platform. Stubbed in current adapters.
3. **Extract** — lift a platform artifact to IR. Stubbed in current adapters.
4. **Reconcile** — diff intended IR state against observed platform state. Stubbed in current adapters.

**Adapters never execute.** They return platform-native statements; the caller composes execution with logging, retry, dry-run, audit, and whatever else the deployment policy requires. This separation keeps adapters testable without platform credentials and keeps the contract synchronous and pure.

All four methods return structured `Result` objects carrying `diagnostics: list[Diagnostic]`. Callers attach the diagnostic stream to CLI output, JSON reports, IDE annotations, or wherever else makes sense in their pipeline.

## `AdapterConfig`

The configuration block that maps Tessera's platform-neutral IR vocabulary to platform-native identifiers. This is the implementation of ADR-021's adapter-configuration-mapping pattern.

```python
from adapters.contract.types import AdapterConfig

config = AdapterConfig(
    identity_bindings={
        # IR PrincipalRef IRI → platform principal identifier
        'group:acme_high_priority_ops': 'acme_high_priority_ops',     # Databricks
        # … or per-platform variant on Snowflake
    },
    resource_bindings={
        # IR ResourceRef IRI → platform-qualified identifier
        'table:acme.tpch.orders': 'ACME.TESSERA.SNOW_ORDERS',
    },
    tag_taxonomy={
        # (axis IRI, axis value) → (platform tag key, platform tag value)
        ('sensitivityAxis', 'PII'): ('classification', 'pii'),
    },
    extras={
        # Per-adapter conventions: warehouse name, default schema, dry-run flag, etc.
        'warehouse': 'COMPUTE_WH',
    },
)
```

**The four mapping axes:**

| Axis | What it resolves | Why per-environment |
|---|---|---|
| `identity_bindings` | Principal IRIs → platform principals (groups, roles, users) | Group/role names differ across platforms; case sensitivity differs |
| `resource_bindings` | Resource IRIs → platform-qualified names | The same logical table is qualified differently per platform (`catalog.schema.table` vs `DB.SCHEMA.TABLE`) |
| `tag_taxonomy` | Attribute (axis, value) pairs → platform tag (key, value) pairs | Databricks governed tags, Snowflake object tags, classification-table values all differ in spelling |
| `extras` | Free-form per-adapter conventions | Some adapters need warehouse / role / dry-run state that doesn't fit the typed axes |

Per ADR-021, the IR carries semantic intent (`sensitivity: PII`) and the adapter carries the per-environment translation (`classification = 'pii'`). Authors don't put platform-specific tag values in policies; operators don't author policies to introduce a new platform.

### Identifier case in extracted IR

When an adapter `extract()`s a deployed policy back into Tessera IR, the IR carries the source platform's identifier case **verbatim**. Snowflake folds to uppercase, so a Snowflake-extracted IR has `table:ACME.TESSERA.SNOW_ORDERS`. Databricks is mixed-case, so a UC-extracted IR has `table:acme.tpch.orders`. The IR is lossless about what the source actually stored.

`AdapterConfig.bind_principal` and `bind_resource` are **case-insensitive on the identifier portion** after the IRI prefix to bridge the gap. The prefix (`table:`, `column:`, `group:`) is the semantic discriminator and stays case-sensitive; the identifier after the colon is matched case-folded. This means you can author bindings in whatever case is natural for the target platform — Databricks-mixed for UC targets, uppercase for Snowflake targets, lowercase for normalized records — and the lookup will find it regardless of the case the IR carries.

```python
config = AdapterConfig(
    resource_bindings={
        # Authored in target-platform case; matches IR identifiers regardless of source case.
        "table:acme.migration_demo.demo_orders":
            "acme.migration_demo.demo_orders",
    },
)
# Both lookups succeed:
config.bind_resource("table:acme.migration_demo.demo_orders")             # exact
config.bind_resource("table:ACME.MIGRATION_DEMO.DEMO_ORDERS")              # case-folded
```

The convention going forward: **carry source case in the IR; rely on the binding-layer case-insensitivity for cross-platform lookups.** Don't pre-normalize identifiers during extraction (the source case is provenance information worth preserving). Issue [#29](https://github.com/bgiesbrecht/tessera/issues/29) tracks the design discussion that produced this convention.

## Capability profiles

Every adapter declares a `CapabilityProfile`:

```python
adapter = UnityCatalogAdapter(config=config)
profile = adapter.capability_profile
print(profile.adapter_name, profile.platform)

from adapters.contract.types import Capability
print(profile.support_for(Capability.ROW_VISIBILITY))   # SUPPORTED / PARTIAL / UNSUPPORTED
print(profile.rationale(Capability.ATTRIBUTE_BASED_SCOPING))
```

The `Capability` enum is closed (eight entries today: row visibility, column visibility, attribute-based scoping, dataset-driven principals, dataset-driven resources, conditional obligations, purpose binding, regulatory-regime attribute). Adding values is a deliberate contract change, not a per-adapter decision — this is what makes capability gaps comparable across adapters.

**Reading a capability entry:** `SUPPORTED` means the adapter emits DDL exercising this concept; `PARTIAL` means coverage is incomplete with a stated boundary; `UNSUPPORTED` means the adapter refuses or warns. Emission may still produce output for `PARTIAL` (with a warning diagnostic) — the profile is informational, not a runtime gate.

For the current state of each adapter's coverage, read the `entries` map in:
- `adapters/unity_catalog/capability.py`
- `adapters/snowflake/capability.py`

## Diagnostics

Every adapter method returns a `Result` carrying `diagnostics: list[Diagnostic]`:

```python
result = adapter.emit(policy)
for d in result.diagnostics:
    print(f"[{d.severity.value}] {d.code} @ {d.location}: {d.message}")
if result.has_errors:
    raise RuntimeError("emission failed")
```

A `Diagnostic` has:
- **severity** — `info` / `warning` / `error`
- **code** — short stable identifier (e.g., `UNIMPLEMENTED_POLICY_KIND`, `UNBOUND_PRINCIPAL`)
- **message** — human-readable explanation
- **location** — optional pointer into the source policy (e.g., `rules[1].condition`)

**Convergent diagnostic vocabulary.** Adapters use parallel codes for parallel concerns (`UNIMPLEMENTED_POLICY_KIND` is the same code in both UC and Snowflake adapters). The contract module does not enforce convergence — see the `claude.ai` handoff doc for an open design question about whether to formalize a shared diagnostic enum.

## Deploying on Databricks

The Databricks adapter (`adapters.unity_catalog`) emits Unity Catalog DDL: `CREATE FUNCTION … RETURNS BOOLEAN` row-filter UDFs plus `ALTER TABLE … SET ROW FILTER` attachments. For column visibility (when implemented), `CREATE FUNCTION` masking UDFs plus `ALTER TABLE … ALTER COLUMN … SET MASK`.

### Connection setup

The standard pattern uses the Databricks SDK with a configured profile:

```bash
databricks auth login --profile your-workspace
```

```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

w = WorkspaceClient(profile='your-workspace')
WH = 'your-warehouse-id'

def run_sql(stmt: str):
    r = w.statement_execution.execute_statement(
        warehouse_id=WH, statement=stmt, wait_timeout='30s',
    )
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"SQL failed: {r.status.error}")
    return r.result.data_array if r.result else None
```

### Identity bindings

Tessera principal IRIs (`group:foo`) lower to Unity Catalog **account-level group names**. Spaces are valid (Databricks' built-in `account users` group includes the space). Case-sensitivity follows Databricks' rules.

```python
identity_bindings = {
    'group:acme_all_priority_ops': 'acme_all_priority_ops',
    'group:account-users': 'account users',
}
```

### Group propagation timing

Membership changes to account-level groups propagate through a cache. Observed window: roughly 2–4 minutes between an SCIM group update and the change being visible to `is_account_group_member`. Per §5.2 of the technical design (timing disclosure), this should be surfaced to policy authors so they don't assume real-time group changes.

### Existing policies on the same table

Databricks rejects attaching multiple row filters to the same table (`COLUMN_MASKS_FEATURE_NOT_SUPPORTED.MULTIPLE_MASKS` for column masks; the equivalent for row filters). Before re-applying a policy, drop the existing attachment:

```sql
ALTER TABLE catalog.schema.table DROP ROW FILTER;
```

This is the empirical observation that drove ADR-023's γ-with-refinement framing. Tessera does not orchestrate the drop; the operator's deployment pipeline does.

### Runnable example

`adapters/tests/live_databricks.py` is the complete deployment loop for the group-row-visibility policy: emit DDL, drop existing filter if present, apply new statements, verify row counts under the calling user.

## Deploying on Snowflake

The Snowflake adapter (`adapters.snowflake`) emits row-access policy DDL: `CREATE ROW ACCESS POLICY … RETURNS BOOLEAN -> …` plus `ALTER TABLE … ADD ROW ACCESS POLICY … ON (col)`. For column visibility (when implemented), masking policy DDL plus `ALTER TABLE … MODIFY COLUMN … SET MASKING POLICY`.

### Connection setup

```bash
pip install snowflake-connector-python
```

```python
import snowflake.connector

conn = snowflake.connector.connect(
    account='YOUR_ACCOUNT', user='YOUR_USER', password='…',
    warehouse='COMPUTE_WH', database='YOURDB', schema='YOURSCHEMA',
    role='ACCOUNTADMIN',
)
cur = conn.cursor()
```

Authentication options: password (shown above), externalbrowser (for interactive SSO), key-pair (for unattended deployments). The adapter does not bundle connection handling.

### Identity bindings

Snowflake roles, not groups. Roles are uppercase by convention; the adapter passes whatever you give it, so case-match your environment:

```python
identity_bindings = {
    'group:acme_all_priority_ops': 'ACME_ALL_PRIORITY_OPS',
    'group:account-users': 'PUBLIC',
}
```

The IR uses `group:` prefix uniformly; the adapter doesn't care that Snowflake's mechanism is "roles" rather than "groups" — that translation is what `identity_bindings` is for.

### Role-discrimination semantics

**Read this section before deploying any Snowflake row-access policy that uses `byIdentity` principal selectors.**

Snowflake offers two distinct primitives for role-based gating, and they carry **different semantics by design**:

| Primitive | Semantics | When to use |
|---|---|---|
| `CURRENT_ROLE()` | Primary-role-only (strict) | Audit / compliance scenarios where user *intent* matters: the user must be acting under role X as their explicit primary role |
| `IS_ROLE_IN_SESSION(X)` | Any active role (primary OR secondary) | Standard RBAC scenarios: if you've been granted role X, you have its permissions, regardless of which role is currently primary |

Both are documented and supported. Snowflake's own guidance: "*If role activation and role hierarchy are important, Snowflake recommends that the policy conditions use the `IS_ROLE_IN_SESSION` function for account roles and the `IS_DATABASE_ROLE_IN_SESSION` function for database roles.*"

**What the Tessera adapter does:** emits `IS_ROLE_IN_SESSION(X)` for `byIdentity` principal selectors — the RBAC-standard semantic, matching Snowflake's recommendation. This means a Tessera policy that selects `group:high_priority_ops` translates to "any user with the `HIGH_PRIORITY_OPS` role granted, regardless of whether it's currently primary."

**Why this matters operationally.** Since BCR-1692 (Snowflake behavior change, rolled out Aug 2024 → Mar 2025), the platform defaults new users to `DEFAULT_SECONDARY_ROLES = ('ALL')` — every role granted to the user is session-active automatically. This is **consistent with the adapter's emission**: secondary roles activate; `IS_ROLE_IN_SESSION` sees them; permission-scope semantics hold. No defeat condition; the platform default and the adapter's choice align.

**The thing to watch for** is an *authoring/emission mismatch* — an author who *expects* primary-role-only semantics (because they're thinking in audit-trail terms: "this data should only be accessible when explicitly acting as role X") will be surprised when their policy doesn't discriminate. The Tessera adapter does not currently express the primary-role-only intent; if you need it, the discussion lives in issue [#14](https://github.com/bgiesbrecht/tessera/issues/14) and is deferred until a worked exercise drives the design.

**Verifying behavior:**

```sql
DESCRIBE USER analyst_x;
-- Look for DEFAULT_SECONDARY_ROLES ⇒ ["ALL"] (default since 2024) or an explicit list.

USE SECONDARY ROLES NONE;
SELECT IS_ROLE_IN_SESSION('HIGH_PRIORITY_OPS');   -- Primary only
USE SECONDARY ROLES ALL;
SELECT IS_ROLE_IN_SESSION('HIGH_PRIORITY_OPS');   -- Primary + secondaries
```

If you need to constrain the effective role set explicitly (because of an Intent A use case the IR doesn't yet express, or for tighter session control regardless of adapter intent), use one of:

```sql
-- Durable, per-user:
ALTER USER analyst_x SET DEFAULT_SECONDARY_ROLES = ('PUBLIC');

-- Per-session, fragile (every connection must set it):
USE SECONDARY ROLES NONE;
```

**When `byDataset` fits better:** if the policy is actually deciding data-driven entitlement (ACL-table-driven, not role-driven), author with `byDataset` rather than `byIdentity`. `byDataset` lowers to a mapping-table-based policy gating on `CURRENT_USER()`, which is orthogonal to role activation entirely — the role-discrimination question doesn't arise. This is the pattern Snowflake [documents for data-driven entitlement](https://docs.snowflake.com/en/user-guide/security-row-using), not a blanket Snowflake-recommended alternative to `byIdentity` for "complex" policies. See [`authoring.md`](./authoring.md) § Snowflake authoring guidance for selector-fit guidance.

ADR-024's postscript records the live-verification finding under refined framing (initially misframed as a "gotcha"; corrected after design discussion). Issue [#14](https://github.com/bgiesbrecht/tessera/issues/14) tracks the open question of whether the IR should grow to express Intent A vs Intent B explicitly.

### Existing policies on the same table

Snowflake permits multiple row-access policies attached to the same column? No — Snowflake permits **one** row-access policy per column (similar to Databricks). For re-application:

```sql
ALTER TABLE db.schema.table DROP ROW ACCESS POLICY db.schema.policy_name;
```

### Runnable examples

- `adapters/tests/live_snowflake.py` — the role-based parity test (`byIdentity` against the seed `SNOW_ORDERS` table; observes secondary-roles behavior).
- `adapters/tests/live_snowflake_bydataset.py` — the `byDataset` exercise (ACL-table-driven; all four scenarios including secondary-roles immunity).

## Validation pipeline

Both validators run before emission. Standard CI shape:

```python
import json, jsonschema
from rdflib import Graph
from pyshacl import validate

# Layer 1 — JSON Schema (structural)
schema = json.loads(open('spec/v0/schema.json').read())
doc = json.loads(open('your-policy.jsonld').read())
jsonschema.validate(doc, schema)

# Layer 2 — SHACL (semantic)
shapes = Graph(); shapes.parse('spec/v0/shapes.ttl', format='turtle')
onto = Graph(); onto.parse('spec/v0/ontology.ttl', format='turtle')
data = Graph(); data.parse('your-policy.jsonld', format='json-ld')
conforms, _, msg = validate(data, shacl_graph=shapes, ont_graph=onto, inference='none')
if not conforms:
    raise RuntimeError(msg)

# Layer 3 — adapter emission diagnostics
result = adapter.emit(doc)
errors = [d for d in result.diagnostics if d.severity.value == 'error']
if errors:
    raise RuntimeError(errors)
```

Layer 1 enforces structure; Layer 2 enforces semantic well-formedness; Layer 3 enforces adapter-specific constraints (capability gaps, unbound principals, unimplemented selectors). Errors in any layer block deployment.

## Dry-run mode

Not yet a first-class adapter mode. The current pattern: emit DDL, print/log, do not execute. The runner scripts under `adapters/tests/` exemplify this — emission is unconditional; execution is gated separately by the script. A formal `verify` adapter responsibility (parallel to discover/extract/emit/reconcile) is an open design question — see the claude.ai handoff doc.

## Per-adapter checklists for production deployment

### Databricks
- [ ] SDK auth profile configured (`databricks auth login --profile X`).
- [ ] Warehouse id known; warehouse running or auto-resume enabled.
- [ ] `identity_bindings` populated for every principal IRI referenced by the policy.
- [ ] `resource_bindings` populated (or the IR target is already the platform-qualified name).
- [ ] Existing row filter / column mask on the target table inspected; drop step scripted if applicable.
- [ ] Schema + SHACL validation pass before the SDK call.
- [ ] Diagnostic output captured to audit log.

### Snowflake
- [ ] Connector installed (`pip install snowflake-connector-python`).
- [ ] Auth method chosen (password / externalbrowser / key-pair) and connection tested.
- [ ] **For every user subject to the policy: `DEFAULT_SECONDARY_ROLES` set explicitly** (do not rely on the platform default).
- [ ] `identity_bindings` use uppercase role names (or whatever your environment uses).
- [ ] `resource_bindings` populated.
- [ ] Existing row-access policy on the target column inspected; drop step scripted if applicable.
- [ ] Selector matches the decision the policy actually makes (role-discrimination → `byIdentity`; ACL-driven entitlement → `byDataset`; see `authoring.md` § Snowflake authoring guidance).
- [ ] Schema + SHACL validation pass before the connector call.
- [ ] Diagnostic output captured to audit log.

## What this page does not cover

- **Discovery, extraction, reconciliation in production.** Stubbed in current adapters; building them out is queued work.
- **Multi-policy orchestration.** ADR-023's γ-with-refinement framing describes the model; production patterns for staged rollout, A/B comparison, and rollback are not yet codified.
- **Tessera CLI.** No CLI exists yet — deployment is library-shaped, called from your own Python. A CLI may emerge once the converter and a few more adapters land.
- **Custom adapters.** See [`contributing.md`](./contributing.md) for writing one against the contract.
