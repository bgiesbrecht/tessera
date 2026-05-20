"""
One-shot scenario verifier for the group-row-visibility worked example.

Runs `is_account_group_member` checks (live, via the warehouse) to determine
which scenario the current session evaluates under, then runs the visibility
query and compares against the expected priorities.

Usage:
    python3 verify_scenario.py
"""
import sys, time
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

EXPECTED = {
    "S1": (
        "in acme_all_priority_ops",
        ["1-URGENT", "2-HIGH", "3-MEDIUM", "4-NOT SPECIFIED", "5-LOW"],
    ),
    "S2": (
        "in acme_high_priority_ops only",
        ["1-URGENT", "2-HIGH"],
    ),
    "S3": (
        "in neither restrictive group",
        ["3-MEDIUM", "4-NOT SPECIFIED", "5-LOW"],
    ),
}

w = WorkspaceClient(profile="DEFAULT")
warehouses = list(w.warehouses.list())
running = [x for x in warehouses if str(x.state) == "State.RUNNING"]
warehouse = next(
    (r for r in running if r.name == "Shared Unity Catalog Serverless"), running[0]
)


def _run(sql):
    resp = w.statement_execution.execute_statement(
        warehouse_id=warehouse.id,
        statement=sql,
        wait_timeout="30s",
        catalog="acme",
        schema="tpch",
    )
    while resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(1)
        resp = w.statement_execution.get_statement(resp.statement_id)
    if resp.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"SQL failed: {resp.status.error}")
    return resp.result.data_array if resp.result else []


def membership():
    rows = _run(
        "SELECT "
        "is_account_group_member('acme_all_priority_ops') AS in_all, "
        "is_account_group_member('acme_high_priority_ops') AS in_high"
    )
    in_all, in_high = rows[0]
    return in_all in (True, "true"), in_high in (True, "true")


def priorities():
    rows = _run(
        "SELECT DISTINCT o_orderpriority AS p "
        "FROM acme.tpch.orders ORDER BY p"
    )
    return [r[0] for r in rows]


def classify(in_all, in_high):
    if in_all:
        return "S1"
    if in_high:
        return "S2"
    return "S3"


def main():
    in_all, in_high = membership()
    print(f"Live membership: all_priority_ops={in_all}  high_priority_ops={in_high}")
    scenario = classify(in_all, in_high)
    desc, expected = EXPECTED[scenario]
    print(f"Scenario: {scenario} ({desc})")
    print(f"Expected: {expected}")
    got = priorities()
    print(f"Observed: {got}")
    match = got == expected
    print(f"Match:    {'YES' if match else 'NO'}")
    sys.exit(0 if match else 2)


if __name__ == "__main__":
    main()
