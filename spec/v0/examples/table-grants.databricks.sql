-- Databricks DDL for the three table-grants scenarios.
-- Hand-derived per the IR shapes in table-grants-scenario-{a,b,c}.jsonld;
-- the UnityCatalogAdapter does not yet emit affirmative grants (queued
-- work surfaced by this exercise — neither adapter currently dispatches
-- on policyKind+effect=allow to emit GRANT statements).
--
-- This file documents what the adapter SHOULD emit; Phase 3 executes the
-- statements directly via the SDK to verify behavior. Adapter emission of
-- this shape is a follow-up.

-- ============================================================================
-- Scenario A: Single-table read grant.
-- IR: policy:table-grants-scenario-a
--     RowVisibilityConstraint, effect: allow, action: Read,
--     appliesTo: table:acme.tpch.orders,
--     principal: group:acme_marketing_analytics
-- ============================================================================

GRANT SELECT ON TABLE acme.tpch.orders TO `acme_marketing_analytics`;


-- ============================================================================
-- Scenario B: Schema-level read grant with downward propagation.
-- IR: policy:table-grants-scenario-b
--     RowVisibilityConstraint, effect: allow, action: Read,
--     appliesTo: byScope schema:acme.tpch_staging (no matching),
--     principal: group:acme_data_engineering
-- ============================================================================

-- USE SCHEMA grants the principal the ability to RESOLVE the schema's
-- name-space (required for any object access within it).
GRANT USE SCHEMA ON SCHEMA acme.tpch_staging TO `acme_data_engineering`;

-- SELECT ON SCHEMA propagates to all current and future tables in the schema —
-- the byScope downward-propagation semantics from ADR-019.
GRANT SELECT ON SCHEMA acme.tpch_staging TO `acme_data_engineering`;

-- USE CATALOG is implicitly granted to account users on the demo catalog;
-- if your environment requires it, uncomment:
-- GRANT USE CATALOG ON CATALOG acme TO `acme_data_engineering`;


-- ============================================================================
-- Scenario C: Function execute grant.
-- IR: policy:table-grants-scenario-c
--     RowVisibilityConstraint, effect: allow, action: Execute,
--     appliesTo: function:acme.tpch.compute_customer_ltv,
--     principal: group:acme_marketing_analytics
-- ============================================================================

GRANT EXECUTE ON FUNCTION acme.tpch.compute_customer_ltv
  TO `acme_marketing_analytics`;
