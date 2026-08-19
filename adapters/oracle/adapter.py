"""Oracle adapter — a third native-platform peer (ADR-033).

Connection handling: `oracledb` is imported lazily so the adapter contract is
importable without the driver. Real discovery/execution against Oracle requires
`pip install oracledb`.
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
from adapters.oracle.capability import ORACLE_PROFILE
from adapters.oracle.emission import emit_policy as _emit
from adapters.oracle.discovery import discover_schema, extract_artifact


class OracleAdapter(Adapter):
    name = "oracle"
    platform = "Oracle"

    def __init__(self, config: AdapterConfig | None = None, connection: Any | None = None) -> None:
        super().__init__(config or AdapterConfig(), connection)

    @property
    def capability_profile(self) -> CapabilityProfile:
        return ORACLE_PROFILE

    def emit(self, policy: dict[str, Any]) -> EmissionResult:
        return _emit(policy, self.config)

    def discover(self, *, schema: str | None = None) -> DiscoveryResult:
        """Inventory VPD / Data Redaction / grant artifacts on a schema.

        Requires a schema and a live oracledb cursor (config.extras['oracle_cursor']
        or the connection).
        """
        sc = schema or self.config.extras.get("discover_schema")
        cursor = self.config.extras.get("oracle_cursor")
        if cursor is None and self._connection is not None:
            cursor = self._connection.cursor()
        if not (sc and cursor):
            return DiscoveryResult(
                artifacts=[],
                diagnostics=[Diagnostic(
                    severity=DiagnosticSeverity.ERROR,
                    code="DISCOVER_MISSING_INPUTS",
                    message=(
                        "Oracle discover() requires a schema and a live oracledb cursor. "
                        "Pass schema= and supply the cursor via config.extras['oracle_cursor'] "
                        "or the connection."
                    ),
                )],
            )
        return discover_schema(cursor, sc)

    def extract(self, artifact: dict[str, Any]) -> ExtractionResult:
        """Lift a discovered Oracle artifact into Tessera IR. See discovery.py."""
        return extract_artifact(artifact)
