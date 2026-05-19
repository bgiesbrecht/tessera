# Tessera and the W3C stack

**Audience:** semantic-web practitioners, ontologists, knowledge-graph engineers, and anyone who reaches reflexively for RDF when modeling cross-domain semantics. This document is a tour of *how* Tessera uses W3C technologies — vocabulary, serialization, validation, alignment — and *why* the choices look the way they do.

Tessera is a portable representation of data governance policy across data platforms. The semantic-web stack is not bolted on; it is the spine. Policy authoring is YAML for ergonomics, but the canonical form is JSON-LD, the formal semantics live in OWL, validation is split between JSON Schema and SHACL, and alignment to existing privacy and rights vocabularies is declared with SKOS. The whole architecture exists *because* the value proposition — "PII means the same thing on Databricks and Snowflake" — is a semantic claim, not a syntactic one. The cleanest way to make a semantic claim is to write down the semantics.

---

## The four artifacts

```
spec/v0/
  ontology.ttl       # OWL 2 ontology, Turtle serialization (~880 lines, 567 triples)
  context.jsonld     # JSON-LD 1.1 context (the canonical form's namespace machinery)
  shapes.ttl         # SHACL shapes graph (~360 triples)
  schema.json        # JSON Schema 2020-12 (structural pre-validation)
```

They coordinate. The ontology is the source of truth for the vocabulary; the context maps the authoring short-names to ontology IRIs; the shapes constrain documents-as-RDF; the JSON Schema does the structural pass that SHACL would express verbosely. Each is dereferenceable on its own; each is also internally referenced by the others.

```
https://bgiesbrecht.github.io/tessera/spec/v0/vocab#      → namespace
https://bgiesbrecht.github.io/tessera/spec/v0/ontology.ttl
https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld
https://bgiesbrecht.github.io/tessera/spec/v0/shapes.ttl
```

The namespace IRI is opaque — `tessera:Policy` resolves to `https://bgiesbrecht.github.io/tessera/spec/v0/vocab#Policy`, the Turtle file is what dereferences. This is ADR-011's persistent-URL choice; GitHub Pages serves the artifacts with whatever content types it serves them under (yes, `text/plain` on a `.ttl` — pragmatic, not pretty). The persistent-IRI discipline survives the content-type pragmatism.

---

## The ontology

`spec/v0/ontology.ttl` is an OWL 2 ontology in Turtle. Standard prefixes:

```turtle
@prefix tessera: <https://bgiesbrecht.github.io/tessera/spec/v0/vocab#> .
@prefix owl:     <http://www.w3.org/2002/07/owl#> .
@prefix rdf:     <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs:    <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:     <http://www.w3.org/2001/XMLSchema#> .
@prefix dpv:     <https://w3id.org/dpv#> .
@prefix odrl:    <http://www.w3.org/ns/odrl/2/> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix skos:    <http://www.w3.org/2004/02/skos/core#> .
```

The core classes mirror the principal / resource / action / effect / constraint shape any policy vocabulary lands on, plus the data-governance-specific machinery (transformations, obligations, attribute axes):

```turtle
tessera:Policy a owl:Class ;
    rdfs:subClassOf tessera:Entity ;
    rdfs:label "Policy"@en ;
    rdfs:comment "Multi-rule policy container per ADR-014. Holds policy-level
                  metadata (appliesTo, action, defaultStrategy) plus an ordered
                  rules list."@en .

tessera:RowVisibilityConstraint a owl:Class ;
    rdfs:subClassOf tessera:PolicyConstraint .

tessera:ColumnVisibilityConstraint a owl:Class ;
    rdfs:subClassOf tessera:PolicyConstraint .

tessera:Action a owl:Class ;
    rdfs:subClassOf tessera:Entity .

tessera:Read     a tessera:Action ; rdfs:label "Read"@en .
tessera:Execute  a tessera:Action ; rdfs:label "Execute"@en ;
    rdfs:comment "Invoke a callable Resource (typically a UDF or stored
                  procedure). Scoped to policy intent; platform-mechanism
                  uses of EXECUTE remain adapter scaffolding, not modeled
                  in the IR."@en .
```

The well-known-individuals pattern — `tessera:Read a tessera:Action` rather than `tessera:Read rdf:type tessera:Action` — is intentional. Actions are *named individuals*, not subclasses, because they are the closed enumeration of action verbs the IR commits to. The same pattern applies to attribute axes (`tessera:sensitivityAxis a tessera:AttributeAxis`), well-known effects, condition operators, and the four core attribute axes (sensitivity, dataSubject, regulatoryRegime, businessDomain — three flat, sensitivity hierarchical).

**Hierarchy where it carries weight.** Tessera's `Classification` class (the sensitivity axis) has real subsumption:

```turtle
tessera:Classification a owl:Class .
tessera:Confidential   a owl:Class ; rdfs:subClassOf tessera:Classification .
tessera:PII            a owl:Class ; rdfs:subClassOf tessera:Confidential .
tessera:Restricted     a owl:Class ; rdfs:subClassOf tessera:Confidential .
```

So `tessera:PII rdfs:subClassOf+ tessera:Classification` — a policy that gates on `Confidential` correctly covers `PII`-tagged data after rdfs inference. This is the one place v0 leans on RDFS reasoning at validation time; the rest is shapes-driven and inference-light.

**Properties** are typed:

```turtle
tessera:appliesTo a owl:ObjectProperty ;
    rdfs:domain tessera:Policy ;
    rdfs:range tessera:ResourceSelector .

tessera:action a owl:ObjectProperty ;
    rdfs:range tessera:Action .

tessera:replacement a owl:DatatypeProperty ;
    rdfs:domain tessera:Redact ;
    rdfs:range xsd:string .
```

Domain and range declarations are documentation, not enforcement — the SHACL shapes do the actual constraint work. This is the pragmatic split that experienced semantic-web practitioners will recognize: OWL describes what the world looks like; SHACL enforces what a document must look like.

---

## JSON-LD 1.1 as the canonical form

Policy authoring is `.tessera.yaml` for ergonomics — comments, multi-line strings, no escaping of typical SQL — but the canonical form is JSON-LD 1.1. The context (`spec/v0/context.jsonld`) does the mapping:

```jsonld
{
  "@context": {
    "@version": 1.1,
    "@protected": true,
    "tessera": "https://bgiesbrecht.github.io/tessera/spec/v0/vocab#",
    "dpv":     "https://w3id.org/dpv#",
    "odrl":    "http://www.w3.org/ns/odrl/2/",

    "Policy":               "tessera:Policy",
    "RowVisibilityConstraint": "tessera:RowVisibilityConstraint",

    "appliesTo": { "@id": "tessera:appliesTo", "@type": "@id" },
    "principal": { "@id": "tessera:principal", "@type": "@id" },
    "action":    { "@id": "tessera:action",    "@type": "@vocab" },
    "effect":    { "@id": "tessera:effect",    "@type": "@vocab" },

    "Read":      "tessera:Read",
    "Write":     "tessera:Write",
    "Execute":   "tessera:Execute",

    "rules":     { "@id": "tessera:rules", "@container": "@list" }
  }
}
```

A few choices worth calling out for an audience that's actually read the JSON-LD 1.1 spec:

- **`@protected: true`** prevents downstream consumers from silently redefining terms. Adopters can extend the vocabulary in their own namespaces; they cannot rebind `tessera:Read` to something else.
- **`@version: 1.1`** opts into the 1.1 features actively used: scoped contexts (not used yet, but available), `@nest`, and the stricter expansion rules.
- **`@type: @vocab`** on `action` and `effect` lets authors write `"action": "Read"` rather than `"action": "tessera:Read"`. The expansion resolves against the active vocabulary, which falls back to `tessera:` per the namespace declaration. This is the JSON-LD machinery that gives YAML authoring its readability.
- **`@type: @id`** on `appliesTo` and `principal` keeps these as resource references rather than literal strings.
- **`@container: @list`** on `rules` — the rules list is ordered (per ADR-015's first-match combining), and JSON-LD's `rdf:List` semantics preserve order. Standard Container Container, but worth flagging: SHACL list-validation requires traversing `rdf:rest`/`rdf:first` paths (see "Shapes" below).

A policy in canonical form:

```jsonld
{
  "@context": "https://bgiesbrecht.github.io/tessera/spec/v0/context.jsonld",
  "@type": "Policy",
  "@id": "policy:group-row-visibility-policy-a",
  "policyKind": "RowVisibilityConstraint",
  "appliesTo": {
    "selector": "byIdentity",
    "resource": "table:bg_rls_demo.tpch.orders"
  },
  "action": "Read",
  "defaultStrategy": "explicit-baseline-group",
  "rules": [
    { "principal": { "selector": "byIdentity",
                     "resource": "group:bg_rls_demo_all_priority_ops" },
      "effect": "keep-matching-rows" }
  ]
}
```

Expanded against the context, this graph carries everything the validators need. The IRIs prefixed `table:`, `group:`, `function:` are informally-conventional resource identifiers — the IR layer treats them as opaque strings; the adapter resolves them to platform identifiers via per-environment configuration (`identity_bindings`, `resource_bindings` — the adapter-configuration-mapping pattern, ADR-021).

---

## SHACL shapes

`spec/v0/shapes.ttl` declares the constraints that go beyond JSON Schema's structural reach. A representative shape:

```turtle
tessera:PolicyShape a sh:NodeShape ;
    sh:targetClass tessera:Policy ;

    sh:property [
        sh:path tessera:policyKind ;
        sh:minCount 1 ;
        sh:in (
            tessera:RowVisibilityConstraint
            tessera:ColumnVisibilityConstraint
            tessera:AccessConstraint
            tessera:DistributionConstraint
        ) ;
    ] ;

    sh:property [
        sh:path tessera:appliesTo ;
        sh:minCount 1 ; sh:maxCount 1 ;
        sh:node tessera:ResourceSelectorShape ;
    ] ;

    sh:property [
        sh:path tessera:action ;
        sh:minCount 1 ;
        sh:in (
            tessera:Read tessera:Write tessera:Delete
            tessera:Share tessera:Sample tessera:Aggregate
            tessera:Execute
        ) ;
    ] ;

    sh:property [
        sh:path ( tessera:rules [ sh:zeroOrMorePath rdf:rest ] rdf:first ) ;
        sh:node tessera:PolicyRuleShape ;
    ] .
```

Three pragmatic decisions are worth showing off because they're the kind of thing that comes from actually shipping a SHACL graph against JSON-LD documents:

### 1. `sh:node` over `sh:targetClass` for blank-node shapes

`PolicyShape` uses `sh:targetClass tessera:Policy` — fine, because the root node has `@type: Policy`. But nested selectors and conditions are JSON-LD blank nodes, and the JSON-LD-to-RDF conversion does not assert `@type` on them. So a shape that tries to use `sh:targetClass tessera:ResourceSelector` will never fire — there's no triple `_:b1 rdf:type tessera:ResourceSelector` to target.

The clean fix is to invoke the shape via `sh:node` from the containing shape's property:

```turtle
sh:property [
    sh:path tessera:appliesTo ;
    sh:node tessera:ResourceSelectorShape ;
] ;
```

`ResourceSelectorShape` itself drops `sh:targetClass` entirely. It's only invoked when something else points at it. This pattern shows up across every blank-node-shaped element: `PrincipalSelectorShape`, `ConditionShape`, `AttributeMatcherShape`, `TransformationInstanceShape`.

### 2. List validation via property-path traversal

Validating each rule in an ordered `rules` list requires traversing the `rdf:List` structure that JSON-LD's `@container: @list` produces. SHACL's property-path syntax handles it cleanly:

```turtle
sh:property [
    sh:path ( tessera:rules [ sh:zeroOrMorePath rdf:rest ] rdf:first ) ;
    sh:node tessera:PolicyRuleShape ;
] ;
```

Reads as: starting from the focus node, follow `tessera:rules` to the list head; then zero or more `rdf:rest` hops; then `rdf:first` to land on each list member. Every member must conform to `PolicyRuleShape`. The path syntax handles the recursion; the shape handles the per-member constraints.

### 3. Closed-vocabulary checks SHACL adds that JSON Schema cannot

Some constraints are expressible in JSON Schema (enum closure on string values; required fields). Others are not:

- **Class typing of IRI references.** `axis: sensitivityAxis` expands to `tessera:sensitivityAxis`; SHACL's `sh:class tessera:AttributeAxis` enforces that the referenced node is a member of the AttributeAxis class. JSON Schema cannot see this — it's syntactic.
- **Adopter-extensible IRI value spaces.** For the hierarchical sensitivity axis, `sh:nodeKind sh:IRI` permits any IRI value (including adopter-namespaced extensions like `acme:CustomerPII`) without enumerating them. JSON Schema would require an open string but couldn't enforce IRI form.
- **Operator vocabulary closure on condition algebra.** Condition operators (`and`, `or`, `eq`, `in`, `purpose-in`, `exists-in-dataset`, ...) are well-known individuals; `sh:in (tessera:and tessera:or ...)` enforces closure at the RDF layer.

These three categories are SHACL's unique value-add in the validation pipeline. Other constraints (cardinality, required fields, type structure) are deliberately delegated to JSON Schema — see "Layered validation" below.

---

## Layered validation: JSON Schema + SHACL

The validation pipeline is two-layer by design:

| Layer | Format | Catches |
|---|---|---|
| 1 | JSON Schema 2020-12 (`schema.json`) | Structural validity, conditional dependencies, enum closure on string values, type structure of nested objects |
| 2 | SHACL (`shapes.ttl`) | Semantic well-formedness: IRI / class typing of references, closed-vocabulary on referenced IRIs, node-shape composition over blank-node structures |

JSON Schema 2020-12 is not a W3C technology but it lives next to one — it's the structural-pre-pass that lets SHACL focus on what it uniquely does. Conditional dependencies (`baselineGroup` is required iff `defaultStrategy: explicit-baseline-group`; `transformation` is required iff `effect: transform`) are JSON-Schema-enforced via `if`/`then`/`else` branches. SHACL Advanced Features' `sh:if`/`sh:then` were tried and abandoned for two reasons: pyshacl's coverage was uneven, and the JSON-Schema layer already enforces them with no semantic loss.

The principle: **each layer does what it does best.** SHACL doesn't try to be JSON Schema; JSON Schema doesn't try to be SHACL. Together they catch everything an emitter can reasonably catch without running the policy.

---

## Alignment via SKOS

Tessera deliberately does *not* formally import DPV or ODRL via `owl:imports`. The choice is documented in ADR-005 and is worth explaining to a W3C-savvy reader: formal import would mean inheriting every axiom of the imported ontology and accepting reasoning consequences that may not match Tessera's scope. Instead, term-level alignment is declared via SKOS:

```turtle
tessera:PII a owl:Class ;
    rdfs:subClassOf tessera:Confidential ;
    skos:exactMatch dpv:PersonalData .

tessera:SensitivePII a owl:Class ;
    rdfs:subClassOf tessera:PII ;
    skos:closeMatch dpv:SensitivePersonalData .

tessera:Purpose a owl:Class ;
    skos:exactMatch dpv:Purpose .

tessera:Obligation a owl:Class ;
    skos:closeMatch odrl:Duty .
```

`skos:exactMatch` declares semantic identity between terms; `skos:closeMatch` declares strong-but-not-perfect overlap. Both are conservative — they don't trigger OWL reasoning consequences; they're navigational annotations for tools and humans alike. Tooling that wants to reason across vocabularies can opt into the alignment; tooling that wants to ignore it is free to.

The four upstream vocabularies Tessera aligns with:

- **DPV** (W3C Data Privacy Vocabulary, w3id.org/dpv) — purpose, personal-data categories, processing concepts. The strongest alignment; many `skos:exactMatch` declarations.
- **ODRL** (W3C Open Digital Rights Language) — permission / prohibition / duty patterns. Used for obligation alignment.
- **Cedar** (AWS Cedar Policy Language) — principal / resource / action shape. Cedar is not a W3C vocabulary but the alignment helps Cedar-fluent readers; we link conceptually, not by IRI.
- **XACML** (OASIS, not W3C) — obligation algebra. Same posture.

Tessera's vocabulary is meant to be *recognizable* to anyone who's worked with these standards. The exact-match annotations make the recognition explicit.

---

## What the architecture enables

The W3C stack is not decoration. It enables three things that the project's value proposition depends on:

### 1. Semantic interoperability of policy across platforms

A policy that gates `tessera:PII`-tagged data on Databricks (where the platform's enforcement uses governed tags) and on Snowflake (where the platform's enforcement uses object tags) refers to the *same* `tessera:PII` IRI. The platforms' tag taxonomies are mapped to Tessera via `AdapterConfig.tag_taxonomy` per ADR-021; the IR carries the meaning, the adapter carries the mechanism. This is the cross-platform fidelity that ADR-003's "adapters are peers" framing depends on — and it works because there is a shared IRI to refer to.

### 2. Honest model of constraints across the validation pipeline

JSON Schema's strength is structural validation; SHACL's strength is semantic validation; OWL's strength is documentation of the underlying conceptual model. Layering them — each doing what it does best — produces a validation surface that is both rigorous and operationally tractable. Every existing policy round-trips through all three layers; the eight worked exercises validate end-to-end against schema + SHACL.

### 3. Extension discipline that respects existing adopters

`@protected: true` in the JSON-LD context blocks adopters from rebinding Tessera terms; adopter-namespaced extensions (their own classification subclasses, their own attribute-axis values) extend cleanly without polluting the canonical vocabulary. The ontology's persistent IRIs are conditionally immutable per ADR-017: once external dependency exists, the v0 namespace freezes; until then, additions are admissible. This is the discipline RDF and OWL were designed for and the project leans into rather than working around.

---

## What Tessera does NOT do (and why)

Listed deliberately because the omissions matter as much as the inclusions:

- **No SPARQL queries.** Tessera does not run SPARQL against policy graphs at evaluation time. Policy combination, conflict detection, and effective-rule resolution are *adapter responsibilities* — the platform's native enforcement mechanism evaluates the policy. Tessera compiles; the platform runs. SPARQL might appear in future tooling (a linter that queries the corpus for findings; a CLI that surfaces "all policies referencing axis X"), but it is not in the evaluation hot path because Tessera has no evaluation hot path.

- **No OWL DL reasoning at validation time.** The validator uses `rdfs` inference for the `Classification` subsumption (so `PII ⊑ Confidential` is honored), but does not invoke a full OWL DL reasoner. pyshacl with `inference="rdfs"` is the configuration. The reasoning load is intentionally bounded.

- **No `owl:imports` of DPV / ODRL.** Alignment via SKOS is declarative and tooling-friendly without triggering imported axioms whose consequences may not match Tessera's scope (ADR-005).

- **No SHACL Advanced Features in production.** `sh:if`/`sh:then` were experimented with and abandoned in favor of JSON-Schema-enforced conditional dependencies. The `shapes.ttl` file uses only core SHACL constraints to maximize portability across validators.

- **No standards-body submission.** ADR-002 documents the project's skunkworks posture; Tessera is not seeking W3C or IETF formalization. It is engineering practice that uses W3C tech because the technology fits the problem, not as a positioning exercise.

- **No PROV-O.** Provenance metadata is carried in JSON-LD via informal `provenance` blocks (extractedFrom, notes) and not modeled formally. If a real customer corpus surfaces the need, PROV-O alignment becomes a candidate; until then, the lightweight approach holds.

---

## The validation pipeline, end to end

Concretely, from a `.tessera.yaml` file to a green check:

```python
# 1. YAML → JSON-LD (mechanical mapping; converter tool queued)
doc = json.loads(open('your-policy.jsonld').read())

# 2. JSON Schema (structural)
import jsonschema
schema = json.loads(open('spec/v0/schema.json').read())
jsonschema.validate(doc, schema)         # raises on structural issues

# 3. SHACL (semantic)
from rdflib import Graph
from pyshacl import validate
shapes = Graph(); shapes.parse('spec/v0/shapes.ttl', format='turtle')
onto   = Graph(); onto.parse('spec/v0/ontology.ttl', format='turtle')
data   = Graph(); data.parse('your-policy.jsonld',   format='json-ld')

conforms, _, msg = validate(
    data_graph=data, shacl_graph=shapes, ont_graph=onto, inference='none')
assert conforms, msg

# 4. Adapter emission (platform-specific; capability-profile-aware)
from adapters.unity_catalog import UnityCatalogAdapter
result = UnityCatalogAdapter(config=...).emit(doc)
```

Step 3's `inference='none'` is deliberate — the rdfs subsumption that matters (for the Classification hierarchy) lives in the ontology graph supplied as `ont_graph` and pyshacl honors it. We don't run an additional inference pass over the data graph because the JSON-LD documents don't need it; they carry their assertions explicitly.

---

## Where to look in the repo

| Concern | Path |
|---|---|
| OWL ontology (Turtle) | `spec/v0/ontology.ttl` |
| JSON-LD 1.1 context | `spec/v0/context.jsonld` |
| SHACL shapes | `spec/v0/shapes.ttl` |
| JSON Schema (structural) | `spec/v0/schema.json` |
| Worked-example JSON-LDs | `spec/v0/examples/*.jsonld` (eight policies, all validating) |
| Vocabulary-alignment rationale | `DECISIONS.md` ADR-005 |
| Persistent-URL choice | `DECISIONS.md` ADR-011 |
| Immutability discipline | `DECISIONS.md` ADR-017 |
| Adapter contract (lowering to platform DDL) | `DECISIONS.md` ADR-024 |
| Architecture overview (broader scope) | `docs/technical-design-v0.2.md` |

The single concrete starting point for a W3C-savvy reader: open `spec/v0/ontology.ttl` and `spec/v0/shapes.ttl` side by side. The vocabulary is small (~50 classes, ~40 properties); the shapes are tight (~360 triples). Forty minutes of reading covers the substantive surface. The pragmatic-engineering decisions hidden in the comments — particularly around `sh:node` vs `sh:targetClass` for JSON-LD blank nodes — are the kind of detail that experienced practitioners will recognize as battle-scarred-but-defensible.

---

## A note on posture

Tessera is not a W3C submission and is not seeking standardization. It is engineering practice that happens to use the W3C stack credibly because the stack is the right tool for the job — modeling cross-domain semantics, declaring vocabulary alignment, validating documents against constraints that are simultaneously structural and semantic. The project leans on RDF, OWL, JSON-LD, SHACL, and SKOS the way a competent engineer leans on a well-maintained library: confidently, but without ceremony.

If the project ever does seek formalization (it currently does not), the artifacts are in shape for that conversation. The persistent IRIs resolve; the ontology is internally consistent; the SHACL shapes are portable across validators; the SKOS alignment is conservative; the JSON-LD context is `@protected`. The W3C-savvy reader's evaluation question — "could this be picked up by a working group without rework?" — has a defensible answer.

But the more interesting question is whether the *practice* survives evaluation: does the cross-platform fidelity claim hold? does the meaning-over-mechanism principle survive contact with real platforms? Eight worked exercises and one live cross-platform deployment say yes, with the discipline of recording where they don't.

The semantic-web stack is not the thing being shown off. The thing being shown off is what becomes possible when the stack is used seriously.
