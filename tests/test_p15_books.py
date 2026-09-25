"""P15 comparator-book initialization and isolation contracts."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from server import p15_books
from sim.schema import init_sim_schema
from tests.conftest import SESSIONS, insert_bars


def _activate(con, checkpoint):
    init_sim_schema(con)
    con.execute(
        "INSERT INTO portfolios (id,name,strategy,config,created,active,cash,initial_cash,"
        "execution_profile) VALUES ('control','control','noop','{}',?,TRUE,100,100,'baseline_v1')",
        [date(2026, 1, 1)],
    )
    con.execute("INSERT INTO sim_equity VALUES ('control',?,100,100,0)", [checkpoint])
    p15_books.initialize_books(con, checkpoint)
    p15_books.activate_books(con, checkpoint)


def _seed_decisions(con, market_date, decisions):
    con.execute(
        "CREATE TABLE agent_evaluation_traces (id BIGINT PRIMARY KEY, policy_id VARCHAR, "
        "market_date DATE, terminal_status VARCHAR)"
    )
    con.execute(
        "CREATE TABLE agent_evaluation_decisions (id BIGINT PRIMARY KEY, trace_id BIGINT, "
        "ticker VARCHAR, decision_payload VARCHAR)"
    )
    con.execute(
        "INSERT INTO agent_evaluation_traces VALUES "
        "(1,'p15-scoring-v1',?,'completed')", [market_date]
    )
    con.executemany(
        "INSERT INTO agent_evaluation_decisions VALUES (1+?,1,?,?)",
        [(index, item["ticker"], json.dumps(item))
         for index, item in enumerate(decisions)],
    )


def _decision(ticker, baseline_rank, expected, *, action="buy_candidate", available=True):
    return {
        "ticker": ticker, "tradeable": True, "stratum": "mover", "close": 100.0,
        "baseline_rank": baseline_rank, "scoring_status": (
            "available" if available else "unavailable"
        ),
        "action": action, "p_outperform_5": 0.70 if available else None,
        "expected_excess_bp_5": expected if available else None,
    }


def test_initialization_creates_exact_inactive_empty_books(con):
    created = date(2026, 9, 25)
    result = p15_books.initialize_books(
        con, created, initialized_at=datetime(2026, 9, 25, tzinfo=timezone.utc)
    )
    replay = p15_books.initialize_books(con, created)

    assert result == replay == {
        "status": "ready", "book_count": 3, "active_count": 0,
        "runtime_counts": {"sim_orders": 0, "sim_fills": 0,
                           "sim_positions": 0, "sim_equity": 0},
    }
    rows = con.execute(
        "SELECT id,active,cash,initial_cash,execution_profile FROM portfolios "
        "WHERE id IN (?,?,?) ORDER BY id", list(p15_books.BOOK_IDS)
    ).fetchall()
    assert [row[0] for row in rows] == sorted(p15_books.BOOK_IDS)
    assert all(row[1:] == (False, 10_000.0, 10_000.0, "baseline_v1") for row in rows)


def test_activation_is_atomic_aligned_and_rejects_contamination(con):
    init_sim_schema(con)
    checkpoint = date(2026, 9, 24)
    con.execute(
        "INSERT INTO portfolios (id,name,strategy,config,created,active,cash,initial_cash,"
        "execution_profile) VALUES ('control','control','noop','{}',?,TRUE,100,100,'baseline_v1')",
        [date(2026, 1, 1)],
    )
    con.execute("INSERT INTO sim_equity VALUES ('control',?,100,100,0)", [checkpoint])
    p15_books.initialize_books(con, checkpoint)

    result = p15_books.activate_books(con, checkpoint)

    assert result == {"status": "active", "book_count": 3,
                      "checkpoint": checkpoint.isoformat()}
    assert con.execute(
        "SELECT COUNT(*) FROM portfolios WHERE id IN (?,?,?) AND active", list(p15_books.BOOK_IDS)
    ).fetchone() == (3,)
    assert con.execute(
        "SELECT COUNT(*) FROM sim_equity WHERE portfolio_id IN (?,?,?) AND date=?",
        [*p15_books.BOOK_IDS, checkpoint],
    ).fetchone() == (3,)

    with pytest.raises(p15_books.P15BookError, match="jointly inactive"):
        p15_books.activate_books(con, checkpoint)


def test_mixed_activation_and_runtime_rows_fail_closed(con):
    checkpoint = date(2026, 9, 24)
    p15_books.initialize_books(con, checkpoint)
    con.execute("UPDATE portfolios SET active=TRUE WHERE id=?", [p15_books.BOOK_IDS[0]])
    with pytest.raises(p15_books.P15BookError, match="mixed activation"):
        p15_books.activation_state(con)

    con.execute("UPDATE portfolios SET active=FALSE WHERE id=?", [p15_books.BOOK_IDS[0]])
    con.execute(
        "INSERT INTO sim_orders VALUES (1,?,'SPY','buy',1,?,'pending',NULL)",
        [p15_books.BOOK_IDS[0], checkpoint],
    )
    with pytest.raises(p15_books.P15BookError, match="runtime state"):
        p15_books.activate_books(con, checkpoint)


def test_queue_orders_applies_three_policies_and_shared_atr_sizing(con):
    market_date = SESSIONS[29]
    for ticker in ("SPY", "AAA", "BBB", "CCC"):
        insert_bars(con, ticker, SESSIONS[:30], open_=100, close=100, high=101, low=99)
    _activate(con, market_date)
    _seed_decisions(con, market_date, [
        _decision("AAA", 2, 100),
        _decision("BBB", 1, -10, action="watch"),
        _decision("CCC", 3, 80),
    ])

    result = p15_books.queue_orders(
        con, market_date, created_at=datetime(2026, 9, 25, tzinfo=timezone.utc)
    )

    assert result == {"status": "queued", "created": 9}
    entries = con.execute(
        "SELECT portfolio_id,ticker,qty,limit_px FROM p15_order_intents "
        "WHERE order_role='entry' ORDER BY portfolio_id,priority"
    ).fetchall()
    assert [(row[0], row[1]) for row in entries] == [
        ("p15_ai_ranked", "AAA"), ("p15_ai_ranked", "CCC"),
        ("p15_hybrid_veto", "AAA"), ("p15_hybrid_veto", "CCC"),
        ("p15_rule_control", "BBB"), ("p15_rule_control", "AAA"),
    ]
    assert all(row[2] == pytest.approx(15.0) for row in entries)
    assert all(row[3] == pytest.approx(101.5) for row in entries)
    sleeves = con.execute(
        "SELECT portfolio_id,qty FROM p15_order_intents "
        "WHERE order_role='spy_reinvest' ORDER BY portfolio_id"
    ).fetchall()
    assert sleeves == [(book_id, 69.0) for book_id in sorted(p15_books.BOOK_IDS)]
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)
    assert p15_books.queue_orders(
        con, market_date, created_at=datetime(2026, 9, 25, tzinfo=timezone.utc)
    ) == {"status": "queued", "created": 0}


def test_inactive_books_are_noop_and_drawdown_halt_blocks_entries(con):
    market_date = SESSIONS[29]
    for ticker in ("SPY", "AAA"):
        insert_bars(con, ticker, SESSIONS[:30], open_=100, close=100, high=101, low=99)
    p15_books.initialize_books(con, market_date)
    assert p15_books.queue_orders(
        con, market_date, created_at=datetime.now(timezone.utc)
    ) == {"status": "inactive", "created": 0}

    con.execute(
        "INSERT INTO portfolios (id,name,strategy,config,created,active,cash,initial_cash,"
        "execution_profile) VALUES ('control','control','noop','{}',?,TRUE,100,100,'baseline_v1')",
        [date(2026, 1, 1)],
    )
    con.execute("INSERT INTO sim_equity VALUES ('control',?,100,100,0)", [market_date])
    p15_books.activate_books(con, market_date)
    con.execute(
        "UPDATE sim_equity SET equity=7900,cash=7900 WHERE portfolio_id IN (?,?,?)",
        list(p15_books.BOOK_IDS),
    )
    _seed_decisions(con, market_date, [_decision("AAA", 1, 100)])
    assert p15_books.queue_orders(
        con, market_date, created_at=datetime.now(timezone.utc)
    ) == {"status": "queued", "created": 0}
    assert con.execute(
        "SELECT COUNT(*) FROM p15_book_state WHERE entry_halted"
    ).fetchone() == (3,)
