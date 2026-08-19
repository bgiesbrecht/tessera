"""Tessera change-impact analysis.

Given a corpus of Tessera policies and a proposed change to it, report how the
change alters what the corpus decides about data, before the change is
authored, validated, or emitted to any platform.

The tool reasons about selector *expressions*, never about the populations
those selectors denote (scoping doc §2). Comparing selector literals, IRIs, and
ontology-typed values is static analysis; resolving group membership or reading
ACL-table rows would be policy evaluation, which ADR-001 disclaims. Every
finding is therefore selector-relative and confidence-tagged (PROVEN vs
CANDIDATE); the report is advisory and never blocks.

Design: docs/v1-candidates/change-impact-analysis.md

Stage 1 public surface:
    analyze(baseline, proposed) -> Report        run checks over two corpora
    analyze_paths(base_paths, prop_paths)         same, loading from files
    load_corpus_from_paths(paths) -> Corpus       build a corpus
    render_text / render_markdown / render_json   render a Report
"""

from tools.impact.analyze import analyze, analyze_paths, lint, lint_paths
from tools.impact.findings import Confidence, Finding, Polarity, Report
from tools.impact.model import Corpus, Policy, load_corpus_from_paths
from tools.impact.report import render_json, render_markdown, render_text

__all__ = [
    "analyze",
    "analyze_paths",
    "lint",
    "lint_paths",
    "load_corpus_from_paths",
    "Corpus",
    "Policy",
    "Report",
    "Finding",
    "Confidence",
    "Polarity",
    "render_text",
    "render_markdown",
    "render_json",
]
