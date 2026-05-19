"""Adapter contract — the shared interface every platform adapter implements."""

from adapters.contract.types import (
    Capability,
    CapabilitySupport,
    CapabilityProfile,
    Diagnostic,
    DiagnosticSeverity,
    EmissionResult,
    DiscoveryResult,
    ExtractionResult,
    ReconciliationResult,
    AdapterConfig,
)
from adapters.contract.adapter import Adapter

__all__ = [
    "Adapter",
    "AdapterConfig",
    "Capability",
    "CapabilityProfile",
    "CapabilitySupport",
    "Diagnostic",
    "DiagnosticSeverity",
    "EmissionResult",
    "DiscoveryResult",
    "ExtractionResult",
    "ReconciliationResult",
]
