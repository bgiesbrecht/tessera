"""Typed model of a Tessera policy corpus, parsed from JSON-LD.

The change-impact tool reasons over policy *documents*, not over the platforms
they compile to. This module lifts the canonical JSON-LD form (the same shape
the converter emits) into small dataclasses that the kernel and checks operate
on. YAML inputs are normalized to JSON-LD first via the converter, so this
module only ever sees the canonical dict shape.

The model is intentionally shallow: it captures exactly the fields the Stage-1
checks (C5 dangling-reference, C6 exposure-polarity) and the kernel need, and
leaves everything else as opaque `raw` for later stages to reach into. Nothing
here evaluates a policy — it only records what the document declares.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ----------------------------------------------------------------------------
# Selector — a principal or resource selector expression
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Selector:
    """A principal or resource selector, in normalized comparable form.

    Only the fields the kernel compares are lifted; the originating dict is
    kept in `raw` for checks that need to reach further. Selectors are compared
    by the kernel (see kernel.py), never by resolving the population they
    denote — that would be evaluation (ADR-001).
    """

    kind: str | None
    # For byIdentity/byScope: the single resource/scope IRI (CURIE form).
    resource: str | None = None
    scope: str | None = None
    # For byScope with attribute matching (ADR-019/020): {axis: value, ...}.
    attributes: tuple[tuple[str, str], ...] = ()
    # byDataset table reference, when present (opaque to static analysis).
    dataset_table: str | None = None
    raw: Any = None

    @classmethod
    def from_dict(cls, d: Any) -> "Selector":
        if not isinstance(d, dict):
            return cls(kind=None, raw=d)
        kind = d.get("selector")
        matching = d.get("matching") or {}
        attrs = matching.get("attributes") if isinstance(matching, dict) else None
        attr_tuple: tuple[tuple[str, str], ...] = ()
        if isinstance(attrs, dict):
            attr_tuple = tuple(sorted((str(k), str(v)) for k, v in attrs.items()))
        dataset = d.get("dataset")
        dataset_table = dataset.get("table") if isinstance(dataset, dict) else None
        return cls(
            kind=kind,
            resource=d.get("resource"),
            scope=d.get("scope"),
            attributes=attr_tuple,
            dataset_table=dataset_table,
            raw=d,
        )

    def describe(self) -> str:
        """A short, human-readable, population-free label for reports."""
        if self.resource:
            return self.resource
        if self.scope:
            attrs = ", ".join(f"{a}={v}" for a, v in self.attributes)
            return f"{self.scope}" + (f" [{attrs}]" if attrs else "")
        if self.dataset_table:
            return f"byDataset({self.dataset_table})"
        return self.kind or "<unknown>"


# ----------------------------------------------------------------------------
# Condition — the leaf condition on a rule
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Condition:
    """A rule condition. Only the comparable shape (operator + operand column +
    value set) is lifted; richer nested algebra is kept in `raw`."""

    op: str | None
    operands: tuple[str, ...] = ()
    values: tuple[str, ...] = ()
    raw: Any = None

    @classmethod
    def from_dict(cls, d: Any) -> "Condition | None":
        if not isinstance(d, dict):
            return None
        operands = d.get("operands") or []
        operand_strs = tuple(o for o in operands if isinstance(o, str))
        values = d.get("values") or []
        value_strs = tuple(str(v) for v in values)
        return cls(op=d.get("op"), operands=operand_strs, values=value_strs, raw=d)


# ----------------------------------------------------------------------------
# Rule
# ----------------------------------------------------------------------------


@dataclass
class Rule:
    principal: Selector | None
    effect: str | None
    condition: Condition | None
    transformation: dict[str, Any] | None
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Rule":
        principal = Selector.from_dict(d["principal"]) if "principal" in d else None
        transformation = d.get("transformation")
        return cls(
            principal=principal,
            effect=d.get("effect"),
            condition=Condition.from_dict(d.get("condition")),
            transformation=transformation if isinstance(transformation, dict) else None,
            raw=d,
        )


# ----------------------------------------------------------------------------
# Policy
# ----------------------------------------------------------------------------


@dataclass
class Policy:
    id: str
    policy_kind: str | None
    applies_to: Selector | None
    action: Any
    default_strategy: str | None
    baseline_group: str | None
    default_branch: Rule | None
    rules: list[Rule]
    raw: dict[str, Any]
    source_path: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any], *, source_path: str | None = None) -> "Policy":
        rules = [Rule.from_dict(r) for r in (d.get("rules") or [])]
        db = d.get("defaultBranch")
        default_branch = Rule.from_dict(db) if isinstance(db, dict) else None
        return cls(
            id=d.get("@id") or d.get("id") or "<unidentified>",
            policy_kind=d.get("policyKind"),
            applies_to=Selector.from_dict(d["appliesTo"]) if "appliesTo" in d else None,
            action=d.get("action"),
            default_strategy=d.get("defaultStrategy"),
            baseline_group=d.get("baselineGroup"),
            default_branch=default_branch,
            rules=rules,
            raw=d,
            source_path=source_path,
        )


# ----------------------------------------------------------------------------
# Corpus
# ----------------------------------------------------------------------------


@dataclass
class Corpus:
    """A set of policies keyed by @id. A corpus is the unit the impact tool
    diffs: a baseline corpus against a proposed corpus."""

    policies: dict[str, Policy] = field(default_factory=dict)

    def add(self, policy: Policy) -> None:
        self.policies[policy.id] = policy

    def get(self, policy_id: str) -> Policy | None:
        return self.policies.get(policy_id)

    def ids(self) -> set[str]:
        return set(self.policies)


def load_policy_dict(d: dict[str, Any], *, source_path: str | None = None) -> Policy:
    return Policy.from_dict(d, source_path=source_path)


def load_corpus_from_paths(paths: list[str | Path]) -> Corpus:
    """Load a corpus from a list of policy file paths.

    Accepts `.jsonld` (parsed directly) and `.tessera.yaml` / `.yaml`
    (normalized to JSON-LD via the converter first). Files that fail to parse
    as a Tessera policy are skipped by the caller's discovery logic; this
    function raises on a genuinely malformed file so problems surface loudly.
    """
    corpus = Corpus()
    for p in paths:
        path = Path(p)
        d = _read_policy_file(path)
        policy = load_policy_dict(d, source_path=str(path))
        existing = corpus.get(policy.id)
        if existing is not None and existing.raw != policy.raw:
            raise ValueError(
                f"Two policy files declare the same @id '{policy.id}' with "
                f"differing content: {existing.source_path} and {path}. A "
                f"corpus must hold one representation per policy id."
            )
        corpus.add(policy)
    return corpus


def _read_policy_file(path: Path) -> dict[str, Any]:
    if path.suffix == ".jsonld" or path.suffix == ".json":
        return json.loads(path.read_text())
    if path.name.endswith(".tessera.yaml") or path.suffix in (".yaml", ".yml"):
        # Lazy import: the converter pulls in ruamel.yaml, which need not be
        # present when the caller only ever passes JSON-LD.
        from tools.converter import yaml_to_jsonld

        return yaml_to_jsonld(path)
    raise ValueError(f"Unrecognized policy file extension: {path}")
