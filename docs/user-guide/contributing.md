# Contributing to Tessera

This page is for engineers extending Tessera — writing a new adapter, adding an IR concept, building tooling. It assumes familiarity with the IR ([`authoring.md`](./authoring.md)) and the adapter contract ([`operating.md`](./operating.md)).

The project's discipline matters more than its current code. Read this page before opening a substantial PR.

## ADR discipline

Every significant decision is recorded as a numbered ADR in `DECISIONS.md`. The discipline is non-negotiable:

- **New decisions get an ADR before the code changes.** If the change is substantive, the ADR comes first and references the PR that implements it.
- **Existing ADRs are never edited.** They are historical record. If a decision needs to change, add a new ADR explicitly superseding the old one (ADR-017 supersedes ADR-014's closing note; ADR-022 corrects an implementation gap in ADR-016 without editing it; ADR-023 closes a question deferred in ADR-019).
- **Documents reference ADRs by number.** "Per ADR-014, the canonical container is `Policy`" is preferred to a prose explanation that drifts.

If a request would push Tessera toward becoming a runtime engine, a standards submission, a Databricks product, or any other direction ADR-001 or ADR-002 rules out, surface the conflict to the project lead (Brice) rather than silently broadening scope.

## Descriptive, not prescriptive (ADR-027)

Tessera's authoring guidance and capability profiles are **descriptive**, not prescriptive. The framework's job is to represent any well-defined policy intent faithfully; it does not prescribe an authoring preference Tessera invents.

In practice:

- **Authoring guidance describes what each selector represents and what each platform documents.** "Snowflake recommends `IS_ROLE_IN_SESSION` for role-discrimination scenarios" with a citation: yes. "Tessera recommends `byDataset` for non-trivial Snowflake policies" without a platform-side source: no.
- **Cite-and-surface, do not invent.** Where a platform's docs make a recommendation, cite it. Where they don't, describe what each shape represents without synthesizing a cross-platform recommendation Tessera has no authoritative basis to make.
- **Capability profiles describe emission and platform behavior.** They do not editorialize about authoring preferences.
- **Where the IR cannot represent a definable intent, file an issue or propose an ADR.** The framework grows by adding representational range, not by adding prescription. Issue [#14](https://github.com/bgiesbrecht/tessera/issues/14) (Intent A primary-role-only semantics) is the canonical example of this discipline.

If a PR introduces "Tessera recommends X" framing into authoring guidance, expect it to be redirected to either (a) a citation of the platform's own recommendation, (b) a descriptive statement of what the shape represents, or (c) an issue tracking an IR-extension candidate. See ADR-027 for the full reasoning and the empirical history (two correction passes — 2026-05-19 secondary-roles reframe, 2026-05-20 Snowflake-guidance reframe — that motivated recording the principle).

## Extending the IR

The v0 immutability bar is suspended (ADR-017) until external dependency exists. v0 admits additions today; once external consumers ship, v0 freezes and changes go to v1.

**Adding a new IR concept** involves:

1. **An ADR proposing the addition.** Reference existing ADRs it relates to. Explain *why* the IR's current shape is insufficient — usually with an example from a worked exercise.
2. **A worked example exercising the concept.** Phase 1 inputs brief in `docs/exercises/`; Phase 2 artifacts in `spec/v0/examples/`; Phase 3 diagnostic in the same directory. The exercise is the empirical grounding for the concept; "exercises drive design, not speculation" is the project's discipline.
3. **Updates to four files**:
   - `spec/v0/ontology.ttl` — the OWL/Turtle definition.
   - `spec/v0/context.jsonld` — JSON-LD short names.
   - `spec/v0/schema.json` — JSON Schema 2020-12 structural validation.
   - `spec/v0/shapes.ttl` — SHACL semantic shapes (if the addition has IRI-resolution or closed-vocabulary semantics).
4. **Updates to the technical design** (`docs/technical-design-v0.2.md`) — typically a new subsection.
5. **A re-validation pass** — every existing JSON-LD example in `spec/v0/examples/` must still validate against the updated schema and shapes.

The 2026-05-19 Stage 4 changes (ADRs 018–021 implementations) are a clean reference for what "extending v0" looks like end to end.

## Writing a new adapter

The adapter contract (`adapters/contract/`) is the reference. Inherit `Adapter`, declare a `CapabilityProfile`, implement `emit`. The other three methods (`discover`, `extract`, `reconcile`) have stub defaults — implement them as your platform supports.

### Minimum viable adapter

```python
from adapters.contract.adapter import Adapter
from adapters.contract.types import (
    AdapterConfig, CapabilityProfile, EmissionResult,
    Capability, CapabilitySupport,
    Diagnostic, DiagnosticSeverity,
)


MY_PLATFORM_PROFILE = CapabilityProfile(
    adapter_name="my-platform",
    platform="MyPlatform",
    entries={
        Capability.ROW_VISIBILITY: (
            CapabilitySupport.PARTIAL,
            "Emitted via … . Subject to <gotcha>. See <reference>.",
        ),
        # … other capabilities the platform supports …
    },
)


class MyPlatformAdapter(Adapter):
    name = "my-platform"
    platform = "MyPlatform"

    def __init__(self, config: AdapterConfig | None = None, connection=None):
        super().__init__(config or AdapterConfig(), connection)

    @property
    def capability_profile(self) -> CapabilityProfile:
        return MY_PLATFORM_PROFILE

    def emit(self, policy: dict) -> EmissionResult:
        # Dispatch on policy.policyKind
        # Resolve identity_bindings, resource_bindings, tag_taxonomy via self.config
        # Return platform-native statements + diagnostics
        ...
```

### Design rules every adapter must follow

- **Never execute.** Return DDL/SQL strings in `result.statements`. The caller composes execution.
- **Always return structured diagnostics.** Empty list is fine; raw exceptions are not. Use `DiagnosticSeverity.ERROR` for blocking issues, `WARNING` for known-incomplete output, `INFO` for advisory.
- **Use `AdapterConfig.bind_principal` and `bind_resource`** for IR → platform translation. Don't embed platform-specific bindings in the adapter code.
- **Declare every capability gap as `PARTIAL` or `UNSUPPORTED`** in the profile, with a non-empty rationale string. The profile is the project's running record of platform-specific concerns.
- **Use parallel diagnostic codes** with existing adapters where the concern is parallel (`UNIMPLEMENTED_POLICY_KIND`, `UNSUPPORTED_PRINCIPAL_SELECTOR`, `UNBOUND_PRINCIPAL`). Diverge codes only where the platform's concern is genuinely different.
- **Row-filter and column-mask UDF parameters must use a fixed alias** that does not collide with any column name referenced in the function body. SQL is case-insensitive on identifiers; Snowflake folds to uppercase; Databricks is mixed-case. Naming the function parameter after a column it binds to creates an ambiguous identifier when the column is also referenced inside the body — the engine resolves the bare identifier to the column, the predicate degenerates to `col = col` (always TRUE), and the policy silently passes everything. Pin a fixed alias: `POLICY_INPUT_VALUE` for uppercase platforms, `policy_input_value` for lowercase. The actual column-to-parameter bind happens positionally via `ALTER TABLE ... ON (col)`. This pattern has bitten three emission paths during development (Snowflake byDataset row, Snowflake column mask, UC byDataset row); the convention is the project's way of preventing a fourth.

### When to add a new `Capability` enum value

The `Capability` enum (`adapters/contract/types.py`) is closed. Adding a value is a contract change. The bar:

- The concept exists in the IR (in the ontology, schema, or technical design).
- At least one existing adapter has a meaningful stance on it (supports, partially supports, refuses).
- The concept is general enough that a future third adapter will need to declare a stance.

If only one adapter cares about a concept, it's a per-adapter rationale, not a capability. Use the rationale text or the `extras` dict.

## Parity testing

`adapters/tests/test_parity.py` is the contract's regression fixture. The test asserts that the same IR produces meaningfully different, platform-correct outputs through both implemented adapters. When you add an emission path on one adapter, add the parity assertion that the other adapter either also implements it (and produces different DDL) or declares it `UNSUPPORTED` in its profile and emits a corresponding diagnostic.

The live-runner pattern (`adapters/tests/live_*.py`) is the empirical-grounding counterpart. Each live runner: emits via the adapter, executes against a real platform, verifies behavioral outcomes against the policy intent. Live runners are not regression tests in the unit-test sense; they are documentation-quality validations that the IR + adapter actually enforce the intended policy.

## Worked-example methodology

The project's design discipline is "exercises drive design, not speculation." Every substantive design choice traces back to a worked exercise that surfaced the question.

The exercise template is in `docs/worked-example-exercise.md`. The phases:

1. **Phase 1 — Inputs brief.** Customer-language policy intent. No platform vocabulary, no IR vocabulary. Lives in `docs/exercises/<exercise-name>-inputs.md`.
2. **Phase 2 — Tessera derivation.** Author the IR (YAML + JSON-LD). If a customer implementation exists, **do not look at it during Phase 2** (blind-derivation discipline). Land artifacts in `spec/v0/examples/<exercise-name>-*`.
3. **Phase 3 — Verification.** Live execution against the platform. If a customer implementation exists, compare. Otherwise, document findings against the brief's success criteria. Land in `<exercise-name>.diagnostic.md` (no comparison impl) or `<exercise-name>.comparison.md` (with comparison).

The seven completed exercises in `spec/v0/examples/` are the corpus. Read them when proposing IR changes — your proposal should cite the exercise(s) that surface the need.

## Validation pipeline

Three layers, all maintained together:

| Layer | File | What it catches |
|---|---|---|
| 1. JSON Schema | `spec/v0/schema.json` | Structural validity, required fields per kind, conditional dependencies, enum closure |
| 2. SHACL | `spec/v0/shapes.ttl` | Semantic well-formedness: IRI resolution, closed vocabulary checks, node-shape composition |
| 3. Adapter emission | `adapters/*/emission.py` | Platform-specific constraints, capability gaps, configuration completeness |

A change that affects any layer must update the others if the contract between layers shifts. The current split:
- JSON Schema is the structural-validation contract; SHACL adds semantics it cannot express.
- Conditional dependencies are JSON-Schema-enforced (baselineGroup ↔ defaultStrategy, transformation ↔ effect, selector-kind → required-fields, transformation-type → required-params). SHACL deliberately defers these; see `spec/v0/shapes.ttl` comments.
- Adapter emission is the platform-specific validation layer. It runs after the first two pass.

## Where to file issues

GitHub issues at `https://github.com/bgiesbrecht/tessera/issues`. Twelve open / closed issues today, all from worked-exercise findings. The issue body should include:

- A short title (one-line summary of the gap or proposed addition).
- The exercise that surfaced it (link to the diagnostic that flags the finding).
- Whether it's a v0 candidate (small structural addition during the suspended-immutability window) or a v1 candidate (deferred until v0 freezes).
- Proposed disposition: ADR draft, schema change, technical-design update, etc.

## When to open a PR vs. propose an ADR first

- **PR without prior ADR:** bug fixes, capability-profile additions, diagnostic-code additions, adapter emission gap-filling, test additions, documentation refinements. Anything that doesn't change a contract.
- **ADR before code:** new IR concepts, new selector kinds, new `Capability` enum values, new transformation types, new condition operators, anything that changes the adapter contract surface, anything that supersedes an existing decision.

When in doubt: write a short ADR draft first. The discipline is cheap; silent contract drift is expensive.

## Project lead

Brice Giesbrecht (`bgiesbrecht`). Mediates the design / implementation split, holds the skunkworks posture (ADR-002), and arbitrates the UC-source-of-truth concession. When the boundary between "extension" and "scope creep" is unclear, surface it to him before merging.
