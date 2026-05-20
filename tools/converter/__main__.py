"""Tiny CLI entry point: `python -m tools.converter <file.tessera.yaml> [--out path]`.

Writes canonical JSON-LD to stdout by default, or to a path when `--out` is given.
Operates on a single file at a time; batch conversions belong in a larger CLI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tools.converter.yaml_to_jsonld import yaml_to_jsonld


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m tools.converter",
        description="Convert a Tessera YAML policy file to canonical JSON-LD.",
    )
    p.add_argument("input", help="Path to a .tessera.yaml file.")
    p.add_argument("--out", help="Write JSON-LD here. Defaults to stdout.")
    args = p.parse_args(argv)

    try:
        doc = yaml_to_jsonld(args.input)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    payload = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        Path(args.out).write_text(payload)
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
