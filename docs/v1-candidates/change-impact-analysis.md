# Change-Impact Analysis — Scoping Document

**Status:** Design document. Lands in v0 per ADR-017 (immutability bar suspended until external dependency). This document scopes a new *tool* (`tessera diff` / change-impact report), not a spec change; it may nonetheless motivate small, additive vocabulary clarifications, which will be filed as their own ADRs if they arise.
**Companion ADRs:** ADR-001 (no runtime engine — the load-bearing scope line for this tool), ADR-013 (default-handling intent), ADR-014 (Policy container), ADR-015 (ordered first-match), ADR-016 (transformation parameterization), ADR-018 (attribute axes / hierarchical-vs-flat), ADR-023 (cross-policy γ-with-refinement).
**Filed under `docs/v1-candidates/`** by the historical convention noted in `abac-and-attribute-axes.md`; the directory name predates ADR-017 and is retained to avoid churn.

---

## §1. What this tool answers

Given a **corpus of Tessera policies** and a **proposed change** to it (an edit, an added policy, a removed rule), the change-impact tool reports *how the change alters what the corpus decides about data* — before the change is authored into JSON-LD, validated, or emitted to any platform.

The governance author's real pre-implementation question is not "is my edited document still well-formed?" (the JSON Schema and SHACL layers answer that) but:

> "If I remove this rule / change this condition / add this policy, **what coverage do I gain or lose, and where does it now overlap or conflict** with the rest of my policies?"

This tool answers that question. It is a *reading* of the policy corpus, not an execution of it.

### The value proposition, stated plainly

Tessera already lets an organization express policy meaning once and translate it to many platforms. Change-impact analysis adds a second form of leverage on the *same* semantic IR: because the IR carries intent (`defaultStrategy`), ordering semantics (ADR-015 first-match), and a typed attribute lattice (ADR-018), a change to a policy can be *reasoned about symbolically* in a way that raw platform DDL cannot. A `SET ROW FILTER` statement on Databricks and an `ADD ROW ACCESS POLICY` on Snowflake tell you nothing about each other; two Tessera policies do. Change-impact analysis is a capability the semantic layer *uniquely* enables.

---

## §2. The principle: reason about selectors, not populations

This tool lives or dies on one distinction, and it is exactly the ADR-001 scope line drawn precisely.

There are two things one could call "policy gap analysis":

- **Reasoning about the populations that selectors denote.** "Who is actually in `group:acme_high_priority_ops`, and which concrete rows do they lose if I delete this rule?" Answering this requires resolving group membership and evaluating conditions against data. This is **policy evaluation** — a runtime engine — and ADR-001 disclaims it. Tessera does not do this, and this tool does not do this.

- **Reasoning about the selector expressions themselves.** "The selector `group:acme_high_priority_ops` was referenced by exactly one rule, and this edit removed that rule; under the policy's declared `defaultStrategy`, principals matching that selector now depend on the baseline net." This is **set arithmetic over the literals, IRIs, and typed values that appear in the policy documents.** It is fully decidable from the corpus alone, without any knowledge of who or what those selectors match.

**The entire tool lives in the second world.** Every finding it emits is phrased *relative to a selector expression* — "principals matching selector S…" — never relative to a resolved identity or a row. This is not a limitation to apologize for; it is the design invariant that keeps the tool sound, honest, and on the correct side of ADR-001.

### The bright line, operationally

- **Permitted:** comparing two selector expressions for equality, IRI-structural containment, condition value-set containment, and ontology-provable attribute subsumption.
- **Forbidden:** materializing the members of a group, reading the rows of an ACL table, or otherwise computing *which concrete principals or rows* a selector resolves to.

The moment subsumption reasoning starts enumerating "which principals match," it has become an evaluator. Holding the tool to lattice-provable relations (§4) is what keeps it static. Consequences of holding this line honestly are catalogued in §7 ("What the tool will not tell you").

---

## §3. Inputs and outputs

### Input

- **A baseline corpus** — a set of Tessera policy documents (YAML or JSON-LD; the converter normalizes YAML to JSON-LD first, per the Priority-5 tool).
- **A proposed corpus** — the same set with the author's change applied. In the common case this is a git working-tree diff. The corpus is the git-tracked policy set by default (see §9.1); the CLI shape is:

  ```
  python -m tools.impact [--git <base-ref> <prop-ref>] [--corpus <dir>] [--format text|md|json]
  ```

  with refs defaulting to `HEAD` → working tree (`WORKING`), matching how a governance author actually works (editing `.tessera.yaml` files in a repo). The bare `python -m tools.impact` compares the git-tracked corpus at HEAD against the working tree. `--corpus <dir>` overrides discovery to a filesystem directory (option A); `--baseline`/`--proposed` take two explicit file sets, bypassing git entirely.

### Output

A **change-impact report**: an ordered list of findings, each carrying

- a **check code** (C1–C6, §5),
- a **selector-relative subject** ("selector `group:X`", "scope `catalog:acme`"),
- a **polarity** where applicable (WIDEN / NARROW / INVERT / NEUTRAL exposure),
- a **confidence tier** — `PROVEN` (follows from lattice relations §4) or `CANDIDATE` (depends on membership/contents the tool cannot see),
- a **grounding reference** (the ADR or structural invariant the finding rests on),
- and a plain-language consequence statement that *flags* rather than *decides*.

The report is advisory. It never blocks; it never asserts a judgment ("this change is bad"); it reports the coverage-semantic consequence and leaves the call to the author. This matches the project's "honesty over completeness" voice: it says what it can prove, labels what it cannot see, and does not oversell.

---

## §4. The reasoning kernel

Four primitives. Each is either decidable from the corpus or explicitly marked unknown. This is the only "smart" part of the tool; the checks in §5 are thin compositions over it.

### 4.1 Selector normalization

Canonicalize each principal and resource selector to a comparable normal form: resolve CURIE prefixes to full IRIs, sort condition operands, canonicalize value sets. Two selectors are *syntactically equal* iff their normal forms match. This handles the common "did this rule's selector change at all?" question directly.

### 4.2 The subsumption lattice

The **only** relations the tool asserts as `PROVEN`:

1. **Identity equality** — `group:X` = `group:X`, `table:a.b.c` = `table:a.b.c`. Trivial but foundational.

2. **Scope-IRI containment** — decidable from IRI structure alone:
   `catalog:acme` ⊇ `schema:acme.tpch` ⊇ `table:acme.tpch.orders` ⊇ `column:acme.tpch.orders.o_clerk`.
   A dotted-path prefix relation. This is what lets the tool reason about `byScope` attachment (ADR-019) overlap without knowing which columns actually carry which tags.

3. **Condition value-set containment** — on a *shared condition column with a shared operator*:
   `in [1-URGENT, 2-HIGH, 3-MEDIUM]` ⊇ `in [1-URGENT]`.
   Straight set containment over literal operand values. Applies to `in`/`eq`; range operators (`lt`/`gt`/`time-window`) use interval containment. Operators the tool cannot compare (e.g. `exists-in-dataset`, which reaches into an ACL table) are treated as opaque and force `CANDIDATE`.

4. **Attribute-axis subsumption via the ontology** — the OWL leverage, and the one place the vocabulary does real inferential work:
   `sensitivity: PII` ⊇ `sensitivity: PIIClerk`, because the *hierarchical* sensitivity axis (ADR-018) declares `PIIClerk ⊂ PII` in `ontology.ttl`.
   **Only hierarchical axes participate.** Flat axes (`dataSubject`, `regulatoryRegime`, `businessDomain`) admit only equality — `regulatoryRegime: GDPR` neither subsumes nor is subsumed by `regulatoryRegime: HIPAA`, exactly as the ABAC scoping document specifies. The tool reads `axisType` from the ontology to decide which regime applies.

Everything provable is provable by composing these four. Nothing else is asserted as fact.

### 4.3 Effect polarity

Classify each rule's effect on an *exposure* axis:

| Effect | Polarity |
|---|---|
| `allow`, `keep-matching-rows` | **expose** |
| `deny`, `drop-matching-rows` | **restrict** |
| `transform` | **partial-restrict** (exposes the row/column but obscures the value) |

Polarity + value-set arithmetic (4.2 #3) is what powers the WIDEN/NARROW classification in check C6.

### 4.4 The unknown boundary

The tool maintains an explicit set of things it *cannot* know and must therefore never claim:

- **Group membership and inter-group subset relations.** Whether `group:acme_high_priority_ops` ⊆ `group:account-users` is unknown; both are opaque identity selectors. Overlap between them is a `CANDIDATE`, never a `PROVEN` finding.
- **`byDataset` / `PrincipalSetFromTable` / `ResourceSetFromTable` contents.** The ACL-table customer's effective policy lives in table rows the tool cannot (and by §2 must not) read. Any finding that would depend on those contents degrades to `CANDIDATE`.
- **`byAttribute` selectors backed by data the adapter tags at runtime.** Whether a given column actually carries `sensitivity: PIIClerk` is a platform-tagging fact, not a policy fact.

The soundness discipline is absolute: **if a finding requires anything in 4.4, it is emitted as `CANDIDATE` with the specific unknown named.** The tool never launders a candidate into a claim.

---

## §5. The check catalog

Six checks, each a thin composition over §4. Ordered roughly by how directly they answer "what did my change do."

### C1 — Fall-through coverage

**Detects:** a principal (or resource) selector that loses its last governing rule, so principals matching it change coverage class.

**Mechanism:** for each selector referenced in the baseline, count governing rules before and after. If a selector drops to zero rules, read the policy's `defaultStrategy`:
- `none` → those principals are now uncovered (fail-closed terminal, no rows / full restriction).
- `explicit-baseline-group` → they now receive only whatever the `baselineGroup` rule grants — *if* they are baseline members (a `CANDIDATE` qualifier, since membership is unknown).
- `negated-complement` → they now fall to the `defaultBranch` effect.

**Grounding:** `defaultStrategy` is a *declared, readable* property (ADR-013). No evaluation is needed to read declared intent. **Confidence:** `PROVEN` that coverage dropped to zero for the selector; `CANDIDATE` for the downstream membership overlap.

### C2 — Default-net removal or weakening

**Detects:** changes to the fallback itself — `defaultStrategy` moving away from `explicit-baseline-group`/`negated-complement` toward `none`; deletion of the baseline rule or `defaultBranch`; a `baselineGroup` value change.

**Mechanism:** direct comparison of the policy-level default-handling fields plus the presence of their required companion (ADR-013/ADR-014 invariants: `baselineGroup` required under `explicit-baseline-group`; `defaultBranch` required under `negated-complement`).

**Grounding:** ADR-013, ADR-014. **Confidence:** `PROVEN` — these are structural policy properties.

### C3 — Reachability / shadowing

**Detects:** a rule that can never fire under ordered first-match (ADR-015) because an earlier rule's selector *and* condition both subsume it. Also its inverse: a change that *un-shadows* a previously dead rule (silently activating dormant policy).

**Mechanism:** for each ordered pair (earlier, later) of rules in a Policy, test whether earlier.selector ⊇ later.selector (4.2) **and** earlier.condition ⊇ later.condition (or earlier is unconditional). If both hold, the later rule is unreachable.

**Grounding:** ADR-015 ordered first-match + lattice §4.2. **Confidence:** `PROVEN` when both subsumptions are provable; not emitted otherwise (shadowing that depends on group-subset relations is unknowable and deliberately *not* guessed).

**Note — the closest check to the ADR-001 line.** C3 reasons about selector *expressions* subsuming one another, never about which principals populate them. This is the boundary to guard most carefully in implementation: subsumption over expressions is static; subsumption computed by enumerating matched principals is evaluation.

### C4 — Cross-policy overlap / conflict

**Detects:** two policies whose attachment scopes overlap (4.2 #2) *and* whose attribute-matches overlap (4.2 #4) but whose effects differ — the `MULTIPLE_MASKS` situation that drove ADR-023.

**Mechanism:** pairwise over the corpus, compute scope-IRI containment and attribute-match subsumption; where both intersect and effects diverge (e.g. one `allow`, one `transform` with different transformations), flag the overlap and point at the ADR-023 γ-with-refinement resolution.

**Grounding:** ADR-023. **Confidence:** `PROVEN` when both sides are attribute predicates (byScope) whose scopes and axis-values provably intersect, or both are concrete resources; the *behavioral* resolution (which policy "wins") is reported as the ADR-023 rule, not computed against data. `CANDIDATE` when one side is an attribute predicate and the other a concrete resource — proving the overlap would require knowing whether that resource carries the attribute tag, which is a platform-tagging fact outside static analysis (§4.4). (Refinement discovered running L2 against the committed corpus: the two ABAC clerk masks are a PROVEN overlap, but a predicate vs. the concrete `o_clerk` column is correctly CANDIDATE.)

### C5 — Dangling reference

**Detects:** references left dangling by the change — a `baselineGroup` naming a group no rule targets; a condition operand column outside the (possibly narrowed) `appliesTo` scope; a `tableRef` to a dataset removed elsewhere in the change; an attribute axis/value not declared in the ontology.

**Mechanism:** referential-integrity sweep across the *proposed* corpus, seeded by what the change touched.

**Grounding:** structural + ontology membership. **Confidence:** `PROVEN`.

### C6 — Exposure polarity (the headline check)

**Detects and classifies** every change by its net effect on exposure:

- **WIDEN** — the change exposes strictly more (a value added to a `keep-matching-rows`/`allow` condition set; a `transform` relaxed to `allow`; a restrict rule removed).
- **NARROW** — the change exposes strictly less (the mirror cases).
- **INVERT** — an effect flips polarity (`allow` → `deny`, or a transform swapped for a pass-through).
- **NEUTRAL** — provably no exposure change (e.g. a description edit, a reordering that C3 proves does not change match outcomes).

**Mechanism:** effect polarity (4.3) combined with value-set arithmetic (4.2 #3) on any changed condition, scoped to the affected selector.

**Grounding:** polarity + lattice. **Confidence:** `PROVEN` when the change is a pure widen/narrow on a comparable condition; `CANDIDATE` when it interacts with an opaque operator or an unknown membership.

**Why C6 leads.** It answers the author's question in one word — *did this expand or restrict what's exposed?* — and it is nearly free given the kernel. It is the most legible output and the strongest demo of what the semantic layer buys.

---

## §6. Worked exercises

These mirror the blind-derivation discipline of the existing worked examples: each takes a committed corpus artifact, applies a concrete change, and states the expected report. They double as the tool's acceptance tests.

### Exercise 1 — Remove Rule A2 from `group-row-visibility-policy-a`

Baseline: the committed three-rule policy (all-priority-ops sees all; high-priority-ops sees `1-URGENT`/`2-HIGH`; baseline `account users` sees the lower priorities). Change: delete Rule A2.

Expected report:

```
CHANGE-IMPACT REPORT  policy:group-row-visibility-policy-a  (v1.0.0 → draft)

[C1] COVERAGE   selector group:acme_high_priority_ops              PROVEN + CANDIDATE
     Lost its only governing rule. defaultStrategy = explicit-baseline-group.
     PROVEN:    coverage via this selector dropped to zero rules.
     CANDIDATE: principals matching it now see rows only if also members of
                the baseline group `account users` (membership not visible to
                static analysis).
     Grounding: ADR-013 (declared default-handling intent).

[C6] POLARITY   NARROW                                             PROVEN
     Removed a keep-matching-rows branch. Net exposure for the affected
     selector is strictly reduced: rows {1-URGENT, 2-HIGH} are no longer
     kept via this rule.

[C5] REFERENCE  clean                                             PROVEN
     Rule A2 introduced no identifiers referenced elsewhere.
```

Contrast case (same policy, different change): *adding* `3-MEDIUM` to A2's value set yields a single `[C6] WIDEN` finding — "condition value-set gained `3-MEDIUM` on a keep-matching-rows rule → exposure increased for `group:acme_high_priority_ops`."

### Exercise 2 — Add an overlapping catalog-scoped mask alongside `abac-column-mask-policy-a`

Baseline corpus: `abac-column-mask-policy-a` (catalog-scoped, matches `sensitivity: PIIClerk`, redacts for non-`acme_all_priority_ops`). Change: add a new policy, catalog-scoped, matching `sensitivity: PII`, hashing for a different principal set.

Expected headline: `[C4] OVERLAP  scope catalog:acme ∩ catalog:acme; sensitivity PII ⊇ PIIClerk  PROVEN`. Because `PII` subsumes `PIIClerk` on the hierarchical axis (4.2 #4), the two masks provably co-apply to the `PIIClerk` columns with divergent transformations (Redact vs Hash). The report points at ADR-023 γ-with-refinement as the resolution rule and flags the divergence for author review — it does *not* decide which mask wins at runtime.

### Exercise 3 — Weaken the Snowflake `byDataset` policy's default

Baseline: `snowflake-byDataset-row-visibility` with `defaultStrategy: none` (fail-closed). Change: switch to `explicit-baseline-group` with some baseline group.

Expected: `[C2] DEFAULT-NET  none → explicit-baseline-group  PROVEN` — "fail-closed terminal replaced by a baseline grant; principals previously seeing no rows now inherit baseline visibility." Plus a `CANDIDATE` qualifier that the *magnitude* depends on ACL-table contents the tool does not read — the honest limit for exactly the customer the design most cares about.

---

## §7. What the tool will not tell you (and says so)

Stated up front, in the report's own footer where relevant, per the honesty-over-completeness value:

- **How many actual users or rows are affected.** That needs membership resolution and row evaluation — a runtime engine (ADR-001). The tool reports coverage change *per selector*, not *per identity*.
- **Whether a given fall-through is acceptable.** It reports the coverage delta and the declared strategy; the judgment stays with the author.
- **Anything gated behind a `byDataset`/ACL-table selector's contents.** The ACL-table customer's effective policy lives in rows the tool cannot read. Findings there are always `CANDIDATE`. This is worth stating plainly: static analysis is *weakest* exactly where that flagship customer's policy is *richest*. The tool is honest about this rather than papering over it.
- **Cross-group subset relations.** Whether one group contains another is invisible; overlaps between distinct identity selectors are always `CANDIDATE`.

These omissions are not bugs to be closed later by loosening §2 — loosening §2 *is* building a runtime engine. They are the permanent shape of a sound static tool.

---

## §8. Where it lives, and staging

This is a distinct tool from the validation linter (Priority 5 in the handoff). The linter answers "is this one document valid?"; the impact tool answers "what did this change do to the corpus?" They share the JSON-LD-normalization front end and the ontology loader, and both are read-only over the corpus. Proposed home: `tools/impact/` alongside `tools/converter/` and `tools/linter/`.

Suggested staging (each stage independently useful and testable):

- **Stage 1 — kernel + C5/C6. _(shipped)_** Selector normalization, the lattice, polarity, referential-integrity. Ships the headline WIDEN/NARROW/INVERT/NEUTRAL classification and dangling-reference detection. This alone is a compelling demo and validates the kernel against Exercise 1's contrast case.
- **Stage 2 — C1/C2. _(shipped)_** Coverage and default-net analysis. Adds the `defaultStrategy`-aware fall-through reporting. Validates against Exercises 1 and 3.
- **Stage 3 — C3 + L1. _(shipped)_** Reachability/shadowing. The check nearest the ADR-001 line, with the guard from §5-C3 explicit in code and tests: opaque selectors never subsume, so membership-dependent shadowing is never claimed. C3 (change-impact) reports both newly-shadowed (dead code) and newly-un-shadowed (dormant policy activated) rules. **L1** is the standing whole-corpus counterpart — a `--lint` mode that reports every provably-dead rule in a single corpus state, regardless of when it went dead, sharing C3's mechanism and guard. A worked timeline demo (`docs/exercises/dead-rule-lint-demo.md`, generated) contrasts the two.
- **Stage 4 — C4 + L2. _(shipped)_** Cross-policy overlap. Same-policyKind pairs whose scopes and attribute-matches provably overlap with divergent effects — the ADR-023 MULTIPLE_MASKS situation. C4 (change-impact) reports overlaps a change introduces or resolves; **L2** is the standing whole-corpus counterpart. The tool reports the overlap and the ADR-023 γ-with-refinement resolution path; it never picks a winner. Confidence discipline holds the ADR-001 line: two attribute predicates that provably co-apply are PROVEN, but a predicate vs. a concrete resource is CANDIDATE (proving it needs the platform-tagging fact). A worked demo (`docs/exercises/cross-policy-overlap-demo.md`, generated) shows both.

Each stage lands with its worked exercise as a regression test, matching how the spec work was validated by worked examples rather than by speculative design.

**Implementation status (2026-08-04).** All four stages are built in `tools/impact/` — kernel (`kernel.py`, ontology-grounded via rdflib), diff checks C1/C2/C3/C4/C5/C6 and standing lints L1 (dead rules) / L2 (cross-policy overlap) (`checks.py`), findings/report model, and a CLI (`__main__.py`) with a `--lint` single-corpus mode. Corpus discovery is git-tracked by default with a `--corpus DIR` filesystem override and an explicit `--baseline`/`--proposed` file mode (§9.1). Report output is deterministic (findings emitted in source/rule order). The §6 exercises run as acceptance tests, alongside kernel, reachability, overlap, lint, CLI, and demo-reproducibility tests (`tools/impact/tests/`, 68 tests). Two generated demos (`build_timeline_demo.py`, `build_overlap_demo.py`) are regression-tested for drift. Run with `./.venv/bin/python -m pytest tools/ -q`.

---

## §9. Open questions for the author

1. **Corpus boundary. _(resolved 2026-08-03 — git-tracked default, filesystem override)_** Is the corpus "every `.tessera.yaml` under a root" (filesystem discovery), an explicit manifest, or git-tracked policy files? Affects C4 (which policies are considered co-resident) and C5 (what counts as a dangling cross-reference). **Decision:** the corpus is the **git-tracked** policy set by default (option C) — it reuses the version boundary the author already works with (committed = the real corpus; uncommitted drafts excluded until staged) and needs no extra config file. A filesystem directory (`--corpus DIR`, option A) is the explicit override for unversioned/scratch policy sets. The default invocation compares `HEAD → WORKING` (working tree). An explicit manifest (option B) remains a possible future opt-in but is not required to use the tool. Implemented in `tools/impact/__main__.py`; tests in `tools/impact/tests/test_cli.py`.
2. **Report as gate vs. advisory.** This document assumes pure advisory (never blocks). If a CI use case wants "fail the build on any INVERT without an override," that is a thin policy layer *on top of* the report — but it should be opt-in and out of the tool's core, to preserve the advisory posture.
3. **Does C3/C4 warrant a vocabulary clarification?** If shadowing/overlap detection surfaces a recurring need to express "these two selectors are declared disjoint" (an author assertion the tool could then trust), that would be an additive vocabulary item and its own ADR. Not needed for Stages 1–2; flagged as a possible Stage-3/4 finding.
