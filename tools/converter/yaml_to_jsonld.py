"""YAML → JSON-LD conversion for Tessera policies.

The conversion is mechanical:

Envelope-form YAML (the practitioner authoring shape):

    policy:
      id: foo
      kind: RowVisibilityConstraint
      …
      rules:
        - principal:
            selector: byDataset
            dataset:
              type: PrincipalSetFromTable
              …

Becomes canonical JSON-LD:

    {
      "@context": "https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld",
      "@type": "Policy",
      "@id": "policy:foo",
      "policyKind": "RowVisibilityConstraint",
      …
      "rules": [
        {
          "principal": {
            "selector": "byDataset",
            "dataset": {
              "@type": "PrincipalSetFromTable",
              …
            }
          }
        }
      ]
    }

Rules applied:

1. Envelope unwrap. If the root has a single `policy:` key, the conversion
   operates on its value and adds `@type: Policy` at the new root.
2. Field renames at the top level: `id → @id`, `kind → policyKind`.
3. The `@id` value gets a `policy:` prefix if it doesn't already have a
   `<prefix>:` form. This matches the convention every committed example uses.
4. Inside nested structures (datasets, condition operands, transformations,
   defaultBranch.transformation), a bare `type:` is renamed to `@type:` so the
   JSON-LD parser sees a typed object.
5. The canonical `@context` URL is prepended at the new root.

Flat-form YAML (the older "JSON-LD-as-YAML" shape) is passed through largely
unchanged — its `@context`, `@type`, `@id`, `policyKind` etc. are already in
JSON-LD form. Only normalization is to ensure `@context` is the canonical URL
(in case of a missing or local reference).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ruamel.yaml import YAML


CANONICAL_CONTEXT_URL = "https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld"

# Set of top-level policy fields whose values may contain nested objects with a
# bare `type:` field that means JSON-LD `@type`. The converter walks these and
# renames recursively.
_TYPED_NEST_KEYS = {
    "rules",
    "appliesTo",
    "defaultBranch",
    "principal",
    "dataset",
    "condition",
    "operands",
    "transformation",
    "matching",
    "criteria",
}


# YAML parser configured for round-trip semantics — ruamel.yaml round-trip mode
# preserves comments and structure, even though v1 of the converter discards
# them on output. Choosing round-trip mode now keeps comment preservation a
# one-step addition rather than a refactor later.
_yaml = YAML(typ="rt")
_yaml.preserve_quotes = True


def yaml_to_jsonld(path: str | Path) -> dict[str, Any]:
    """Read a Tessera YAML file and return its canonical JSON-LD form as a dict."""
    text = Path(path).read_text()
    return yaml_to_jsonld_str(text)


def yaml_to_jsonld_str(yaml_text: str) -> dict[str, Any]:
    """Convert a YAML document (as text) to canonical JSON-LD (as a dict).

    Accepts both shapes (envelope + flat). Always returns a JSON-LD-shaped dict.
    """
    parsed = _yaml.load(yaml_text)
    if parsed is None:
        raise ValueError("Empty or unparseable YAML document.")

    data = _to_plain(parsed)

    if "policy" in data and isinstance(data["policy"], dict) and len(data) == 1:
        return _convert_envelope(data["policy"])
    if "@context" in data or "@type" in data:
        return _normalize_flat(data)
    raise ValueError(
        "YAML document does not look like a Tessera policy. Expected either a "
        "`policy:` envelope or a JSON-LD-shaped document with @context / @type."
    )


def convert_file(in_path: str | Path, out_path: str | Path, *, indent: int = 2) -> None:
    """Read a YAML file at `in_path`, write canonical JSON-LD to `out_path`."""
    import json
    doc = yaml_to_jsonld(in_path)
    Path(out_path).write_text(json.dumps(doc, indent=indent, ensure_ascii=False) + "\n")


# ----------------------------------------------------------------------------
# Internal conversion helpers
# ----------------------------------------------------------------------------


def _to_plain(value: Any) -> Any:
    """Recursively convert ruamel.yaml's CommentedMap/CommentedSeq to plain dict/list."""
    # ruamel.yaml round-trip mode returns CommentedMap and CommentedSeq subclasses
    # of dict and list respectively. We want plain types for JSON serialization.
    if isinstance(value, dict):
        return {k: _to_plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_plain(v) for v in value]
    return value


def _convert_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """Unwrap the `policy:` envelope into a JSON-LD-shaped dict.

    Field-level transformations applied:
        * id    → @id (with `policy:` prefix added if no prefix present)
        * kind  → policyKind
        * type  → @type (recursively, inside nested values)
    """
    out: dict[str, Any] = {
        "@context": CANONICAL_CONTEXT_URL,
        "@type": "Policy",
    }

    raw_id = envelope.get("id")
    if raw_id is not None:
        out["@id"] = _id_with_prefix(str(raw_id))

    # Preserve declaration order of remaining fields, applying renames.
    rename = {"kind": "policyKind"}
    skip = {"id"}
    for key, value in envelope.items():
        if key in skip:
            continue
        out_key = rename.get(key, key)
        out[out_key] = _rename_types_recursively(value)
    return out


def _normalize_flat(data: dict[str, Any]) -> dict[str, Any]:
    """Lightly normalize a flat-form (JSON-LD-shaped) document.

    Ensures the canonical @context URL is present at root; renames any nested
    `type:` to `@type:` for consistency with the envelope output shape.
    """
    if "@context" not in data:
        data = {"@context": CANONICAL_CONTEXT_URL, **data}
    return _rename_types_recursively(data)


def _rename_types_recursively(value: Any, *, parent_key: str | None = None) -> Any:
    """Walk a structure renaming bare `type` to `@type` where the JSON-LD shape requires.

    Context matters. The Tessera schema is deliberately asymmetric:

        * `dataset: {type: PrincipalSetFromTable, …}`         → @type    (JSON-LD typed)
        * `operands[i]: {type: ResourceSetFromTable, …}`      → @type    (JSON-LD typed)
        * `transformation: {type: Redact, replacement: …}`    → keep `type`  (schema field)
        * `defaultBranch.transformation: {type: Redact, …}`   → keep `type`  (schema field)

    Transformations are not modeled as JSON-LD-typed blank nodes; the schema
    declares `type` as a plain enum-valued field. Datasets are JSON-LD-typed.
    The rename is therefore conditioned on the parent key.

    String values are right-stripped to drop trailing whitespace that YAML's
    block-scalar styles (`>` folded, `|` literal) commonly append. This makes
    the converter output match hand-authored JSON-LDs that omit those.
    """
    if isinstance(value, dict):
        renamed: dict[str, Any] = {}
        # `transformation:` is the parent whose immediate-child dict keeps `type`.
        # Anywhere else where a child dict has a class-cased `type`, we rename.
        keep_type_here = parent_key == "transformation"
        for k, v in value.items():
            new_k = k
            if (
                k == "type"
                and not keep_type_here
                and isinstance(v, str)
                and v[:1].isupper()
            ):
                new_k = "@type"
            renamed[new_k] = _rename_types_recursively(v, parent_key=k)
        return renamed
    if isinstance(value, list):
        return [_rename_types_recursively(v, parent_key=parent_key) for v in value]
    if isinstance(value, str):
        # Trailing-whitespace strip is conservative: it removes only newlines
        # and spaces that YAML's block scalars add. Internal whitespace is
        # preserved verbatim.
        return value.rstrip()
    return value


def _id_with_prefix(raw: str) -> str:
    """Prepend `policy:` to an id if it has no `<prefix>:` form.

    The committed examples all use `policy:<slug>` IRIs. The envelope YAML shape
    typically just declares `id: <slug>` to keep authoring readable; the
    converter normalizes to the canonical IRI.
    """
    if ":" in raw:
        return raw
    return f"policy:{raw}"
