"""Unity Catalog adapter — concrete Adapter implementation."""

from __future__ import annotations

from typing import Any

from adapters.contract.adapter import Adapter
from adapters.contract.types import (
    AdapterConfig,
    CapabilityProfile,
    EmissionResult,
)
from adapters.unity_catalog.capability import UNITY_CATALOG_PROFILE
from adapters.unity_catalog.emission import emit_policy as _emit


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
