# Sharing governance and the DistributionConstraint shape

**Status:** scoping. No spec changes yet. Sister document to `abac-and-attribute-axes.md` (which scoped what eventually became ADRs 018–021).

**Purpose:** Frame what it would take for Tessera to represent governance policies around data sharing (Delta Sharing, Snowflake Secure Shares and Listings, marketplace publications, cloud-storage hand-offs, BigQuery Analytics Hub, ad-hoc exports) in a portable way that respects ADR-027's descriptive-not-prescriptive posture.

The end state this scoping aims at: a v0 IR extension that admits a `DistributionConstraint` policy expressing **who can share what to whom, under what conditions, via what class of channel, for how long, with what obligations**. Adapters lower that intent to whichever platform mechanism enforces the closest fit.

---

## §1. Where Tessera stands today

`DistributionConstraint` is one of five `policyKind` discriminators declared in the ontology and JSON Schema. It has no implementation: no worked exercise, no example YAML, no SHACL shape detail beyond presence in the policyKind enumeration. The `Share` action is in the well-known action vocabulary, also unexercised.

The technical design's "what this project does not deliver" list says:

> Operational interoperability (policy behavior on data physically moving between platforms via Delta Sharing, Iceberg, federated queries). Reserved; not in v0.

That disclaimer is narrower than it reads. It says Tessera does not *follow data across platforms once moved*. It does not say Tessera has nothing to express about *the decision to share in the first place*. The decision-to-share is policy intent; the data-following-data is the unresolvable cross-platform enforcement question that v0 punts on. This document targets the first; the disclaimer should be sharpened to reflect that distinction.

---

## §2. The dimensions a sharing policy must express

The platforms in scope are Delta Sharing (Databricks UC-governed and open protocol), Snowflake Secure Shares, Snowflake Listings, BigQuery Analytics Hub / Authorized Views, cloud-storage hand-offs (signed URLs, IAM cross-account), marketplace publications, and ad-hoc query-result exports. Across them, a credible sharing policy needs to express the following:

| Dimension | What the policy says | Examples of authoring intent |
|---|---|---|
| **Who can share** | Principal selector (the sharer) | "Only members of `data_publishing` can initiate shares of marketing data." |
| **What can be shared** | Resource selector + per-share scope | "Schema-level, but only the columns tagged non-PII." "Aggregations only, no row-level." |
| **To whom** | Recipient selector with classification | "Only to recipients in `partner` classification within EU/UK/CA jurisdictions." |
| **Channel guarantees** | Required properties of the sharing mechanism | "Must be audited, recipient-identified, revocable, time-bounded." |
| **Time bound** | Maximum duration and/or hard expiration | "Maximum 90 days from grant; no recurring auto-renew." |
| **Required transformations** | Minimization applied to the shared form | "Apply email/phone redaction. Apply k-anonymity ≥ 5 on demographic rows." |
| **Obligations** | Out-of-band actions the share triggers | "Audit-log every consumer access. Notify DPO on creation. Require signed DPA." |
| **Revocation conditions** | When the share must be terminated | "Revoke immediately on consent withdrawal. Revoke on partner agreement termination." |

These split naturally into two groups: **what the IR carries** (the policy intent), and **what the adapter resolves** (the platform mechanism that implements as much of the intent as it can, with diagnostics on gaps).

---

## §3. Proposed IR additions

### §3.1 `tessera:ChannelCharacteristic` — named individuals for channel guarantees

Named individuals describing properties a sharing channel must (or must not) provide. Following the pattern set by `Action`, attribute axes, effects, and condition operators:

```turtle
tessera:ChannelCharacteristic a owl:Class ;
    rdfs:subClassOf tessera:Entity .

tessera:audited                a tessera:ChannelCharacteristic ;
    rdfs:label "Audited"@en ;
    rdfs:comment "Channel logs every consumer access in a tamper-evident store."@en .

tessera:recipientIdentified    a tessera:ChannelCharacteristic ;
    rdfs:label "Recipient identified"@en ;
    rdfs:comment "Consumer is a named principal (account, organization), not an anonymous URL holder."@en .

tessera:revocable              a tessera:ChannelCharacteristic ;
    rdfs:label "Revocable"@en ;
    rdfs:comment "Access can be terminated mid-stream by the provider."@en .

tessera:timeBounded            a tessera:ChannelCharacteristic ;
    rdfs:label "Time-bounded"@en ;
    rdfs:comment "Channel supports hard expiration enforced at the channel layer."@en .

tessera:encryptedInTransit     a tessera:ChannelCharacteristic ;
    rdfs:label "Encrypted in transit"@en .

tessera:agreementRequired      a tessera:ChannelCharacteristic ;
    rdfs:label "Agreement required"@en ;
    rdfs:comment "Recipient must accept declared terms before access is granted."@en .

tessera:queryOnly              a tessera:ChannelCharacteristic ;
    rdfs:label "Query-only"@en ;
    rdfs:comment "Recipient can query but cannot copy or export bulk data."@en .

tessera:copyAllowed            a tessera:ChannelCharacteristic ;
    rdfs:label "Copy allowed"@en ;
    rdfs:comment "Recipient may copy data to their own storage."@en .
```

These are *channel properties*, not mechanism names. A policy requiring `audited + recipientIdentified + revocable + timeBounded` is satisfied by Delta Sharing, failed by cloud-storage signed URLs (no recipient identification), and partially satisfied by Snowflake Listings.

### §3.2 `tessera:DistributionConstraint` — the policy shape

Building on the existing PolicyConstraint structure, `DistributionConstraint` adds two properties: `recipient` (who the data goes to) and `channel` (what the channel must guarantee).

```turtle
tessera:DistributionConstraint a owl:Class ;
    rdfs:subClassOf tessera:PolicyConstraint .

tessera:recipient   a owl:ObjectProperty ;
    rdfs:domain tessera:PolicyRule ;
    rdfs:range tessera:PrincipalSelector .

tessera:channel     a owl:ObjectProperty ;
    rdfs:domain tessera:PolicyRule ;
    rdfs:range tessera:ChannelRequirement .

tessera:ChannelRequirement a owl:Class ;
    rdfs:subClassOf tessera:Entity .

tessera:requires    a owl:ObjectProperty ;
    rdfs:domain tessera:ChannelRequirement ;
    rdfs:range tessera:ChannelCharacteristic .

tessera:forbids     a owl:ObjectProperty ;
    rdfs:domain tessera:ChannelRequirement ;
    rdfs:range tessera:ChannelCharacteristic .

tessera:maxDuration a owl:DatatypeProperty ;
    rdfs:domain tessera:PolicyRule ;
    rdfs:range xsd:duration .

tessera:notAfter    a owl:DatatypeProperty ;
    rdfs:domain tessera:PolicyRule ;
    rdfs:range xsd:dateTime .
```

The `recipient` property reuses `PrincipalSelector`. Recipients are principals: Delta Sharing recipients are organizations or metastores; Snowflake consumers are accounts; BigQuery subscribers are GCP projects. Treating them as principals keeps the IR vocabulary minimal.

### §3.3 Recipient classification via existing attribute axes

A new well-known attribute axis:

```turtle
tessera:recipientTypeAxis a tessera:AttributeAxis ;
    rdfs:label "Recipient type"@en ;
    rdfs:comment "Classification of a sharing recipient — internal, partner, vendor, public, etc."@en .

tessera:internal     a tessera:RecipientType .
tessera:partner      a tessera:RecipientType .
tessera:vendor       a tessera:RecipientType .
tessera:publicAccess a tessera:RecipientType .
```

Existing `jurisdiction` (under `regulatoryRegime` axis) and `dataSubject` axes apply unchanged: a policy can constrain recipients by jurisdiction (`partner-in-EU-only`) using the same machinery that exists for resource matching.

### §3.4 Time-bound expressions

Two forms, both serializable as xsd types:

- **`maxDuration: P90D`.** Relative TTL from grant; xsd:duration in ISO 8601 form.
- **`notAfter: 2026-12-31T00:00:00Z`.** Hard expiration timestamp; xsd:dateTime in ISO 8601 form.

Either or both may be specified; if both, the earlier resulting expiration wins. The IR carries the intent; the adapter chooses whichever it can enforce (Delta Sharing supports both via token TTL + share expiration; cloud-storage signed URLs support only `maxDuration` via URL expiry).

### §3.5 Transformations and obligations on shared data

Reuse existing primitives. A `DistributionConstraint` rule may carry:

- **`transformation`** referencing an existing `TransformationInstance` (Redact, Mask, Hash, Aggregate). The transformation applies to the shared form: the share is filtered through it.
- **`obligation`** referencing an Obligation instance (audit-log, watermark, agreement-required, breach-notification). Obligations are largely out-of-band on most platforms; the adapter emits diagnostics surfacing which obligations the platform can enforce natively and which must be carried by the operator.

### §3.6 Combined rule shape (proposed)

```yaml
rules:
  - principal:       { selector: byIdentity, resource: group:data_publishing }
    recipient:
      selector: byClassification
      attributes:
        recipientType: partner
        jurisdiction: { in: [EU, UK, CA] }
    channel:
      requires:
        - audited
        - recipientIdentified
        - revocable
        - timeBounded
        - agreementRequired
      forbids:
        - copyAllowed
    maxDuration: P90D
    transformations:
      - { type: Redact, columns: [email, phone, dob] }
    obligations:
      - { type: AuditLog,           destination: tessera:auditBucket }
      - { type: AgreementRequired,  agreement:    dpa:2026-partner }
    effect: allow
```

This rule reads as: members of `data_publishing` may share to recipients classified as partner-in-EU/UK/CA via a channel that is audited, recipient-identified, revocable, time-bounded, and agreement-required (and is NOT copy-allowed); for at most 90 days; with PII columns redacted; logging every access and requiring a signed agreement.

---

## §4. Per-platform mechanism mapping

Each adapter declares which channels it can construct and what each channel guarantees. The capability profile carries this as a structured fact, not in prose.

### Channels available per platform

| Channel | Platform | Provider primitive |
|---|---|---|
| **Delta Sharing (UC-governed)** | Databricks UC | `CREATE SHARE`, `ADD TABLE`, `CREATE RECIPIENT`, `GRANT SELECT ON SHARE` |
| **Delta Sharing (open protocol)** | Databricks UC (open recipients) | Same primitives + recipient profile sharing-identifier |
| **Snowflake Secure Share** | Snowflake | `CREATE SHARE`, `GRANT USAGE ON DATABASE TO SHARE`, `ALTER ACCOUNT ADD SHARE` |
| **Snowflake Listing (Marketplace/Private)** | Snowflake | Listings UI / `CREATE LISTING`; consumer accepts via marketplace |
| **BigQuery Analytics Hub Listing** | GCP | Analytics Hub data exchange + listing |
| **BigQuery Authorized View** | GCP | View granting query access without underlying-table access |
| **Cloud storage signed URL** | AWS / Azure / GCP | Signed URL with TTL |
| **Cloud storage cross-account IAM** | AWS / Azure / GCP | Role assumption / SAS token / GCS bucket policy |
| **Ad-hoc query export** | All | Adapter cannot constrain after-the-fact downloads |

### Channel-characteristic guarantees per channel

| Characteristic | Delta Sharing (UC) | Open Delta Sharing | Snowflake Share | Snowflake Listing | BQ Analytics Hub | BQ Authorized View | Cloud Storage Signed URL | Cloud Storage IAM |
|---|---|---|---|---|---|---|---|---|
| `audited` | ✓ (UC audit log) | ✓ (delta-sharing-recipient access logs) | ✓ (`account_usage.access_history`) | ✓ | ✓ | partial (project-level) | partial (cloud audit, coarse) | ✓ (CloudTrail/Cloud Audit Logs) |
| `recipientIdentified` | ✓ (metastore) | ✓ (recipient profile) | ✓ (consumer account) | ✓ (consumer account) | ✓ (subscriber project) | ✓ (granted principal) | ✗ (URL-holder is anonymous) | ✓ (IAM principal) |
| `revocable` | ✓ | ✓ (revoke recipient) | ✓ (revoke share) | ✓ (unpublish listing) | ✓ | ✓ | partial (rotate signing key — affects all URLs from that key) | ✓ |
| `timeBounded` | ✓ (token TTL) | ✓ (token TTL) | partial (manual revoke; no native TTL on share) | partial (no native TTL; listing T&C may stipulate) | partial | partial (manual) | ✓ (URL expiry; native) | partial (manual rotation) |
| `encryptedInTransit` | ✓ (TLS) | ✓ (TLS) | ✓ (TLS) | ✓ | ✓ | ✓ | ✓ (HTTPS) | ✓ (HTTPS) |
| `agreementRequired` | partial (out-of-band) | partial | partial | ✓ (listing T&Cs accepted at subscription) | ✓ (data exchange terms) | ✗ (no agreement layer) | ✗ | partial (sometimes encoded in IAM conditions, brittle) |
| `queryOnly` | ✓ (read-only by construction) | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ (signed URL implies download) | partial |
| `copyAllowed` | partial (depends on recipient's storage) | partial | ✓ (recipient can copy via `CREATE TABLE AS`) | ✓ | ✓ | partial | ✓ (URL holders typically download) | ✓ |

A policy requiring `audited + recipientIdentified + timeBounded + agreementRequired` matches Snowflake Listings or Delta Sharing, partially matches Snowflake Secure Share (no native TTL), and mismatches cloud-storage signed URLs.

### Channel-selection algorithm in the adapter

When an adapter receives a `DistributionConstraint` to emit, it enumerates the channels it can construct on this platform, checks whether each channel's guarantees satisfy the policy's requirements, picks the most-constrained satisfying channel, lowers transformations to the channel's mechanism, and emits obligations as diagnostics where the channel can't carry them natively. This follows the same capability-profile-driven pattern the other adapters use.

---

## §5. Sample policy authorings

### §5.1 Partner data share with PII redaction

```yaml
policy:
  id: product-analytics-to-partner
  kind: DistributionConstraint
  description: |
    Members of data_publishing may share product_analytics
    schema to partner recipients in EU/UK/CA jurisdictions, for
    up to 90 days, via an audited and revocable channel, with
    PII columns redacted and a signed DPA required.
  appliesTo:
    selector: byScope
    scope: schema:acme.product_analytics
  action: Share
  rules:
    - principal:
        selector: byIdentity
        resource: group:data_publishing
      recipient:
        selector: byClassification
        attributes:
          recipientType: partner
          jurisdiction: { in: [EU, UK, CA] }
      channel:
        requires: [audited, recipientIdentified, revocable, timeBounded, agreementRequired]
        forbids: [copyAllowed]
      maxDuration: P90D
      transformations:
        - { type: Redact, columns: [email, phone, dob], replacement: "REDACTED" }
      obligations:
        - { type: AgreementRequired, agreement: dpa:2026-partner }
        - { type: AuditLog, destination: tessera:audit-bucket }
      effect: allow
```

### §5.2 Public marketplace listing

```yaml
policy:
  id: industry-benchmarks-public-listing
  kind: DistributionConstraint
  description: |
    Industry-benchmark aggregates can be listed publicly on
    the marketplace. No per-recipient identity required
    (publicAccess), no time bound, no copy restriction, but
    must be query-only (no bulk download) and aggregation-only.
  appliesTo:
    selector: byIdentity
    resource: table:acme.benchmarks.industry_quarterly
  action: Share
  rules:
    - principal: { selector: byIdentity, resource: group:data_publishing }
      recipient:
        selector: byClassification
        attributes:
          recipientType: publicAccess
      channel:
        requires: [encryptedInTransit, queryOnly]
        # Note: recipientIdentified intentionally omitted — marketplace
        # listings to publicAccess do not require identity. agreementRequired
        # may apply (marketplace T&Cs) but not policy-mandated.
      transformations:
        - { type: AggregationOnly, minimumGroupSize: 50 }
      effect: allow
```

### §5.3 Internal export, time-boxed audit copy

```yaml
policy:
  id: q4-audit-extract-finance
  kind: DistributionConstraint
  description: |
    Finance audit can export the q4 transactions to their
    own bucket for the duration of the audit. Must be a
    named recipient, audited, revocable, and bounded by the
    audit end date. Encrypted in transit. Copy is allowed
    (this is an extract by design).
  appliesTo:
    selector: byIdentity
    resource: table:acme.finance.q4_transactions
  action: Share
  rules:
    - principal: { selector: byIdentity, resource: group:legal_team }
      recipient:
        selector: byClassification
        attributes:
          recipientType: internal
          businessDomain: audit
      channel:
        requires: [audited, recipientIdentified, revocable, timeBounded, encryptedInTransit]
      notAfter: "2026-12-31T23:59:59Z"
      transformations: []
      obligations:
        - { type: AuditLog, destination: tessera:audit-bucket }
      effect: allow
```

The three policies use the same vocabulary; the adapter chooses different channel mechanisms for each. (§5.1 → Delta Sharing recipient with token TTL + filtered share with masking views. §5.2 → marketplace listing of an aggregation view. §5.3 → cloud-storage cross-account IAM with hard expiration, audit logging configured separately, or, if the adapter is sufficiently expressive, a Delta Sharing extract with a copy step orchestrated out-of-band.)

---

## §6. Operational-interoperability disclaimer: sharpening needed

The existing technical-design disclaimer reads:

> Operational interoperability (policy behavior on data physically moving between platforms via Delta Sharing, Iceberg, federated queries). Reserved; not in v0.

This conflates two distinct concerns:

- **(A) Policy behavior on data after it moves to a different platform.** *"If a column is shared via Delta Sharing to a Snowflake consumer, does the column-masking policy follow it across the boundary?"* Answer: no, that is not in v0 (or arguably ever), since Tessera does not control the recipient's enforcement layer.
- **(B) Policy expression about the decision to share.** *"Can a Tessera policy say 'this column may be shared to internal recipients with no transformation, to partners only with redaction, and never to public'?"* Yes. `DistributionConstraint` expresses exactly this. The policy constrains the *creation* of the share, even if it cannot follow the data.

The current disclaimer reads as denying (B). When this scoping document advances toward implementation, the disclaimer needs to be rewritten to deny only (A):

> *Policy enforcement once data has crossed platform boundaries is not in scope. Tessera expresses sharing-intent policies that constrain share creation, the conditions on the channel, transformations applied to the shared form, and obligations attached; the recipient platform's own governance is responsible for enforcement after data hand-off.*

This sharpening preserves ADR-001's framing while admitting `DistributionConstraint` as a legitimate IR concern.

---

## §7. v0 disposition — proposed ADRs

Parallel to how the ABAC scoping produced ADRs 018–021, this scoping would produce roughly three ADRs:

- **ADR-028: `DistributionConstraint` semantic shape (recipient, channel, time, transformations, obligations).** Records the policy kind's intended semantics and the new ObjectProperties (`recipient`, `channel`, `maxDuration`, `notAfter`).
- **ADR-029: `ChannelCharacteristic` as a named-individuals vocabulary.** Records the closed vocabulary of channel guarantees, following the ADR-018 pattern for axes (named individuals, closed-vocabulary validation via `sh:in`, adopter-extensibility via subclassing if needed).
- **ADR-030: sharpening the operational-interoperability disclaimer.** Records the (A) vs (B) distinction above; updates the technical design and ADR-001 commentary.

Spec changes (parallel to Stage 4 of the ABAC work):

- `spec/v0/ontology.ttl`: `DistributionConstraint`, `ChannelCharacteristic`, named individuals, `recipient`/`channel`/`maxDuration`/`notAfter` properties, `recipientTypeAxis` and its values.
- `spec/v0/context.jsonld`: short-name bindings.
- `spec/v0/schema.json`: JSON Schema structural validation for the new shape.
- `spec/v0/shapes.ttl`: SHACL shapes for the new selector and channel-requirement node shape; closed-vocabulary on `ChannelCharacteristic`.
- `docs/technical-design-v0.2.md`: new subsection on `DistributionConstraint` semantics.

The total surface is comparable to the ABAC additions (a few classes, a few properties, a closed vocabulary, three to five worked-example artifacts).

---

## §8. Open questions

These are real design choices the worked exercise will need to resolve:

1. **Are recipients principals or a parallel concept?** Proposed as principals (§3.2). Alternative: introduce `tessera:Recipient` as a sibling class with its own selector. The principal-reuse path is simpler but conflates "who initiated" with "who receives" at the IR level. The parallel-class path is more explicit but doubles the surface. Worked exercise will pressure-test which.

2. **How does `DistributionConstraint` compose with existing `RowVisibilityConstraint` / `ColumnVisibilityConstraint` policies on the same resource?** If a share is created on a table that already has a column mask, does the mask apply to the share? On Databricks the answer is yes (UC policies follow the data into the share); on Snowflake the answer is more nuanced (secure views may need to be reconstructed). The ADR-023 γ-with-refinement question recurs here, across policy kinds.

3. **Should `aggregationOnly` be a channel characteristic or a transformation?** It's currently shown as a transformation in §5.2 (`AggregationOnly` with `minimumGroupSize`). But it also constrains the channel: recipients of an aggregation-only share cannot run row-level queries. Which is the cleaner home? Possibly both, with the transformation being authoritative and the channel characteristic being derived for capability-matching.

4. **`agreementRequired`: how is the agreement identified?** §5.1 uses `agreement: dpa:2026-partner`. Should this be an IRI to an external agreement document? An obligation? A standalone concept? Some marketplaces (Snowflake Listings) carry T&Cs natively; others require out-of-band tracking. The IR shape needs to admit both.

5. **Audit-log destinations.** Tessera shouldn't model storage paths in the IR, but the `obligations` block needs *some* way to identify where audit logs go. Probably an opaque IRI (`tessera:audit-bucket`) resolved per-environment in `AdapterConfig.extras`, parallel to the tag-taxonomy pattern.

6. **Recipient-attribute provenance.** A policy says "share only to partners in EU." How does the system know a given recipient *is* a partner in EU? On Delta Sharing, recipient metadata is provider-managed and can carry attributes. On Snowflake, consumer-account attributes are less structured. This may surface a new `AdapterConfig` mapping for recipient classification.

7. **What about "no share" policies?** A `DistributionConstraint` with no `effect: allow` rule and a default-deny posture would express "this resource may never be shared." The IR shape needs to admit deny as well as allow (the rules support both per ADR-026 framing); but worth confirming the semantics align with what platforms can enforce.

8. **Cross-cutting: how does `byScope` interact with `DistributionConstraint`?** A schema-scoped sharing policy (`appliesTo: scope: schema:foo`) means "anything in this schema can only be shared per these rules." It is the share-time analog of the ABAC scoping pattern. Should pressure-test in the worked exercise.

---

## §9. What the worked exercise should target (Phase B)

Following the discipline of the ABAC and table-grants exercises, the worked exercise that grounds this scoping should:

- **Pick one concrete scenario** that exercises the maximum surface. Recommendation: **§5.1 (partner data share with PII redaction)**. It touches recipient classification, channel requirements, time bounds, transformations, and obligations, and has a clean implementation path on both Databricks Delta Sharing and Snowflake Listings.
- **Hand-derive the Tessera policy YAML and JSON-LD** in `spec/v0/examples/distribution-partner-share-*` artifacts.
- **Hand-derive the platform DDL on both platforms:** Databricks Delta Sharing recipient + share + filtered view; Snowflake Listing with marketplace T&Cs + secure share + masked view.
- **Write the diagnostic and comparison documents** capturing what landed cleanly, what surfaced as gaps, what proved that recipients-as-principals is the right shape (or isn't).
- **Implement adapter emission** in both UC and Snowflake adapters; live-verify on the `acme` infrastructure provisioned by `setup_demo_infra.py`.
- **Update the capability profiles** with the channel-characteristic guarantee matrix from §4.

Estimated effort: parallel to the table-grants exercise (~1 day of focused work, plus the live-platform verification cycle).

Outcomes if the exercise succeeds:
- Three ADRs land (028–030).
- v0 IR gains `DistributionConstraint` with full semantic shape.
- One worked example end-to-end on both platforms.
- The migration demo grows from six policies to seven (adding the partner share scenario).
- Capability profiles gain the channel-characteristic matrix as a structured fact.

---

## §10. Open questions for the design review (before the worked exercise)

For Brice and any reviewers before greenlighting the worked exercise:

1. **Scope of v0 vs reserved-for-v1.** Should all eight channel characteristics land at once, or pick a subset for the worked exercise (say five: audited, recipientIdentified, revocable, timeBounded, agreementRequired) and queue the rest? The minimum-viable set is the one the worked example actually exercises.
2. **Marketplace listings vs direct shares.** Are listings a separate channel class, or a layered concept (a listing is a publication of an underlying share)? Operationally the latter: listings advertise, and the underlying share enforces. The IR might just model the share and treat the listing as adapter-side scaffolding.
3. **Ad-hoc query exports.** Should Tessera even try to express policies that constrain "user runs query, downloads CSV"? The platform-side enforcement surface is thin (Databricks has download-controls; Snowflake has download-prevention via secure views; others lack it). May be reasonable to declare ad-hoc exports as out-of-scope and document.
4. **Snowflake's data clean room mechanism.** Snowflake's *Native App Framework* + data clean rooms support a "query-only, never-extract" guarantee that's stronger than typical shares. Worth a callout for v1; probably not in scope for the first DistributionConstraint pass.
5. **BigQuery Analytics Hub and Authorized Views.** Should the first worked exercise also target BigQuery, or stick with Databricks + Snowflake parity? Lean: Databricks + Snowflake for the first pass, BigQuery as a follow-up adapter exercise.
6. **The disclaimer rewrite (§6).** Is the (A) vs (B) distinction the right framing? Anything missing (for example, does the project need an explicit position on "what does Tessera say about data crossing into a *non-Tessera-governed* environment")?

---

## §11. Recommended next step

If this scoping is greenlit, the immediate next move is **Phase B (the worked exercise)**, targeting §5.1 (partner data share with PII redaction) end-to-end on Databricks Delta Sharing and Snowflake Listings, following the same Phase 1 / Phase 2 / Phase 3 discipline that produced the ABAC and table-grants exercises.

The worked exercise will pressure-test the IR shape proposed here against real platform DDL, and surface the design choices §8's open questions enumerate. The result lands as ADRs 028–030 plus v0 spec additions plus adapter emission code. Tessera grows from five policy kinds with three exercised (RowVis, ColVis, AccessGrant) to five with four exercised.

Sharing is the largest unexercised surface in the v0 IR. Landing it cleanly moves Tessera from "two-thirds of the declared policy kinds work" to "four-fifths work," and brings the framework's coverage in line with what real customer corpora actually carry. (`DataQualityConstraint` and the reserved-space additions remain out of scope per ADR-001.)
