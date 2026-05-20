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

    def reconcile(
        self,
        intended: list[dict[str, Any]],
        *,
        catalog: str | None = None,
        schema: str | None = None,
        database: str | None = None,
    ) -> ReconciliationResult:
        """Diff intended IR state against the platform's observed state.

        Default implementation: invoke `discover()` to enumerate deployed
        artifacts, `extract()` each into IR, then diff the resulting observed
        IR against the supplied `intended` corpus. Adapters that need a
        platform-specific reconciliation (e.g., richer state comparison) can
        override.

        Args:
            intended: list of IR-shaped policy dicts representing what should be
                deployed (typically the validated corpus on disk).
            catalog/schema/database: optional kwargs forwarded to discover().

        Returns ReconciliationResult with additions / removals / modifications.
        """
        from adapters.contract.reconcile import reconcile as _do_reconcile

        # Build the discover() kwargs from whatever the adapter accepts.
        discover_kwargs: dict[str, Any] = {}
        if catalog is not None:
            discover_kwargs["catalog"] = catalog
        if schema is not None:
            discover_kwargs["schema"] = schema
        if database is not None:
            discover_kwargs["database"] = database
        try:
            disc = self.discover(**discover_kwargs)
        except TypeError:
            disc = self.discover()

        observed: list[dict[str, Any]] = []
        observe_diagnostics = list(disc.diagnostics)
        for art in disc.artifacts:
            r = self.extract(art)
            observe_diagnostics.extend(r.diagnostics)
            if r.policy is not None:
                observed.append(r.policy)

        result = _do_reconcile(intended, observed)
        result.diagnostics = observe_diagnostics + result.diagnostics
        return result


def _stub_diagnostic(code: str, message: str):
    from adapters.contract.types import Diagnostic, DiagnosticSeverity
    return Diagnostic(severity=DiagnosticSeverity.INFO, code=code, message=message)
