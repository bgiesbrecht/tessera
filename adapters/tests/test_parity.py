"""Parity test: one IR, two adapters, two valid platform-native outputs.

This is the test that pressure-tests the adapter contract. Both adapters consume
the same JSON-LD policy from spec/v0/examples and emit platform-native SQL. The
test asserts:
    * Both adapters emit without errors.
    * Both produce non-empty target_artifacts referencing the same logical table.
    * Each adapter emits the platform-specific principal-binding mechanism
      (Databricks `is_account_group_member`, Snowflake `IS_ROLE_IN_SESSION`).
    * The two adapters' SQL is meaningfully different (the IR has been lowered
      to platform-specific DDL, not merely echoed).
"""

from __future__ import annotations

import json
from pathlib import Path

from adapters.contract.types import AdapterConfig
from adapters.snowflake import SnowflakeAdapter
from adapters.unity_catalog import UnityCatalogAdapter


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = REPO_ROOT / "spec" / "v0" / "examples"


def _load(name: str) -> dict:
    with open(EXAMPLES / name) as f:
        return json.load(f)


def test_row_visibility_parity_emits_clean_on_both_adapters():
    policy = _load("group-row-visibility-policy-a.jsonld")

    uc_config = AdapterConfig(
        identity_bindings={"principal:acme_high_priority_ops": "acme_high_priority_ops"},
    )
    sf_config = AdapterConfig(
        identity_bindings={"principal:acme_high_priority_ops": "ACME_HIGH_PRIORITY_OPS"},
    )

    uc = UnityCatalogAdapter(config=uc_config).emit(policy)
    sf = SnowflakeAdapter(config=sf_config).emit(policy)

    assert not uc.has_errors, f"UC emission errors: {uc.diagnostics}"
    assert not sf.has_errors, f"Snowflake emission errors: {sf.diagnostics}"
    assert uc.statements, "UC produced no statements"
    assert sf.statements, "Snowflake produced no statements"

    uc_sql = "\n".join(uc.statements)
    sf_sql = "\n".join(sf.statements)

    assert "is_account_group_member" in uc_sql, "UC SQL missing platform-native group binding"
    assert "IS_ROLE_IN_SESSION" in sf_sql, "Snowflake SQL missing platform-native role binding"
    assert "SET ROW FILTER" in uc_sql, "UC SQL missing row-filter attachment DDL"
    assert "ROW ACCESS POLICY" in sf_sql, "Snowflake SQL missing row-access-policy DDL"
    assert uc_sql != sf_sql, "Adapters emitted identical SQL — the contract did not lower to platform-native form"


def test_column_visibility_parity_emits_clean_on_both_adapters():
    """Same IR for the column-mask-orders-clerk policy, both adapters emit valid
    platform-native column-mask DDL with the correct primitives.
    """
    policy = _load("column-mask-orders-clerk-policy.jsonld")

    uc_config = AdapterConfig(
        identity_bindings={"group:orders_full_access": "orders_full_access"},
    )
    sf_config = AdapterConfig(
        identity_bindings={"group:orders_full_access": "ORDERS_FULL_ACCESS"},
        resource_bindings={
            "column:acme.tpch.orders.o_clerk": "ACME.TESSERA.SNOW_ORDERS.O_CLERK",
        },
    )

    uc = UnityCatalogAdapter(config=uc_config).emit(policy)
    sf = SnowflakeAdapter(config=sf_config).emit(policy)

    assert not uc.has_errors, f"UC emission errors: {uc.diagnostics}"
    assert not sf.has_errors, f"Snowflake emission errors: {sf.diagnostics}"

    uc_sql = "\n".join(uc.statements)
    sf_sql = "\n".join(sf.statements)

    # Both must produce the platform-native column-mask primitive.
    assert "SET MASK" in uc_sql, "UC SQL missing column-mask attachment DDL"
    assert "MASKING POLICY" in sf_sql, "Snowflake SQL missing masking-policy DDL"

    # Both must reference the policy's Redact replacement literal.
    assert "CLERK-REDACTED" in uc_sql and "CLERK-REDACTED" in sf_sql, \
        "Redact replacement literal missing from one or both adapters' output"

    # Platform-specific principal-binding mechanism present in each.
    assert "is_account_group_member" in uc_sql
    assert "IS_ROLE_IN_SESSION" in sf_sql

    assert uc_sql != sf_sql


def test_abac_byscope_alias_is_sanitized_for_namespaced_values():
    """A namespaced attribute value (acme:PIIClerk, per ADR-028) must not leak
    its colon into the emitted `AS <alias>` / `ON COLUMN <alias>` — that would be
    invalid Databricks SQL. The alias is sanitized to a legal identifier."""
    policy = _load("abac-column-mask-policy-a.jsonld")
    assert policy["appliesTo"]["matching"]["attributes"]["sensitivity"] == "acme:PIIClerk"
    result = UnityCatalogAdapter().emit(policy)
    sql = "\n".join(result.statements)
    # The colon is fine inside the quoted tag value; it must not appear in the
    # identifier positions (AS / ON COLUMN).
    assert "AS acme:PIIClerk" not in sql and "ON COLUMN acme:PIIClerk" not in sql
    assert "AS acme_PIIClerk" in sql and "ON COLUMN acme_PIIClerk" in sql


def test_snowflake_abac_byscope_column_mask_is_tag_based():
    """#31: byScope ColumnVisibility lowers to Snowflake tag-based masking —
    CREATE MASKING POLICY reading SYSTEM$GET_TAG_ON_CURRENT_COLUMN, attached via
    ALTER TAG ... SET MASKING POLICY."""
    policy = _load("abac-column-mask-policy-a.jsonld")
    assert policy["appliesTo"]["selector"] == "byScope"
    result = SnowflakeAdapter().emit(policy)
    sql = "\n".join(result.statements)
    assert not result.has_errors
    assert "CREATE OR REPLACE MASKING POLICY" in sql
    assert "SYSTEM$GET_TAG_ON_CURRENT_COLUMN(" in sql
    assert "SET MASKING POLICY" in sql
    assert "IS_ROLE_IN_SESSION('ACME_ALL_PRIORITY_OPS')" in sql  # allow-role pass-through
    assert "'CLERK-REDACTED'" in sql                             # the Redact transform


def test_snowflake_abac_byscope_row_filter_is_tag_based():
    """#31: byScope RowVisibility lowers to Snowflake tag-based row access —
    CREATE ROW ACCESS POLICY as a CASE ladder over IS_ROLE_IN_SESSION + a
    predicate on the matched column, attached via ALTER TAG ... SET ROW ACCESS
    POLICY ... ON (col)."""
    policy = _load("abac-row-filter-priority.jsonld")
    assert policy["appliesTo"]["selector"] == "byScope"
    result = SnowflakeAdapter().emit(policy)
    sql = "\n".join(result.statements)
    assert not result.has_errors
    assert "CREATE OR REPLACE ROW ACCESS POLICY" in sql
    assert "RETURNS BOOLEAN" in sql
    # The ON clause names the real discriminator column (from the matching value),
    # not the abstract policy param — required for tag-based row access to bind
    # (live-verified 2026-08-13).
    assert "SET ROW ACCESS POLICY" in sql and "ON (orderpriority VARCHAR)" in sql
    # Three-branch first-match: all-ops → all rows; high-ops → 1/2; else → 3/4/5.
    assert "IS_ROLE_IN_SESSION('ACME_ALL_PRIORITY_OPS') THEN TRUE" in sql
    assert "matched IN ('1-URGENT', '2-HIGH')" in sql
    assert "ELSE matched IN ('3-MEDIUM', '4-NOT SPECIFIED', '5-LOW')" in sql
    # The $matched sentinel must not leak into the emitted SQL.
    assert "$matched" not in sql


def test_snowflake_abac_byscope_uses_configured_tag_taxonomy():
    """With a schema-qualified tag_taxonomy binding, the emitted tag key is the
    configured one (no UNBOUND_TAG_ATTRIBUTE warning), and it is schema-qualified."""
    policy = _load("abac-column-mask-policy-a.jsonld")
    config = AdapterConfig(
        tag_taxonomy={("sensitivity", "acme:PIIClerk"): ("governance.tags.data_class", "clerk")},
    )
    result = SnowflakeAdapter(config=config).emit(policy)
    sql = "\n".join(result.statements)
    assert "SYSTEM$GET_TAG_ON_CURRENT_COLUMN('governance.tags.data_class') = 'clerk'" in sql
    assert "ALTER TAG governance.tags.data_class SET MASKING POLICY" in sql
    assert not any(d.code == "UNBOUND_TAG_ATTRIBUTE" for d in result.diagnostics)


def test_capability_profiles_differ_meaningfully():
    """Both adapters declare profiles, with different platform names."""
    uc = UnityCatalogAdapter()
    sf = SnowflakeAdapter()
    assert uc.capability_profile.platform == "Databricks"
    assert sf.capability_profile.platform == "Snowflake"
    # Sanity: both adapters declare at least one capability as SUPPORTED.
    from adapters.contract.types import Capability, CapabilitySupport
    assert uc.capability_profile.support_for(Capability.ROW_VISIBILITY) == CapabilitySupport.SUPPORTED
    assert sf.capability_profile.support_for(Capability.ROW_VISIBILITY) == CapabilitySupport.SUPPORTED
    assert uc.capability_profile.support_for(Capability.COLUMN_VISIBILITY) == CapabilitySupport.SUPPORTED
    assert sf.capability_profile.support_for(Capability.COLUMN_VISIBILITY) == CapabilitySupport.SUPPORTED
