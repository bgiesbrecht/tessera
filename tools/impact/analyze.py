"""Top-level orchestration for change-impact analysis.

`analyze(baseline, proposed)` runs the diff-based checks over a baseline and a
proposed corpus and returns a Report (C1/C2/C3/C5/C6).

`lint(corpus)` runs the standing whole-corpus checks over a single corpus state
(L1 dead-rule detection): a health check on the corpus as it stands, rather
than a diff between two versions.
"""

from __future__ import annotations

from pathlib import Path

from tools.impact.checks import (
    check_c1_fallthrough_coverage,
    check_c2_default_net,
    check_c3_reachability,
    check_c4_cross_policy_overlap,
    check_c5_dangling_reference,
    check_c6_exposure_polarity,
    lint_cross_policy_overlap,
    lint_dead_rules,
)
from tools.impact.findings import Report
from tools.impact.model import Corpus, load_corpus_from_paths


# The check registry. Each entry is (name, callable(baseline, proposed) -> [Finding]).
DEFAULT_CHECKS = [
    ("C6", check_c6_exposure_polarity),
    ("C1", check_c1_fallthrough_coverage),
    ("C2", check_c2_default_net),
    ("C3", check_c3_reachability),
    ("C4", check_c4_cross_policy_overlap),
    ("C5", check_c5_dangling_reference),
]


def analyze(baseline: Corpus, proposed: Corpus, *, checks=None) -> Report:
    """Run the enabled checks and collect findings into a Report."""
    checks = checks if checks is not None else DEFAULT_CHECKS
    report = Report()
    for _name, fn in checks:
        report.extend(fn(baseline, proposed))
    return report


def analyze_paths(
    baseline_paths: list[str | Path],
    proposed_paths: list[str | Path],
    *,
    checks=None,
) -> Report:
    """Convenience: load two corpora from file paths and analyze them."""
    baseline = load_corpus_from_paths(baseline_paths)
    proposed = load_corpus_from_paths(proposed_paths)
    return analyze(baseline, proposed, checks=checks)


# The standing lint registry. Each entry is (name, callable(corpus) -> [Finding]).
LINT_CHECKS = [
    ("L1", lint_dead_rules),
    ("L2", lint_cross_policy_overlap),
]


def lint(corpus: Corpus, *, checks=None) -> Report:
    """Run the standing whole-corpus checks over a single corpus state."""
    checks = checks if checks is not None else LINT_CHECKS
    report = Report()
    for _name, fn in checks:
        report.extend(fn(corpus))
    return report


def lint_paths(paths: list[str | Path], *, checks=None) -> Report:
    """Convenience: load a corpus from file paths and lint it."""
    return lint(load_corpus_from_paths(paths), checks=checks)
