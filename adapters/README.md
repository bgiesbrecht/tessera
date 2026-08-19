# Tessera platform adapters

This directory contains the adapter contract (`contract/`) and concrete adapter
implementations. Adapters are peers against one contract (ADR-003): native-platform
adapters and custom-pattern adapters implement the same four responsibilities
(emit / discover / extract / reconcile) and each publishes a capability profile.

## Contents

```
contract/                Adapter ABC, CapabilityProfile, AdapterConfig, Result types
unity_catalog/           Databricks adapter (Unity Catalog) — native platform
snowflake/               Snowflake adapter — native platform
oracle/                  Oracle adapter (VPD / Data Redaction / GRANT) — native platform (ADR-033)
custom_acl/              Custom ACL-table + wrapping-view adapter — pattern adapter (ADR-032)
tests/                   Cross-adapter parity tests + live_*.py integration scripts
```

See `DECISIONS.md` ADR-024 for the contract shape, ADR-003 for the peer-adapter
model, and ADR-032 for the pattern-adapter category (custom-ACL).

## Adding an adapter

Mirror an existing package (`snowflake/` is the closest template):

- `__init__.py` — export the `*Adapter` class only.
- `adapter.py` — subclass `adapters.contract.adapter.Adapter`; set `name` / `platform`;
  implement `emit()` and (optionally) `discover()` / `extract()` (`reconcile()` has a
  default: discover → extract → diff).
- `capability.py` — a module-level `<PLATFORM>_PROFILE` mapping each `Capability` to
  `(CapabilitySupport, rationale)`. Keep it honest — cite platform docs per ADR-027.
- `emission.py` — `emit_policy(policy, config) -> EmissionResult`, dispatching on
  `policy.get("policyKind") or policy.get("@type")`.
- `discovery.py` — `discover_schema(...)` and `extract_artifact(...)`.

Then register it in `tools/cli/main.py` (`_build_adapter` + the four subcommand
`--adapter` choices lists) and add parity coverage in `adapters/tests/test_parity.py`.

## Running the parity test

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, '.')
from adapters.tests.test_parity import (
    test_row_visibility_parity_emits_clean_on_both_adapters,
    test_capability_profiles_differ_meaningfully,
)
test_row_visibility_parity_emits_clean_on_both_adapters()
test_capability_profiles_differ_meaningfully()
print('parity tests: PASS')
"
```

The test loads `spec/v0/examples/group-row-visibility-policy-a.jsonld`, emits
through both adapters, and verifies that the platform-specific principal-binding
mechanism (`is_account_group_member` on Databricks; `IS_ROLE_IN_SESSION` on
Snowflake) is present and that the two outputs differ meaningfully.

## Live execution

Both adapters return platform-native SQL statements; execution is the caller's
responsibility. For live execution:

- **Databricks** — use `databricks-sdk` (already installed in `.venv`) and the
  Statement Execution API. The worked-example transcripts in `docs/exercises/`
  show the canonical pattern.
- **Snowflake** — `pip install snowflake-connector-python` and connect with the
  JDBC-style settings the operator provides. The scaffold's `SnowflakeAdapter`
  does not bundle connection handling; lazy-import the connector in the calling
  script.

## Capability profiles

Each adapter declares a `CapabilityProfile` enumerating which IR concepts it
supports, partially supports, or refuses. Diagnostics emitted during `emit()`
cite the profile when a policy concept must be downgraded or refused. The
profile is informational, not a runtime gate — emission may still produce
output for a PARTIAL capability with a warning diagnostic.

## Coverage, honestly

- **Unity Catalog / Snowflake** — full ADR-024 cycle (emit / discover / extract /
  reconcile). Emit covers `RowVisibilityConstraint` (`byIdentity`, `byScope`,
  `byDataset`), `ColumnVisibilityConstraint` (`Redact`), and `AccessGrantConstraint`.
  `RetentionConstraint` is expression-only (`RETENTION_EXPRESSION_ONLY`, ADR-031).
- **Oracle** — full cycle against Oracle primitives (ADR-033): row visibility via VPD
  (`DBMS_RLS.ADD_POLICY` + a role-gated / EXISTS policy function), column masking via
  Data Redaction (`DBMS_REDACT.ADD_POLICY`, REGEXP so the replacement is honored),
  access grants via `GRANT`. No tag-driven ABAC (`byScope` refused with a diagnostic;
  OLS deferred). Live-verified 2026-08-17 on Oracle 23ai Free (`tests/live_oracle.py`): VPD row
  visibility (2/5/0 rows) and Data Redaction (role-gated) both enforce.
- **custom-ACL** — emit lowers a `byDataset` `RowVisibilityConstraint` to a wrapping
  secure view; extract lifts such a view back to IR (the selective-migration on-ramp,
  ADR-032). Column masking in the view is a queued follow-up.

Gaps surface as structured diagnostics, never silent output. Adding coverage proceeds
by extending `emission.py` per adapter and adding parity tests against worked examples.
