"""Shared types used across the adapter contract.

All adapters return structured Result objects (never raw SQL strings or dicts) so
callers can attach diagnostics, capability gaps, and provenance without having to
re-parse adapter output. The Result types are deliberately simple dataclasses to
keep the contract auditable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Capability(str, Enum):
    """IR concepts an adapter may declare support for.

    Adding a new value here is a breaking change to the contract; do not extend
    casually. The intent is to enumerate the concepts the spec defines, so a
    capability gap on one adapter is comparable to a gap on another.
    """

    ROW_VISIBILITY = "row-visibility"
    COLUMN_VISIBILITY = "column-visibility"
    ATTRIBUTE_BASED_SCOPING = "attribute-based-scoping"        # byScope + matching
    DATASET_DRIVEN_PRINCIPALS = "dataset-driven-principals"    # PrincipalSetFromTable
    DATASET_DRIVEN_RESOURCES = "dataset-driven-resources"      # ResourceSetFromTable
    CONDITIONAL_OBLIGATIONS = "conditional-obligations"
    PURPOSE_BINDING = "purpose-binding"
    REGULATORY_REGIME_ATTRIBUTE = "regulatory-regime-attribute"


class CapabilitySupport(str, Enum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class CapabilityProfile:
    """Per-adapter declaration of what the platform can and cannot express.

    Each entry pairs a Capability with a support level and a free-form rationale
    explaining the boundary. Diagnostic reports cite this profile when emission
    must downgrade, refuse, or warn about a policy concept.
    """

    adapter_name: str
    platform: str
    entries: dict[Capability, tuple[CapabilitySupport, str]] = field(default_factory=dict)

    def support_for(self, cap: Capability) -> CapabilitySupport:
        entry = self.entries.get(cap)
        return entry[0] if entry else CapabilitySupport.UNSUPPORTED

    def rationale(self, cap: Capability) -> str:
        entry = self.entries.get(cap)
        return entry[1] if entry else "Not declared in capability profile."


class DiagnosticSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class Diagnostic:
    severity: DiagnosticSeverity
    code: str                      # short stable identifier (e.g., "UNSUPPORTED_CONDITION")
    message: str                   # human-readable explanation
    location: str | None = None    # path into the policy, e.g., "rules[1].condition"


@dataclass
class EmissionResult:
    """Platform statements + diagnostics for one policy."""

    policy_id: str | None
    target_artifacts: list[str]          # e.g., ["catalog.schema.table"]
    statements: list[str]                # ordered platform-native DDL/SQL
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(d.severity == DiagnosticSeverity.ERROR for d in self.diagnostics)


@dataclass
class DiscoveryResult:
    """Inventory of policy-bearing artifacts found on the platform."""

    artifacts: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)


@dataclass
class ExtractionResult:
    """An artifact lifted to the IR (or a partial lift with diagnostics)."""

    policy: dict[str, Any] | None        # parsed JSON-LD-shape dict, or None if extraction failed
    confidence: float                    # 0.0–1.0; <1.0 means heuristic/partial extraction
    diagnostics: list[Diagnostic] = field(default_factory=list)


@dataclass
class ReconciliationResult:
    """Diff between intended IR state and observed platform state."""

    additions: list[dict[str, Any]] = field(default_factory=list)
    removals: list[dict[str, Any]] = field(default_factory=list)
    modifications: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)


@dataclass
class AdapterConfig:
    """Per-environment configuration mapping IR concepts to platform mechanisms.

    Per ADR-021: every adapter takes a configuration block that maps Tessera's
    semantic vocabulary (PrincipalRef IRIs, AttributeAxis + axisValue pairs)
    to the platform-native identifiers (group names, role names, governed tag
    keys, object-tag values). Adapters do not embed these mappings.
    """

    # PrincipalRef IRI (e.g., "principal:high_priority_ops") → platform principal id
    identity_bindings: dict[str, str] = field(default_factory=dict)

    # ResourceRef IRI (e.g., "table:acme.tpch.orders") → platform-qualified identifier.
    # Mirrors identity_bindings for resources: a platform-neutral IR target lowers to a
    # platform-specific table / column / schema name. Surfaced by the parity exercise on
    # 2026-05-19: the same IR targets Databricks `acme.tpch.orders` and Snowflake
    # `ACME.TESSERA.ORDERS`, and the adapter must not invent the mapping.
    resource_bindings: dict[str, str] = field(default_factory=dict)

    # (axis IRI, axisValue) → (platform tag key, platform tag value)
    tag_taxonomy: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)

    # Free-form extra config; per-adapter conventions (warehouse name, schema, etc.)
    extras: dict[str, Any] = field(default_factory=dict)

    def bind_principal(self, principal_ref: str) -> str | None:
        """Resolve an IR PrincipalRef to a platform principal identifier.

        Case-insensitive on the identifier portion (the part after the first
        colon). Snowflake stores identifiers uppercase; extracted IRs come back
        uppercase too; bindings authored lowercase would otherwise miss.
        """
        if principal_ref in self.identity_bindings:
            return self.identity_bindings[principal_ref]
        return _case_insensitive_lookup(self.identity_bindings, principal_ref)

    def bind_resource(self, resource_ref: str) -> str | None:
        """Resolve an IR ResourceRef to a platform-qualified identifier.

        Case-insensitive on the identifier portion. Same rationale as bind_principal.
        """
        if resource_ref in self.resource_bindings:
            return self.resource_bindings[resource_ref]
        return _case_insensitive_lookup(self.resource_bindings, resource_ref)


def _case_insensitive_lookup(bindings: dict[str, str], key: str) -> str | None:
    """Find a binding by matching the IRI prefix exactly and the identifier
    portion case-insensitively. Prefix (`table:`, `column:`, `group:`) is
    semantic and stays case-sensitive; identifier (the part after the first
    colon) is case-insensitive to bridge Snowflake's uppercase / mixed-case gap.
    """
    if ":" not in key:
        return None
    prefix, ident = key.split(":", 1)
    ident_cf = ident.casefold()
    for candidate_key, value in bindings.items():
        if ":" not in candidate_key:
            continue
        c_prefix, c_ident = candidate_key.split(":", 1)
        if c_prefix == prefix and c_ident.casefold() == ident_cf:
            return value
    return None
