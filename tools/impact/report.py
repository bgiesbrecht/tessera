"""Rendering of a change-impact Report to text / markdown / json (§3 output)."""

from __future__ import annotations

import json

from tools.impact.findings import Report


def render_text(report: Report, *, title: str = "CHANGE-IMPACT REPORT") -> str:
    lines = [title, "=" * len(title), ""]
    if report.is_empty():
        lines.append("No exposure-relevant changes detected.")
        return "\n".join(lines) + "\n"

    for f in report.ordered():
        head = f"{f.code_line()}   {f.confidence.value}"
        lines.append(head)
        lines.append(f"     {f.consequence}")
        if f.unknown:
            lines.append(f"     unknown: {f.unknown}")
        lines.append(f"     grounding: {f.grounding}")
        lines.append("")
    return "\n".join(lines) + "\n"


def render_markdown(report: Report, *, title: str = "Change-impact report") -> str:
    lines = [f"# {title}", ""]
    if report.is_empty():
        lines.append("_No exposure-relevant changes detected._")
        return "\n".join(lines) + "\n"
    lines += ["| Check | Polarity | Subject | Confidence | Consequence | Grounding |",
              "|---|---|---|---|---|---|"]
    for f in report.ordered():
        polarity = f.polarity.value if f.polarity else ""
        consequence = f.consequence + (
            f" _(unknown: {f.unknown})_" if f.unknown else ""
        )
        lines.append(
            f"| {f.check} | {polarity} | {f.subject} | {f.confidence.value} "
            f"| {consequence} | {f.grounding} |"
        )
    return "\n".join(lines) + "\n"


def render_json(report: Report) -> str:
    payload = [
        {
            "check": f.check,
            "subject": f.subject,
            "polarity": f.polarity.value if f.polarity else None,
            "confidence": f.confidence.value,
            "consequence": f.consequence,
            "grounding": f.grounding,
            "policy_id": f.policy_id,
            "unknown": f.unknown,
        }
        for f in report.ordered()
    ]
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
