"""Evaluation clocks restart at the recorded P22 commission break."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from engine import forward_review, p15_evaluation, xs_forward_review
from sim import book_breaks


def _portfolio(con, portfolio_id: str, created: date):
    con.execute(
        "INSERT INTO portfolios "
        "(id,name,strategy,config,created,active,cash,initial_cash,execution_profile) "
        "VALUES (?,?, 'none','{}',?,TRUE,10000,10000,'baseline_v1')",
        [portfolio_id, portfolio_id, created],
    )


def _break(con, portfolio_id: str, boundary: date):
    con.execute(
        "INSERT INTO sim_book_breaks VALUES "
        "(?,?,'cost_profile','baseline_v1','ibkr_pro_tiered_v1',13,'test',now())",
        [portfolio_id, boundary],
    )


def test_common_clock_uses_latest_break_in_a_comparison(con):
    _portfolio(con, "a", date(2026, 1, 2))
    _portfolio(con, "b", date(2026, 1, 2))
    _break(con, "a", date(2026, 10, 12))
    _break(con, "b", date(2026, 10, 13))

    assert book_breaks.evaluation_start(
        con, ("a", "b"), date(2026, 1, 2)
    ) == date(2026, 10, 13)


def test_p15_book_and_p8_clocks_exclude_pre_break_sessions_and_trades(con):
    created = date(2026, 1, 2)
    boundary = date(2026, 10, 12)
    con.execute("CREATE TABLE p15_book_contracts (portfolio_id VARCHAR)")
    con.execute(
        "CREATE TABLE p15_book_windows "
        "(portfolio_id VARCHAR,market_date DATE,equity DOUBLE)"
    )
    con.execute(
        "CREATE TABLE p15_book_fills "
        "(intent_id BIGINT,portfolio_id VARCHAR,ticker VARCHAR,qty DOUBLE,"
        "fill_px DOUBLE,fill_date DATE)"
    )
    con.execute(
        "CREATE TABLE p15_order_intents "
        "(id BIGINT,portfolio_id VARCHAR,ticker VARCHAR,side VARCHAR,status VARCHAR)"
    )
    for offset, portfolio_id in enumerate(p15_evaluation.BOOK_IDS):
        _portfolio(con, portfolio_id, created)
        _break(con, portfolio_id, boundary)
        con.execute("INSERT INTO p15_book_contracts VALUES (?)", [portfolio_id])
        con.executemany(
            "INSERT INTO p15_book_windows VALUES (?,?,?)",
            [
                (portfolio_id, created, 10_000.0),
                (portfolio_id, boundary, 10_100.0 + offset),
                (portfolio_id, boundary + timedelta(days=1), 10_200.0 + offset),
            ],
        )
        con.executemany(
            "INSERT INTO p15_order_intents VALUES (?,?,?,'sell','filled')",
            [(offset * 10 + 1, portfolio_id, "OLD"),
             (offset * 10 + 2, portfolio_id, "NEW")],
        )
        con.executemany(
            "INSERT INTO p15_book_fills VALUES (?,?,?,?,?,?)",
            [
                (offset * 10 + 1, portfolio_id, "OLD", 1, 100, boundary - timedelta(days=1)),
                (offset * 10 + 2, portfolio_id, "NEW", 1, 100, boundary),
            ],
        )

    books = p15_evaluation.books(con)
    assert all(item["evaluation_clock_start"] == boundary.isoformat()
               for item in books["books"])
    assert all(item["closed_trade_count"] == 1 for item in books["books"])
    assert all(item["calendar_days"] == 1 for item in books["books"])
    assert not any(item["comparison_eligible"] for item in books["books"])

    _portfolio(con, "daily_opportunity_agent_v1", created)
    _break(con, "daily_opportunity_agent_v1", boundary)
    con.execute(
        "CREATE TABLE agent_evaluation_traces "
        "(market_date DATE,policy_id VARCHAR,terminal_status VARCHAR)"
    )
    con.executemany(
        "INSERT INTO agent_evaluation_traces VALUES "
        "(?,'nightly_opportunity_tool_v1','completed')",
        [(boundary - timedelta(days=1),), (boundary,), (boundary + timedelta(days=1),)],
    )
    p8 = p15_evaluation.p8_rule(
        con, datetime.combine(boundary + timedelta(days=1), datetime.min.time(), timezone.utc)
    )
    assert p8["cohort_start"] == boundary.isoformat()
    assert p8["completed_session_count"] == 2
    assert p8["elapsed_calendar_days"] == 1


def test_sector_monitor_keeps_frozen_prefix_but_restarts_metrics(
    con, monkeypatch,
):
    start = forward_review.OBSERVATION_START
    boundary = start + timedelta(days=2)
    for portfolio_id in (forward_review.CANDIDATE_ID, forward_review.CONTROL_ID):
        _portfolio(con, portfolio_id, date(2024, 1, 2))
        _break(con, portfolio_id, boundary)
        con.execute(
            "UPDATE portfolios SET strategy=?,config=? WHERE id=?",
            [portfolio_id, json.dumps({"id": portfolio_id}), portfolio_id],
        )
    con.executemany(
        "INSERT INTO sim_equity VALUES (?,?,?,0,1)",
        [
            (forward_review.CANDIDATE_ID, start, 100.0),
            (forward_review.CONTROL_ID, start, 100.0),
            (forward_review.CANDIDATE_ID, start + timedelta(days=1), 80.0),
            (forward_review.CONTROL_ID, start + timedelta(days=1), 120.0),
            (forward_review.CANDIDATE_ID, boundary, 90.0),
            (forward_review.CONTROL_ID, boundary, 90.0),
        ],
    )
    monkeypatch.setattr(forward_review, "_validate_registration", lambda *_args: None)
    monkeypatch.setattr(forward_review, "_validate_published_runtime", lambda *_args: None)
    monkeypatch.setattr(forward_review, "_validate_baseline_state", lambda *_args: {})
    monkeypatch.setattr(forward_review, "_validate_prior_equity", lambda *_args: None)
    monkeypatch.setattr(forward_review, "_forward_ledger", lambda *_args: {})
    monkeypatch.setattr(forward_review, "_ledger_checkpoint", lambda *_args: {})
    monkeypatch.setattr(forward_review, "_execution_audit", lambda *_args: {})
    monkeypatch.setattr(
        forward_review,
        "EXPECTED_BASELINE_EQUITY",
        {forward_review.CANDIDATE_ID: 100.0, forward_review.CONTROL_ID: 100.0},
    )

    result = forward_review.evaluate(con)

    assert result["observation"]["first_shared_date"] == start.isoformat()
    assert result["observation"]["evaluation_clock_start"] == boundary.isoformat()
    assert result["observation"]["pre_break_shared_sessions"] == 2
    assert result["metrics"]["excess_return"] == 0.0
    assert "restart at the recorded break" in forward_review.render(result)


def test_xs_monitor_restarts_metrics_without_rewriting_frozen_baseline(
    con, monkeypatch,
):
    start = xs_forward_review.OBSERVATION_START
    boundary = start + timedelta(days=2)
    for portfolio_id in (xs_forward_review.CANDIDATE_ID, xs_forward_review.CONTROL_ID):
        _portfolio(con, portfolio_id, date(2026, 9, 2))
        _break(con, portfolio_id, boundary)
    con.executemany(
        "INSERT INTO sim_equity VALUES (?,?,?,0,1)",
        [
            (xs_forward_review.CANDIDATE_ID, start, 100.0),
            (xs_forward_review.CONTROL_ID, start, 100.0),
            (xs_forward_review.CANDIDATE_ID, start + timedelta(days=1), 80.0),
            (xs_forward_review.CONTROL_ID, start + timedelta(days=1), 120.0),
            (xs_forward_review.CANDIDATE_ID, boundary, 90.0),
            (xs_forward_review.CONTROL_ID, boundary, 90.0),
        ],
    )
    monkeypatch.setattr(xs_forward_review, "_validate_runtime", lambda *_args: None)
    monkeypatch.setattr(
        xs_forward_review, "_validate_published_runtime", lambda *_args: None
    )
    monkeypatch.setattr(xs_forward_review, "_validate_prior", lambda *_args: {})
    monkeypatch.setattr(
        xs_forward_review, "_validate_initial_transition", lambda *_args: "transition"
    )
    monkeypatch.setattr(xs_forward_review, "_ledger_sha256", lambda *_args: "ledger")
    baseline_state = {
        portfolio_id: {"n_positions": 1}
        for portfolio_id in (
            xs_forward_review.CANDIDATE_ID, xs_forward_review.CONTROL_ID
        )
    }
    monkeypatch.setattr(
        xs_forward_review, "_baseline_state", lambda *_args: baseline_state
    )
    monkeypatch.setattr(
        xs_forward_review,
        "_execution_audit",
        lambda *_args: {
            xs_forward_review.CANDIDATE_ID: {
                "filled": 1, "rejected": 0, "stale_pending": 0,
            },
            xs_forward_review.CONTROL_ID: {
                "filled": 1, "rejected": 0, "stale_pending": 0,
            },
        },
    )

    result = xs_forward_review.evaluate(con)

    assert result["frozen_runtime"]["baseline_equity"] == {
        xs_forward_review.CANDIDATE_ID: 100.0,
        xs_forward_review.CONTROL_ID: 100.0,
    }
    assert result["observation"]["evaluation_clock_start"] == boundary.isoformat()
    assert result["observation"]["pre_break_shared_sessions"] == 2
    assert result["metrics"]["cumulative_excess"] == 0.0
    assert "restart at the recorded break" in xs_forward_review.render(result)
