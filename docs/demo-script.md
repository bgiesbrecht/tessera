# Tessera demo script

**Audience:** data governance leads, platform architects, and engineers who run more than one data platform. No RDF or semantic-web background assumed.

**Length:** 25–30 minutes for the full arc; a 5-minute lightning version is in the appendix.

**What they will see:** a governance policy authored once as a standalone artifact, checked for unintended access changes before deployment, then lowered into native enforcement on Databricks, Snowflake, and Oracle from that single source.

**One-line promise:** express what a policy *means* once; enforce it natively everywhere, and know what a change does before you ship it.

---

## Pre-flight (before the room is watching)

Run these once so the live portion has no surprises. Everything runs offline from the repo root against the bundled `.venv`.

```bash
cd /path/to/tessera
.venv/bin/python -m tools.cli validate spec/v0/examples/group-row-visibility-policy-a.jsonld
.venv/bin/python -m pytest tools/ adapters/ -q      # 99 passing
```

If you plan to run the optional live-enforcement act (Act 5), have the Oracle connection ready: `oracle_auth.txt` at the repo root and `pip install oracledb`. Skip Act 5 if you have no instance; the emitted SQL still tells the story.

A reset block for re-running the demo is in the appendix.

---

## The story first (5 minutes, no terminal)

### Genesis: one company, two source-of-truth catalogs

A customer runs Databricks and Snowflake side by side. Different teams landed on different platforms, and both hold regulated data: PII, order records, clerk identities. The same governance rule ("fraud investigators may read order priorities; everyone else sees a filtered set; the clerk column is masked outside the finance group") has to hold in both places.

Today that rule is authored twice. Once as a Databricks row filter and column mask, once as a Snowflake row-access policy and masking policy. The two are written in different languages by different people, reviewed separately, and they drift. When an auditor asks "what is the policy," the honest answer is "read the Databricks DDL, then read the Snowflake DDL, then trust that they agree." They frequently do not.

A third pressure sits underneath: this customer, like many, also enforces policy through a hand-built pattern that predates native controls. Thousands of rows in ACL tables, joined into views. That pattern is invisible to either platform's catalog, and nobody wants to rewrite it by hand to migrate.

### The idea: policy as a standalone artifact

Tessera separates what a policy *means* from how a platform *enforces* it. The meaning is written once, in a platform-neutral representation that carries the governance intent (who, what, under which conditions, with which obligations) and nothing about the mechanism. That artifact is reviewable, version-controlled, and diffable on its own, independent of any platform's DDL or query language.

From that one artifact, a per-platform *adapter* lowers the policy into the native enforcement mechanism of each environment. The same meaning becomes a Databricks row filter, a Snowflake row-access policy, an Oracle VPD policy, or the customer's own ACL-view pattern. The policy is the token; each platform holds a matching half.

### What Tessera is not (say this early; it earns trust)

Tessera does not sit in the query path. It is not a runtime engine, and it does not replace Unity Catalog or Snowflake governance. Inside Databricks, Unity Catalog remains the source of truth. Tessera operates *between* governance estates and compiles to the enforcement each platform already does well. Where a platform cannot enforce something, Tessera says so rather than pretending.

---

## Act 1: Author a policy (3 minutes)

**Point:** governance intent, written in a form a human reviews.

Open the authoring form. This is what an engineer or a governance lead writes and checks into a repository.

```bash
.venv/bin/python -m tools.cli convert spec/v0/examples/group-row-visibility-policy-a.tessera.yaml | head -40
```

Talk through the YAML on screen (`spec/v0/examples/group-row-visibility-policy-a.tessera.yaml`):

- `appliesTo` names the protected table by meaning, `table:acme.tpch.orders`, not a platform-qualified object.
- Three ordered rules: the all-priority-ops group sees every row; the high-priority group sees `1-URGENT` and `2-HIGH`; the baseline group sees the lower priorities. First match wins.
- `defaultStrategy: explicit-baseline-group` records the *intent* for principals who match no rule. That intent is part of the artifact, not an accident of how the SQL happened to be written.

Nothing here mentions `is_account_group_member`, `IS_ROLE_IN_SESSION`, a masking function, or a role name. The mechanism is absent by design.

---

## Act 2: Canonicalize and validate (3 minutes)

**Point:** the artifact is machine-checkable before it ever reaches a platform.

```bash
.venv/bin/python -m tools.cli convert spec/v0/examples/group-row-visibility-policy-a.tessera.yaml \
  --out /tmp/policy.jsonld
.venv/bin/python -m tools.cli validate /tmp/policy.jsonld
```

Expected:

```
schema: OK
shacl: OK

/tmp/policy.jsonld: validates clean.
```

Two layers run. JSON Schema checks structure (required fields, the conditional dependency that `baselineGroup` must be present when `defaultStrategy` is `explicit-baseline-group`). SHACL checks meaning (closed vocabularies, that an attribute value is a real class in the ontology). Both pass here. If a reviewer had dropped the baseline group, validation would catch it before any DDL was generated. This is the W3C stack doing the work; more on that in a moment.

---

## Act 3: Check the impact of a change before you ship it (6 minutes)

**Point:** the moment that lands with governance owners. A change that looks harmless is shown to open or close access, statically, before deployment.

Take the same policy and make an edit that looks routine: let the high-priority group also see `3-MEDIUM` orders.

```bash
# a proposed version with one widened rule
cp spec/v0/examples/group-row-visibility-policy-a.jsonld /tmp/proposed.jsonld
# (edit /tmp/proposed.jsonld: add "3-MEDIUM" to rule 1's condition values)

.venv/bin/python -m tools.cli impact \
  --baseline spec/v0/examples/group-row-visibility-policy-a.jsonld \
  --proposed /tmp/proposed.jsonld
```

Real output:

```
CHANGE-IMPACT REPORT
====================

[C6]  WIDEN  selector group:acme_high_priority_ops   PROVEN
     Condition value-set gained ['3-MEDIUM'] on a keep-matching-rows rule → exposure increased.
     grounding: §4.2 value-set arithmetic
```

The tool read two versions of the policy and reported that the change *widens* exposure for a named group, with a proof grounded in value-set arithmetic. It never connected to a platform and never asked who is in the group. It reasons about the policy expression, not about populations. That line is the boundary Tessera holds (no runtime evaluation, ADR-001), and it is why the finding is labeled `PROVEN` rather than a guess.

Now the harder case Tessera also catches: two policies that individually look fine but conflict when combined.

```bash
.venv/bin/python -m tools.cli impact \
  --baseline tools/impact/demo/overlap/before/*.jsonld \
  --proposed tools/impact/demo/overlap/after/*.jsonld
```

Real output (excerpt):

```
[C4]  policy:pii-hash ∩ policy:pii-redact   PROVEN
     Change introduces a cross-policy overlap: ... both ColumnVisibilityConstraint policies whose
     scopes and attribute-matches provably overlap, with divergent effects ... the adapter will
     refuse to emit the pair; resolve before deployment (ADR-023 γ-with-refinement).

[C4]  policy:clerk-redact ∩ policy:pii-hash   CANDIDATE
     ... may overlap ...
     unknown: whether resource 'column:acme.tpch.orders.o_clerk' carries attribute(s) [sensitivity:PII]
     is a platform-tagging fact not visible to static analysis
```

Two things to point out. First, `PROVEN` versus `CANDIDATE`: Tessera separates what it can prove from the surrounding IR from what depends on a platform-tagging fact it cannot see, and it names the exact unknown. It does not overclaim. Second, the grounding cites ADR-023 and the platform constraint that a column takes at most one mask. A reviewer gets not just "these conflict" but why, and what to do before deployment.

This act answers the question a governance owner actually loses sleep over: *did my change quietly open or close access somewhere I did not intend?*

The same checks run as a standing corpus health pass:

```bash
.venv/bin/python -m tools.cli lint --corpus tools/impact/demo/timeline/v4
```

`lint` flags dead rules (a rule no request can reach) and standing cross-policy overlaps, so problems surface in CI rather than in an incident.

---

## Act 4: Lower the same policy into every environment (7 minutes)

**Point:** one artifact, native enforcement everywhere, mechanisms that look nothing alike.

Emit the group-visibility policy to Databricks and Snowflake from the identical IR.

```bash
.venv/bin/python -m tools.cli emit spec/v0/examples/group-row-visibility-policy-a.jsonld --adapter uc
.venv/bin/python -m tools.cli emit spec/v0/examples/group-row-visibility-policy-a.jsonld --adapter sf
```

Databricks produces a SQL UDF plus `SET ROW FILTER`, binding principals with `is_account_group_member(...)`. Snowflake produces a `ROW ACCESS POLICY` object plus `ADD ROW ACCESS POLICY`, binding with `IS_ROLE_IN_SESSION(...)`. Same three branches, same priority predicates, same first-match order. Different object model, different principal-binding function, different identifier casing.

The Snowflake emission also prints `UNBOUND_PRINCIPAL` warnings: role names are case-sensitive and no identity binding was configured, so the adapter fell back to the IR slug and told you it did. A real deployment risk, surfaced as first-class output rather than a silent guess.

Now the punchline. Take the ACL-table policy (the customer's data-driven pattern) and lower the one IR four ways:

```bash
for a in uc sf oracle custom-acl; do
  echo "===== $a ====="
  .venv/bin/python -m tools.cli emit spec/v0/examples/acl-row-visibility-policy.jsonld --adapter $a
done
```

The same policy becomes:

- **Databricks:** a row-filter function whose body is an `EXISTS` join over the two ACL tables.
- **Snowflake:** a row-access policy with the same `EXISTS` join.
- **Oracle:** a Virtual Private Database policy function (`DBMS_RLS.ADD_POLICY`) returning an `IN`-subquery predicate.
- **Custom ACL pattern:** a wrapping secure view where the view itself is the enforcement, the customer's own convention, no platform primitive at all.

Four mechanisms, one meaning. The committed artifacts sit side by side for reference: `spec/v0/examples/acl-row-visibility.{databricks.sql,custom-acl.sql,oracle.sql}` and `snowflake-byDataset-row-visibility.snowflake.sql`.

Then show the honesty boundary. Emit an attribute-scoped policy to Oracle:

```bash
.venv/bin/python -m tools.cli emit spec/v0/examples/abac-column-mask-policy-a.jsonld --adapter oracle
```

Oracle has no tag-driven policy attachment, so the adapter emits no DDL and returns a diagnostic saying exactly that (`UNSUPPORTED_ABAC_SCOPING`, Oracle Label Security deferred). Every adapter publishes a capability profile, and a gap is reported, never approximated. Governance buyers trust a tool more when it refuses cleanly than when it silently does the wrong thing.

**The migration on-ramp** (mention, optionally show): the custom-ACL adapter also runs in reverse. Its `extract` reads an existing hand-built ACL view and lifts it back into the Tessera artifact, which can then be re-emitted onto Databricks or Snowflake. That is the path off thousands of ACL rows without hand-rewriting them, and it is why the adapters are peers rather than a privileged native core with plugins.

---

## Act 5 (optional, needs a live instance): prove it enforces (4 minutes)

**Point:** the emitted SQL is not a mock; it enforces on a real database.

```bash
TESSERA_ORA_USER=SYSTEM TESSERA_ORA_DSN=<host>:1521/FREEPDB1 \
  .venv/bin/python -m adapters.tests.live_oracle
```

The script sets up the ACL tables, emits the VPD policy through the adapter, applies it, and queries under changing ACL membership. Row visibility moves 2 → 5 → 0 as mappings are added and then removed (fail-closed when the user is absent from the ACL join). The Oracle column-mask path was verified the same way: a non-privileged reader sees `CLERK-REDACTED`, a member of the allowed role sees the real value. Live verification of this adapter caught three emission bugs that all unit tests had passed, which is a fair thing to admit in the room: it is why the profile is stamped "live-verified" with a date, not just "emitted."

---

## The W3C foundation (3 minutes)

> Interpreting the "WSC" note as W3C. Redirect me if you meant something else.

Tessera does not invent a bespoke policy format. It is built on the W3C semantic-web stack, and the choice is deliberate (ADR-005).

- **JSON-LD** is the canonical serialization. The artifact is ordinary JSON that is also a graph, so it round-trips through standard tooling.
- **OWL / Turtle ontology** defines the vocabulary and its hierarchy. Because sensitivity classes form a real subclass hierarchy, a policy about `PII` can be reasoned to cover a policy about a subtype of PII, using standard subsumption rather than hand-maintained lookup tables.
- **SHACL** carries the semantic validation shown in Act 2: closed vocabularies, class membership, structural shape.
- **Vocabulary reuse.** Where W3C ODRL (policy expression) and DPV (data-privacy terms) already define a concept, Tessera aligns to them through SKOS mappings rather than coining a private term. Interoperability is the goal, so standing on shared standards is the mechanism, not decoration.

The payoff for the buyer: the artifact is not a proprietary lock-in format. It is a standards-grounded representation that other tools can read, validate, and reason over. `docs/w3c-overview.md` is the deeper tour if the room wants it.

---

## Close (1 minute)

Bring it back to the customer.

- One policy artifact, reviewed and version-controlled on its own, independent of any platform's language.
- The same artifact lowered into Databricks, Snowflake, Oracle, and a custom ACL pattern, each in its native mechanism.
- A change checked for unintended access shifts before it ships, with proofs and honestly-labeled unknowns.
- A path to lift existing hand-built policy back into the artifact and migrate it.
- Honest capability reporting: where a platform cannot enforce a concept, the tool says so.

The name is the point. A tessera is a token split between parties, where the halves match to prove one agreement. That is what a governance policy becomes across platforms.

---

## Appendix

### 5-minute lightning version

1. Show the YAML policy (Act 1), 60 seconds.
2. Run the widening `impact` command (Act 3, first example), 90 seconds. This is the highest-signal moment for a governance audience.
3. Run the four-way ACL emit loop (Act 4), 2 minutes.
4. One sentence on the W3C foundation and the "no runtime engine" boundary.

### Likely questions

- **"Does this run in our query path?"** No. It compiles to platform-native enforcement and steps out. Unity Catalog stays the source of truth inside Databricks (ADR-002).
- **"What if two policies disagree?"** Shown in Act 3: the cross-policy overlap check (C4) flags divergent effects on an overlapping scope and refuses to emit an unenforceable pair, grounded in ADR-023.
- **"What about a platform you do not support?"** Adapters are peers against one contract. Adding a platform is a new adapter, not a change to the IR. The capability profile states honestly what it can and cannot enforce.
- **"How do we get our existing policies in?"** Extraction. Each adapter lifts deployed enforcement back into the artifact; the custom-ACL adapter does this for the hand-built ACL-view pattern.
- **"Is the impact tool guessing?"** No. It reasons about the policy expression, labels every finding `PROVEN` or `CANDIDATE`, and names the platform fact behind any unknown. It never evaluates group membership (ADR-001).

### Reset between runs

```bash
git checkout -- spec/v0/examples/         # if you edited any example in place
rm -f /tmp/policy.jsonld /tmp/proposed.jsonld
```

### Command reference

| Act | Command |
|---|---|
| Author / convert | `python -m tools.cli convert <file.tessera.yaml> [--out PATH]` |
| Validate | `python -m tools.cli validate <file.jsonld>` |
| Impact (change) | `python -m tools.cli impact --baseline <a> --proposed <b>` |
| Lint (corpus) | `python -m tools.cli lint --corpus <dir>` |
| Emit | `python -m tools.cli emit <file.jsonld> --adapter {uc,sf,oracle,custom-acl}` |
| Live enforce (Oracle) | `python -m adapters.tests.live_oracle` |
