-- Oracle adapter emissions showing the three distinct Oracle governance primitives
-- (ADR-033). Each is the OracleAdapter emission of an existing worked-example IR.

-- 1) Row visibility (byIdentity) — Virtual Private Database, role-gated predicate.
--    Source: group-row-visibility-policy-a.jsonld. Role membership is tested via
--    SYS_CONTEXT('SYS_SESSION_ROLES','<ROLE>'); each branch returns that role's
--    row predicate; ELSE is fail-closed. Group names map to Oracle roles (bind
--    'account users' explicitly — it is not a legal unquoted identifier).
CREATE OR REPLACE FUNCTION TPCH.TESSERA_GROUP_ROW_VISIBILITY_POLICY_A_VPD(
  p_schema IN VARCHAR2, p_object IN VARCHAR2
) RETURN VARCHAR2 AS
BEGIN
  IF SYS_CONTEXT('SYS_SESSION_ROLES', 'ACME_ALL_PRIORITY_OPS') = 'TRUE' THEN
    RETURN '1=1';
  ELSIF SYS_CONTEXT('SYS_SESSION_ROLES', 'ACME_HIGH_PRIORITY_OPS') = 'TRUE' THEN
    RETURN 'o_orderpriority IN (''1-URGENT'', ''2-HIGH'')';
  ELSIF SYS_CONTEXT('SYS_SESSION_ROLES', 'ACCOUNT_USERS') = 'TRUE' THEN
    RETURN 'o_orderpriority IN (''3-MEDIUM'', ''4-NOT SPECIFIED'', ''5-LOW'')';
  ELSE
    RETURN '1=0';
  END IF;
END;
/
BEGIN
  DBMS_RLS.ADD_POLICY(
    object_schema   => 'TPCH',
    object_name     => 'ORDERS',
    policy_name     => 'TESSERA_GROUP_ROW_VISIBILITY_POLICY_A',
    function_schema => 'TPCH',
    policy_function => 'TESSERA_GROUP_ROW_VISIBILITY_POLICY_A_VPD',
    statement_types => 'SELECT'
  );
END;
/

-- 2) Column visibility — Oracle Data Redaction. Source: column-mask-orders-clerk-policy.jsonld.
--    Redact-with-replacement lowers to DBMS_REDACT.REGEXP (FULL cannot carry an
--    arbitrary replacement); the expression redacts for sessions lacking the allowed role.
BEGIN
  DBMS_REDACT.ADD_POLICY(
    object_schema        => 'TPCH',
    object_name          => 'ORDERS',
    column_name          => 'O_CLERK',
    policy_name          => 'TESSERA_COLUMN_MASK_ORDERS_CLERK_REDACT',
    function_type        => DBMS_REDACT.REGEXP,
    regexp_pattern       => '(.*)',
    regexp_replace_string => 'CLERK-REDACTED',
    regexp_position      => 1,
    regexp_occurrence    => 0,
    expression           => 'SYS_CONTEXT(''SYS_SESSION_ROLES'', ''ORDERS_FULL_ACCESS'') IS NULL'
  );
END;
/

-- 3) Access grant — GRANT. Source: table-grants-scenario-a.jsonld.
GRANT SELECT ON TPCH.ORDERS TO ACME_MARKETING_ANALYTICS;
