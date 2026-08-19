"""Oracle capability profile.

Oracle's governance primitives differ in shape from Unity Catalog's and
Snowflake's, which is what makes it a useful portability test (ADR-033). Rationale
strings cite the primitive per ADR-027 (describe, don't invent). The profile is
marked emitted-not-live-verified until the live run against the provided instance
stamps a verification date.
"""

from adapters.contract.types import (
    Capability,
    CapabilityProfile,
    CapabilitySupport,
)

ORACLE_PROFILE = CapabilityProfile(
    adapter_name="oracle",
    platform="Oracle",
    entries={
        Capability.ROW_VISIBILITY: (
            CapabilitySupport.SUPPORTED,
            "Emitted via Virtual Private Database (VPD): DBMS_RLS.ADD_POLICY attaches a PL/SQL "
            "policy function that returns a predicate appended to every query's WHERE clause "
            "(docs.oracle.com — Using Oracle Virtual Private Database to Control Data Access). "
            "byIdentity rules become IF/ELSIF branches over SYS_CONTEXT('SYS_SESSION_ROLES','<ROLE>') "
            "= 'TRUE', each returning the rule's row predicate; a fail-closed ELSE ('1=0') covers "
            "principals in no rule (explicit-baseline-group is modeled as an explicit baseline rule). "
            "byDataset rules return a correlated EXISTS over the ACL tables keyed off "
            "SYS_CONTEXT('USERENV','SESSION_USER'). Emitted; live verification against the provided "
            "instance is pending (profile will be stamped with the date once run).",
        ),
        Capability.COLUMN_VISIBILITY: (
            CapabilitySupport.SUPPORTED,
            "Emitted via Oracle Data Redaction: DBMS_REDACT.ADD_POLICY (docs.oracle.com — Oracle "
            "Database Advanced Security Guide, Using Oracle Data Redaction). A Redact with a "
            "replacement literal lowers to function_type => DBMS_REDACT.REGEXP (regexp_pattern '(.*)', "
            "regexp_replace_string => the replacement) because FULL redaction cannot carry an arbitrary "
            "replacement string — it uses type-default masking values. The `expression` gates who sees "
            "redaction: allowed roles (effect=allow) see real data, so redaction applies when the "
            "session has none of them. Coverage: byIdentity column targets, Redact transformation. "
            "Mask/Hash queued. Emitted; live verification pending.",
        ),
        Capability.DATASET_DRIVEN_PRINCIPALS: (
            CapabilitySupport.SUPPORTED,
            "PrincipalSetFromTable lowers to a correlated EXISTS inside the VPD policy function, joining "
            "the mapping table to the resource-ACL table on the shared codename. This is Oracle's "
            "documented pattern for data-driven VPD predicates.",
        ),
        Capability.DATASET_DRIVEN_RESOURCES: (
            CapabilitySupport.SUPPORTED,
            "ResourceSetFromTable is the second ACL table, joined inside the VPD predicate.",
        ),
        Capability.ATTRIBUTE_BASED_SCOPING: (
            CapabilitySupport.UNSUPPORTED,
            "Oracle has no governed-tag-driven policy attachment (the UC/Snowflake byScope mechanism). "
            "Oracle Label Security (OLS) is the nearest primitive and is deferred; byScope row/column "
            "policies emit a diagnostic rather than DDL.",
        ),
        Capability.CONDITIONAL_OBLIGATIONS: (
            CapabilitySupport.UNSUPPORTED,
            "Oracle exposes no obligation primitive in DDL; obligations are out-of-band.",
        ),
        Capability.PURPOSE_BINDING: (
            CapabilitySupport.UNSUPPORTED,
            "No native session-purpose attribute; a purpose could be carried in an application context "
            "but that is deferred.",
        ),
        Capability.REGULATORY_REGIME_ATTRIBUTE: (
            CapabilitySupport.UNSUPPORTED,
            "Regime attributes are semantic axes resolved by tag taxonomies; Oracle has no tag-driven "
            "attachment (see ATTRIBUTE_BASED_SCOPING).",
        ),
        Capability.RETENTION: (
            CapabilitySupport.UNSUPPORTED,
            "RetentionConstraint (ADR-031) is expression-first everywhere; Oracle has no declarative "
            "delete-after primitive (a scheduled DBMS_SCHEDULER + DELETE job would be operational, not "
            "declarative). Emission reports RETENTION_EXPRESSION_ONLY.",
        ),
    },
)
