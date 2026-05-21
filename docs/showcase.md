# Tessera at 0.6.0 — what works, end to end

This document is for someone who has heard about Tessera and wants to know what it actually does today, before reading the README, the technical design, or any of the ADRs. It is a 5–10 minute read. Pointers throughout to runnable artifacts and supporting docs.

The claim it makes — and demonstrates with real numbers from real workspaces — is this:

> The same data governance policy, authored once in YAML, can be validated, lowered to Databricks-native enforcement and Snowflake-native enforcement, deployed on both platforms, behaviorally verified, and migrated between platforms in either direction. End to end. Runnable. Today.

Everything below is grounded in scripts and committed artifacts in this repository. None of it is aspirational.

---

## The shape of the thing

```
                 ┌─────────────────────────────┐
                 │   YAML policy (you write)   │
                 └────────────┬────────────────┘
                              │  converter (lossless)
                              ▼
                 ┌─────────────────────────────┐
                 │   JSON-LD canonical form     │
                 │   (validated by JSON Schema  │
                 │    + SHACL)                  │
                 └──┬──────────────────────┬───┘
                    │  UC adapter          │  Snowflake adapter
                    ▼                      ▼
              Databricks DDL           Snowflake DDL
              (row filters,            (row-access policies,
               column masks,            masking policies,
               GRANT statements)        GRANT statements)
                    │                      │
                    ▼                      ▼
              Enforced on              Enforced on
              Unity Catalog            Snowflake
```

Three policy shapes carry across both platforms. Each shape exists in the IR (`spec/v0/ontology.ttl`) and has emission paths on both adapters (`adapters/{unity_catalog,snowflake}/emission.py`). The bidirectional arrows are the migration story (`adapters/tests/live_migration_demo*.py`).

---

## What 0.6.0 ships

### The full adapter cycle, on both platforms

Per ADR-024, every adapter implements four responsibilities. At 0.6.0 the four are real (not stubbed) on both Unity Catalog and Snowflake:

| Responsibility | Unity Catalog | Snowflake | What it does |
|---|---|---|---|
| **emit** | ✓ | ✓ | Lowers a Tessera IR policy to platform-native DDL/SQL |
| **discover** | ✓ | ✓ | Inventories deployed policies on a target schema |
| **extract** | ✓ | ✓ | Lifts discovered platform state back into Tessera IR |
| **reconcile** | ✓ | ✓ | Diffs intended IR against observed deployed state |

The four compose. `reconcile` is the `discover` + `extract` of observed state vs the intended IR corpus on disk, returning structured additions / removals / modifications.

### Three policy shapes, three enforcement primitives per platform

| Policy shape | Databricks DDL | Snowflake DDL |
|---|---|---|
| **`RowVisibilityConstraint`** (byIdentity multi-rule) | `CREATE FUNCTION ... RETURNS BOOLEAN` + `ALTER TABLE ... SET ROW FILTER` | `CREATE ROW ACCESS POLICY ... -> ...` + `ADD ROW ACCESS POLICY ... ON (col)` |
| **`RowVisibilityConstraint`** (byScope ABAC) | UC ABAC: `CREATE POLICY ... ROW FILTER ... MATCH COLUMNS has_tag_value(...)` | (queued — see issue [#31](https://github.com/bgiesbrecht/tessera/issues/31)) |
| **`RowVisibilityConstraint`** (byDataset) | `CREATE FUNCTION ... RETURN EXISTS (SELECT 1 FROM map JOIN acl ...)` | `CREATE ROW ACCESS POLICY ... -> EXISTS (... CURRENT_USER() ...)` |
| **`ColumnVisibilityConstraint`** (byIdentity, Redact) | `CREATE FUNCTION` + `ALTER TABLE ... SET MASK` | `CREATE MASKING POLICY ... -> CASE ... END` + `ALTER TABLE ... SET MASKING POLICY` |
| **`ColumnVisibilityConstraint`** (byScope ABAC) | UC ABAC: `CREATE POLICY ... COLUMN MASK ... MATCH COLUMNS has_tag_value(...) ON COLUMN ...` | (queued — see issue [#31](https://github.com/bgiesbrecht/tessera/issues/31)) |
| **`AccessGrantConstraint`** (byIdentity, table) | `GRANT SELECT ON TABLE ... TO \`group\`` | `GRANT SELECT ON TABLE ... TO ROLE` |
| **`AccessGrantConstraint`** (byIdentity, function) | `GRANT EXECUTE ON FUNCTION ... TO \`group\`` | `GRANT USAGE ON FUNCTION ... TO ROLE` (signature auto-resolved) |
| **`AccessGrantConstraint`** (byScope, schema fan-out) | `GRANT USE SCHEMA` + `GRANT SELECT ON SCHEMA` | `GRANT USAGE` + `GRANT SELECT ON ALL TABLES IN SCHEMA` + `GRANT SELECT ON FUTURE TABLES IN SCHEMA` |

Snowflake's schema-level read grant doesn't map to a single SQL statement (`SELECT ON SCHEMA` isn't valid). Tessera's `byScope` downward-propagation semantics (ADR-019) lower to the Snowflake idiom of fanning out to all current + future tables — preserving the IR's intent across the platform difference.

### The migration round trip, both directions

Two runnable scripts:

```bash
# Snowflake → Databricks: discover, extract, emit, deploy, verify
.venv/bin/python -m adapters.tests.live_migration_demo

# Databricks → Snowflake: same thing, reversed
.venv/bin/python -m adapters.tests.live_migration_demo_reverse
```

Each one provisions fresh schemas on both sides, deploys six Tessera policies on the source (via the source-platform adapter's `emit`), uses `discover` + `extract` to lift them back into IR, then uses the target-platform adapter's `emit` to produce platform-native DDL, applies it, and runs verification queries against the deployed enforcement.

The verification numbers from a real run on real workspaces:

| Policy | Surface after migration | Caller-visible result |
|---|---|---|
| Group row visibility (3-branch CASE) | `acme.migration_demo.demo_orders` | 59,998 rows visible (priorities 3-MEDIUM / 4-NOT SPECIFIED / 5-LOW — the third branch fires because the caller is in `account users` only) |
| byDataset row visibility (mapping-table EXISTS) | `acme.migration_demo.demo_orders_rls_acl` | 40,002 rows visible (priorities 1-URGENT + 2-HIGH — the caller's ACL codenames) |
| Column mask (Redact, group exception) | `acme.migration_demo.demo_orders.o_clerk` | `'CLERK-REDACTED'` for every distinct value |
| Table grant (SELECT) | `acme.migration_demo.demo_orders` | Three explicit grants visible via `SHOW GRANTS` |
| Schema grant (fans out to per-table) | `acme.migration_demo_staging.staged_orders` | `SELECT` grant visible (the schema-level intent landed as a per-table grant on Databricks) |
| Function grant (EXECUTE) | `acme.migration_demo.compute_customer_ltv` | `EXECUTE` grant visible |

All six policies enforcing. Bidirectional cycle. Run it yourself: the scripts are idempotent and ship with a `--cleanup` flag.

---

## Why the IR pivot matters

The conventional answer to "how do I keep my Databricks and Snowflake governance in sync" is "you can't, exactly — write equivalent policies in both, hope they stay aligned, audit when they drift." The cost is real: policy drift between platforms is one of the more expensive governance failure modes, and every customer with a multi-platform footprint either pays it or builds bespoke tooling.

Tessera's IR is what changes that. The same `.tessera.yaml` file lowers to clean Databricks DDL and clean Snowflake DDL via per-platform adapters. The bindings layer (`AdapterConfig`) carries the per-environment translation — group names, role names, table identifiers, governed-tag mappings — without contaminating the policy itself. The policy author writes intent; the operator configures the translation; the platform handles enforcement.

This is the W3C semantic-web stack used seriously, not decoratively. The vocabulary is in OWL (`spec/v0/ontology.ttl`); the canonical form is JSON-LD 1.1 (`spec/v0/context.jsonld`); validation is layered between JSON Schema and SHACL; vocabulary alignment to DPV and ODRL is declared via SKOS. None of this is overhead — it's the substrate that makes the cross-platform claim mean something. See `docs/w3c-overview.md` for the semantic-web-savvy view.

---

## The migration story, end to end

Eight phases. Idempotent. Verifiable.

1. **Provision the source schema** (Snowflake or UC, depending on direction). Fresh schema; sample data from TPC-H; mapping-ACL data seeded.
2. **Deploy six Tessera policies on the source** via the source-platform adapter's `emit`. Three visibility policies (row filter, byDataset row filter, column mask) plus three RBAC policies (table grant, schema grant with fan-out, function grant).
3. **Discover** — list what's deployed: row filters, masking policies, grant rows. Both platforms expose this via their respective primitives (`DESCRIBE TABLE EXTENDED` + `SHOW GRANTS` on Databricks; `SHOW ROW ACCESS POLICIES` + `SHOW GRANTS` on Snowflake).
4. **Extract** — lift each discovered artifact into Tessera IR. Pattern-driven over policy body text (the worked-example shapes the project has actually deployed); produces JSON-LD that validates against schema + SHACL.
5. **Provision the target schema** on the other platform.
6. **Emit** the extracted IR via the target-platform adapter, with bindings translating identifiers (Snowflake-uppercase → Databricks-mixed-case, and vice versa).
7. **Deploy** the migrated DDL on the target.
8. **Verify** — query the migrated tables; confirm row counts, distinct values, and `SHOW GRANTS` output match the original policy intent.

The script that runs this lives at `adapters/tests/live_migration_demo.py`. The reverse-direction sibling lives at `adapters/tests/live_migration_demo_reverse.py`. Both are ~500 lines of Python that exercise every adapter responsibility in coordinated fashion.

A walkthrough in prose lives at `docs/user-guide/scenarios/migrating-snowflake-to-uc.md` — Phase-by-phase, with the empirical results and the findings that surfaced during development.

---

## What you'd actually run as a practitioner

For an author writing a new policy:

```bash
# Author in YAML (the practitioner-friendly shape)
$ cat my-policy.tessera.yaml
policy:
  id: my-policy
  kind: RowVisibilityConstraint
  appliesTo: { selector: byIdentity, resource: table:catalog.schema.foo }
  action: Read
  defaultStrategy: explicit-baseline-group
  baselineGroup: account-users
  rules:
    - principal: { selector: byIdentity, resource: group:my-team }
      effect: keep-matching-rows

# Validate (JSON Schema + SHACL)
$ python -m tools.cli validate my-policy.tessera.yaml
schema: OK
shacl: OK
my-policy.tessera.yaml: validates clean.

# Convert to canonical JSON-LD (mechanical; lossless)
$ python -m tools.cli convert my-policy.tessera.yaml --out my-policy.jsonld

# Emit Databricks DDL
$ python -m tools.cli emit my-policy.tessera.yaml --adapter unity-catalog --config bindings.yaml
Statements:
CREATE OR REPLACE FUNCTION ...
ALTER TABLE catalog.schema.foo SET ROW FILTER ...

# Emit the same IR as Snowflake DDL
$ python -m tools.cli emit my-policy.tessera.yaml --adapter snowflake --config bindings.yaml
Statements:
CREATE OR REPLACE ROW ACCESS POLICY ...
ALTER TABLE catalog.schema.foo ADD ROW ACCESS POLICY ...
```

For an operator deploying or reconciling:

```bash
$ python -m tools.cli discover --adapter unity-catalog --catalog X --schema Y
Discovered 12 artifact(s):
  • [row_filter] X.Y.fn1 → X.Y.tbl.col
  • [column_mask] X.Y.fn2 → X.Y.tbl.col
  • [access_grant] group1 SELECT on TABLE X.Y.tbl
  ...

$ python -m tools.cli reconcile --adapter snowflake --database D --schema S --intended ./corpus/
loaded 6 intended policies from ./corpus/
Additions:     0
Removals:      0
Modifications: 3
  ~ ('table:D.S.foo', 'read'): diff fields = ['rules']
```

For a migration:

```bash
$ python -m adapters.tests.live_migration_demo
# (8 phases; one screen of output per phase; ~60 seconds end to end)
```

---

## Honest limitations at 0.6.0

The framing of these matters: not "TODO" items, but documented decisions about what the version does and doesn't cover. Each links to the tracking issue.

- **Snowflake ABAC byScope is not implemented** ([#31](https://github.com/bgiesbrecht/tessera/issues/31)). Snowflake uses object tags + tag-based-attachment masking/row-access policies, which is structurally different from Databricks' `CREATE POLICY ... MATCH COLUMNS has_tag_value(...)`. Real design step, wants a worked exercise before implementation.
- **No comment preservation in YAML round-trips** ([deferred from converter v1](docs/user-guide/scenarios/acl-and-masking.md)). The converter uses `ruamel.yaml` from the start so the round-trip parser already preserves the structural metadata; the actual comment-mapping work (per ADR-004) is a future v2 increment.
- **No formal `verify` adapter mode** for deployment-time configuration checks. Today's `reconcile` covers some of this surface (drift detection); a separate `verify` for things like "this principal binding maps to a role that doesn't exist on the target" or "the target column type doesn't match the policy's expected type" is queued as a design question.
- **Schema-pattern resource bindings** would simplify migration tooling (today the demo enumerates per-table bindings when migrating schema-scoped grants); not yet built.
- **Three governance gaps** ([#19](https://github.com/bgiesbrecht/tessera/issues/19) audit logging vocabulary, [#21](https://github.com/bgiesbrecht/tessera/issues/21) retention/deletion, [#25](https://github.com/bgiesbrecht/tessera/issues/25) AI governance attribute axes) have scoping documents queued.
- **The IR is pre-1.0 by design** (ADR-002 documents the project's skunkworks posture; ADR-017 documents the suspended-immutability framing — additions continue to land in v0 until external dependency exists).

Twenty of thirty-one filed issues remain open. The breakdown is in `docs/issue-drafts/README.md`. None of the open issues represents a blocking gap for the policy shapes the worked-example corpus exercises.

---

## What Tessera deliberately is not

These are non-goals, documented in ADRs and held consistently:

- **Not a runtime policy engine** (ADR-001). Tessera compiles to platform-native enforcement; there is no Tessera service in the query path.
- **Not a replacement for Unity Catalog inside Databricks-only shops.** Single-platform shops should use Unity Catalog directly. Tessera adds value precisely when policy must mean the same thing across estates.
- **Not a Databricks product.** Skunkworks (ADR-002). No commercial commitments, no SLA, no roadmap commitments to customers.
- **Not seeking standardization.** Uses W3C technology (RDF, OWL, JSON-LD, SHACL, SKOS) because the technology fits the problem; not pursuing W3C recommendation status.
- **Not operational interoperability.** Policy behavior on data physically moving between platforms (Delta Sharing, Iceberg replication) is out of scope.
- **Not prescriptive about authoring style** (ADR-027). Tessera represents policy intent; it does not invent cross-platform authoring recommendations the platforms themselves do not document. Where a platform's docs make a recommendation, Tessera surfaces and cites it.

The `docs/user-guide/evaluating.md` page expands these into a fuller adopt/don't-adopt decision framework.

---

## Where to read next

| If you want to | Read |
|---|---|
| Try Tessera against a real situation | `docs/user-guide/scenarios/acl-and-masking.md` (practitioner tutorial) |
| See the full migration cycle in prose | `docs/user-guide/scenarios/migrating-snowflake-to-uc.md` |
| Understand the IR semantics | `docs/technical-design-v0.2.md` |
| Audit the W3C-stack usage | `docs/w3c-overview.md` |
| Decide whether Tessera fits | `docs/user-guide/evaluating.md` |
| Extend Tessera | `docs/user-guide/contributing.md` + `DECISIONS.md` (the ADRs) |
| See what's actually committed and runnable | `adapters/tests/live_migration_demo.py` and the worked examples in `spec/v0/examples/` |
| Look at the open issue tracker | `docs/issue-drafts/README.md` |

---

## One last framing

Tessera is honest engineering practice on a real problem: governance policy that has to mean the same thing across data platforms. The cross-platform claim is empirically grounded — the migration scripts run; the verification queries return the expected numbers; the IR validates; the adapters round-trip.

The version is 0.6.0 because v0 isn't frozen yet (per ADR-017's suspended-immutability framing). Whether it ever reaches 1.0 depends on whether external dependency arrives — a real customer corpus, a third adapter, a tooling integration — at which point the spec freezes and the project commits to the surface it has.

Until then: the corpus is open, the artifacts are runnable, and the discipline holds. That is what 0.6.0 ships.
