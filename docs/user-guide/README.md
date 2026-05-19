# Tessera user guide

This guide is the entry point for working with Tessera. Read whichever audience-shaped page below fits what you need; the [tutorial](./tutorial.md) is a complete end-to-end walkthrough for first-time readers.

Tessera is a portable representation of data governance policy. It expresses *what* policies decide about data — in a vocabulary independent of any platform — and translates that meaning into native enforcement on Databricks, Snowflake, and other platforms via adapters. The value proposition is **semantic interoperability of policy**: agreeing once that "PII," "EU residency," "fraud-investigation purpose," "audit-log obligation" mean the same thing wherever they are enforced. For the architectural framing and what Tessera explicitly is *not*, read [`evaluating.md`](./evaluating.md) before going further.

## Choose your starting point

| Who you are | Read first | Then |
|---|---|---|
| **Policy author** — you write `.tessera.yaml` files describing what governance the organization needs | [Tutorial](./tutorial.md) → [Authoring](./authoring.md) | The capability profiles linked from `operating.md` to know what your target platforms can and can't express |
| **Operator / adopter** — you wire Tessera into a deployment pipeline (CI, configuration management, audit) | [Tutorial](./tutorial.md) → [Operating](./operating.md) | [Authoring](./authoring.md) for the vocabulary you'll be lowering |
| **Evaluator** — you're deciding whether Tessera fits | [Evaluating](./evaluating.md) | [Tutorial](./tutorial.md) for a concrete end-to-end |
| **Future contributor** — you're extending Tessera (new adapter, new IR concept) | [Contributing](./contributing.md) | `DECISIONS.md` (ADRs) and [Operating](./operating.md) |

## Pages

- [**Tutorial**](./tutorial.md) — write a policy, validate it, emit DDL through both adapters, deploy on Databricks and Snowflake, verify. Single narrative; ~30 minutes end to end.
- [**Authoring**](./authoring.md) — the policy vocabulary. Selectors, conditions, transformations, the Policy container, the recommended Snowflake authoring pattern.
- [**Operating**](./operating.md) — adapter configuration, identity / resource / tag bindings, capability profiles, deployment patterns per platform, the Snowflake `DEFAULT_SECONDARY_ROLES` caveat.
- [**Evaluating**](./evaluating.md) — scope, non-goals, honest limitations, posture.
- [**Contributing**](./contributing.md) — how to extend Tessera. Adapter contract, ADR discipline, validation pipeline.

## Conventions used in this guide

- **YAML is the authoring form**, JSON-LD is the canonical form (ADR-004). Examples in this guide show YAML unless the JSON-LD shape is what's being illustrated.
- **Identifiers**: `policy:foo` for policy IRIs, `table:catalog.schema.name` for table references, `group:name` for principals. These are platform-neutral; the adapter resolves them to platform identifiers via configuration.
- **Pointers into the repo**: file paths are relative to the repo root. Code examples assume the `.venv` Python interpreter and a working directory of the repo root.

## What this guide does not duplicate

- ADRs — `DECISIONS.md` is the authoritative log of design decisions. The user guide references ADRs by number; it does not restate them.
- The technical design — `docs/technical-design-v0.2.md` is the spec-level reference. The user guide explains *how to use* the spec; the technical design explains *what the spec is*.
- The README — the README is the front door for someone landing on the repo cold. This guide is for someone who's decided to actually use Tessera and needs operational depth.
