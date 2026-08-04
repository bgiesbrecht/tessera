"""Findings and report types for change-impact analysis (scoping doc §3).

Every finding is selector-relative, carries a confidence tier (PROVEN /
CANDIDATE), and grounds in an ADR or structural invariant. The report is
advisory: it flags consequences; it never decides and never blocks.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class Confidence(enum.Enum):
    """§3 confidence tiers. PROVEN follows from the lattice (§4.2); CANDIDATE
    depends on membership/contents the tool cannot see (§4.4)."""

    PROVEN = "PROVEN"
    CANDIDATE = "CANDIDATE"


class Polarity(enum.Enum):
    """Exposure-change classification for C6."""

    WIDEN = "WIDEN"
    NARROW = "NARROW"
    INVERT = "INVERT"
    NEUTRAL = "NEUTRAL"


@dataclass
class Finding:
    check: str                     # "C5", "C6", ...
    subject: str                   # selector-relative subject ("selector group:X")
    consequence: str               # plain-language, flags rather than decides
    confidence: Confidence
    grounding: str                 # ADR or structural invariant reference
    policy_id: str | None = None
    polarity: Polarity | None = None
    # Optional CANDIDATE qualifier naming the specific unknown (§4.4).
    unknown: str | None = None

    def code_line(self) -> str:
        bits = [f"[{self.check}]"]
        if self.polarity is not None:
            bits.append(self.polarity.value)
        bits.append(self.subject)
        return "  ".join(bits)


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def add(self, f: Finding) -> None:
        self.findings.append(f)

    def extend(self, fs: list[Finding]) -> None:
        self.findings.extend(fs)

    def is_empty(self) -> bool:
        return not self.findings

    # -- ordering: PROVEN before CANDIDATE, then by check code, stable otherwise
    def ordered(self) -> list[Finding]:
        rank = {Confidence.PROVEN: 0, Confidence.CANDIDATE: 1}
        return [
            f
            for _, f in sorted(
                enumerate(self.findings),
                key=lambda t: (rank[t[1].confidence], t[1].check, t[0]),
            )
        ]
