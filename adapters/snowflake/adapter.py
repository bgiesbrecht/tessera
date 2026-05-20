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
    Diagnostic,
    DiagnosticSeverity,
    DiscoveryResult,
    EmissionResult,
    ExtractionResult,
)
from adapters.snowflake.capability import SNOWFLAKE_PROFILE
from adapters.snowflake.emission import emit_policy as _emit
from adapters.snowflake.discovery import discover_schema, extract_artifact


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

    def discover(self, *, database: str | None = None, schema: str | None = None) -> DiscoveryResult:
        """Inventory row-access policies and masking policies on the target schema.

        Caller passes `database` and `schema` (or sets them in `config.extras`
        as `discover_database` / `discover_schema`). A live Snowflake cursor
        must already be attached as `self._connection.cursor()` or passed via
        `config.extras["snowflake_cursor"]`.
        """
        db = database or self.config.extras.get("discover_database")
        sc = schema or self.config.extras.get("discover_schema")
        cursor = self.config.extras.get("snowflake_cursor")
        if cursor is None and self._connection is not None:
            cursor = self._connection.cursor()
        if not (db and sc and cursor):
            return DiscoveryResult(
                artifacts=[],
                diagnostics=[Diagnostic(
                    severity=DiagnosticSeverity.ERROR,
                    code="DISCOVER_MISSING_INPUTS",
                    message=(
                        "Snowflake discover() requires a database, a schema, and a live cursor. "
                        "Pass `database=` and `schema=` kwargs, or supply them via "
                        "config.extras['discover_database'/'discover_schema']; supply a cursor "
                        "via config.extras['snowflake_cursor'] or via the connection."
                    ),
                )],
            )
        return discover_schema(cursor, db, sc)

    def extract(self, artifact: dict[str, Any]) -> ExtractionResult:
        """Lift a discovered Snowflake policy into Tessera IR. See discovery.py."""
        return extract_artifact(artifact)
