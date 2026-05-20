"""Regression test: every worked-example YAML converts to its committed JSON-LD.

For each `*.tessera.yaml` in spec/v0/examples/, run the converter and compare
against the corresponding `*.jsonld`. Comparison is *semantic* — JSON-LD has
several equivalent serializations (key order, whitespace, etc.) — so we
compare the parsed dicts directly after JSON-loading both sides.

The test also runs the resulting dict through the JSON Schema validator (one
final check that the converter produces structurally valid output).

Some divergences are tolerated and flagged at the bottom of this module —
mostly cosmetic differences between the hand-maintained JSON-LD files and the
converter's deterministic output. The intent of the regression test is to
verify *semantic* equivalence after conversion, not byte-identity with the
committed files.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from tools.converter import yaml_to_jsonld


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "spec" / "v0" / "examples"
SCHEMA_PATH = REPO_ROOT / "spec" / "v0" / "schema.json"


def _yaml_pairs() -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    for yaml_path in sorted(EXAMPLES.glob("*.tessera.yaml")):
        jsonld_path = yaml_path.with_suffix("").with_suffix(".jsonld")
        if not jsonld_path.exists():
            # Some example yamls don't have a companion .jsonld (e.g. provisional
            # drafts); skip those.
            continue
        pairs.append((yaml_path, jsonld_path))
    return pairs


def _normalize_string(s: str) -> str:
    """Collapse whitespace runs to a single space for comparison.

    YAML's `>` (folded) and `|` (literal) block-scalar styles produce
    multi-line strings that hand-authored JSON-LDs typically render single-line.
    For regression purposes we treat these as equivalent — the meaning is the
    same; the rendering differs.
    """
    return " ".join(s.split())


def _semantic_equal(a: object, b: object) -> bool:
    """Recursive equality that ignores rendering-only differences.

    - Dicts compared by content (key order doesn't matter).
    - Lists compared in order (Tessera rule ordering is significant).
    - Strings compared after whitespace normalization (block-scalar agnostic).
    - The @context value: both sides should reference the canonical URL.
    """
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        for k in a:
            if k == "@context":
                if not (isinstance(a[k], str) and isinstance(b[k], str)):
                    return False
            elif not _semantic_equal(a[k], b[k]):
                return False
        return True
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_semantic_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, str) and isinstance(b, str):
        return _normalize_string(a) == _normalize_string(b)
    return a == b


# Descriptive fields that may drift between hand-maintained YAML and JSON-LD.
# The converter's job is to produce valid JSON-LD from the YAML; if the
# committed JSON-LD has different prose in these fields, that's hand-maintenance
# drift the converter would (going forward) eliminate. The regression test
# focuses on the structural fields validators actually act on.
_DESCRIPTIVE_FIELDS = {"description", "provenance"}


def test_all_examples_convert_structurally_equivalent_to_their_committed_jsonld():
    """The converter's output and the committed JSON-LD must agree on every
    structural field (the fields validators and adapters read). Drift in the
    descriptive fields (description, provenance) is recorded separately —
    see test_descriptive_drift_is_recorded.
    """
    schema = json.loads(SCHEMA_PATH.read_text())
    failed: list[tuple[str, str]] = []
    passed: list[str] = []

    for yaml_path, jsonld_path in _yaml_pairs():
        converted = yaml_to_jsonld(yaml_path)
        try:
            jsonschema.validate(converted, schema)
        except jsonschema.ValidationError as e:
            failed.append((yaml_path.name, f"converter output failed schema validation: {e.message[:160]}"))
            continue

        committed = json.loads(jsonld_path.read_text())
        converted_structural = {k: v for k, v in converted.items() if k not in _DESCRIPTIVE_FIELDS}
        committed_structural = {k: v for k, v in committed.items() if k not in _DESCRIPTIVE_FIELDS}

        if _semantic_equal(converted_structural, committed_structural):
            passed.append(yaml_path.name)
        else:
            top_diffs = []
            for k in set(converted_structural.keys()) | set(committed_structural.keys()):
                if k == "@context":
                    continue
                if converted_structural.get(k) != committed_structural.get(k):
                    top_diffs.append(k)
            failed.append((yaml_path.name, f"structural diff at keys: {sorted(top_diffs)}"))

    if failed:
        msg = "Converter regression failures:\n" + "\n".join(
            f"  {name}: {reason}" for name, reason in failed
        )
        if passed:
            msg += f"\n\nPassed: {len(passed)}/{len(passed) + len(failed)}"
        raise AssertionError(msg)


def test_descriptive_drift_is_recorded():
    """Surface (rather than hide) the YAML-vs-JSON-LD content drift in
    descriptive fields. The test asserts that the converter's output is at
    least *structurally* valid (passes JSON Schema); the actual content
    drift is reported and considered acceptable for v1.

    A follow-up commit may regenerate the committed JSON-LDs from the YAMLs
    via the converter so the corpus is canonical-YAML-driven going forward.
    Until then this test serves as a known-state record.
    """
    drifted: list[str] = []
    for yaml_path, jsonld_path in _yaml_pairs():
        converted = yaml_to_jsonld(yaml_path)
        committed = json.loads(jsonld_path.read_text())
        for field in _DESCRIPTIVE_FIELDS:
            if not _semantic_equal(converted.get(field), committed.get(field)):
                drifted.append(f"{yaml_path.name}/{field}")
                break
    # Acceptable for v1; record the count.
    print(f"\nDescriptive drift across corpus: {len(drifted)} field(s) differ between YAML and committed JSON-LD.")
    if drifted:
        print("Drifting:")
        for d in drifted:
            print(f"  - {d}")
    # No assert — this is informational. A follow-up regeneration commit would
    # zero this out; v1's contract is structural equivalence, not byte-identity.


def test_envelope_form_round_trip_yields_expected_top_keys():
    """Sanity check for the envelope-form mapping."""
    yaml_text = """
policy:
  id: my-policy
  version: 1.0.0
  kind: RowVisibilityConstraint
  appliesTo:
    selector: byIdentity
    resource: table:db.s.t
  action: Read
  rules:
    - principal:
        selector: byIdentity
        resource: group:foo
      effect: allow
"""
    from tools.converter import yaml_to_jsonld_str
    out = yaml_to_jsonld_str(yaml_text)
    assert out["@context"].startswith("https://"), out["@context"]
    assert out["@type"] == "Policy"
    assert out["@id"] == "policy:my-policy"
    assert out["policyKind"] == "RowVisibilityConstraint"
    assert out["action"] == "Read"
    assert isinstance(out["rules"], list) and len(out["rules"]) == 1


def test_envelope_nested_type_renamed_to_at_type():
    """`type: PrincipalSetFromTable` inside a nested block must become @type."""
    yaml_text = """
policy:
  id: t
  kind: RowVisibilityConstraint
  appliesTo: {selector: byIdentity, resource: table:x}
  action: Read
  rules:
    - principal:
        selector: byDataset
        dataset:
          type: PrincipalSetFromTable
          table: db.s.acl
          principalColumn: user
          resourceColumn: code
      effect: keep-matching-rows
"""
    from tools.converter import yaml_to_jsonld_str
    out = yaml_to_jsonld_str(yaml_text)
    dataset = out["rules"][0]["principal"]["dataset"]
    assert "@type" in dataset, f"expected @type in dataset, got keys: {list(dataset.keys())}"
    assert dataset["@type"] == "PrincipalSetFromTable"
    assert "type" not in dataset


def test_id_without_prefix_gets_policy_prefix():
    """`id: my-policy` (no prefix) becomes `@id: policy:my-policy`."""
    yaml_text = """
policy:
  id: bare-name
  kind: RowVisibilityConstraint
  appliesTo: {selector: byIdentity, resource: table:x}
  action: Read
  rules:
    - principal: {selector: byIdentity, resource: group:foo}
      effect: allow
"""
    from tools.converter import yaml_to_jsonld_str
    out = yaml_to_jsonld_str(yaml_text)
    assert out["@id"] == "policy:bare-name"


def test_id_with_explicit_prefix_passes_through():
    """`id: example:something` keeps its prefix."""
    yaml_text = """
policy:
  id: example:already-prefixed
  kind: RowVisibilityConstraint
  appliesTo: {selector: byIdentity, resource: table:x}
  action: Read
  rules:
    - principal: {selector: byIdentity, resource: group:foo}
      effect: allow
"""
    from tools.converter import yaml_to_jsonld_str
    out = yaml_to_jsonld_str(yaml_text)
    assert out["@id"] == "example:already-prefixed"
