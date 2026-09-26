"""P15 comparator-book initialization and isolation contracts."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from server import p15_books
from sim import portfolio
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
        "CREATE TABLE IF NOT EXISTS agent_evaluation_traces "
        "(id BIGINT PRIMARY KEY, policy_id VARCHAR, "
        "market_date DATE, terminal_status VARCHAR)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS agent_evaluation_decisions "
        "(id BIGINT PRIMARY KEY, trace_id BIGINT, "
        "ticker VARCHAR, decision_payload VARCHAR)"
    )
    trace_id = int(con.execute(
        "SELECT COALESCE(MAX(id),0)+1 FROM agent_evaluation_traces"
    ).fetchone()[0])
    decision_id = int(con.execute(
        "SELECT COALESCE(MAX(id),0)+1 FROM agent_evaluation_decisions"
    ).fetchone()[0])
    con.execute(
        "INSERT INTO agent_evaluation_traces VALUES "
        "(?,'p15-scoring-v1',?,'completed')", [trace_id, market_date]
    )
    con.executemany(
        "INSERT INTO agent_evaluation_decisions VALUES (?, ?, ?, ?)",
        [(decision_id + index, trace_id, item["ticker"], json.dumps(item))
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


def test_scoped_fill_executes_entries_then_whole_share_spy_sleeve(con):
    market_date, fill_date = SESSIONS[29:31]
    for ticker in ("SPY", "AAA", "BBB", "CCC"):
        insert_bars(con, ticker, SESSIONS[:31], open_=100, close=100, high=101, low=99)
    _activate(con, market_date)
    _seed_decisions(con, market_date, [
        _decision("AAA", 2, 100),
        _decision("BBB", 1, -10, action="watch"),
        _decision("CCC", 3, 80),
    ])
    p15_books.queue_orders(
        con, market_date, created_at=datetime(2026, 9, 25, tzinfo=timezone.utc)
    )

    result = p15_books.process_pending(con, fill_date)

    assert result == {"filled": 9, "rejected": 0, "pending": 0}
    assert con.execute(
        "SELECT COUNT(*) FROM sim_orders WHERE status='filled'"
    ).fetchone() == (9,)
    assert con.execute("SELECT COUNT(*) FROM sim_fills").fetchone() == (9,)
    assert con.execute(
        "SELECT COUNT(*) FROM p15_limit_attempts WHERE outcome='filled'"
    ).fetchone() == (6,)
    assert con.execute(
        "SELECT COUNT(*) FROM p15_position_rules WHERE status='open' AND stop_px=95.1"
    ).fetchone() == (6,)
    sleeves = con.execute(
        "SELECT portfolio_id,qty FROM sim_positions WHERE ticker='SPY' ORDER BY portfolio_id"
    ).fetchall()
    assert sleeves == [(book_id, 69.0) for book_id in sorted(p15_books.BOOK_IDS)]
    assert con.execute(
        "SELECT COUNT(*) FROM sim_orders WHERE status='pending'"
    ).fetchone() == (0,)


def test_limit_miss_is_terminal_and_keeps_counterfactual_price(con):
    market_date, fill_date = SESSIONS[29:31]
    insert_bars(con, "SPY", SESSIONS[:31], open_=100, close=100, high=101, low=99)
    insert_bars(
        con, "AAA", SESSIONS[:30], open_=100, close=100, high=101, low=99
    )
    insert_bars(con, "AAA", [fill_date], open_=102, close=102, high=103, low=101)
    _activate(con, market_date)
    _seed_decisions(con, market_date, [_decision("AAA", 1, 100)])
    p15_books.queue_orders(
        con, market_date, created_at=datetime(2026, 9, 25, tzinfo=timezone.utc)
    )

    result = p15_books.process_pending(con, fill_date)

    assert result == {"filled": 3, "rejected": 3, "pending": 0}
    assert con.execute(
        "SELECT DISTINCT status,reject_reason FROM sim_orders WHERE ticker='AAA'"
    ).fetchall() == [("rejected", "limit_not_reached")]
    attempts = con.execute(
        "SELECT outcome,limit_px,counterfactual_fill_px FROM p15_limit_attempts ORDER BY intent_id"
    ).fetchall()
    assert len(attempts) == 3
    assert all(row[0] == "limit_not_reached" and row[1] == pytest.approx(101.5)
               and row[2] > row[1] for row in attempts)
    assert con.execute(
        "SELECT COUNT(*) FROM sim_positions WHERE ticker='AAA'"
    ).fetchone() == (0,)


def test_spy_funds_entries_and_time_exit_reinvests_next_open(con):
    signal_date, fill_date = SESSIONS[29:31]
    exit_signal, exit_fill = SESSIONS[39:41]
    for ticker in ("SPY", "AAA"):
        insert_bars(con, ticker, SESSIONS[:41], open_=100, close=100, high=101, low=99)
    _activate(con, signal_date)
    con.execute(
        "UPDATE portfolios SET cash=100 WHERE id IN (?,?,?)", list(p15_books.BOOK_IDS)
    )
    con.executemany(
        "INSERT INTO sim_positions VALUES (?, 'SPY', 99, 100)",
        [(book_id,) for book_id in p15_books.BOOK_IDS],
    )
    _seed_decisions(con, signal_date, [_decision("AAA", 1, 100)])

    queued = p15_books.queue_orders(
        con, signal_date, created_at=datetime(2026, 9, 25, tzinfo=timezone.utc)
    )
    assert queued == {"status": "queued", "created": 6}
    assert con.execute(
        "SELECT DISTINCT qty FROM p15_order_intents WHERE order_role='spy_fund'"
    ).fetchall() == [(15.0,)]
    assert p15_books.process_pending(con, fill_date) == {
        "filled": 6, "rejected": 0, "pending": 0,
    }

    for book_id in p15_books.BOOK_IDS:
        portfolio.mark_to_market(con, book_id, exit_signal)
    _seed_decisions(con, exit_signal, [
        {**_decision("AAA", 1, 100, action="watch"), "tradeable": False}
    ])
    exits = p15_books.queue_orders(
        con, exit_signal, created_at=datetime(2026, 9, 25, tzinfo=timezone.utc)
    )
    assert exits == {"status": "queued", "created": 3}
    assert con.execute(
        "SELECT DISTINCT order_role FROM p15_order_intents WHERE signal_date=?",
        [exit_signal],
    ).fetchall() == [("time_exit",)]
    assert p15_books.process_pending(con, exit_fill) == {
        "filled": 3, "rejected": 0, "pending": 0,
    }
    for book_id in p15_books.BOOK_IDS:
        portfolio.mark_to_market(con, book_id, exit_fill)
    _seed_decisions(con, exit_fill, [
        {**_decision("AAA", 1, 100, action="watch"), "tradeable": False}
    ])
    rebuys = p15_books.queue_orders(
        con, exit_fill, created_at=datetime(2026, 9, 25, tzinfo=timezone.utc)
    )
    assert rebuys == {"status": "queued", "created": 3}
    assert con.execute(
        "SELECT COUNT(*) FROM p15_order_intents WHERE signal_date=? "
        "AND order_role='spy_reinvest' AND side='buy'",
        [exit_fill],
    ).fetchone() == (3,)


def test_complete_window_is_replay_safe_and_does_not_touch_other_book(con):
    signal_date, fill_date = SESSIONS[29:31]
    for ticker in ("SPY", "AAA"):
        insert_bars(con, ticker, SESSIONS[:31], open_=100, close=100, high=101, low=99)
    _activate(con, signal_date)
    _seed_decisions(con, signal_date, [_decision("AAA", 1, 100)])
    sentinel_before = con.execute(
        "SELECT * FROM portfolios WHERE id='control'"
    ).fetchall(), con.execute(
        "SELECT * FROM sim_equity WHERE portfolio_id='control'"
    ).fetchall()

    first = p15_books.run_window(
        con, signal_date, observed_at=datetime(2026, 9, 25, tzinfo=timezone.utc)
    )
    _seed_decisions(con, fill_date, [
        {**_decision("AAA", 1, 100, action="watch"), "tradeable": False}
    ])
    second = p15_books.run_window(
        con, fill_date, observed_at=datetime(2026, 9, 26, tzinfo=timezone.utc)
    )
    replay = p15_books.run_window(
        con, fill_date, observed_at=datetime(2026, 9, 26, tzinfo=timezone.utc)
    )

    assert first["queued"] == 6 and first["filled"] == 0
    assert second["filled"] == 6 and second["queued"] == 0
    assert replay["filled"] == replay["rejected"] == replay["pending"] == 0
    assert replay["queued"] == 0
    assert sentinel_before == (
        con.execute("SELECT * FROM portfolios WHERE id='control'").fetchall(),
        con.execute("SELECT * FROM sim_equity WHERE portfolio_id='control'").fetchall(),
    )
    assert con.execute(
        "SELECT COUNT(DISTINCT portfolio_id) FROM sim_fills"
    ).fetchone() == (3,)
