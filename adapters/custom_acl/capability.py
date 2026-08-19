"""custom-ACL capability profile.

This is a *pattern* adapter (ADR-032), not a platform adapter. Its enforcement
target is the customer's ACL-table + wrapping-view convention (ADR-003), so its
capability surface is shaped by what a view over a two-table ACL join can express
exactly the data-driven selectors the native adapters treat as a
secondary path.
"""

from adapters.contract.types import (
    Capability,
    CapabilityProfile,
    CapabilitySupport,
)

CUSTOM_ACL_PROFILE = CapabilityProfile(
    adapter_name="custom-acl",
    platform="Custom ACL (view-layer)",
    entries={
        Capability.ROW_VISIBILITY: (
            CapabilitySupport.SUPPORTED,
            "Emitted as CREATE OR REPLACE VIEW <base>_secured wrapping the base table with "
            "a correlated EXISTS over the two-table ACL join. The view is the enforcement "
            "mechanism (no platform RLS primitive); consumers are granted the view, not the "
            "base table. Coverage: byDataset principal + exists-in-dataset condition "
            "(the ACL-join shape). defaultStrategy: none is inherent, since principals absent from "
            "the ACL join match no rows (fail-closed). byIdentity group gating in the view is "
            "a queued follow-up.",
        ),
        Capability.DATASET_DRIVEN_PRINCIPALS: (
            CapabilitySupport.SUPPORTED,
            "PrincipalSetFromTable is this adapter's raison d'être: the mapping table is joined "
            "in the view body, keyed off lower(trim(current_user())). This is the pattern the "
            "custom-ACL customer already runs by hand (ADR-003); the adapter's extract() lifts "
            "such views back to IR for selective migration to a native platform.",
        ),
        Capability.DATASET_DRIVEN_RESOURCES: (
            CapabilitySupport.SUPPORTED,
            "ResourceSetFromTable is the second ACL table, joined on the shared codename column. "
            "Issue #13 (resourceColumn conflated as ACL value column vs protected discriminator) "
            "is surfaced as an INFO diagnostic on emit; the aligned convention (p.<col> = b.<col>) "
            "is used, matching the native adapters.",
        ),
        Capability.COLUMN_VISIBILITY: (
            CapabilitySupport.PARTIAL,
            "A column mask can be expressed as a CASE in the view's SELECT list, but that path is "
            "not yet emitted. RowVisibility via the ACL-join view is the shipped shape.",
        ),
        Capability.ATTRIBUTE_BASED_SCOPING: (
            CapabilitySupport.UNSUPPORTED,
            "The view-layer pattern has no tag/attribute machinery; ABAC byScope belongs to the "
            "native adapters. Emission would report the gap.",
        ),
        Capability.CONDITIONAL_OBLIGATIONS: (
            CapabilitySupport.UNSUPPORTED,
            "No obligation primitive in a plain view; obligations are out-of-band.",
        ),
        Capability.PURPOSE_BINDING: (
            CapabilitySupport.UNSUPPORTED,
            "No session-purpose attribute available to a view predicate in the generic pattern.",
        ),
        Capability.REGULATORY_REGIME_ATTRIBUTE: (
            CapabilitySupport.UNSUPPORTED,
            "Regime attributes are semantic axes resolved by native tag taxonomies; not modeled "
            "by the view-layer pattern.",
        ),
        Capability.RETENTION: (
            CapabilitySupport.UNSUPPORTED,
            "RetentionConstraint (ADR-031) is expression-first everywhere; the view-layer pattern "
            "has no retention mechanism.",
        ),
    },
)
