-- Snowflake DDL emitted by SnowflakeAdapter from
-- spec/v0/examples/snowflake-byDataset-row-visibility-policy.jsonld
--
-- Counterpart to spec/v0/examples/acl-row-visibility.databricks.sql.
-- Same IR; different platform lowering.
--
-- The policy parameter is named POLICY_INPUT_VALUE specifically to avoid
-- collision with the joined column reference (p.O_ORDERPRIORITY). Snowflake
-- resolves a bare identifier inside the policy body to the column reference
-- rather than the parameter when names match, which would degenerate the
-- predicate to `col = col` (always true).

CREATE OR REPLACE ROW ACCESS POLICY ACME.TESSERA.snowflake_byDataset_row_visibility_rap
AS (POLICY_INPUT_VALUE VARCHAR) RETURNS BOOLEAN ->
        EXISTS (
            SELECT 1
            FROM ACME.TESSERA.RLS_ACL_MAPPING m
            JOIN ACME.TESSERA.RLS_PRIORITY_ACL p
              ON m.CODE_NAME = p.CODE_NAME
            WHERE m.USERNAME = CURRENT_USER()
              AND p.O_ORDERPRIORITY = POLICY_INPUT_VALUE
        );

ALTER TABLE ACME.TESSERA.SNOW_ORDERS_RLS_ACL
  ADD ROW ACCESS POLICY ACME.TESSERA.snowflake_byDataset_row_visibility_rap
  ON (O_ORDERPRIORITY);
