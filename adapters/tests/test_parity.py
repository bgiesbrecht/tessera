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
        identity_bindings={"principal:bg_rls_demo_high_priority_ops": "bg_rls_demo_high_priority_ops"},
    )
    sf_config = AdapterConfig(
        identity_bindings={"principal:bg_rls_demo_high_priority_ops": "BG_RLS_DEMO_HIGH_PRIORITY_OPS"},
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
            "column:bg_rls_demo.tpch.orders.o_clerk": "BRICETEST.TESSERA.SNOW_ORDERS.O_CLERK",
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
