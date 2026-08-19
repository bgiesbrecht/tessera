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
from adapters.custom_acl import CustomACLAdapter
from adapters.oracle import OracleAdapter
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
    assert uc_sql != sf_sql, "Adapters emitted identical SQL; the contract did not lower to platform-native form"


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
    its colon into the emitted `AS <alias>` / `ON COLUMN <alias>`, which would be
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
    """#31: byScope ColumnVisibility lowers to Snowflake tag-based masking:
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
    """#31: byScope RowVisibility lowers to Snowflake tag-based row access:
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
    # not the abstract policy param; required for tag-based row access to bind
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


def test_ai_governance_axis_composes_with_column_mask_on_both_adapters():
    """ADR-029: an AI-governance axis (trainingEligibility) drives an ordinary
    byScope column mask (no new emission path). Both adapters lower it to real
    masking DDL keyed off the axis, which is where the axis gets teeth."""
    policy = _load("ai-governance-training-mask-policy.jsonld")
    assert policy["appliesTo"]["matching"]["attributes"]["trainingEligibility"] == "NoTraining"

    uc = "\n".join(UnityCatalogAdapter().emit(policy).statements)
    assert "COLUMN MASK" in uc and "has_tag_value('trainingEligibility', 'NoTraining')" in uc

    sf = "\n".join(SnowflakeAdapter().emit(policy).statements)
    assert "MASKING POLICY" in sf
    assert "SYSTEM$GET_TAG_ON_CURRENT_COLUMN('trainingEligibility') = 'NoTraining'" in sf
    assert "'NOT-FOR-TRAINING'" in uc and "'NOT-FOR-TRAINING'" in sf  # the mask value on both


def test_retention_constraint_is_expression_only_on_both_adapters():
    """ADR-031: RetentionConstraint is expressed + validated but not emitted:
    no platform declarative retention primitive, and Tessera does not emit
    destructive scheduled jobs in v0. Both adapters emit zero statements and a
    RETENTION_EXPRESSION_ONLY diagnostic (not the generic UNIMPLEMENTED TODO)."""
    policy = _load("retention-delete-after-policy.jsonld")
    assert policy["@type"] == "RetentionConstraint"
    for adapter in (UnityCatalogAdapter(), SnowflakeAdapter()):
        result = adapter.emit(policy)
        assert result.statements == [], f"{adapter} should emit no DDL for retention"
        assert not result.has_errors
        assert any(d.code == "RETENTION_EXPRESSION_ONLY" for d in result.diagnostics)


def test_bydataset_acl_lowers_to_three_distinct_mechanisms():
    """ADR-032: the same byDataset ACL IR lowers to three distinct mechanisms:
    a UC row-filter function, a Snowflake row-access policy, and a custom-ACL
    wrapping VIEW. All three carry the ACL EXISTS-join; none errors; the custom-ACL
    adapter (a *pattern* adapter, not a platform) is a peer of the two native ones."""
    policy = _load("acl-row-visibility-policy.jsonld")

    uc = UnityCatalogAdapter().emit(policy)
    sf = SnowflakeAdapter().emit(policy)
    acl = CustomACLAdapter().emit(policy)

    for name, r in (("uc", uc), ("snowflake", sf), ("custom-acl", acl)):
        assert not r.has_errors, f"{name} emission errors: {r.diagnostics}"
        assert r.statements, f"{name} produced no statements"

    uc_sql = "\n".join(uc.statements)
    sf_sql = "\n".join(sf.statements)
    acl_sql = "\n".join(acl.statements)

    # Each emits its own platform-native mechanism.
    assert "ROW FILTER" in uc_sql
    assert "ROW ACCESS POLICY" in sf_sql
    assert "CREATE OR REPLACE VIEW" in acl_sql and "ROW FILTER" not in acl_sql

    # All three carry the shared ACL EXISTS-join over the same two ACL tables.
    for sql in (uc_sql, sf_sql, acl_sql):
        assert "EXISTS" in sql.upper()
        assert "rls_acl_mapping" in sql and "rls_priority_acl" in sql

    # The view is the enforcement in the custom pattern; no native primitive.
    assert "orders_rls_acl_secured" in acl_sql
    assert "current_user()" in acl_sql


def test_custom_acl_emit_extract_round_trips_to_equivalent_ir():
    """The migration on-ramp (ADR-003/ADR-032): emit an ACL view, then extract it
    back to IR. The reconstructed byDataset dataset + condition operand + protected
    table must match the source IR. That is what lets a hand-built ACL view be
    lifted and re-emitted to a native platform."""
    policy = _load("acl-row-visibility-policy.jsonld")
    adapter = CustomACLAdapter()

    emitted = adapter.emit(policy)
    assert not emitted.has_errors

    artifact = {
        "kind": "acl_view",
        "fq_name": "acme.tpch.orders_rls_acl_secured",
        "definition": emitted.statements[0],
    }
    ext = adapter.extract(artifact)
    assert ext.policy is not None
    assert ext.confidence >= 0.9
    assert not any(d.severity.value == "error" for d in ext.diagnostics)

    src_rule = policy["rules"][0]
    out_rule = ext.policy["rules"][0]
    assert out_rule["principal"]["dataset"] == src_rule["principal"]["dataset"]
    assert out_rule["condition"]["operands"][0] == src_rule["condition"]["operands"][0]
    assert out_rule["effect"] == src_rule["effect"]
    assert ext.policy["appliesTo"]["resource"] == policy["appliesTo"]["resource"]


def test_custom_acl_profile_is_pattern_adapter():
    """The custom-ACL adapter declares itself a peer with data-driven selectors as
    its core (SUPPORTED), and honestly UNSUPPORTED for tag/ABAC machinery."""
    from adapters.contract.types import Capability, CapabilitySupport
    acl = CustomACLAdapter()
    assert acl.capability_profile.platform == "Custom ACL (view-layer)"
    assert acl.capability_profile.support_for(Capability.ROW_VISIBILITY) == CapabilitySupport.SUPPORTED
    assert acl.capability_profile.support_for(Capability.DATASET_DRIVEN_PRINCIPALS) == CapabilitySupport.SUPPORTED
    assert acl.capability_profile.support_for(Capability.ATTRIBUTE_BASED_SCOPING) == CapabilitySupport.UNSUPPORTED


def test_oracle_row_visibility_lowers_to_vpd():
    """ADR-033: byIdentity row visibility → an Oracle VPD policy function (role-gated
    predicate over SYS_CONTEXT) attached with DBMS_RLS.ADD_POLICY. Distinct from the
    UC row-filter function and Snowflake row-access policy for the same IR."""
    policy = _load("group-row-visibility-policy-a.jsonld")
    r = OracleAdapter().emit(policy)
    assert not r.has_errors, r.diagnostics
    sql = "\n".join(r.statements)
    assert "DBMS_RLS.ADD_POLICY" in sql
    assert "SYS_CONTEXT('SYS_SESSION_ROLES', 'ACME_HIGH_PRIORITY_OPS')" in sql
    # The `in` condition is lowered to an IN predicate with doubled quotes (PL/SQL literal).
    assert "o_orderpriority IN (''1-URGENT'', ''2-HIGH'')" in sql
    # Fail-closed ELSE for principals in no rule.
    assert "RETURN '1=0'" in sql


def test_oracle_column_mask_lowers_to_data_redaction_with_quoted_expression():
    """ADR-033: Redact-with-replacement → DBMS_REDACT.REGEXP so the replacement
    literal is honored (FULL cannot). The `expression` is a PL/SQL string literal, so
    its inner quotes must be doubled; a regression guard for that."""
    policy = _load("column-mask-orders-clerk-policy.jsonld")
    r = OracleAdapter().emit(policy)
    assert not r.has_errors, r.diagnostics
    sql = "\n".join(r.statements)
    assert "DBMS_REDACT.ADD_POLICY" in sql
    assert "function_type        => DBMS_REDACT.REGEXP" in sql
    assert "regexp_replace_string => 'CLERK-REDACTED'" in sql
    # Inner quotes doubled; the literal would be malformed otherwise.
    assert "''SYS_SESSION_ROLES''" in sql and "''ORDERS_FULL_ACCESS''" in sql


def test_oracle_bydataset_vpd_round_trips_to_equivalent_ir():
    """Oracle's full cycle: emit a byDataset VPD policy, then extract its function
    body back to IR. The reconstructed dataset + operand match the source."""
    policy = _load("acl-row-visibility-policy.jsonld")
    adapter = OracleAdapter()
    emitted = adapter.emit(policy)
    assert not emitted.has_errors
    artifact = {
        "kind": "vpd_policy", "object_owner": "TPCH", "object_name": "ORDERS_RLS_ACL",
        "function_body": emitted.statements[0],
    }
    ext = adapter.extract(artifact)
    assert ext.policy is not None and ext.confidence >= 0.85
    src_rule = policy["rules"][0]
    out_rule = ext.policy["rules"][0]
    assert out_rule["principal"]["dataset"]["principalColumn"] == src_rule["principal"]["dataset"]["principalColumn"]
    assert out_rule["condition"]["operands"][0]["resourceColumn"] == src_rule["condition"]["operands"][0]["resourceColumn"]


def test_oracle_access_grant_lowers_to_grant_statement():
    policy = _load("table-grants-scenario-a.jsonld")
    r = OracleAdapter().emit(policy)
    assert not r.has_errors, r.diagnostics
    assert "GRANT SELECT ON TPCH.ORDERS TO ACME_MARKETING_ANALYTICS;" in "\n".join(r.statements)


def test_oracle_byscope_is_refused_honestly():
    """Oracle has no tag-driven attachment; byScope must produce a diagnostic, not DDL."""
    policy = _load("abac-column-mask-policy-a.jsonld")
    r = OracleAdapter().emit(policy)
    assert r.statements == []
    assert any(d.code == "UNSUPPORTED_ABAC_SCOPING" for d in r.diagnostics)


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
