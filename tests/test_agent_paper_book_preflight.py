"""Paper-book initialization preflight is exact, stable, and read-only."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime, timezone

import pytest

from server import (
    agent_paper_attribution,
    agent_paper_book_plan,
    agent_paper_book_preflight,
    agent_policy,
)
from sim.strategies.configs import config_by_id
from tests.agent_test_helpers import fixed_etf_market

START = date(2026, 9, 11)
PLANNED = datetime(2026, 9, 10, 20, 0, tzinfo=timezone.utc)


def _attribution_tables(con) -> None:
    agent_paper_attribution.init_schema(con)


def _controls(con, *, equity: bool = True) -> None:
    fixed_etf_market(con)
    config = config_by_id("spy_benchmark")
    con.execute(
        "INSERT INTO portfolios "
        "(id, name, strategy, config, created, active, cash, initial_cash, "
        "execution_profile) VALUES (?, ?, ?, ?, DATE '2026-09-01', TRUE, "
        "114, 39000, 'baseline_v1')",
        [
            config["id"],
            config["name"],
            config["strategy"],
            json.dumps(config),
        ],
    )
    if equity:
        for portfolio_id, cash, positions in (
            ("dual_momentum", 0.1582718773055234, 1),
            ("spy_benchmark", 114.03300708008464, 1),
        ):
            con.execute(
                "INSERT INTO sim_equity "
                "(portfolio_id, date, equity, cash, n_positions) "
                "VALUES (?, ?, 39000, ?, ?)",
                [portfolio_id, START, cash, positions],
            )


def _plan(policy_id: str = "dual_momentum_agent_shadow_v1") -> tuple[dict, dict]:
    policy = agent_policy.get(policy_id)
    return (
        policy,
        agent_paper_book_plan.plan(
            policy,
            START,
            planned_at=PLANNED,
        ),
    )


def _snapshot(con) -> dict[str, list[tuple]]:
    tables = [
        "portfolios",
        "sim_orders",
        "sim_fills",
        "sim_positions",
        "sim_dividends",
        "sim_equity",
        "agent_paper_book_attribution",
        "agent_paper_order_attribution",
    ]
    return {
        table: con.execute(f"SELECT * FROM {table} ORDER BY ALL").fetchall()
        for table in tables
    }


@pytest.mark.parametrize(
    "policy_id",
    [
        "dual_momentum_agent_shadow_v1",
        "dual_momentum_hybrid_veto_shadow_v1",
    ],
)
def test_complete_preflight_passes_without_mutating_any_table(con, policy_id):
    _controls(con)
    _attribution_tables(con)
    policy, plan = _plan(policy_id)
    before = _snapshot(con)

    result = agent_paper_book_preflight.assess(con, plan, policy)

    assert result["status"] == "ready_for_backup_gated_inactive_initialization"
    assert result["preconditions_passed"] is True
    assert result["blockers"] == []
    assert {gate["status"] for gate in result["gates"]} == {"pass"}
    assert result["protected_portfolio_ids"] == [
        "dual_momentum",
        "spy_benchmark",
    ]
    assert result["database_mutation_performed"] is False
    assert result["writer_implemented"] is True
    assert result["writer_entrypoint"] == "tools.initialize_agent_paper_book"
    assert result["scheduler_integration_implemented"] is False
    assert result["order_route_implemented"] is False
    assert result["initialization_authority"] == "none"
    assert result["execution_authority"] == "none"
    assert _snapshot(con) == before


def test_missing_attribution_tables_are_explicit_blockers(con):
    _controls(con)
    policy, plan = _plan()

    result = agent_paper_book_preflight.assess(con, plan, policy)
    gates = {gate["name"]: gate for gate in result["gates"]}

    assert result["status"] == "blocked"
    assert result["blockers"] == [
        "required_persistence_schema",
        "reserved_identity_absent",
    ]
    schemas = {
        item["table"]: item["status"]
        for item in gates["required_persistence_schema"]["evidence"]["tables"]
    }
    assert schemas["agent_paper_book_attribution"] == "missing"
    assert schemas["agent_paper_order_attribution"] == "missing"
    assert gates["existing_control_portfolios"]["status"] == "pass"
    assert gates["control_equity_anchor"]["status"] == "pass"
    assert gates["stable_read_snapshot"]["status"] == "pass"
    assert result["initialization_authority"] == "none"


def test_existing_reserved_state_blocks_global_absence_proof(con):
    _controls(con)
    _attribution_tables(con)
    policy, plan = _plan()
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(101, ?, 'SPY', 'buy', 1, ?, 'pending', NULL)",
        [plan["portfolio_id"], START],
    )

    result = agent_paper_book_preflight.assess(con, plan, policy)
    gate = next(
        gate
        for gate in result["gates"]
        if gate["name"] == "reserved_identity_absent"
    )

    assert gate["status"] == "blocked"
    assert gate["evidence"]["row_counts"]["sim_orders"] == 1
    assert result["blockers"] == ["reserved_identity_absent"]


def test_control_drift_and_missing_anchor_are_separate_blockers(con):
    _controls(con, equity=False)
    _attribution_tables(con)
    policy, plan = _plan()
    con.execute(
        "UPDATE portfolios SET execution_profile = 'conservative_v1' "
        "WHERE id = 'dual_momentum'"
    )

    result = agent_paper_book_preflight.assess(con, plan, policy)

    assert result["blockers"] == [
        "existing_control_portfolios",
        "control_equity_anchor",
    ]
    assert result["protected_portfolio_snapshot_sha256"]


def test_incompatible_schema_blocks_without_querying_it(con):
    _controls(con)
    con.execute(
        "CREATE TABLE agent_paper_book_attribution (portfolio_id BIGINT)"
    )
    order_columns = ", ".join(
        f"{name} {kind}"
        for name, kind in agent_paper_attribution.ORDER_ATTRIBUTION_SCHEMA
    )
    con.execute(f"CREATE TABLE agent_paper_order_attribution ({order_columns})")
    policy, plan = _plan()

    result = agent_paper_book_preflight.assess(con, plan, policy)
    schema_gate = next(
        gate
        for gate in result["gates"]
        if gate["name"] == "required_persistence_schema"
    )

    assert schema_gate["status"] == "blocked"
    assert result["blockers"] == [
        "required_persistence_schema",
        "reserved_identity_absent",
    ]


def test_snapshot_change_blocks_preflight(con, monkeypatch):
    _controls(con)
    _attribution_tables(con)
    policy, plan = _plan()
    original = agent_paper_book_preflight._capture
    calls = 0

    def changing(connection, value):
        nonlocal calls
        calls += 1
        captured = original(connection, value)
        if calls == 2:
            captured = deepcopy(captured)
            captured["protected_portfolio_snapshot_sha256"] = "0" * 64
        return captured

    monkeypatch.setattr(agent_paper_book_preflight, "_capture", changing)

    result = agent_paper_book_preflight.assess(con, plan, policy)

    assert result["blockers"] == ["stable_read_snapshot"]
    assert result["preconditions_passed"] is False


def test_invalid_plan_fails_closed(con):
    _controls(con)
    _attribution_tables(con)
    policy, plan = _plan()
    plan["portfolio_id"] = "dual_momentum"

    with pytest.raises(
        agent_paper_book_preflight.PaperBookPreflightError,
        match="does not match policy",
    ):
        agent_paper_book_preflight.assess(con, plan, policy)
