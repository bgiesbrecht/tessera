# Tessera demo — video transcript (5–10 minutes)

A spoken transcript for a screen-recorded demo, timed to about **8 minutes**. It follows the arc in [`demo-script.md`](demo-script.md), compressed to the lightning spine. A 5-minute cut is noted at the end.

**How to read this:** `SCREEN` is what the viewer sees; `VOICE` is what the presenter says. Spoken word counts run about 150 per minute, so the timings assume commands are pre-run and their output edited in rather than typed live. Record the terminal at a readable font size and keep each command on screen while you narrate its result.

**Setup before recording:** work from the repo root with the bundled `.venv`. Have a proposed-change file ready for the impact act (`cp spec/v0/examples/group-row-visibility-policy-a.jsonld /tmp/proposed.jsonld`, then add `"3-MEDIUM"` to rule 1's condition values). Reset with `git checkout -- spec/v0/examples/` afterward.

---

## 0:00 — Cold open

**SCREEN:** title card, "Tessera — one governance policy, every platform." Fade to a split screen: a Databricks notebook on the left, a Snowflake worksheet on the right, both showing access-control SQL.

**VOICE:**
> This company runs two data platforms. Databricks on one side, Snowflake on the other. Both hold regulated data, and the same governance rule has to hold in both places: fraud investigators can read order priorities, everyone else sees a filtered set, and the clerk column is masked outside finance.
>
> Today that rule is written twice. Once in Databricks SQL, once in Snowflake SQL, by different people, reviewed separately. And they drift. When an auditor asks "what is the policy," the honest answer is "read both dialects and hope they agree."

---

## 0:40 — The problem, sharpened

**SCREEN:** the two SQL panes highlight a subtle difference between them (a priority value present on one side, missing on the other). Then a third pane slides in: a wall of rows in an ACL table joined to a view.

**VOICE:**
> There is usually a third thing too. A hand-built pattern that predates the native controls: thousands of rows in ACL tables, joined into views. It works, but neither platform's catalog can see it, and nobody wants to rewrite it by hand to migrate.
>
> So the real problem is not any one platform. It is that the *meaning* of the policy lives nowhere. It is scattered across dialects and conventions.

---

## 1:15 — The idea

**SCREEN:** the three panes collapse into a single small file icon labeled `orders.tessera.yaml`. Arrows fan out from it to four targets: Databricks, Snowflake, Oracle, and "custom ACL views."

**VOICE:**
> Tessera separates what a policy *means* from how a platform *enforces* it. You write the meaning once, in a platform-neutral artifact that carries the intent and nothing about the mechanism. Then a per-platform adapter lowers that one artifact into each environment's native enforcement.
>
> One thing to say up front, because it earns trust: Tessera does not sit in the query path. It is not a runtime engine, and it does not replace Unity Catalog or Snowflake governance. It compiles to what each platform already does well, and it steps out.

---

## 1:55 — Act 1: author the policy

**SCREEN:** open `spec/v0/examples/group-row-visibility-policy-a.tessera.yaml` in an editor. Scroll slowly through the `appliesTo`, `action`, `defaultStrategy`, and the three `rules`.

**VOICE:**
> Here is the artifact. It is YAML, so it reviews like code. It applies to a table by name. It has three ordered rules: the all-priority-ops group sees every row, the high-priority group sees urgent and high orders, and the baseline group sees the lower priorities. First match wins.
>
> Notice what is *not* here. No `is_account_group_member`, no `IS_ROLE_IN_SESSION`, no masking function, no role name. The mechanism is absent on purpose. This file is only about who may see what.

---

## 2:55 — Act 2: validate

**SCREEN:** run the two commands; let the output appear.

```
$ python -m tools.cli convert spec/v0/examples/group-row-visibility-policy-a.tessera.yaml --out /tmp/policy.jsonld
$ python -m tools.cli validate /tmp/policy.jsonld
schema: OK
shacl: OK

/tmp/policy.jsonld: validates clean.
```

**VOICE:**
> The YAML converts to a canonical JSON-LD form, and it validates in two layers before it ever touches a platform. JSON Schema checks the structure. SHACL checks the meaning: that the vocabulary is closed, that every attribute is a real term. Both pass. If a reviewer had dropped the baseline group, this step would have caught it.

---

## 3:25 — Act 3: check the impact of a change

**SCREEN:** editor diff view showing one line added to the high-priority rule: `"3-MEDIUM"` appended to its values. Then run the impact command.

```
$ python -m tools.cli impact \
    --baseline spec/v0/examples/group-row-visibility-policy-a.jsonld \
    --proposed /tmp/proposed.jsonld

[C6]  WIDEN  selector group:acme_high_priority_ops   PROVEN
     Condition value-set gained ['3-MEDIUM'] on a keep-matching-rows rule → exposure increased.
     grounding: §4.2 value-set arithmetic
```

**VOICE:**
> Now the part governance owners care about. I make an edit that looks routine: let the high-priority group also see medium orders. One line.
>
> Before I deploy anything, I ask Tessera what the change does. And it tells me: this *widens* exposure for a named group, and it can prove it. It never connected to a platform, and it never asked who is in that group. It reasons about the policy text, not about people. That is the line Tessera holds, and it is why this says PROVEN instead of "maybe."

**SCREEN:** run the cross-policy example; show the top two findings.

```
$ python -m tools.cli impact \
    --baseline tools/impact/demo/overlap/before/*.jsonld \
    --proposed tools/impact/demo/overlap/after/*.jsonld

[C4]  policy:pii-hash ∩ policy:pii-redact   PROVEN
     ... both mask the same column with divergent effects; the adapter will refuse to
     emit the pair; resolve before deployment (ADR-023).

[C4]  policy:clerk-redact ∩ policy:pii-hash   CANDIDATE
     unknown: whether column o_clerk carries attribute [sensitivity:PII] is a
     platform-tagging fact not visible to static analysis.
```

**VOICE:**
> It also catches conflicts *between* policies. Here two masks land on the same column with different effects, and Tessera flags it before deployment. Look at the two labels. PROVEN, when it can show the conflict from the policies alone. CANDIDATE, when the answer depends on a platform fact it cannot see, and it names exactly which fact. It does not bluff.

---

## 5:15 — Act 4: lower it into every platform

**SCREEN:** run the two emit commands side by side; highlight the different principal-binding functions in each output.

```
$ python -m tools.cli emit .../group-row-visibility-policy-a.jsonld --adapter uc
   ... is_account_group_member('acme_high_priority_ops') ... SET ROW FILTER ...

$ python -m tools.cli emit .../group-row-visibility-policy-a.jsonld --adapter sf
   ... IS_ROLE_IN_SESSION('ACME_HIGH_PRIORITY_OPS') ... ADD ROW ACCESS POLICY ...
```

**VOICE:**
> Same artifact, two platforms. Databricks gets a row-filter function. Snowflake gets a row-access policy. Same three branches, same order, but a different object model and a different way of binding the principal. I wrote the policy once; the adapters handled the dialects.

**SCREEN:** the four-way loop over the ACL policy; show the header for each adapter and one line of its distinct output.

```
$ for a in uc sf oracle custom-acl; do
    python -m tools.cli emit spec/v0/examples/acl-row-visibility-policy.jsonld --adapter $a
  done
```

**VOICE:**
> And here is the point of the whole project. Take the ACL-table policy, the one that used to live in that wall of rows, and lower it four ways. Databricks: a row-filter function. Snowflake: a row-access policy. Oracle: a Virtual Private Database policy. And the customer's own pattern: a wrapping view, where the view itself is the enforcement, no platform primitive at all.
>
> Four mechanisms. One meaning. And this runs in reverse too: Tessera can read an existing hand-built ACL view and lift it back into the artifact, which is the path off that legacy pattern without rewriting it by hand.

---

## 7:05 — The honesty boundary

**SCREEN:** emit an attribute-scoped policy to Oracle; show the diagnostic, no DDL.

```
$ python -m tools.cli emit spec/v0/examples/abac-column-mask-policy-a.jsonld --adapter oracle
   [warning] UNSUPPORTED_ABAC_SCOPING: Oracle has no tag-driven policy attachment;
             not emitted (Oracle Label Security deferred).
```

**VOICE:**
> One more thing, because it matters. Ask Oracle to do something Oracle cannot: an attribute-scoped, tag-driven mask. Tessera emits nothing and tells you exactly why. Every adapter publishes what it can and cannot enforce. A gap is reported, never faked. That is the difference between a tool you can put in front of an auditor and one you cannot.

---

## 7:35 — Close

**SCREEN:** back to the single file icon with four arrows, now each showing a green check. Title card returns.

**VOICE:**
> So: one policy artifact, reviewed on its own, independent of any platform's language. The same artifact enforced natively on Databricks, Snowflake, Oracle, and a custom pattern. A change checked for unintended access before it ships. And an honest account of what each platform can enforce.
>
> A tessera was a token split between two parties, where the halves matched to prove one agreement. That is what a governance policy becomes across platforms. Thanks for watching.

**SCREEN:** end card with the repo path and `docs/showcase.md` for a deeper tour.

---

## The 5-minute cut

Drop these to reach roughly five minutes, keeping the spine intact:

- Merge 0:00 and 0:40 into one 45-second open (state the two-catalog drift problem; keep the ACL pattern to a single sentence).
- Keep Act 1 but stop narrating individual rules; say "three ordered rules, first match wins" over a scroll.
- In Act 3, keep the widening example (the highest-signal moment) and cut the cross-policy overlap.
- In Act 4, keep the four-way ACL loop and cut the separate Databricks/Snowflake row-visibility comparison.
- Keep the honesty boundary and the close; they are short and they land.

## Recording notes

- Pre-run every command and paste trimmed output, or the pauses will pad the runtime past ten minutes.
- The impact and emit outputs are the moments to hold on screen. Zoom the terminal so `PROVEN`, `WIDEN`, and the differing platform functions are legible.
- Keep one browser tab or slide with the four-arrow diagram; returning to it at the open, Act 4, and the close gives the video a visual through-line.
- All commands are verified runnable against the bundled `.venv`; see `docs/demo-script.md` for the full 25-minute version, the command reference, and a likely-questions appendix.
