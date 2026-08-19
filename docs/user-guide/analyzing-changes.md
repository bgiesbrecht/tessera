# Analyzing policy changes

This page is for anyone editing a corpus of Tessera policies who wants to know *what a change does* before deploying it: an operator reviewing a pull request, an author revising a policy, or a CI pipeline gating merges. It assumes you understand the IR vocabulary at the level of [`authoring.md`](./authoring.md).

The change-impact tool answers one question: **given the policies you have and a change you're proposing, how does the change alter what the corpus decides about data?** It reads your policies and reasons about them symbolically. It does not connect to any platform, run any query, or resolve who is in which group; that would be policy *evaluation*, which Tessera does not do (ADR-001). Everything it reports follows from the policy text alone.

## Two modes

**Change-impact (`tessera impact`)** diffs two versions of the corpus and reports what changed. This is the pull-request / pre-deploy question: "what does this edit do?"

**Standing lint (`tessera lint`)** audits a single corpus state for latent problems (dead rules, conflicting policies) regardless of when they were introduced. This is the health-check question: "is my corpus in good shape right now?"

Both are read-only and advisory. Neither blocks anything on its own; the exit code is zero whether or not findings are present (unless you opt into CI gating — see below).

## The corpus is git-tracked by default

A "corpus" is the set of policy files the tool considers together. By default that is **the policies git tracks**: committed policies are the real corpus; uncommitted drafts are excluded until you stage them. This reuses the version boundary you already work with, so the common invocation needs no arguments:

```bash
# What does my working-tree edit do to the tracked policies?
tessera impact

# Is the tracked corpus healthy right now?
tessera lint
```

`tessera impact` with no arguments compares `HEAD` against your working tree. To compare two explicit commits:

```bash
tessera impact --git main HEAD
```

The sentinel `WORKING` means the working tree, so `--git HEAD WORKING` is the explicit form of the default.

Two overrides exist when git-tracked isn't what you want:

```bash
# Treat every policy file under a directory as the corpus, ignoring git:
tessera impact --corpus path/to/policies
tessera lint   --corpus path/to/policies

# Compare two hand-picked file sets, bypassing git entirely:
tessera impact --baseline old/*.jsonld --proposed new/*.jsonld
```

Both `.tessera.yaml` and `.jsonld` are accepted; YAML is converted first. When a directory holds both forms of the same policy (e.g. a source `.tessera.yaml` and its generated `.jsonld`), the canonical `.jsonld` wins.

## Reading a report

A finding looks like this:

```
[C6]  NARROW  selector group:acme_high_priority_ops   PROVEN
     Removed a keep-matching-rows rule (kept ['1-URGENT', '2-HIGH']). Net exposure
     for the affected selector is strictly reduced.
     grounding: §4.3 effect polarity
```

Each finding carries:

- **A check code** (`C6`, `C1`, …): which analysis produced it (see the table below).
- **A polarity**, where the check computes one: `WIDEN` / `NARROW` / `INVERT` / `NEUTRAL` (whether the change exposes more, less, flips, or provably nothing).
- **A selector-relative subject.** Findings are always phrased about a *selector expression* ("principals matching `group:X`", "scope `catalog:acme`"), never about resolved identities.
- **A confidence tier:** `PROVEN` or `CANDIDATE` (see next section).
- **A grounding:** the ADR or rule the finding rests on.

Findings are ordered PROVEN before CANDIDATE, then by check. Use `--format md` for a Markdown table (handy in PR comments) or `--format json` for machine-readable output.

## PROVEN vs CANDIDATE — what the tool can and can't know

The two tiers mark what the tool can prove against what it can only flag. A **PROVEN** finding follows from the policy text and the ontology alone: scope-IRI containment (`catalog:acme` contains `table:acme.tpch.orders`), value-set arithmetic, or attribute subsumption declared in the ontology (`PII` subsumes `PHI`). You can rely on it.

A **CANDIDATE** finding is a real possibility the tool cannot confirm without information it deliberately does not read. The classic case: a policy that masks "PII columns in `catalog:acme`" *may* conflict with one masking the specific column `o_clerk`, but only if `o_clerk` actually carries the PII tag, which is a platform-tagging fact, not a policy fact. The tool flags it and names the unknown rather than guessing:

```
[L2]  policy:clerk-redact ∩ policy:pii-hash   CANDIDATE
     ... may overlap, with divergent effects — the platform
     'single-column-mask-per-column' constraint. ...
     unknown: whether resource 'column:acme.tpch.orders.o_clerk' carries
     attribute(s) [sensitivity:PII] is a platform-tagging fact not visible to
     static analysis
```

Where the corpus uses data-driven selectors (`byDataset` / ACL tables), the tool is weakest by design: it cannot read the ACL rows, so findings that would depend on them are CANDIDATE, exactly the situation (the custom-ACL customer) where the policy carries the most.

## The checks

| Check | Reports | Grounding |
|---|---|---|
| **C6** | Exposure change per edit: WIDEN / NARROW / INVERT / NEUTRAL | effect polarity + value-set arithmetic |
| **C1** | A selector that lost its last governing rule; where its principals now fall through | ADR-013 (`defaultStrategy` intent) |
| **C2** | Changes to the fallback itself — `defaultStrategy`, `baselineGroup`, `defaultBranch` | ADR-013 / ADR-014 |
| **C3** | A rule newly *shadowed* (dead code) or newly *un-shadowed* (dormant policy activated) under ordered first-match | ADR-015 |
| **C4** | A cross-policy overlap the change introduces or resolves (two masks on the same target) | ADR-023 |
| **C5** | A reference left dangling by the change (baseline group with no rule, operand outside scope, unknown axis) | structural / ADR-018 |

`tessera impact` runs C1–C6. `tessera lint` runs the standing checks:

| Lint | Reports | Grounding |
|---|---|---|
| **L1** | Every provably-dead (unreachable) rule in the corpus, and the earlier rule that shadows it | ADR-015 |
| **L2** | Every cross-policy overlap currently in the corpus (the ADR-023 MULTIPLE_MASKS situation) | ADR-023 |

Worked, runnable demonstrations of both live in [`docs/exercises/dead-rule-lint-demo.md`](../exercises/dead-rule-lint-demo.md) (C3/L1) and [`docs/exercises/cross-policy-overlap-demo.md`](../exercises/cross-policy-overlap-demo.md) (C4/L2).

## Using it in CI

Because the exit code is zero regardless of findings, the tool never blocks by accident. To gate a pipeline, opt in with `--exit-on`, which makes `tessera impact` exit nonzero if any finding has a given polarity:

```bash
# Fail the build if a change inverts any policy's effect without review:
tessera impact --git origin/main HEAD --exit-on INVERT
```

Keep this opt-in and narrow. `--exit-on WIDEN` on every PR will be noisy: widening exposure is often exactly the intended change. INVERT (an effect flipping polarity) is the one to gate on. For a softer integration, run without `--exit-on` and post the `--format md` output as a PR comment for a human to read.

## What it will not tell you

Stated plainly, because the boundaries are deliberate:

- **How many actual users or rows are affected.** That needs group membership and row evaluation: a runtime engine (ADR-001). The tool reports coverage change *per selector*, not *per identity*.
- **Whether a change is good.** It reports the consequence and leaves the judgment to you. A WIDEN may be the whole point of the change.
- **Anything gated behind data it doesn't read**, such as ACL-table contents or whether a concrete column carries a tag. Those surface as CANDIDATE with the unknown named, never as a confident claim.

For the full design rationale (the reasoning kernel, the ADR-001 line, and why each check is shaped the way it is), see the scoping document, [`docs/v1-candidates/change-impact-analysis.md`](../v1-candidates/change-impact-analysis.md).
