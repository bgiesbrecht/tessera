"""The Adapter abstract base class.

Every platform adapter inherits from this class and implements the four
responsibilities defined in technical-design-v0.2.md §5: discovery, extraction,
emission, reconciliation. The base class is intentionally thin — it declares
the interface and provides no platform-specific behavior of its own.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from adapters.contract.types import (
    AdapterConfig,
    CapabilityProfile,
    DiscoveryResult,
    EmissionResult,
    ExtractionResult,
    ReconciliationResult,
)


class Adapter(ABC):
    name: str
    platform: str

    def __init__(self, config: AdapterConfig, connection: Any | None = None) -> None:
        self.config = config
        self._connection = connection

    @property
    @abstractmethod
    def capability_profile(self) -> CapabilityProfile:
        """Declares which IR concepts this adapter supports, partially supports, or refuses."""

    @abstractmethod
    def emit(self, policy: dict[str, Any]) -> EmissionResult:
        """Lower a parsed JSON-LD policy to platform-native DDL/SQL statements.

        Emission never executes the statements — that is the caller's
        responsibility. The returned EmissionResult carries the statements and
        any diagnostics produced during lowering (capability gaps, configuration
        misses, etc.).
        """

    def discover(self) -> DiscoveryResult:
        """Inventory policy-bearing artifacts on the platform. Default: not implemented."""
        return DiscoveryResult(diagnostics=[
            _stub_diagnostic("DISCOVERY_NOT_IMPLEMENTED",
                             f"{self.name} adapter has not implemented discovery yet.")
        ])

    def extract(self, artifact: dict[str, Any]) -> ExtractionResult:
        """Lift a platform artifact (row filter, masking policy, etc.) to IR. Default: not implemented."""
        return ExtractionResult(
            policy=None,
            confidence=0.0,
            diagnostics=[_stub_diagnostic(
                "EXTRACTION_NOT_IMPLEMENTED",
                f"{self.name} adapter has not implemented extraction yet.",
            )],
        )

    def reconcile(self, policy: dict[str, Any]) -> ReconciliationResult:
        """Diff the intended IR state against observed platform state. Default: not implemented."""
        return ReconciliationResult(diagnostics=[
            _stub_diagnostic("RECONCILIATION_NOT_IMPLEMENTED",
                             f"{self.name} adapter has not implemented reconciliation yet.")
        ])


def _stub_diagnostic(code: str, message: str):
    from adapters.contract.types import Diagnostic, DiagnosticSeverity
    return Diagnostic(severity=DiagnosticSeverity.INFO, code=code, message=message)
