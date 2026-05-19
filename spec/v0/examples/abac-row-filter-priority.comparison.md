# Phase 3 Comparison — ABAC Row-Filter (priority) (stub)

**Companion artifacts:**
- `abac-row-filter-priority.tessera.yaml` / `.jsonld`
- `abac-row-filter-priority.databricks.sql`
- `abac-row-filter-priority.diagnostic.md`

**Inputs:** `docs/exercises/abac-row-filter-priority-inputs.md`
**Exercise framing:** Canonical three-phase mode, blind derivation. Phase 2 derived from inputs only; existing implementation will be shared by Brice after Phase 2 commits.

**Status:** Phase 2 artifacts committed. Phase 3 deployment + Scenario 3 observation **completed 2026-05-19**. Scenarios 1 and 2 pending Brice's group-membership toggles. Existing-implementation structural comparison pending Brice's share.

---

## 1. Summary (pending Phase 3)

The Phase 2 artifacts express the three-branch row-visibility intent using the post-ABAC vocabulary and an adopter-namespaced axis. Phase 3 deploys the SQL emission and observes:

1. **Behavioral correctness** — three scenarios across group membership states match the expected priorities.
2. **Cross-policy combination for row filters** — does Databricks reject multiple row filters on the same table, analogous to the multi-mask error from the column-mask exercise?
3. **Structural comparison** against Brice's existing implementation, shared after Phase 2.

---

## 2. Behavioral observation (Phase 3)

### 2.1 Test scenarios — results

Deployed 2026-05-19 against `bg_rls_demo.tpch.orders_abac` on Azure workspace `adb-984752964297111`. Brice's group memberships verified live via `is_account_group_member`.

| Scenario | Brice's membership | Expected priorities | Observed | Match |
|---|---|---|---|---|
| 3 | Neither restrictive group | `3-MEDIUM`, `4-NOT SPECIFIED`, `5-LOW` | Same (4,499,708 rows; 60% of unfiltered 7,500,000) | ✓ |
| 1 | Member of `bg_rls_demo_all_priority_ops` | All five | **Pending Brice's toggle** | — |
| 2 | Member of `bg_rls_demo_high_priority_ops` only | `1-URGENT`, `2-HIGH` | **Pending Brice's toggle** | — |

Per-priority breakdown for Scenario 3 confirms exact source-distribution match for the visible priorities:

| Priority | Visible | Source (`samples.tpch.orders`) | Match |
|---|---|---|---|
| `1-URGENT` | 0 | 1,501,100 | ✓ filtered out |
| `2-HIGH` | 0 | 1,499,192 | ✓ filtered out |
| `3-MEDIUM` | 1,498,710 | 1,498,710 | ✓ |
| `4-NOT SPECIFIED` | 1,501,281 | 1,501,281 | ✓ |
| `5-LOW` | 1,499,717 | 1,499,717 | ✓ |

Scenarios 1 and 2 require Brice to add himself to the respective restrictive group with the standard 2–4 minute account-group cache lag. The exercise's design point (Mechanism B with three-branch CASE) is already validated by Scenario 3 — the principal-not-matched fall-through branch (the ELSE) is the one whose correctness was most in question, since Mechanism B's branching logic depends on the CASE traversal order. Scenarios 1 and 2 are confirmation that the WHEN branches above the ELSE also work.

### 2.2 Bonus observation — column mask + row filter compose correctly

`o_clerk` continues to return `'CLERK-REDACTED'` for non-privileged principals on rows that survive the row filter. The two ABAC policies (`tessera__abac_column_mask_clerk_redact` + `tessera__abac_row_filter_priority`) layer correctly: the row filter narrows which rows are visible; the column mask redacts the `o_clerk` value on those visible rows. No conflict, no error, no surprises.

This is an orthogonal-composition success — two different ABAC mechanisms on the same table, both applying simultaneously. Distinct from the multi-mask conflict observed in the prior column-mask exercise (which was *two* column masks competing on the *same* column).

`SHOW POLICIES ON CATALOG bg_rls_demo` confirms both attached:

```
tessera__abac_column_mask_clerk_redact  COLUMN_MASK  bg_rls_demo  ...
tessera__abac_row_filter_priority       ROW_FILTER   bg_rls_demo  ...
```

### 2.2 Multi-row-filter cross-policy test (optional)

After Scenario 3 is verified, attach a *second* row filter policy that also matches `o_orderpriority` (via the same MATCH COLUMNS predicate) with a different UDF. Observe whether Databricks:

- Rejects the second attachment.
- Accepts both attachments but rejects evaluation (analogous to the column-mask multi-mask error).
- Composes the two filters (e.g., AND of both return values).

The observation discriminates among possible cross-policy combination resolutions for row filters and informs ADR-023 (the follow-on ADR being drafted for column masks).

---

## 3. Structural comparison against the existing implementation

Existing implementation shared by Brice on 2026-05-19 (after Phase 2 commit; blind-derivation property held). Brice's submission included two versions — a "stale buffer" first draft with a table-level `WHEN has_tag_value('abac_scope', 'orders_demo')` clause, and a corrected version that omits the WHEN clause. The corrected version is canonical for the comparison; the first draft's design surface is captured separately in §3.3.

### 3.1 Line-by-line: Tessera vs. existing

| Dimension | Existing (`priority_rls` + `filter_priority_abac`) | Tessera-derived | Category |
|---|---|---|---|
| UDF function name | `filter_priority_abac` | `tessera__abac_row_filter_priority__filter` | **Accepted divergence**. |
| UDF parameter | `orderpriority STRING` | `priority STRING` | **Accepted divergence**. |
| `RETURNS BOOLEAN` | Explicit | Explicit | **Match.** |
| WHEN branch 1 — `all_priority_ops` THEN TRUE | Yes | Yes | **Match** verbatim. |
| WHEN branch 2 — `high_priority_ops` THEN `IN ('1-URGENT', '2-HIGH')` | Yes | Yes | **Match** verbatim. |
| ELSE branch | `NOT IN ('1-URGENT', '2-HIGH')` | `IN ('3-MEDIUM', '4-NOT SPECIFIED', '5-LOW')` | **Real divergence — same observable behavior on current data, different intent under data evolution.** See §3.2. |
| `GRANT EXECUTE ON FUNCTION` | **Absent** | **Present** | **Real divergence**, same as prior exercises (issue #10). |
| Policy name | `priority_rls` | `tessera__abac_row_filter_priority` | **Accepted divergence**. |
| Policy attachment scope | `ON SCHEMA bg_rls_demo.tpch` | `ON CATALOG bg_rls_demo` | **Real divergence.** See §3.4. |
| `COMMENT` | Yes | Yes | **Match on form**, content differs. |
| `ROW FILTER fn` | Same | Same | **Match.** |
| `TO account users` | Same | Same | **Match.** No EXCEPT in either (Mechanism B). |
| `FOR TABLES` | Same | Same | **Match.** |
| Table-level `WHEN has_tag_value(...)` | **Absent** in final; **present** in first draft (see §3.3) | **Absent** | **Match on the final**, but see §3.3 for the design surface implication. |
| `MATCH COLUMNS has_tag_value('abac_column', 'orderpriority') AS alias` | Same (`AS pri`) | Same (`AS priority_col`) | **Match** on form; alias names differ. |
| `USING COLUMNS (alias)` | Same (`(pri)`) | Same (`(priority_col)`) | **Match.** |

The substantive structural match is **very tight**. The Tessera derivation independently reached the same Mechanism-B shape — UDF with CASE branches, broad `TO account users`, `MATCH COLUMNS` + `USING COLUMNS`. Two findings of real consequence (the ELSE branch form and the scope choice) plus one platform-design surface the Tessera IR doesn't yet model (§3.3).

### 3.2 ELSE branch form: `NOT IN` vs explicit enumeration (recurring finding)

Brice's UDF ELSE branch: `orderpriority NOT IN ('1-URGENT', '2-HIGH')`.
Tessera's UDF ELSE branch: `priority IN ('3-MEDIUM', '4-NOT SPECIFIED', '5-LOW')`.

**For the current TPC-H data**, both produce identical observable behavior: priorities 3, 4, 5 visible to default-branch principals.

**Under data evolution**, the two diverge:

- A new priority value (e.g., `'6-EMERGENCY'`) added to the orders table: Brice's form admits it (it is `NOT IN ('1-URGENT', '2-HIGH')`); Tessera's form excludes it.
- The two encode different intent: Brice's "show everything except high-priority"; Tessera's "show specifically the three medium/low priorities."

This is the **same finding as the original group row-visibility exercise's §3.5 Finding 1**. Brice's pattern is consistent across both his row-visibility implementations (legacy `SET ROW FILTER` + ABAC); his idiom is `NOT IN ('1-URGENT', '2-HIGH')` for the default branch. Tessera's derivation continues to use the explicit-enumeration form because the inputs §4.1 specified it that way.

**The Tessera IR can express either form.** The current Phase 2 YAML carries:

```yaml
defaultBranch:
  effect: keep-matching-rows
  condition:
    op: in
    operands: [column:$matched]
    values: ["3-MEDIUM", "4-NOT SPECIFIED", "5-LOW"]
```

A Brice-style "NOT IN" Tessera variant would be:

```yaml
defaultBranch:
  effect: keep-matching-rows
  condition:
    op: not
    operands:
      - op: in
        operands: [column:$matched]
        values: ["1-URGENT", "2-HIGH"]
```

(Using the closed condition algebra's `not` combinator over an `in` sub-condition.)

The choice is policy-author intent, not an IR limitation. The recurring observation across two exercises now suggests a small documentation addition: the Tessera inputs template could prompt the author to choose between enumeration (more restrictive under data evolution) and negation (more permissive). Not a v1 spec finding; just a UX recommendation.

### 3.3 Two-axis attribute matching (table-level + column-level) — new finding

Brice's submission included **two versions** of the policy DDL:

- The *first draft* (before "stale buffer") had `FOR TABLES WHEN has_tag_value('abac_scope', 'orders_demo') MATCH COLUMNS has_tag_value('abac_column', 'orderpriority') AS pri`.
- The *corrected final* omits the WHEN clause: `FOR TABLES MATCH COLUMNS has_tag_value('abac_column', 'orderpriority') AS pri`.

The setup script still applies the `abac_scope = orders_demo` tag to the table even in the final version. The intent — visible in Brice's *Assumptions* section — is to support a pattern where:

- Tables that should be "in scope" for ABAC management get tagged `abac_scope = orders_demo` (a *table-level* tag).
- Columns within those tables that drive specific policies get tagged `abac_column = ...` (a *column-level* tag).
- Policies attach at schema/catalog scope and narrow attachment via the WHEN clause (table tag) AND/OR the MATCH COLUMNS clause (column tag).

This is **two-axis attribute matching**: the policy filters which tables it applies to (by table-level attribute) AND which columns within those tables it operates on (by column-level attribute).

Tessera's `matching.attributes` shape is **single-axis** (column-level only):

```yaml
appliesTo:
  selector: byScope
  scope: catalog:bg_rls_demo
  matching:
    attributes:
      bg:rowDiscriminator: orderpriority   # column attribute
```

There is no place to add a *table-level* attribute predicate. To express Brice's `WHEN has_tag_value('abac_scope', 'orders_demo')`, the Tessera shape would need something like:

```yaml
appliesTo:
  selector: byScope
  scope: catalog:bg_rls_demo
  matching:
    resource:
      attributes:
        bg:abacScope: orders_demo     # table attribute (proposed)
    column:
      attributes:
        bg:rowDiscriminator: orderpriority    # column attribute (existing shape)
```

**This is a new v1 candidate.** ADRs 018–021 give Tessera the IR shape for attribute axes and scoped attachment, but the *two-tier matching* (resource-level predicate + column-level predicate) isn't modeled. ABAC supports both axes; Tessera would benefit from being able to express both.

**Why the design matters even though Brice's final omits the WHEN:**

- The `abac_scope` tag is applied to the table in setup, not in the policy. It exists as metadata that another policy *could* use even though `priority_rls` currently doesn't.
- Brice's *Assumptions* section explicitly describes the intent ("Tag the table so the schema-scoped policies only apply to this demo table").
- For real customers deploying ABAC alongside legacy mechanisms, the table-tag-narrowing pattern is the safe-migration recommendation — they tag the new ABAC-managed tables, and ABAC policies narrow via `WHEN` to avoid affecting legacy tables.

**Proposed candidate naming:** `policy-two-axis-attribute-matching` (or similar). v1 design surface; not blocking the Stage 4 ABAC additions but a natural follow-on.

**On the optionality of the scope tag:** Brice's clarification (2026-05-19) confirms that the `abac_scope` table-level tag and the corresponding `WHEN has_tag_value(...)` policy clause are **optional design surface**. They are used when the requirement needs to narrow the policy's table-attachment beyond what `MATCH COLUMNS` alone provides; they are omitted when the policy's column-tag predicate is sufficient. Two-axis matching becomes important precisely when the column predicate is too broad (e.g., a tag used across multiple business domains) and a table-level predicate is needed to disambiguate. Tessera v0 cannot express this case; the v1 candidate would.

### 3.4 Schema vs. catalog scope (recurring finding)

Same as the ABAC column-mask exercise's §3.4. Brice consistently chooses `ON SCHEMA bg_rls_demo.tpch`. Tessera's Phase 1 inputs defaulted to catalog scope and the derivation followed. Both valid; Brice's is narrower.

**Pattern observation across exercises:** When the inputs don't specify scope explicitly, the natural-language hint ("a row-visibility policy on `bg_rls_demo.tpch.orders_abac`") suggests *table* scope; Brice generalizes to *schema* scope; my interpretation generalized to *catalog* scope. The three are valid for different reasons — table is narrowest, catalog is broadest, schema is the sensible middle. The Phase 1 inputs template for future ABAC exercises should make the scope choice explicit so the divergence stops recurring.

### 3.5 GRANT EXECUTE asymmetry (recurring finding)

Same as all prior exercises. Brice's impl omits `GRANT EXECUTE ON FUNCTION`; the Tessera derivation emits it defensively. Issue #10 (`policy-execute-grants`) remains the canonical place this lives.

### 3.6 ABAC + legacy mechanism coexistence — platform context worth recording

Brice's *Assumptions* section captures real platform behavior:

> *"ABAC and table-level filters/masks can coexist, but if they resolve to different functions for the same table and user, Databricks blocks access."*

This is structurally analogous to the multi-mask rejection observed in the prior ABAC column-mask exercise, but at the **cross-mechanism boundary** (ABAC row filter alongside legacy `ALTER TABLE … SET ROW FILTER`). Same shape, different boundary.

**Implication for Tessera:** the Databricks adapter's capability profile should declare the constraint that *for any single column, only one row-filter mechanism may apply*. This generalizes the column-mask-conflict-detection v1 candidate (filed from the prior exercise) to cover both column masks and row filters, both within-ABAC and across-mechanism. Folds naturally into the same v1 candidate; doesn't need a separate one.

### 3.7 What Tessera adds (confirmed pattern across exercises)

Same as prior exercises:

| Element | Tessera form | Existing implementation |
|---|---|---|
| Canonical IR form | `.tessera.yaml` + `.jsonld` | None |
| Declared `defaultStrategy: negated-complement` | Explicit | Implicit (in the CASE's ELSE) |
| Adopter-namespaced axis (`bg:rowDiscriminator`) | Declared in IR; surfaces design gap | Implicit (the column tag IS the discriminator marker) |
| Tag-taxonomy mapping | Configurable per environment | Hardcoded in the SQL DDL |
| Provenance | Header comments link back to policy ID | None |
| Diagnostic + Comparison | Present | None |
| Capability requirements declared | `scoped-policy-attachment`, `attribute-axis-matching`, `tag-taxonomy-mapping`, `matched-column-reference` | None |

### 3.8 What the existing implementation has that Tessera does not capture

- **The `abac_scope` table-level tag and the design pattern around it** (§3.3). The new v1 candidate.
- **Brice's design commentary** in the *Assumptions* and prose. Tessera's IR carries machine-readable structure but not human-targeted prose explaining design choices. The diagnostic/comparison documents serve some of this purpose at the artifact level; nothing equivalent exists at the policy-file level. Not a finding — Tessera's IR being prose-free is correct — but worth noting that the existing impl carries more design context than the IR alone.
- **The `NOT IN` ELSE form as the author's actual idiom.** Tessera captured the inputs' enumeration form; Brice's actual preference is negation. Not a Tessera gap — both forms are expressible — but a UX observation.

---

## 4. Lessons for v0

### 4.1 v0 spec changes for Stage 4 — proceed as planned

Phase 3 deployment (Scenario 3) and structural comparison did not surface design problems with ADRs 018–021. The ABAC vocabulary holds up: `byScope` attached cleanly; `matching.attributes` translated to the verified `MATCH COLUMNS` predicate; the structured TransformationInstance / Boolean-UDF emission worked. Stage 4 can proceed.

### 4.2 Findings carried from Phase 2 (in the diagnostic)

- **Axis-naming gap (`bg:rowDiscriminator`)** — v1 candidate; choice between adding a well-known axis or documenting adopter-extensibility.
- **Condition-operand reference (`column:$matched`)** — v1 candidate; formalize a reserved identifier.
- **Mechanism A vs B collapses for multi-branch row filter** — observation; document in technical design.

### 4.3 New findings from the structural comparison

- **`policy-two-axis-attribute-matching` (new v1 candidate, §3.3).** The platform supports table-level matching (WHEN) plus column-level matching (MATCH COLUMNS); Tessera's `matching.attributes` is single-axis. The two-axis shape is worth designing.
- **ELSE branch idiom — enumeration vs negation (§3.2).** Recurring finding from the original group exercise. Both forms expressible in Tessera; the inputs template could prompt the author to choose explicitly. UX observation, not a spec change.
- **Schema vs catalog scope (§3.4).** Recurring; the Phase 1 inputs template should make scope explicit so the divergence stops recurring across exercises.
- **ABAC + legacy mechanism conflict (§3.6).** Platform context; folds into the existing `column-mask-conflict-detection` v1 candidate by generalizing to row filters and cross-mechanism cases.

### 4.4 Recurring findings reinforced

- **GRANT EXECUTE asymmetry** — same pattern as all prior exercises (issue #10).
- **Cosmetic divergences accepted** — function names, alias names, comment content all diverge cosmetically; semantically equivalent.

---

## 5. Recommended actions

1. ✓ **Deploy Tessera-derived SQL** — done 2026-05-19.
2. ✓ **Scenario 3 observation** — done; passes.
3. ✓ **Brice shares existing implementation** — done; §3 populated.
4. **Scenarios 1 and 2 (optional)** — empirical verification of the WHEN branches above the ELSE in the CASE expression. Structural argument from §3.1 is already strong; empirical confirmation is icing.
5. **File new v1-candidate issue: `policy-two-axis-attribute-matching`** (from §3.3).
6. **Update Phase 1 inputs template** to prompt the author about ELSE form (enumeration vs negation) and scope choice (table vs schema vs catalog).
7. **Continue or extend the prior `column-mask-conflict-detection` v1 candidate** to cover row filters and cross-mechanism conflicts (§3.6).

---

## 6. What this comparison did not do

- **Did not empirically verify Scenarios 1 and 2.** The structural argument is strong (deterministic CASE expression; first-match ordering matches IR; ELSE branch verified via Scenario 3). Empirical verification of the WHEN branches above the ELSE would confirm what the structural argument already establishes.
- **Did not test multi-row-filter cross-policy combination.** Optional follow-on per §2.2.
- **Did not test the `WHEN has_tag_value(...)` table-level matching pattern.** §3.3's new v1 candidate could drive a follow-on exercise that constructs a second tagged table to validate the two-axis matching shape.

---

## 7. Closing observation

This exercise's structural comparison surfaced one new v1 candidate (`policy-two-axis-attribute-matching`) and reinforced several existing findings. The pattern across the worked-example series is now visible:

- The first ABAC exercise (column mask) surfaced **mechanism choice** (Mechanism A vs B) and the **cross-policy combination question** (γ-resolution for multi-mask on same column).
- This second ABAC exercise (row filter) surfaces **two-axis matching** (table-level + column-level attribute predicates) and reinforces the mechanism choice (forced to B for multi-branch).
- Both reinforce the recurring **scope choice** (schema vs catalog) and **ELSE form** (enumeration vs negation) findings the original group exercise also surfaced.

The Tessera framework's value-add holds up across mechanisms (column mask vs row filter), across exercises (legacy vs ABAC), and across the blind-derivation property (Phase 2 reached the same shape independently, with the right kinds of divergences surfacing as findings). The next worthwhile exercise would either:

- Validate two-axis matching by constructing a multi-table scope scenario, or
- Drive ADR-023 (cross-policy combination resolution) by deploying conflicting row filters, or
- Pivot to the SHACL or converter work that's been queued behind the exercise series.

Brice's call.
