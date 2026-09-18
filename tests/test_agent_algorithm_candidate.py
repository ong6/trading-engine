"""Hybrid candidates reproduce the registered algorithm without side effects."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from engine.lib.provenance import canonical_sha256
from server import (
    agent_algorithm_candidate,
    agent_context,
    agent_policy,
    agent_price_observations,
)
from sim.strategies.configs import config_by_id


def _weekdays_ending(end: date, count: int) -> list[date]:
    values = []
    current = end
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current)
        current -= timedelta(days=1)
    return list(reversed(values))


def _market(con):
    config = config_by_id("dual_momentum")
    con.execute(
        "INSERT INTO portfolios "
        "(id, name, strategy, config, created, active, cash, initial_cash, "
        "execution_profile) VALUES ('dual_momentum', 'Dual Momentum', "
        "'dual_momentum', ?, DATE '2026-01-01', TRUE, 39000, 39000, 'baseline_v1')",
        [json.dumps(config)],
    )
    con.execute(
        "CREATE TABLE universe ("
        "ticker VARCHAR PRIMARY KEY, yf_ticker VARCHAR, name VARCHAR, exchange VARCHAR, "
        "etf BOOLEAN, member VARCHAR, added DATE, active BOOLEAN, liquid BOOLEAN, "
        "backfill_done BOOLEAN)"
    )
    sessions = _weekdays_ending(date(2026, 9, 30), 253)
    for ticker, end_close in (("SPY", 120.0), ("EFA", 110.0), ("BIL", 100.0)):
        con.execute(
            "INSERT INTO universe VALUES (?, ?, ?, 'NYSE', TRUE, NULL, "
            "DATE '2020-01-01', TRUE, TRUE, TRUE)",
            [ticker, ticker, ticker],
        )
        closes = [
            100.0 + (end_close - 100.0) * index / 252
            for index in range(253)
        ]
        con.executemany(
            "INSERT INTO prices "
            "(ticker, date, open, high, low, close, volume, source, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 1000000, 'yfinance', "
            "TIMESTAMP '2026-10-01 00:00:00')",
            [
                (ticker, session, close, close + 1, close - 1, close)
                for session, close in zip(sessions, closes, strict=True)
            ],
        )
    return sessions[-1]


def test_hybrid_candidate_is_exact_hashed_and_read_only(con):
    market_date = _market(con)
    policy = agent_policy.get("dual_momentum_hybrid_veto_shadow_v1")
    before = {
        table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("portfolios", "sim_orders", "sim_fills", "sim_equity")
    }

    first = agent_algorithm_candidate.materialize(con, policy, market_date)
    second = agent_algorithm_candidate.materialize(con, policy, market_date)

    assert first == second
    assert first["status"] == "materialized"
    assert first["cadence_admitted"] is True
    assert first["order_count"] == 1
    assert first["buy_order_count"] == 1
    assert first["sell_order_count"] == 0
    assert first["orders"] == [
        {
            "sequence": 1,
            "portfolio_id": "dual_momentum",
            "ticker": "SPY",
            "side": "buy",
            "quantity": 325.0,
            "signal_date": "2026-09-30",
            "signal_close": 120.0,
            "signal_notional": 39000.0,
            "veto_eligible": True,
        }
    ]
    assert first["candidate_sha256"] == canonical_sha256(
        {key: value for key, value in first.items() if key != "candidate_sha256"}
    )
    after = {
        table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in before
    }
    assert after == before


def test_price_observation_capture_does_not_change_algorithm_candidate(con):
    market_date = _market(con)
    policy = agent_policy.get("dual_momentum_hybrid_veto_shadow_v1")

    before = agent_algorithm_candidate.materialize(con, policy, market_date)
    captured = agent_price_observations.capture_strategy_scope(
        con,
        "dual_momentum",
        market_date,
        observed_at=datetime(2026, 10, 1, 1, 0, tzinfo=timezone.utc),
    )
    after = agent_algorithm_candidate.materialize(con, policy, market_date)

    assert captured["inserted_observations"] == 759
    assert after == before
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


def test_hybrid_context_contains_candidate_without_execution_authority(con):
    _market(con)

    payload = agent_context.build(
        con,
        "dual_momentum",
        "SPY",
        policy_id="dual_momentum_hybrid_veto_shadow_v1",
    )

    assert payload["policy"]["mode"] == "hybrid"
    assert payload["policy"]["generation_enabled"] is True
    assert payload["algorithm_candidate"]["order_count"] == 1
    assert payload["algorithm_candidate"]["orders"][0]["ticker"] == "SPY"
    assert con.execute(
        "SELECT COUNT(*) FROM portfolios WHERE id = "
        "'hybrid_dual_momentum_veto_shadow_v1'"
    ).fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


def test_candidate_rejects_non_hybrid_policy(con):
    market_date = _market(con)

    with pytest.raises(agent_algorithm_candidate.CandidateError, match="hybrid"):
        agent_algorithm_candidate.materialize(
            con,
            agent_policy.get("dual_momentum_agent_shadow_v1"),
            market_date,
        )
