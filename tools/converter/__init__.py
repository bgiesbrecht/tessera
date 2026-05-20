"""Tessera YAML ↔ JSON-LD converter.

v1 scope:
    * YAML → JSON-LD conversion (the practitioner-friendly authoring direction).
    * Two input shapes supported:
        - "envelope" form  — `policy: {id, kind, …}` wrapper (the
          form the tutorial teaches authors to write).
        - "flat" form      — JSON-LD-shaped YAML with `@context`, `@type`,
          `@id`, `policyKind` at top level (the form used by the early worked
          examples; passes through structurally).
    * Comment preservation is deferred (ADR-004) — `ruamel.yaml` is used
      from the start so the structural read preserves enough metadata to
      add comment preservation later without re-architecting.
    * The reverse direction (JSON-LD → YAML) is deferred — single direction
      covers the practitioner path; reverse-direction work belongs with the
      adapter extraction story (migration use case).

Public surface:
    yaml_to_jsonld(path) -> dict          read YAML file, return JSON-LD dict
    yaml_to_jsonld_str(yaml_text) -> dict same, from a string
    convert_file(in_path, out_path)       write JSON-LD file from YAML file
"""

from tools.converter.yaml_to_jsonld import (
    yaml_to_jsonld,
    yaml_to_jsonld_str,
    convert_file,
    CANONICAL_CONTEXT_URL,
)

__all__ = [
    "yaml_to_jsonld",
    "yaml_to_jsonld_str",
    "convert_file",
    "CANONICAL_CONTEXT_URL",
]
