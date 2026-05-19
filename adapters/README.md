# Tessera platform adapters

This directory contains the adapter contract (`contract/`) and concrete adapter
implementations for the platforms Tessera targets. The current implementations
are scaffolds: the contract is fully defined and emission is wired up for
group-driven row-visibility policies on both platforms; discovery, extraction,
and reconciliation are stubbed with explicit diagnostics.

## Contents

```
contract/                Adapter ABC, CapabilityProfile, DiagnosticReport, AdapterConfig
unity_catalog/           Databricks adapter (Unity Catalog)
snowflake/               Snowflake adapter
tests/                   Cross-adapter parity tests
```

See `DECISIONS.md` ADR-024 for the rationale behind the contract shape.

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

## What the scaffolds do not yet do

- **Discovery** — both adapters return `DISCOVERY_NOT_IMPLEMENTED`.
- **Extraction** — both adapters return `EXTRACTION_NOT_IMPLEMENTED`.
- **Reconciliation** — both adapters return `RECONCILIATION_NOT_IMPLEMENTED`.
- **Non-row-visibility policy kinds** — `ColumnVisibilityConstraint`,
  ABAC-scoped policies, etc. emit a placeholder statement plus an
  `UNIMPLEMENTED_POLICY_KIND` diagnostic.
- **Selector kinds beyond byIdentity** — `byClassification`, `byScope`,
  `byDataset`, `byComposition` all warn.

Adding coverage proceeds by extending `emission.py` per adapter and adding
parity tests against additional worked examples.
