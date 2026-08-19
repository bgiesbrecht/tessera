-- custom-ACL adapter emission for acl-row-visibility-policy.jsonld
-- Emitted by CustomACLAdapter (ADR-032). Counterpart to
-- acl-row-visibility.databricks.sql (UC row-filter function) and
-- snowflake-byDataset-row-visibility.snowflake.sql (Snowflake row-access policy).
--
-- Same IR; different mechanism. The custom-ACL adapter targets the customer's own
-- pattern (ADR-003): no platform RLS primitive — a wrapping secure VIEW *is* the
-- enforcement. Consumers are granted SELECT on the view instead of the base table.
-- Principals absent from the ACL join match no rows (fail-closed; defaultStrategy: none).

CREATE OR REPLACE VIEW acme.tpch.orders_rls_acl_secured AS
SELECT * FROM acme.tpch.orders_rls_acl b
WHERE EXISTS (
  SELECT 1
  FROM acme.tpch.rls_acl_mapping m
  JOIN acme.tpch.rls_priority_acl p ON m.code_name = p.code_name
  WHERE lower(trim(m.username)) = lower(trim(current_user()))
    AND p.orderpriority = b.orderpriority
);

-- Operational step (out of Tessera's emission scope, shown for completeness):
-- expose the secured view to consumers instead of the base table, e.g.
--   GRANT SELECT ON acme.tpch.orders_rls_acl_secured TO <consumers>;
-- and revoke direct SELECT on acme.tpch.orders_rls_acl.
