"""CLI: change-impact analysis over a Tessera policy corpus.

The corpus boundary (scoping-doc §9.1) is git-tracked by default: the policies
git knows about form the corpus. This reuses the version boundary an author
already works with: committed policies are the real corpus, uncommitted drafts
are naturally excluded until staged, and needs no extra config file. A
filesystem directory is available as an explicit override.

Three ways to invoke:

  Default (git-tracked corpus, HEAD → working tree), the common case,
  "what did my working-tree edit do to the tracked policies?":
      python -m tools.impact

  Git-tracked corpus across two explicit refs:
      python -m tools.impact --git main HEAD

  Filesystem override: treat every policy file under a directory as the
  corpus, ignoring git (useful for a scratch/unversioned policy set):
      python -m tools.impact --corpus spec/v0/examples
      python -m tools.impact --corpus spec/v0/examples --git HEAD WORKING

  Explicit file mode: compare two hand-picked sets of files:
      python -m tools.impact \
          --baseline a.jsonld b.jsonld \
          --proposed a-edited.jsonld b.jsonld

  Lint mode: whole-corpus health check for dead rules (single corpus state,
  not a diff); audits one ref (default the working tree):
      python -m tools.impact --lint
      python -m tools.impact --lint --at HEAD
      python -m tools.impact --lint --corpus spec/v0/examples

Refs: any git ref; the sentinel WORKING means the working tree (files as they
are on disk). The default refs are HEAD → WORKING.

Output format: --format text (default) | md | json.

The report is advisory; the process exit code is 0 whether or not findings are
present (findings are information, not errors). Use --exit-on <polarity> to opt
into a nonzero exit for CI gating (kept out of the core per scoping-doc §9.2).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from tools.impact.analyze import analyze_paths, lint_paths
from tools.impact.findings import Polarity
from tools.impact.report import render_json, render_markdown, render_text


POLICY_SUFFIXES = (".jsonld", ".tessera.yaml")
WORKING = "WORKING"  # ref sentinel: the working tree


# ----------------------------------------------------------------------------
# Policy-file identity helpers
# ----------------------------------------------------------------------------


def _is_policy_file(name: str) -> bool:
    return name.endswith(".jsonld") or name.endswith(".tessera.yaml")


def _policy_stem(name: str) -> str:
    """The stem shared by `X.jsonld` and `X.tessera.yaml`."""
    if name.endswith(".tessera.yaml"):
        return name[: -len(".tessera.yaml")]
    return name[: -len(".jsonld")] if name.endswith(".jsonld") else name


def _dedup_by_stem(paths: list[str]) -> list[str]:
    """Keep one representation per policy stem, preferring canonical `.jsonld`
    over its `.tessera.yaml` sibling (ADR-004). `paths` are repo-relative
    strings; siblings are recognized by matching directory + stem.

    A corpus holds one representation per policy id; a directory that keeps both
    the YAML source and its generated JSON-LD (e.g. spec/v0/examples) would
    otherwise load both and have one silently clobber the other.
    """
    jsonld = [p for p in paths if p.endswith(".jsonld")]
    jsonld_keys = {(str(Path(p).parent), _policy_stem(Path(p).name)) for p in jsonld}
    yaml = [
        p for p in paths
        if p.endswith(".tessera.yaml")
        and (str(Path(p).parent), _policy_stem(Path(p).name)) not in jsonld_keys
    ]
    return sorted(jsonld + yaml)


# ----------------------------------------------------------------------------
# Git plumbing
# ----------------------------------------------------------------------------


def _git(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True, text=True, check=True,
    ).stdout


def _git_root(start: Path) -> Path:
    out = _git(start, "rev-parse", "--show-toplevel")
    return Path(out.strip())


def _tracked_policy_files(repo_root: Path, ref: str) -> list[str]:
    """Repo-relative policy files git tracks at `ref` (§9.1 default corpus).

    WORKING lists the working-tree tracked set (`git ls-files`); any other ref
    lists that commit's tree (`git ls-tree`). Deduplicated by stem.
    """
    if ref == WORKING:
        raw = _git(repo_root, "ls-files")
    else:
        raw = _git(repo_root, "ls-tree", "-r", "--name-only", ref)
    files = [line for line in raw.splitlines() if _is_policy_file(line)]
    return _dedup_by_stem(files)


def _materialize(repo_root: Path, rel_paths: list[str], ref: str, dest: Path) -> list[Path]:
    """Write each repo-relative policy file's content at `ref` under `dest`,
    preserving directory structure, and return the written paths.

    WORKING reads the file from disk; any other ref reads it from git. A file
    absent at the given ref (e.g. added later) is skipped for that side.
    """
    out: list[Path] = []
    for rel in rel_paths:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if ref == WORKING:
            src = repo_root / rel
            if not src.exists():
                continue
            target.write_text(src.read_text())
        else:
            try:
                content = _git(repo_root, "show", f"{ref}:{rel}")
            except subprocess.CalledProcessError:
                continue
            target.write_text(content)
        out.append(target)
    return out


# ----------------------------------------------------------------------------
# Discovery backends
# ----------------------------------------------------------------------------


def _filesystem_policy_files(repo_root: Path, corpus_dir: Path) -> list[str]:
    """Repo-relative policy files found by globbing a directory (option A
    override). Recurses so a nested policy layout is still captured."""
    found: list[str] = []
    for suffix in POLICY_SUFFIXES:
        for p in corpus_dir.rglob(f"*{suffix}"):
            found.append(str(p.resolve().relative_to(repo_root)))
    return _dedup_by_stem(found)


# ----------------------------------------------------------------------------
# Run modes
# ----------------------------------------------------------------------------


def _run_corpus_mode(repo_root: Path, base_ref: str, prop_ref: str, corpus_dir: Path | None):
    """Compare a corpus across two refs. Discovery is git-tracked by default;
    a corpus_dir switches to filesystem discovery (option A)."""
    if corpus_dir is not None:
        base_files = _filesystem_policy_files(repo_root, corpus_dir)
        prop_files = base_files  # same file set; content differs per ref
    else:
        base_files = _tracked_policy_files(repo_root, base_ref)
        prop_files = _tracked_policy_files(repo_root, prop_ref)

    if not base_files and not prop_files:
        where = corpus_dir if corpus_dir is not None else f"git-tracked files at {base_ref}/{prop_ref}"
        raise ValueError(f"no Tessera policy files found ({where}).")

    with tempfile.TemporaryDirectory() as bdir, tempfile.TemporaryDirectory() as pdir:
        base_paths = _materialize(repo_root, base_files, base_ref, Path(bdir))
        prop_paths = _materialize(repo_root, prop_files, prop_ref, Path(pdir))
        return analyze_paths(base_paths, prop_paths)


def _run_lint_mode(repo_root: Path, ref: str, corpus_dir: Path | None):
    """Lint a single corpus state (one ref) for dead rules. Same discovery as
    the diff modes, but materializes and audits just one side."""
    if corpus_dir is not None:
        files = _filesystem_policy_files(repo_root, corpus_dir)
    else:
        files = _tracked_policy_files(repo_root, ref)

    if not files:
        where = corpus_dir if corpus_dir is not None else f"git-tracked files at {ref}"
        raise ValueError(f"no Tessera policy files found ({where}).")

    with tempfile.TemporaryDirectory() as ddir:
        paths = _materialize(repo_root, files, ref, Path(ddir))
        return lint_paths(paths)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m tools.impact",
        description="Report the exposure impact of a change to a Tessera policy corpus.",
    )
    p.add_argument("--lint", action="store_true",
                   help="Whole-corpus health check for dead rules (single corpus state, "
                        "not a diff). Audits one ref (default WORKING; override with --at).")
    p.add_argument("--at", metavar="REF",
                   help="Ref to lint (--lint mode only; default WORKING = working tree).")
    p.add_argument("--git", nargs=2, metavar=("BASE_REF", "PROP_REF"),
                   help="Compare across two git refs (default: HEAD WORKING). "
                        "WORKING means the working tree.")
    p.add_argument("--corpus", help="Filesystem override: treat every policy file under "
                                     "this directory as the corpus, ignoring git tracking.")
    p.add_argument("--baseline", nargs="+", help="Baseline policy files (explicit file mode).")
    p.add_argument("--proposed", nargs="+", help="Proposed policy files (explicit file mode).")
    p.add_argument("--format", choices=("text", "md", "json"), default="text")
    p.add_argument("--exit-on", choices=[x.value for x in Polarity],
                   help="Exit nonzero if any finding has this polarity (CI gating; opt-in).")
    args = p.parse_args(argv)

    if (args.baseline is None) != (args.proposed is None):
        p.error("--baseline and --proposed must be given together.")
        return 2
    if args.lint and (args.git or args.baseline):
        p.error("--lint is a single-corpus mode; it does not take --git or --baseline/--proposed.")
        return 2

    try:
        if args.lint:
            ref = args.at if args.at else WORKING
            start = Path(args.corpus) if args.corpus else Path.cwd()
            repo_root = _git_root(start)
            corpus_dir = Path(args.corpus).resolve() if args.corpus else None
            report = _run_lint_mode(repo_root, ref, corpus_dir)
        elif args.baseline and args.proposed:
            # Explicit file mode: no git, no discovery.
            report = analyze_paths(args.baseline, args.proposed)
        else:
            base_ref, prop_ref = args.git if args.git else ("HEAD", WORKING)
            start = Path(args.corpus) if args.corpus else Path.cwd()
            repo_root = _git_root(start)
            corpus_dir = Path(args.corpus).resolve() if args.corpus else None
            report = _run_corpus_mode(repo_root, base_ref, prop_ref, corpus_dir)
    except (FileNotFoundError, ValueError, subprocess.CalledProcessError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.format == "json":
        sys.stdout.write(render_json(report))
    elif args.format == "md":
        sys.stdout.write(render_markdown(report))
    else:
        sys.stdout.write(render_text(report))

    if args.exit_on:
        if any(f.polarity and f.polarity.value == args.exit_on for f in report.findings):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
