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
            "ALTER TABLE ... ALTER COLUMN ... SET MASK (byIdentity), OR via CREATE POLICY "
            "... COLUMN MASK ... FOR TABLES MATCH COLUMNS has_tag_value(...) ON COLUMN ... "
            "(byScope ABAC; 0.6.3, closes #30). byIdentity live-verified 2026-05-19 against "
            "acme.tpch.orders.o_clerk: the same IR that produced the hand-derived "
            "spec/v0/examples/column-mask-orders-clerk.databricks.sql now emits byte-equivalent "
            "DDL through the adapter; the mask enforces correctly for non-members of the "
            "granted group (caller sees CLERK-REDACTED). byScope verified against "
            "spec/v0/examples/abac-column-mask-policy-{a,b}.jsonld: emission is functionally "
            "equivalent to the hand-derived abac-column-mask.databricks.sql (only "
            "stylistic differences — auto-generated alias `clerk` vs hand-stylized "
            "`pii_clerk_col`; defensive `cast(val AS STRING)` in the Hash UDF). Coverage: "
            "byIdentity column targets and byScope ABAC targets; rules with effect=allow or "
            "effect=transform; defaultBranch with effect=transform; Redact and Hash (sha256) "
            "transformations. Mask transformation emits NULL placeholder with a queued "
            "diagnostic (parameter shape is settled in v0; SQL template queued).",
        ),
        Capability.ATTRIBUTE_BASED_SCOPING: (
            CapabilitySupport.SUPPORTED,
            "ABAC row visibility AND column visibility via byScope + matching both implemented. "
            "Row visibility live-verified 2026-05-19 against acme.tpch.orders_abac (three-piece DDL: "
            "CREATE FUNCTION returning BOOLEAN with CASE branching (Mechanism B); GRANT EXECUTE "
            "scaffolding; CREATE POLICY ... ON CATALOG/SCHEMA/TABLE ... ROW FILTER ... "
            "MATCH COLUMNS has_tag_value(...) AS alias USING COLUMNS (alias)). Column "
            "visibility added 0.6.3 (closes #30): parallel three-piece DDL with COLUMN MASK "
            "in place of ROW FILTER and ON COLUMN <alias> in place of USING COLUMNS — the "
            "rule's principal becomes the EXCEPT clause; the defaultBranch transformation "
            "becomes the UDF body. The IR's `column:$matched` reference substitutes the "
            "function parameter at emit time (row-filter path). tag_taxonomy (ADR-021) "
            "translates Tessera axis+value to Databricks tag key+value; unbound attributes "
            "fall back with a warning. ADR-023's γ-with-refinement combination is observed "
            "but not yet enforced at emission time.",
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
