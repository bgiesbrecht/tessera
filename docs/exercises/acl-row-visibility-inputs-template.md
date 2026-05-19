# Phase 1 Inputs — ACL Row-Visibility Exercise

**For:** Brice to complete before handing to Claude Code.
**Companion document:** `docs/worked-example-exercise.md` (§1 for the input categories this template instantiates).
**Output:** A completed brief that gives Claude Code everything needed to derive a Tessera policy and a platform-native translation, *without* providing the existing implementation itself.

**Instructions to the author (Brice):**

- Answer each prompt in plain English. Do not paste SQL or code from the existing implementation.
- Where a prompt asks for a name or schema, give the names and types as they appear, but do not include the bodies of functions or views.
- If a prompt does not apply to your case, write "not applicable" and a one-sentence reason. Do not skip prompts silently.
- Where you have a choice between "what the implementation does" and "what the policy intent requires," answer the intent question. The implementation is being held back deliberately.
- At the end, the "Demo or production?" question matters for scope — answer it deliberately rather than by default.

---

## 0. Framing

**0.1 — Demo or production scope?**

Is this exercise validating Tessera against a demonstration of patterns, or against a production implementation with all its operational concerns? Pick one:

- [ ] **Demo.** Tessera's job is to express the same patterns. Edge cases around concurrency, hot paths, audit, and operational resilience are out of scope for the comparison.
- [ ] **Production.** Tessera's job is to express the patterns *and* match the production concerns. Comparison includes operational behavior.

Reason for the choice:

> _[Your answer]_

**0.2 — Target platform**

The exercise produces a translation to which platform's native enforcement?

- [ ] Databricks Unity Catalog
- [ ] Snowflake
- [ ] Other (specify):

Reason if not the project's typical first-target (Unity Catalog):

> _[Your answer]_

**0.3 — Scope of this exercise**

This exercise covers (check all that apply):

- [ ] An ACL-table-driven row-visibility pattern.
- [ ] A group-based row-visibility pattern (referenced in the conversation as a parallel pattern in the same notebook).
- [ ] Both patterns, treated as separate Tessera policies that share inputs.
- [ ] Other:

If both patterns: do you want Tessera to express them as two distinct policies, or as one policy with multiple selectors? (The recommendation is two policies because conflating them obscures whether the framework handles each correctly. Confirm or override.)

> _[Your answer]_

---

## 1. The protected resource

**1.1 — Protected table(s)**

Fully qualified name(s) of the table(s) the policy applies to:

> _[Your answer]_

**1.2 — Relevant columns**

Which columns are involved in the policy decision (the columns the row filter reads to decide visibility)?

> _[Your answer]_

Which columns identify a row (primary key, surrogate key, business key)?

> _[Your answer]_

**1.3 — Existing classifications**

Does the protected table already carry classifications (PII, PHI, Confidential, etc.) in any catalog or tagging system? If so, list them and where they live. If not, write "none."

> _[Your answer]_

**1.4 — Should the protected table carry a classification?**

For the purposes of this policy, what classification would best describe the data? (This is asking what the policy *should* select against, not what is currently tagged. If the answer is "the policy targets a specific table by name, classification is not how this policy selects," say so explicitly.)

> _[Your answer]_

---

## 2. The ACL table

(Skip this section if the pattern is purely group-based without an ACL table. Note that and move to §3.)

**2.1 — ACL table name**

Fully qualified name:

> _[Your answer]_

**2.2 — ACL schema**

Column names and types, as defined. Do not include the body of any function that uses this table; just the table's columns.

> _[Your answer]_

**2.3 — Principal column**

Which column identifies the principal? What identifier type — email, username, group name, opaque ID?

> _[Your answer]_

**2.4 — Resource column**

Which column identifies the resource (the row, the group of rows, or the category)? What is the identifier — table name, primary key, business category, something else?

> _[Your answer]_

**2.5 — Permission column**

Is there a column representing the permission level? If so, what values are used (read, select, view, etc.)? If permission is implicit (presence in the table = read access), say so.

> _[Your answer]_

**2.6 — Other relevant columns**

Are there other columns the policy depends on? Effective-date columns, tenant IDs, expiration timestamps, conditional flags?

> _[Your answer]_

**2.7 — Indirection between ACL and protected table**

How does an ACL row relate to a row in the protected table? Direct (an ACL row identifies a specific protected row), categorical (an ACL row grants access to a category of rows defined by a value in the protected table), or some other relationship?

> _[Your answer]_

---

## 3. The principal model

**3.1 — Principal identification at session time**

How is the current principal identified in the target platform at query time? `current_user()`, `current_role()`, session tag, custom function?

> _[Your answer]_

**3.2 — Matching session identity to ACL or group**

What is the matching logic between the session identity and the principal column in the ACL (or the group definition, if group-based)? Exact match, case-insensitive, trimmed, lookup-through-another-table?

> _[Your answer]_

**3.3 — Role or group hierarchy**

Does the policy depend on role or group inheritance? If so, describe — "members of group A also have the privileges of group B" — without referencing how that inheritance is implemented.

> _[Your answer]_

**3.4 — Exceptional principals**

Are there principals (admins, break-glass roles, service accounts, audit roles) that bypass or modify the policy? List them and what behavior they have.

> _[Your answer]_

---

## 4. The policy intent

**4.1 — In plain English**

In one or two sentences, what is this policy supposed to do?

> _[Your answer]_

**4.2 — Principals with an entry**

What should happen for a principal who has an entry in the ACL (or who is a member of a relevant group)?

> _[Your answer]_

**4.3 — Principals without an entry**

What should happen for a principal with no entry?

> _[Your answer]_

**4.4 — Purpose binding**

Does the policy depend on the *purpose* the principal claims for accessing the data (analytics, fraud investigation, audit)? If yes, describe. If no, write "no purpose binding."

> _[Your answer]_

**4.5 — Time-of-day or jurisdiction conditions**

Does the policy depend on time-of-day, day-of-week, jurisdiction, or other context predicates beyond the principal's identity?

> _[Your answer]_

**4.6 — Obligations**

When the policy applies, what must happen as a consequence? Audit log entries? Notifications? Watermarking? List each obligation and what makes it required.

> _[Your answer]_

---

## 5. Edge cases the implementation handles

This is the section where the most useful information lives. Answer each in terms of intended behavior, not current implementation.

**5.1 — Duplicate ACL entries**

If the ACL table has two entries for the same principal-resource pair, what should the policy do?

> _[Your answer]_

**5.2 — Stale or expired ACL entries**

If an ACL entry should be valid only during a specific window, how is that captured? (If it isn't, write "no expiration semantics.")

> _[Your answer]_

**5.3 — Mid-session changes**

If the ACL or group membership changes during an active query session, when do the changes take effect? Next query, current query, never?

> _[Your answer]_

**5.4 — Joins with other tables**

If a query joins the protected table with another table, how is the policy applied? Same row filter applies to the join result? Differently?

> _[Your answer]_

**5.5 — Views over the protected table**

If a view is defined on top of the protected table, does the policy apply to the view, the underlying table, both?

> _[Your answer]_

**5.6 — Service accounts**

How does the policy treat service accounts and non-human principals?

> _[Your answer]_

**5.7 — ACL table unavailability**

If the ACL table is unreachable at query time (corrupted, locked, missing), should the policy fail-closed (deny all) or fail-open (allow all)?

> _[Your answer]_

**5.8 — Empty ACL**

If the ACL table is empty (legitimately, not due to error), what is the behavior?

> _[Your answer]_

**5.9 — Cross-tenant or cross-region considerations**

If the data spans tenants or regions, does the policy interact with that? Describe.

> _[Your answer]_

**5.10 — Any other edge cases**

Anything else the implementation handles that the questions above didn't capture. List them.

> _[Your answer]_

---

## 6. Non-functional requirements

**6.1 — Performance**

Is the protected table on a hot query path? Is there a latency budget the policy must respect? If yes, quantify (milliseconds, percentile, throughput).

> _[Your answer]_

**6.2 — Auditability**

What must be logged for each access? To where? Format requirements?

> _[Your answer]_

**6.3 — Change control**

How are policy changes deployed? Can the ACL table be updated live, or is there a deployment window? Are there rollback requirements?

> _[Your answer]_

**6.4 — Compliance traceability**

Does the policy need to trace to a specific regulation, internal control framework, or contractual obligation? Name it.

> _[Your answer]_

---

## 7. What success looks like for this exercise

**7.1 — Behavioral equivalence criteria**

What test cases would you use to confirm the Tessera-derived implementation behaves the same as the existing one? List specific principal-resource-action combinations whose outcomes you would check.

> _[Your answer]_

**7.2 — Acceptable divergences**

Are there areas where you'd accept the Tessera derivation diverging from the existing implementation (better naming, different SQL structure, additional safety) as long as behavior matches?

> _[Your answer]_

**7.3 — Disqualifying divergences**

Are there areas where any divergence is unacceptable (specific SQL constructs required, specific function names required for downstream tooling)?

> _[Your answer]_

---

## 8. Anything not covered above

Anything else Claude Code needs to know to do this work correctly, that the prompts above didn't ask about.

> _[Your answer]_

---

## How to hand this off

Once this template is completed:

1. Save the completed version into the repo at `docs/exercises/acl-row-visibility-inputs.md`. (The `docs/exercises/` directory does not exist yet; create it.)
2. Confirm with Claude Code that Phase 1 is complete and Phase 2 may begin.
3. **Do not share the original notebook or implementation with Claude Code until Phase 2 artifacts are committed.** Phase 3 (comparison) is when the existing implementation is introduced.

If a prompt is ambiguous or you discover during answering that an intent question is genuinely undecided, note it explicitly rather than picking a default. Discovering that policy intent was ambiguous is one of the valuable findings the exercise can produce.
