"""custom-ACL adapter: the ADR-003 reference pattern adapter.

A *pattern* adapter, not a platform adapter (ADR-032): its enforcement target is
the customer's own ACL-table + wrapping-view convention, which predates and sits
alongside native RLS. It is a peer of the Unity Catalog and Snowflake adapters
against the same contract (ADR-024).

`emit` lowers a byDataset RowVisibilityConstraint to a wrapping secure view.
`extract` lifts such a view back to IR (the selective
migration on-ramp). `discover` inventories candidate ACL views; `reconcile` uses
the default contract implementation (discover → extract → diff).
"""

from __future__ import annotations

from typing import Any

from adapters.contract.adapter import Adapter
from adapters.contract.types import (
    AdapterConfig,
    CapabilityProfile,
    Diagnostic,
    DiagnosticSeverity,
    DiscoveryResult,
    EmissionResult,
    ExtractionResult,
)
from adapters.custom_acl.capability import CUSTOM_ACL_PROFILE
from adapters.custom_acl.emission import emit_policy as _emit
from adapters.custom_acl.discovery import discover_schema, extract_artifact


class CustomACLAdapter(Adapter):
    name = "custom-acl"
    platform = "Custom ACL (view-layer)"

    def __init__(self, config: AdapterConfig | None = None, connection: Any | None = None) -> None:
        super().__init__(config or AdapterConfig(), connection)

    @property
    def capability_profile(self) -> CapabilityProfile:
        return CUSTOM_ACL_PROFILE

    def emit(self, policy: dict[str, Any]) -> EmissionResult:
        return _emit(policy, self.config)

    def discover(self, *, database: str | None = None, schema: str | None = None) -> DiscoveryResult:
        """Inventory ACL-wrapping views.

        Offline: supply view artifacts via config.extras['acl_views']. Live: attach
        a DB-API cursor via config.extras['acl_cursor'] (or the connection) and pass
        `schema` (and optionally `database`).
        """
        offline = self.config.extras.get("acl_views")
        if offline is not None:
            return discover_schema(offline_views=offline)

        db = database or self.config.extras.get("discover_database")
        sc = schema or self.config.extras.get("discover_schema")
        cursor = self.config.extras.get("acl_cursor")
        if cursor is None and self._connection is not None:
            cursor = self._connection.cursor()
        if not (sc and cursor):
            return DiscoveryResult(
                artifacts=[],
                diagnostics=[Diagnostic(
                    severity=DiagnosticSeverity.ERROR,
                    code="DISCOVER_MISSING_INPUTS",
                    message=(
                        "custom-acl discover() needs either config.extras['acl_views'] "
                        "(offline), or a schema plus a DB-API cursor "
                        "(config.extras['acl_cursor'] or the connection)."
                    ),
                )],
            )
        return discover_schema(cursor, db, sc)

    def extract(self, artifact: dict[str, Any]) -> ExtractionResult:
        """Lift an ACL view into Tessera IR: the selective-migration on-ramp."""
        return extract_artifact(artifact)
