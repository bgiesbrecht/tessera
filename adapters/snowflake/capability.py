"""Snowflake capability profile.

Snowflake's policy primitives are row-access policies and masking policies
attached to objects, optionally driven by object tags. The capability surface
overlaps substantially with Unity Catalog but differs in several specifics that
matter for IR translation — most notably, Snowflake uses session roles, not
account-level group membership, as the canonical principal-binding axis.
"""

from adapters.contract.types import (
    Capability,
    CapabilityProfile,
    CapabilitySupport,
)

SNOWFLAKE_PROFILE = CapabilityProfile(
    adapter_name="snowflake",
    platform="Snowflake",
    entries={
        Capability.ROW_VISIBILITY: (
            CapabilitySupport.SUPPORTED,
            "Emitted via CREATE ROW ACCESS POLICY ... RETURNS BOOLEAN -> ... plus "
            "ALTER TABLE ... ADD ROW ACCESS POLICY ... ON (col). Two semantic distinctions "
            "matter when authoring against this adapter (see issue #14):\n"
            "(1) Role-discrimination semantics. Snowflake offers two distinct primitives "
            "for role-based gating: `CURRENT_ROLE()` (primary role only) and "
            "`IS_ROLE_IN_SESSION(X)` (any active role, primary OR secondary). The adapter "
            "currently emits `IS_ROLE_IN_SESSION(X)` for byIdentity principal selectors, "
            "matching Snowflake's recommendation for role-discrimination scenarios: 'If role "
            "activation and role hierarchy are important, Snowflake recommends that the policy "
            "conditions use the IS_ROLE_IN_SESSION function for account roles...' "
            "(docs.snowflake.com/en/user-guide/security-row-using). This carries "
            "permission-scope semantics: any user granted role X sees the data. Policies "
            "needing strict primary-role discrimination would require a different adapter "
            "emission, currently a deferred design question pending an exercise that drives "
            "it. Per BCR-1692 (rolled out Aug 2024 → Mar 2025), Snowflake defaults new users "
            "to `DEFAULT_SECONDARY_ROLES = ('ALL')`, which is consistent with the adapter's "
            "emission choice — secondary roles activate, IS_ROLE_IN_SESSION sees them, "
            "permission-scope semantics hold.\n"
            "(2) Snowflake roles form an inheritance hierarchy, unlike Databricks' flat "
            "group membership: if HIGH inherits PUBLIC, a user with HIGH active sees both "
            "HIGH's branch and PUBLIC's branch. The same IR therefore produces different "
            "effective row-set arithmetic on the two platforms — `IS_ROLE_IN_SESSION` "
            "behaves transitively in Snowflake but `is_account_group_member` does not in "
            "Databricks. Author accordingly.",
        ),
        Capability.COLUMN_VISIBILITY: (
            CapabilitySupport.SUPPORTED,
            "Emitted via CREATE OR REPLACE MASKING POLICY ... AS (col VARCHAR) RETURNS VARCHAR -> CASE ... END "
            "plus ALTER TABLE ... MODIFY COLUMN ... SET MASKING POLICY. Live-verified 2026-05-19 against "
            "BRICETEST.TESSERA.SNOW_ORDERS.O_CLERK: identity-bound role sees real values; all other "
            "tested roles (ACCOUNTADMIN, ALL_PRIORITY_OPS, PUBLIC) see the Redact replacement literal. "
            "Coverage: byIdentity column targets; rules with effect=allow or effect=transform; "
            "defaultBranch with effect=transform; Redact transformation. Role-discrimination semantics "
            "are Intent B (IS_ROLE_IN_SESSION) per Snowflake's recommendation and the adapter's "
            "convention (see issue #14). Mask and Hash transformations have SQL templates queued. "
            "ABAC byScope column masking remains a separate emission path, not yet implemented.",
        ),
        Capability.ATTRIBUTE_BASED_SCOPING: (
            CapabilitySupport.PARTIAL,
            "Snowflake supports tag-based policies via CREATE TAG and ALTER ... SET TAG, with policies referencing "
            "SYSTEM$GET_TAG. The IR's `byScope` + `matching` clauses can be lowered to tag references, but the "
            "scaffold currently emits per-table mechanisms only and routes ABAC paths through a TODO.",
        ),
        Capability.DATASET_DRIVEN_PRINCIPALS: (
            CapabilitySupport.PARTIAL,
            "PrincipalSetFromTable lowers to a correlated EXISTS subquery inside the row-access policy body, "
            "joining the IR's mapping table to the IR's resource-ACL table on the shared codename column. "
            "Live-verified on 2026-05-19 against BRICETEST.TESSERA.SNOW_ORDERS_RLS_ACL — all four scenarios "
            "(seed, additive grant, removal, secondary-roles immunity) pass. This is the pattern Snowflake "
            "documents for data-driven entitlement (membership is a relation, not a role): see "
            "docs.snowflake.com/en/user-guide/security-row-using — 'A row access policy condition can reference "
            "a mapping table to filter the query result set... use a mapping table to determine the revenue "
            "values a sales manager can see in a specified sales region.' Gating on CURRENT_USER() makes the "
            "policy orthogonal to role activation, including the DEFAULT_SECONDARY_ROLES=('ALL') default. "
            "This is the right pattern for ACL-driven entitlements; NOT a substitute for byIdentity in "
            "role-discrimination scenarios, where Snowflake recommends IS_ROLE_IN_SESSION (see ROW_VISIBILITY "
            "entry). Snowflake's performance caveat applies: mapping-table lookups are slower than simple "
            "predicate-only policies. SUPPORTED for RowVisibilityConstraint; PARTIAL overall because "
            "ColumnVisibilityConstraint and ABAC-scoped byDataset are not yet implemented.",
        ),
        Capability.DATASET_DRIVEN_RESOURCES: (
            CapabilitySupport.PARTIAL,
            "ResourceSetFromTable can be expressed via JOIN inside the policy body, with the same performance caveat.",
        ),
        Capability.CONDITIONAL_OBLIGATIONS: (
            CapabilitySupport.UNSUPPORTED,
            "Snowflake does not surface obligation primitives in DDL. Diagnostic is emitted; obligations are "
            "out-of-band.",
        ),
        Capability.PURPOSE_BINDING: (
            CapabilitySupport.UNSUPPORTED,
            "No native session-purpose attribute in Snowflake; emission emits a WARNING.",
        ),
        Capability.REGULATORY_REGIME_ATTRIBUTE: (
            CapabilitySupport.PARTIAL,
            "Modeled via Snowflake object tags per ADR-021's tag taxonomy mapping. Per-environment binding required.",
        ),
    },
)
