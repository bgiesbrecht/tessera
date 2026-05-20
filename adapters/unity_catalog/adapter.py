"""Unity Catalog adapter — concrete Adapter implementation."""

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
from adapters.unity_catalog.capability import UNITY_CATALOG_PROFILE
from adapters.unity_catalog.emission import emit_policy as _emit
from adapters.unity_catalog.discovery import discover_schema, extract_artifact


class UnityCatalogAdapter(Adapter):
    name = "unity-catalog"
    platform = "Databricks"

    def __init__(self, config: AdapterConfig | None = None, connection: Any | None = None) -> None:
        super().__init__(config or AdapterConfig(), connection)

    @property
    def capability_profile(self) -> CapabilityProfile:
        return UNITY_CATALOG_PROFILE

    def emit(self, policy: dict[str, Any]) -> EmissionResult:
        return _emit(policy, self.config)

    def discover(self, *, catalog: str | None = None, schema: str | None = None) -> DiscoveryResult:
        """Inventory row filters and column masks on a Databricks schema.

        Caller passes `catalog` and `schema` (or sets them in `config.extras` as
        `discover_catalog` / `discover_schema`). A `run_sql` callable must be
        supplied via `config.extras["run_sql"]` — a function `(sql: str) ->
        list[list]` that executes via whatever SDK / connection the caller has
        in hand. Keeps this module SDK-agnostic.
        """
        cat = catalog or self.config.extras.get("discover_catalog")
        sc = schema or self.config.extras.get("discover_schema")
        run_sql = self.config.extras.get("run_sql")
        if not (cat and sc and run_sql):
            return DiscoveryResult(
                artifacts=[],
                diagnostics=[Diagnostic(
                    severity=DiagnosticSeverity.ERROR,
                    code="DISCOVER_MISSING_INPUTS",
                    message=(
                        "Unity Catalog discover() requires a catalog, a schema, and a run_sql callable. "
                        "Pass `catalog=` and `schema=` kwargs, or supply them via "
                        "config.extras['discover_catalog'/'discover_schema']. The run_sql callable "
                        "must be supplied via config.extras['run_sql']."
                    ),
                )],
            )
        return discover_schema(run_sql, cat, sc)

    def extract(self, artifact: dict[str, Any]) -> ExtractionResult:
        """Lift a discovered UC artifact into Tessera IR. See discovery.py."""
        return extract_artifact(artifact)
