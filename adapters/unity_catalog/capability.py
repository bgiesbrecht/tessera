"""Unity Catalog capability profile.

The shape of this declaration is intentionally informational. The adapter
references it when emitting diagnostics about features that would be downgraded
or refused. It is not a runtime gate — emission may still produce output for a
PARTIAL capability, accompanied by a warning diagnostic explaining the boundary.
"""

from adapters.contract.types import (
    Capability,
    CapabilityProfile,
    CapabilitySupport,
)

UNITY_CATALOG_PROFILE = CapabilityProfile(
    adapter_name="unity-catalog",
    platform="Databricks",
    entries={
        Capability.ROW_VISIBILITY: (
            CapabilitySupport.SUPPORTED,
            "Emitted via CREATE FUNCTION ... AS FILTER plus ALTER TABLE ... SET ROW FILTER.",
        ),
        Capability.COLUMN_VISIBILITY: (
            CapabilitySupport.SUPPORTED,
            "Emitted via CREATE FUNCTION returning the masked value plus ALTER TABLE ... ALTER COLUMN ... SET MASK.",
        ),
        Capability.ATTRIBUTE_BASED_SCOPING: (
            CapabilitySupport.PARTIAL,
            "ABAC via governed tags + CREATE POLICY ... ON CATALOG/SCHEMA/TABLE is supported in principle; "
            "the scaffold currently emits per-table mechanisms and routes ABAC paths through a TODO. ADR-023's "
            "γ-with-refinement combination is observed but not yet enforced at emission time.",
        ),
        Capability.DATASET_DRIVEN_PRINCIPALS: (
            CapabilitySupport.PARTIAL,
            "PrincipalSetFromTable is expressed via subquery joins inside the row-filter function body. "
            "Confidence depends on the ACL table schema mapping declared in adapter configuration.",
        ),
        Capability.DATASET_DRIVEN_RESOURCES: (
            CapabilitySupport.PARTIAL,
            "ResourceSetFromTable can be emitted as a CTE-driven row filter, but performance characteristics "
            "depend on the source table's clustering and Photon coverage.",
        ),
        Capability.CONDITIONAL_OBLIGATIONS: (
            CapabilitySupport.UNSUPPORTED,
            "Obligations (audit-log, redaction-marker, etc.) are not expressible in Unity Catalog DDL. "
            "Diagnostic is emitted; callers must handle obligations out-of-band.",
        ),
        Capability.PURPOSE_BINDING: (
            CapabilitySupport.UNSUPPORTED,
            "Databricks does not surface a session purpose-of-use attribute; emission emits a WARNING.",
        ),
        Capability.REGULATORY_REGIME_ATTRIBUTE: (
            CapabilitySupport.PARTIAL,
            "Modeled via governed tags per ADR-021's tag taxonomy mapping. Per-environment binding required.",
        ),
    },
)
