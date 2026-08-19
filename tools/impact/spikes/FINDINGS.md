# Spike findings — graph surface (Layer 1) and request enumeration (Layer 2)

**Status:** Spike record, 2026-08-05. Exploratory; informs whether to pursue a graph-backed interaction surface (Layer 1) and a request-space evaluator (Layer 2) for change-impact analysis. Code in `tools/impact/spikes/`; not wired into the shipped tool.

These spikes answer two questions from the design conversation: does querying the corpus as an RDF graph buy us more than the Python checks, and can we detect "unintentional access opened/closed" by enumerating the abstract request space?

> **Update 2026-08-05.** Spike 1's blocker is resolved. The graph finding below (attribute values don't resolve to `vocab#` IRIs, so ontology subsumption can't reach them) drove **ADR-028**: `sensitivity` is now `"@type": "@vocab"` and the context declares a top-level `@vocab`. Bare values now resolve to the Tessera namespace and the `subClassOf*` property path reaches the ontology; adopter-specific values carry an explicit prefix (`acme:PIIClerk`) and stay outside Tessera subsumption. The Layer-1 recommendation "defer until the corpus adopts CURIE-resolvable values" is thus **discharged**: that corpus/context change has been made. The spike's original text is left below as the record that motivated the ADR.

---

## Spike 1 — corpus as a graph (`graph_surface.py`)

**What works.** Loading the ontology + policy JSON-LD into one rdflib graph and running SPARQL is straightforward (no network; the context is inlined). SELECT queries extract each policy's attachment target and attribute matches cleanly. Genuine ontology subsumption via a property path works: with two policies matching `tessera:PII` and `tessera:PHI`, this one line

```sparql
?p1 t:appliesTo/t:matching/t:attributesMap/t:sensitivity ?v1 .
?p2 t:appliesTo/t:matching/t:attributesMap/t:sensitivity ?v2 .
?v2 rdfs:subClassOf* ?v1 .
```

correctly finds that the PII policy covers the PHI policy (and not the reverse). The graph buys transitive hierarchy traversal for free, where the Python kernel hand-loads a transitive closure.

**The catch.** On the *current corpus* that subsumption query returns nothing useful, because the example policies author attribute values as **bare terms** (`sensitivity: PIIClerk`) and the context has no `@vocab`. So the values do not expand to `vocab#` IRIs; they expand against the document base to junk (`file:///…/PIIClerk`), and the ontology cannot reach them. Worse: the property path *appears* to return matches, but only **reflexively** (identical values match `subClassOf*` at length zero), which looks like subsumption reasoning while the ontology contributes nothing. A naive reading would give false confidence.

Verified both directions:
- Bare `PIIClerk` values → `subsumption_reachable: False`, values unresolved.
- CURIE `tessera:PII` / `tessera:PHI` values → `subsumption_reachable: True`, PII→PHI edge found correctly.

**Scope containment is a wash.** `catalog:acme ⊇ table:acme.tpch.orders` is dotted-path string logic whether done in SPARQL or Python; the graph doesn't win here. Against the committed corpus the graph surfaced exactly the one nesting pair C4 already finds (the two ABAC clerk masks).

**Conclusion (Layer 1).** The graph's one genuine advantage, ontology-driven attribute subsumption, is **blocked by a corpus/context modeling gap, not a tooling gap**. Unlocking it requires authoring attribute values as CURIEs (or adding `@vocab` to the context) *and* using declared ontology classes. That is a spec/authoring decision, and arguably a good one, since it would let C4/L2 and future reasoning lean on the ontology instead of a hand-maintained closure. Until then, a graph-backed interaction surface is not worth building: it would duplicate the Python checks and mislead on subsumption. **Recommendation: defer Layer 1; if pursued, do the CURIE/`@vocab` corpus change first (own ADR), then the graph reasoning becomes a thin, principled layer.**

---

## Spike 2 — within-policy request enumeration (`request_enum.py`)

**What it does.** Enumerates the finite abstract request space a single policy discriminates (the product of "does the principal match selector S?" over the distinct selectors, and "which value-class is column C in?" over the mentioned condition values), evaluates the policy's ordered first-match decision (ADR-015) on each, and diffs two versions, reporting every abstract request whose decision flips, classified OPENED / CLOSED / CHANGED by effect polarity.

**It works, and it's more precise than C6.** On Exercise 1 (remove Rule A2 from `group-row-visibility-policy-a`) it reports **4 CLOSED** flips, each a concrete witness: `group:acme_high_priority_ops` on `1-URGENT` and `2-HIGH` (with and without co-membership in `account-users`). C6 says "NARROW for the selector"; the enumeration says *exactly which (principal, priority) combinations lost access*. On the innocent-looking widening (add `3-MEDIUM` to the high-ops rule) it reports **1 OPENED** flip naming precisely the request that gained access. On a semantically inert reorder (swap two rules with disjoint principals and conditions) it reports **0** flips: it *proves* the reorder changed nothing, which neither C3 nor C6 does.

**Honest limits, by construction.**
- **Opaque operators.** Conditions beyond `in`/`eq` on a single column (notably `exists-in-dataset` / ACL selectors) are not enumerable; the spike surfaces them as an explicit note rather than mis-evaluating them. The ADR-001 data line reappears exactly where expected.
- **Principal over-approximation.** Selectors are treated as independent booleans, so the space includes principal combinations real membership might forbid (matching two disjoint groups). This can over-report a flip, never miss one: sound for a safety check, and refinable with a declared-disjointness assertion (scoping-doc §9.3).

**Conclusion (Layer 2, within-policy).** The within-policy request diff is worth pursuing. It directly answers "did this edit open or close access, and for which requests" for the attribute/enumerable slice, needs no solver and no combining commitment, stays behind ADR-001, and is strictly more informative than the shipped C6. It generalizes C6 from a per-rule heuristic to a per-request decision diff, and subsumes part of C3 (an unreachable rule is one that changes no request's decision).

---

## Recommendation

1. **Promote Spike 2 toward a real check.** A within-policy request-space diff with witnesses. It is what the original concern ("innocent change quietly opens/closes access") actually needs. Next step would be hardening (larger spaces, range conditions via interval classes) and deciding whether it replaces or complements C6.
2. **Cross-policy is the following step.** It applies the bracket / `[floor, ceiling]` model from the design chat: the same enumeration machinery, evaluating the corpus under the floor/ceiling bounds so guarantees are implementation-independent and the ambiguous zone is flagged. That step wants the ADR that states the faithfulness assumptions (not a combining algorithm).
3. **Hold Spike 1 (graph)** until the corpus adopts CURIE attribute values. The subsumption win is real but contingent; today the graph would duplicate Python and risk the reflexive-match trap.

The through-line: the semantic substrate pays off at Layer 2 (enumeration over the finite attribute space) more readily than at Layer 1 (graph queries), because the payoff of the graph is gated on a modeling convention the corpus hasn't adopted, while enumeration works on the policies as they are.
