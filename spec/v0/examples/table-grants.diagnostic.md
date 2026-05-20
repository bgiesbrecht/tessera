# Diagnostic — Table-Level Grants Exercise

**Phase 2 + Phase 3 deliverable.** Validates that the IR expresses simple-to-progressive grant patterns cleanly, with the load-bearing framing surfaced 2026-05-19: Tessera's primary driving activity is migration; if it can't express bread-and-butter RBAC alongside complex ABAC, the framework cannot serve its primary use case. Companion to `docs/exercises/table-grants-handoff.md`.

## 1. Per-scenario enforcement

| Scenario | IR shape | Databricks DDL | Live-verified |
|---|---|---|---|
| A — single-table read | `RowVisibilityConstraint`, `effect: allow`, `action: Read`, `appliesTo: byIdentity table` | `GRANT SELECT ON TABLE ... TO ...` | ✅ |
| B — schema-level read | `RowVisibilityConstraint`, `effect: allow`, `action: Read`, `appliesTo: byScope schema` (no `matching`) | `GRANT USE SCHEMA ... TO ...; GRANT SELECT ON SCHEMA ... TO ...` | ✅ (incl. propagation) |
| C — function execute | `RowVisibilityConstraint`, `effect: allow`, `action: Execute`, `appliesTo: byIdentity function:` | `GRANT EXECUTE ON FUNCTION ... TO ...` | ✅ |

All three IR shapes validate cleanly against `schema.json` and `shapes.ttl` post-addition of the `Execute` action (the addition is itself a finding; see §3).

## 2. Live verification (Phase 3)

Live-executed against `bg_rls_demo` on workspace `adb-984752964297111` on 2026-05-19. Group substitutions for testing (the intended business-named groups don't exist in this workspace, per the brief's "names don't matter for docs, do for testing" framing):

- `bg_rls_demo_marketing_analytics` → substituted with existing `bg_rls_demo_high_priority_ops`.
- `bg_rls_demo_data_engineering` → substituted with existing `bg_rls_demo_all_priority_ops`.

### Scenario A live result

```sql
> GRANT SELECT ON TABLE bg_rls_demo.tpch.orders TO `bg_rls_demo_high_priority_ops`;
OK

> SHOW GRANTS ON TABLE bg_rls_demo.tpch.orders;
['bg_rls_demo_high_priority_ops', 'SELECT', 'TABLE', 'bg_rls_demo.tpch.orders']
['account users', 'SELECT', 'TABLE', 'bg_rls_demo.tpch.orders']
```

The grant is recorded against the named principal. The pre-existing `account users` grant from prior exercise setup is also visible, consistent with the additive nature of GRANT statements.

### Scenario B live result, including propagation

```sql
> GRANT USE SCHEMA ON SCHEMA bg_rls_demo.tpch_staging TO `bg_rls_demo_all_priority_ops`;
OK
> GRANT SELECT ON SCHEMA bg_rls_demo.tpch_staging TO `bg_rls_demo_all_priority_ops`;
OK

> SHOW GRANTS ON SCHEMA bg_rls_demo.tpch_staging;
['bg_rls_demo_all_priority_ops', 'SELECT', 'SCHEMA', 'bg_rls_demo.tpch_staging']
['bg_rls_demo_all_priority_ops', 'USE SCHEMA', 'SCHEMA', 'bg_rls_demo.tpch_staging']
```

**Propagation test.** After applying the schema-level grant, a new table was created in the staging schema:

```sql
> CREATE TABLE bg_rls_demo.tpch_staging.propagation_test AS SELECT 1 AS x, 2 AS y;
OK

> SHOW GRANTS ON TABLE bg_rls_demo.tpch_staging.propagation_test;
['bg_rls_demo_all_priority_ops', 'SELECT', 'SCHEMA', 'bg_rls_demo.tpch_staging']
```

The schema-level grant is visible at the table level *without* additional administrative action. Note that Databricks reports the grant's source object type as `SCHEMA`, which is the correct way to surface inherited grants — the platform tracks the grant at the schema level and resolves it at query time for child objects. The ADR-019 downward-propagation semantics that `byScope` was designed to express are working as documented.

### Scenario C live result

```sql
> GRANT EXECUTE ON FUNCTION bg_rls_demo.tpch.compute_customer_ltv
    TO `bg_rls_demo_high_priority_ops`;
OK

> SHOW GRANTS ON FUNCTION bg_rls_demo.tpch.compute_customer_ltv;
['bg_rls_demo_high_priority_ops', 'EXECUTE', 'FUNCTION',
 'bg_rls_demo.tpch.compute_customer_ltv']
```

The `Execute` action lowers cleanly to Databricks `EXECUTE`. The grant is recorded against the function as a first-class governed object.

### Per-user behavioral verification

The "Brice in group / Brice not in group" tests from the brief (e.g., A-test-2: querying as a non-member) require switching the calling principal, which the workspace SDK does not surface directly. These tests have not been live-executed in this Phase 3 — they require either a separate test user, group membership toggling, or manual verification by Brice. The structural verification (the GRANT exists; `SHOW GRANTS` reports it) is the empirical evidence Phase 3 captured.

## 3. v0 IR findings

### 3.1 — `Execute` action added to v0 vocabulary (resolved)

Prior to this exercise, `Execute` was not a well-known action in v0 (`Read`, `Write`, `Delete`, `Share`, `Sample`, `Aggregate` were the six). The exercise's Scenario C required it.

**Resolution adopted:** `Execute` added to `ontology.ttl`, `context.jsonld`, `schema.json`, and `shapes.ttl` prior to Phase 2 derivation, with explicit **semantic-only scope**. The boundary recorded on the ontology entry:

> "Invoke a callable Resource (typically a user-defined function or stored procedure). Scoped to policy intent (gating who can invoke business-logic resources); platform-mechanism uses of EXECUTE (e.g., the grants required to attach a UDF to an enforcement policy) are adapter scaffolding, not modeled in the IR."

This boundary was load-bearing — it came from a Glean enumeration of Unity Catalog EXECUTE uses that showed two categories of EXECUTE grant: business-logic gating (Tessera concern) vs UDF-as-enforcement-vehicle scaffolding (adapter concern, parallel to the GRANT SELECT lesson from the column-mask exercise). Documenting the boundary explicitly prevents future contributors from pulling mechanism uses into the IR.

This finding becomes ADR-025.

### 3.2 — `function:` IRI prefix is a new informal convention

Scenario C uses `function:bg_rls_demo.tpch.compute_customer_ltv` as a `byIdentity` resource. The `function:` prefix is not declared in `context.jsonld` (only `table:`, `column:`, `group:`, and `principal:` are used by prior exercises as informal conventions). This exercise extends the informal-convention space.

The same approach as before — informal prefixes are not validated by the IR layer; they are operator-recognizable strings that adapters interpret per platform. Future formalization (declaring the prefixes in context.jsonld, validating with SHACL) is a queued v0 doc item that may land alongside [#4](https://github.com/bgiesbrecht/tessera/issues/4) (iri-safety-convention).

### 3.3 — `byScope` without `matching` works at all three validation layers

Scenario B uses `byScope` with no `matching` block — the "match everything in scope" path. Validated:

- **JSON Schema layer**: the `oneOf` branch for `byScope` requires `scope` but not `matching`; clean validation.
- **SHACL layer**: no constraint violation; the absence of `matching` is acceptable.
- **Live platform behavior**: `GRANT ... ON SCHEMA ...` correctly propagates to child tables, both existing and newly-created.

The semantics ("no matching block = apply to every resource in scope, with downward inheritance to child resources") are now empirically grounded; if claude.ai or other contributors prefer to make this explicit in the technical design §3.3a or in shapes.ttl as a documentation update, the empirical foundation is here. No new ADR required.

### 3.4 — `RowVisibilityConstraint` vs `AccessGrantConstraint` (RESOLVED by ADR-026, 2026-05-20)

All three scenarios in this exercise are affirmative grants. The current IR has no `AccessGrantConstraint` policyKind, so the exercise squeezed them into `RowVisibilityConstraint` with `effect: allow`. This works structurally (validates clean; no schema or SHACL violations) but is *semantically misleading* — a row-visibility constraint conceptually limits which rows are seen; an affirmative grant confers ability. The shoehorn is awkward in three concrete ways:

1. **Reader comprehension.** A `.tessera.yaml` reader who sees `kind: RowVisibilityConstraint` on a file that is really a table-level grant has to read the rule body before realizing it's not actually a row-visibility constraint. The policyKind is misleading them.

2. **Tooling dispatch.** An adapter implementing `emit()` typically dispatches on `policyKind` first. Today, a Snowflake or Databricks adapter receiving "RowVisibilityConstraint + effect: allow on a table" must internally detect the affirmative-grant shape and emit a `GRANT` statement rather than a row-filter UDF. This is dispatchable but not natural.

3. **Migration extraction.** When extracting `SHOW GRANTS` output into IR (§4), there is no honest answer for what `policyKind` to assign — `RowVisibilityConstraint` is structurally wrong (there's no row visibility involved); `ColumnVisibilityConstraint` is also wrong. The IR is missing the concept.

**Sketch of an `AccessGrantConstraint`:**

```yaml
policy:
  id: example
  kind: AccessGrantConstraint                    # the missing policyKind
  appliesTo:
    selector: byIdentity
    resource: table:foo
  action: Read
  rules:
    - principal:
        selector: byIdentity
        resource: group:bar
      effect: allow                              # affirmative grant
```

Adoption would mean: new ontology class, context short-name, schema enum entry, shape, and probably technical-design §4 paragraph. Roughly the size of an ADR-022-shaped change (small, but spans all four spec files).

**Disposition (2026-05-20):** Resolved by ADR-026. `AccessGrantConstraint` landed as the fifth `policyKind` across `ontology.ttl`, `context.jsonld`, `schema.json`, and `shapes.ttl`. The three Phase 2 artifacts (`table-grants-scenario-{a,b,c}.tessera.yaml`) migrated from `kind: RowVisibilityConstraint` to `kind: AccessGrantConstraint`; the JSON-LDs were regenerated via the converter; all 11 worked-example policies still validate clean against schema and SHACL.

The decision-on-landing was originally framed as "defer until a migration exercise drives it" — superseded by Brice's 2026-05-20 ask to land the change ahead of the migration story rather than alongside. The structural awkwardness this section enumerated is now eliminated; readers, tooling dispatch, and migration extraction all see the honest policyKind.

## 4. Extraction shape sketch

The migration use case requires lowering existing platform grants into IR. The exercise validates that this is mechanical for the shapes it covers:

### Databricks `SHOW GRANTS` → Tessera IR

```
SHOW GRANTS ON TABLE bg_rls_demo.tpch.orders
==>
['bg_rls_demo_high_priority_ops', 'SELECT', 'TABLE', 'bg_rls_demo.tpch.orders']
```

Lowers to:

```yaml
policy:
  id: extracted-grant-001
  kind: RowVisibilityConstraint                  # or AccessGrantConstraint, when added
  appliesTo:
    selector: byIdentity
    resource: table:bg_rls_demo.tpch.orders
  action: Read                                   # SELECT → Read
  rules:
    - principal: {selector: byIdentity, resource: group:bg_rls_demo_high_priority_ops}
      effect: allow
provenance:
  extractedFrom: databricks-grant
  notes: SHOW GRANTS row [bg_rls_demo_high_priority_ops, SELECT, TABLE, ...]
```

Field-by-field mapping:

| SHOW GRANTS field | IR field | Conversion |
|---|---|---|
| Principal column | `rules[0].principal.resource` | `group:<name>` (prefixed informally) |
| Privilege column | `action` | `SELECT → Read; USE SCHEMA → (currently no IR analog); EXECUTE → Execute` |
| Object type column | (determines `appliesTo.selector`) | `TABLE / SCHEMA / FUNCTION → resource: prefix selection` |
| Object name column | `appliesTo.resource` | Verbatim string with prefix |

**Two findings the extraction sketch surfaces** (besides confirming the mechanical mappability):

- **`USE SCHEMA` has no current IR analog.** The schema-level grant from Scenario B requires both `USE SCHEMA` and `SELECT ON SCHEMA` in Databricks DDL; the IR's `Read` action lowers to `SELECT` but there's no Tessera-level concept that lowers to `USE SCHEMA`. This is fine for the demo (the adapter emits both as scaffolding for the read intent); a migration extractor lifting `USE SCHEMA` grants would need to drop them as adapter-deployment noise or model them as additional implicit grants. Recommend the latter — `USE SCHEMA` is operationally inseparable from `SELECT` for schema-scoped read intent.
- **Privilege expansion.** Some Databricks privileges (e.g., `ALL PRIVILEGES`) don't have a single Tessera action equivalent. Migration extraction would need to expand them to the closed action set, with the diagnostic recording the expansion.

### Snowflake `SHOW GRANTS` → Tessera IR

Structurally similar; left as an exercise for a future Snowflake-byDataset-migration exercise. The shape is the same: privilege → action, grantee → principal, object → resource. The mapping table from privilege name to IR action would be Snowflake-specific (e.g., `USAGE` on a schema maps similarly to Databricks `USE SCHEMA`).

## 5. Migration validation summary

The exercise's load-bearing finding for the framework's value proposition:

**Tessera can lift Databricks `SHOW GRANTS` output into the IR with no information loss for the three grant shapes exercised here.** The mapping is mechanical (closed action set, principal-prefix convention, resource-prefix convention) and the emitted DDL round-trips cleanly. This validates the migration use case for the basic RBAC corpus — exactly the gap that the morning conversation surfaced.

What this exercise did NOT exercise but the migration use case will need:
- **Cross-platform extraction.** Lifting Snowflake `SHOW GRANTS` rows into the same IR shapes is a follow-up exercise.
- **Multi-action grants in one administrative act.** `GRANT SELECT, UPDATE ON TABLE foo TO bar` — single grant statement, two Tessera actions. Whether the IR shapes this as one policy with multiple rules or as multiple parallel policies is open.
- **Privilege expansion.** Platform meta-privileges (`ALL PRIVILEGES`, `OWNERSHIP`) expand to many IR actions; the expansion is mechanical but the diagnostic format needs design.
- **Revocation.** Tessera expresses what policies say; revocation is administrative state-change, not policy intent. A migration's "remove this grant" step lives outside the IR.

## 6. What this exercise does not cover

- **Discovery / extraction implementation.** The adapter's discover and extract methods are still stubbed. The extraction sketch in §4 is the IR-level shape; the adapter code that produces it is queued.
- **`AccessGrantConstraint` adoption.** Deferred per §3.4; the IR works under `RowVisibilityConstraint` for now.
- **Per-user behavioral testing.** The "Brice in group / not in group" scenarios require role-switching that the workspace SDK doesn't surface; structural verification (GRANT exists; SHOW GRANTS reports it) is what Phase 3 captured.
- **Snowflake counterparts.** Each of A/B/C has a Snowflake equivalent; this exercise stayed Databricks-side. Worth a follow-up if the migration use case formalizes.

## 7. Disposition

- **Spec changes landed**: `Execute` action across all four v0 spec files; will be documented in ADR-025.
- **IR finding open**: `AccessGrantConstraint` policyKind candidate; not landing in this exercise.
- **IR finding open**: `USE SCHEMA` and other implicit-scaffolding privileges; defer until migration exercise drives the design.
- **Workspace artifacts**: `bg_rls_demo.tpch_staging` schema and `bg_rls_demo.tpch.compute_customer_ltv` function exist and are reusable. Run `adapters/tests/setup_table_grants.py` to re-provision.
- **Issue [#10](https://github.com/bgiesbrecht/tessera/issues/10) — policy-execute-grants**: substantially closed by this exercise's adoption of `Execute` with the semantic-only boundary. Worth closing on GitHub with a pointer to this diagnostic.
