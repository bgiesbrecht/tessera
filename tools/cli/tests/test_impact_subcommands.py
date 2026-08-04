"""The `tessera impact` / `tessera lint` subcommands delegate to tools.impact.

These verify the unified-CLI wiring end to end: flags are translated and the
change-impact engine runs, producing the same findings it would via
`python -m tools.impact`. Uses a throwaway git repo so the Tessera working tree
is neither depended on nor mutated.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tools.cli.main import main


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "policies").mkdir(parents=True)
    _run_git(repo, "init", "-q")
    _run_git(repo, "config", "user.email", "t@t")
    _run_git(repo, "config", "user.name", "t")
    return repo


def _row_policy(pid: str, values: list[str]) -> dict:
    return {
        "@context": "https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld",
        "@type": "Policy",
        "@id": f"policy:{pid}",
        "policyKind": "RowVisibilityConstraint",
        "appliesTo": {"selector": "byIdentity", "resource": "table:a.b.c"},
        "action": "Read",
        "defaultStrategy": "none",
        "rules": [{
            "principal": {"selector": "byIdentity", "resource": "group:g"},
            "effect": "keep-matching-rows",
            "condition": {"op": "in", "operands": ["column:a.b.c.col"], "values": values},
        }],
    }


def _dead_rule_policy(pid: str) -> dict:
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


def test_impact_subcommand_reports_widen(tmp_path, capsys, monkeypatch):
    repo = _init_repo(tmp_path)
    pol = repo / "policies" / "p.jsonld"
    pol.write_text(json.dumps(_row_policy("p", ["1"])))
    _run_git(repo, "add", "policies/p.jsonld")
    _run_git(repo, "commit", "-qm", "add p")
    pol.write_text(json.dumps(_row_policy("p", ["1", "2"])))  # widen

    monkeypatch.chdir(repo)
    rc = main(["impact", "--format", "json"])
    assert rc == 0
    findings = json.loads(capsys.readouterr().out)
    assert any(f["check"] == "C6" and f["polarity"] == "WIDEN" for f in findings)


def test_lint_subcommand_flags_dead_rule(tmp_path, capsys, monkeypatch):
    repo = _init_repo(tmp_path)
    (repo / "policies" / "p.jsonld").write_text(json.dumps(_dead_rule_policy("p")))
    _run_git(repo, "add", "policies/p.jsonld")
    _run_git(repo, "commit", "-qm", "add p")

    monkeypatch.chdir(repo)
    rc = main(["lint", "--format", "json"])
    assert rc == 0
    findings = json.loads(capsys.readouterr().out)
    assert any(f["check"] == "L1" for f in findings)


def test_impact_subcommand_explicit_file_mode(tmp_path, capsys, monkeypatch):
    # --baseline/--proposed bypasses git; runnable from anywhere.
    monkeypatch.chdir(tmp_path)
    base = tmp_path / "base.jsonld"
    prop = tmp_path / "prop.jsonld"
    base.write_text(json.dumps(_row_policy("p", ["1", "2"])))
    prop.write_text(json.dumps(_row_policy("p", ["1"])))  # narrow

    rc = main(["impact", "--baseline", str(base), "--proposed", str(prop), "--format", "json"])
    assert rc == 0
    findings = json.loads(capsys.readouterr().out)
    assert any(f["check"] == "C6" and f["polarity"] == "NARROW" for f in findings)
