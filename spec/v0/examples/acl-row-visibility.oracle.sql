-- Oracle adapter emission for acl-row-visibility-policy.jsonld
-- Emitted by OracleAdapter (ADR-033). Fourth mechanism for the same ACL IR,
-- alongside acl-row-visibility.databricks.sql (UC row-filter function),
-- snowflake-byDataset-row-visibility.snowflake.sql (Snowflake row-access policy),
-- and acl-row-visibility.custom-acl.sql (custom wrapping view).
--
-- Oracle mechanism: Virtual Private Database (VPD). DBMS_RLS.ADD_POLICY attaches a
-- PL/SQL policy function returning a predicate appended to every query's WHERE
-- clause. The byDataset ACL join is returned as a correlated EXISTS keyed off
-- SYS_CONTEXT('USERENV','SESSION_USER'). Principals absent from the join match no
-- rows (fail-closed). Object naming maps the Tessera catalog.schema.table to
-- Oracle SCHEMA.OBJECT (no catalog tier); override via resource_bindings.

CREATE OR REPLACE FUNCTION TPCH.TESSERA_ACL_ROW_VISIBILITY_VPD(
  p_schema IN VARCHAR2, p_object IN VARCHAR2
) RETURN VARCHAR2 AS
BEGIN
  RETURN 'EXISTS (SELECT 1 FROM TPCH.RLS_ACL_MAPPING m JOIN TPCH.RLS_PRIORITY_ACL p ON m.code_name = p.code_name WHERE lower(trim(m.username)) = lower(trim(SYS_CONTEXT(''USERENV'',''SESSION_USER''))) AND p.orderpriority = orderpriority)';
END;
/
BEGIN
  DBMS_RLS.ADD_POLICY(
    object_schema   => 'TPCH',
    object_name     => 'ORDERS_RLS_ACL',
    policy_name     => 'TESSERA_ACL_ROW_VISIBILITY',
    function_schema => 'TPCH',
    policy_function => 'TESSERA_ACL_ROW_VISIBILITY_VPD',
    statement_types => 'SELECT'
  );
END;
/
