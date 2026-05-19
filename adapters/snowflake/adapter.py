"""Snowflake adapter — concrete Adapter implementation.

Connection handling: the snowflake-connector-python dependency is imported lazily
so the rest of the adapter contract is importable without it. Real execution
against Snowflake requires `pip install snowflake-connector-python`.
"""

from __future__ import annotations

from typing import Any

from adapters.contract.adapter import Adapter
from adapters.contract.types import (
    AdapterConfig,
    CapabilityProfile,
    EmissionResult,
)
from adapters.snowflake.capability import SNOWFLAKE_PROFILE
from adapters.snowflake.emission import emit_policy as _emit


class SnowflakeAdapter(Adapter):
    name = "snowflake"
    platform = "Snowflake"

    def __init__(self, config: AdapterConfig | None = None, connection: Any | None = None) -> None:
        super().__init__(config or AdapterConfig(), connection)

    @property
    def capability_profile(self) -> CapabilityProfile:
        return SNOWFLAKE_PROFILE

    def emit(self, policy: dict[str, Any]) -> EmissionResult:
        return _emit(policy, self.config)
