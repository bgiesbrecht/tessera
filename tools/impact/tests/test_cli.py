"""CLI tests, focused on the §9.1 corpus-boundary decision.

Corpus discovery is git-tracked by default (option C), with a filesystem
`--corpus DIR` override (option A). The key behaviors to pin:
  * the default corpus is the git-tracked policy set — untracked drafts are
    excluded until staged;
  * `.jsonld` / `.tessera.yaml` siblings dedup to one policy (prefer .jsonld);
  * the filesystem override globs a directory regardless of git.

These run against a throwaway git repo built in a temp dir, so they neither
depend on nor mutate the Tessera working tree.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tools.impact.__main__ import (
    _dedup_by_stem,
    _tracked_policy_files,
    main,
)


# -- stem dedup (sibling handling) ------------------------------------------


def test_dedup_prefers_jsonld_over_yaml_sibling():
    paths = ["dir/p.jsonld", "dir/p.tessera.yaml", "dir/q.tessera.yaml"]
    out = _dedup_by_stem(paths)
    assert "dir/p.jsonld" in out
    assert "dir/p.tessera.yaml" not in out  # sibling dropped
    assert "dir/q.tessera.yaml" in out       # no jsonld sibling -> kept


def test_dedup_keeps_same_stem_in_different_dirs():
    # A stem collision across directories is two different policies, not siblings.
    paths = ["a/p.jsonld", "b/p.jsonld"]
    assert set(_dedup_by_stem(paths)) == {"a/p.jsonld", "b/p.jsonld"}


# -- git-tracked default corpus ---------------------------------------------


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _policy(pid: str, values: list[str]) -> dict:
    return {
        "@context": "https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld",
        "@type": "Policy",
        "@id": f"policy:{pid}",
        "policyKind": "RowVisibilityConstraint",
        "appliesTo": {"selector": "byIdentity", "resource": "table:a.b.c"},
        "action": "Read",
        "defaultStrategy": "none",
        "rules": [
            {
                "principal": {"selector": "byIdentity", "resource": "group:g"},
                "effect": "keep-matching-rows",
                "condition": {
                    "op": "in",
                    "operands": ["column:a.b.c.col"],
                    "values": values,
                },
            }
        ],
    }


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "policies").mkdir(parents=True)
    _run_git(repo, "init", "-q")
    _run_git(repo, "config", "user.email", "t@t")
    _run_git(repo, "config", "user.name", "t")
    return repo


def test_tracked_files_exclude_untracked(tmp_path):
    repo = _init_repo(tmp_path)
    pol = repo / "policies" / "p.jsonld"
    pol.write_text(json.dumps(_policy("p", ["1"])))
    _run_git(repo, "add", "policies/p.jsonld")
    _run_git(repo, "commit", "-qm", "add p")

    # An untracked draft in the same dir must NOT be part of the corpus.
    (repo / "policies" / "draft.jsonld").write_text(json.dumps(_policy("draft", ["1"])))

    tracked = _tracked_policy_files(repo, "WORKING")
    assert tracked == ["policies/p.jsonld"]


def test_default_mode_reports_working_tree_edit(tmp_path, capsys, monkeypatch):
    repo = _init_repo(tmp_path)
    pol = repo / "policies" / "p.jsonld"
    pol.write_text(json.dumps(_policy("p", ["1"])))
    _run_git(repo, "add", "policies/p.jsonld")
    _run_git(repo, "commit", "-qm", "add p")

    # Widen the tracked policy's value set in the working tree.
    pol.write_text(json.dumps(_policy("p", ["1", "2"])))

    monkeypatch.chdir(repo)
    rc = main(["--format", "json"])
    assert rc == 0
    findings = json.loads(capsys.readouterr().out)
    c6 = [f for f in findings if f["check"] == "C6"]
    assert len(c6) == 1
    assert c6[0]["polarity"] == "WIDEN"


def test_default_mode_ignores_untracked_draft(tmp_path, capsys, monkeypatch):
    repo = _init_repo(tmp_path)
    pol = repo / "policies" / "p.jsonld"
    pol.write_text(json.dumps(_policy("p", ["1"])))
    _run_git(repo, "add", "policies/p.jsonld")
    _run_git(repo, "commit", "-qm", "add p")

    # Untracked draft present, tracked file unchanged -> no findings.
    (repo / "policies" / "draft.jsonld").write_text(json.dumps(_policy("draft", ["9"])))

    monkeypatch.chdir(repo)
    rc = main(["--format", "json"])
    assert rc == 0
    findings = json.loads(capsys.readouterr().out)
    assert findings == []


def test_baseline_without_proposed_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    try:
        main(["--baseline", "a.jsonld"])
    except SystemExit as e:
        assert e.code == 2


# -- lint mode ---------------------------------------------------------------


def _policy_with_dead_rule(pid: str) -> dict:
    """A policy whose second rule is shadowed by the first (unconditional broad
    keep before a narrower conditional keep on the same selector)."""
    return {
        "@context": "https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld",
        "@type": "Policy",
        "@id": f"policy:{pid}",
        "policyKind": "RowVisibilityConstraint",
        "appliesTo": {"selector": "byIdentity", "resource": "table:a.b.c"},
        "action": "Read",
        "defaultStrategy": "none",
        "rules": [
            {"principal": {"selector": "byIdentity", "resource": "group:g"},
             "effect": "keep-matching-rows"},
            {"principal": {"selector": "byIdentity", "resource": "group:g"},
             "effect": "drop-matching-rows",
             "condition": {"op": "in", "operands": ["column:a.b.c.col"], "values": ["1"]}},
        ],
    }


def test_lint_mode_flags_dead_rule(tmp_path, capsys, monkeypatch):
    repo = _init_repo(tmp_path)
    (repo / "policies" / "p.jsonld").write_text(json.dumps(_policy_with_dead_rule("p")))
    _run_git(repo, "add", "policies/p.jsonld")
    _run_git(repo, "commit", "-qm", "add p")

    monkeypatch.chdir(repo)
    rc = main(["--lint", "--format", "json"])
    assert rc == 0
    findings = json.loads(capsys.readouterr().out)
    l1 = [f for f in findings if f["check"] == "L1"]
    assert len(l1) == 1


def test_lint_rejects_git_flag(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    monkeypatch.chdir(repo)
    try:
        main(["--lint", "--git", "HEAD", "WORKING"])
    except SystemExit as e:
        assert e.code == 2


def test_lint_corpus_override_globs_directory(tmp_path, capsys, monkeypatch):
    repo = _init_repo(tmp_path)
    # File is present but NOT git-tracked; --corpus should still find it.
    (repo / "policies" / "p.jsonld").write_text(json.dumps(_policy_with_dead_rule("p")))
    _run_git(repo, "commit", "-qm", "init", "--allow-empty")

    monkeypatch.chdir(repo)
    rc = main(["--lint", "--corpus", "policies", "--format", "json"])
    assert rc == 0
    findings = json.loads(capsys.readouterr().out)
    assert any(f["check"] == "L1" for f in findings)
