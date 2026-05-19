# Issue drafts

Staging area for issues queued to be filed against `bgiesbrecht/tessera`. Keeping drafts here lets them be reviewed and edited before filing, and keeps a record of intent under version control.

## How to use

1. Write the issue body as a Markdown file (the first H1 is **not** the title — pass the title separately).
2. With `gh` authenticated to `bgiesbrecht`, file with:
   ```bash
   gh issue create --label <label> --title "<title>" --body-file docs/issue-drafts/<file>.md
   ```
3. Once filed, delete the draft file (the live issue is now the source of truth).

## Filed history

| Date | Issue | Title | Status |
|---|---|---|---|
| 2026-05-18 | [#1](https://github.com/bgiesbrecht/tessera/issues/1) | policy-container — first-class multi-branch policy primitive | open |
| 2026-05-18 | [#2](https://github.com/bgiesbrecht/tessera/issues/2) | default-branch-predicate — default-branch row predicate on the policy container | open |
| 2026-05-18 | [#3](https://github.com/bgiesbrecht/tessera/issues/3) | principal-in-group-condition — group-membership operator in the condition algebra | open |
| 2026-05-18 | [#4](https://github.com/bgiesbrecht/tessera/issues/4) | iri-safety-convention — dual-identifier carrier pattern for non-IRI-safe platform names | open |
| 2026-05-18 | [#5](https://github.com/bgiesbrecht/tessera/issues/5) | adapter-emission-pattern-recognition — negated-complement → readable-ELSE expectation | open |
| 2026-05-18 | [#6](https://github.com/bgiesbrecht/tessera/issues/6) | adapter-capability-profile-timing-disclosure — extend §5.2 to cover per-mechanism timing disclosure | closed-on-arrival (paragraph landed in same revision) |
| 2026-05-18 | [#7](https://github.com/bgiesbrecht/tessera/issues/7) | principal-set-from-joined-tables — multi-table support for data-driven principal sets | open (ACL exercise) |
| 2026-05-18 | [#8](https://github.com/bgiesbrecht/tessera/issues/8) | principal-set-match-modifiers — case-insensitive / trim match flag on PrincipalSetFromTable | open (ACL exercise) |
| 2026-05-18 | [#9](https://github.com/bgiesbrecht/tessera/issues/9) | exists-in-dataset-operand-formalization — formal operand shape for the existsInDataset operator | open (ACL exercise) |
| 2026-05-18 | [#10](https://github.com/bgiesbrecht/tessera/issues/10) | policy-execute-grants — declare function-execute grants in the IR | closed by ADR-025 (table-grants exercise) |
| 2026-05-18 | [#11](https://github.com/bgiesbrecht/tessera/issues/11) | acl-integrity-checks — surface silent failure modes in data-driven access patterns | open (ACL exercise, lower priority) |
| 2026-05-19 | [#12](https://github.com/bgiesbrecht/tessera/issues/12) | policy-two-axis-attribute-matching — table-level + column-level attribute predicates | open (ABAC row-filter exercise) |
| 2026-05-19 | [#13](https://github.com/bgiesbrecht/tessera/issues/13) | resourcecolumn-conflation — ResourceSetFromTable.resourceColumn carries two distinct identifiers | open (Snowflake byDataset exercise) |
| 2026-05-19 | [#14](https://github.com/bgiesbrecht/tessera/issues/14) | snowflake-role-discrimination-semantics — primary vs active role discrimination | open (reframing of secondary-roles finding per claude.ai) |
| 2026-05-19 | [#15](https://github.com/bgiesbrecht/tessera/issues/15) | access-grant-constraint-policykind — affirmative-grant policyKind missing from v0 | open (table-grants exercise) |

## Queued

None at present.
