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
            "Emitted via CREATE OR REPLACE FUNCTION returning the masked value plus "
            "ALTER TABLE ... ALTER COLUMN ... SET MASK. Live-verified 2026-05-19 against "
            "bg_rls_demo.tpch.orders.o_clerk: the same IR that produced the hand-derived "
            "spec/v0/examples/column-mask-orders-clerk.databricks.sql now emits byte-equivalent "
            "DDL through the adapter; the mask enforces correctly for non-members of the "
            "granted group (caller sees CLERK-REDACTED). Coverage: byIdentity column targets; "
            "rules with effect=allow or effect=transform; defaultBranch with effect=transform; "
            "Redact transformation (literal replacement). Mask and Hash transformations land in "
            "future scaffold passes (the parameter-shape semantics are settled in v0; the SQL "
            "templates are queued). ABAC byScope column masking remains UNIMPLEMENTED — the IR "
            "shape exists in spec/v0/examples/abac-column-mask-policy-* but the adapter does not "
            "yet handle byScope+matching for column visibility.",
        ),
        Capability.ATTRIBUTE_BASED_SCOPING: (
            CapabilitySupport.PARTIAL,
            "ABAC row visibility via byScope + matching is implemented and live-verified 2026-05-19 "
            "against bg_rls_demo.tpch.orders_abac. Emission produces the three-piece DDL: "
            "(1) CREATE OR REPLACE FUNCTION ... RETURNS BOOLEAN with CASE branching (Mechanism B); "
            "(2) GRANT EXECUTE ... TO `account users` (adapter scaffolding per ADR-025); "
            "(3) CREATE OR REPLACE POLICY ... ON CATALOG/SCHEMA/TABLE ... ROW FILTER ... "
            "FOR TABLES MATCH COLUMNS has_tag_value(<tag_key>, <tag_value>) AS alias "
            "USING COLUMNS (alias). The IR's `column:$matched` reference substitutes the function "
            "parameter at emit time. tag_taxonomy (ADR-021) translates Tessera axis+value to "
            "Databricks tag key+value; unbound attributes fall back with a warning. "
            "ABAC column masking via byScope is not yet implemented (the abac-column-mask-policy-* "
            "IR shapes are queued). ADR-023's γ-with-refinement combination is observed but not "
            "yet enforced at emission time.",
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
