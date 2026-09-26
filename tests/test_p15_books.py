"""P15 comparator-book initialization and isolation contracts."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from engine.lib import db
from sim import league, p15_books, portfolio
from sim.schema import init_sim_schema
from tests.conftest import PRICES_DDL, SESSIONS, insert_bars


def _activate(con, checkpoint):
    init_sim_schema(con)
    con.execute(
        "INSERT INTO portfolios (id,name,strategy,config,created,active,cash,initial_cash,"
        "execution_profile) VALUES "
        "('control','control','agent_only_policy','{}',?,TRUE,100,100,'baseline_v1')",
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
        "atr_14": 2.0,
        "baseline_rank": baseline_rank, "scoring_status": (
            "available" if available else "unavailable"
        ),
        "decision": action,
        "action": {"buy_candidate": "buy", "exit": "sell"}.get(action, "none"),
        "p_outperform_5": 0.70 if available else None,
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


def test_initialization_and_activation_are_atomic_and_reject_owned_state(con):
    checkpoint = date(2026, 9, 24)
    con.execute(
        "INSERT INTO portfolios VALUES "
        "('p15_rule_control','wrong','noop','{}',?,FALSE,1,1,'baseline_v1')",
        [checkpoint],
    )
    with pytest.raises(p15_books.P15BookError, match="differs"):
        p15_books.initialize_books(con, checkpoint)
    assert con.execute(
        "SELECT id FROM portfolios WHERE id IN (?,?,?) ORDER BY id",
        list(p15_books.BOOK_IDS),
    ).fetchall() == [("p15_rule_control",)]
    con.execute("DELETE FROM portfolios WHERE id='p15_rule_control'")
    p15_books.initialize_books(con, checkpoint)
    con.execute(
        "INSERT INTO portfolios VALUES "
        "('control','control','noop','{}',?,TRUE,100,100,'baseline_v1')",
        [checkpoint],
    )
    con.execute("INSERT INTO sim_equity VALUES ('control',?,100,100,0)", [checkpoint])
    con.execute(
        "INSERT INTO p15_order_intents VALUES "
        "(1,NULL,?,'SPY','buy',1,?,'spy_reinvest',99,100,NULL,NULL,"
        "'pending',NULL,NULL,CURRENT_TIMESTAMP)",
        [p15_books.BOOK_IDS[0], checkpoint],
    )
    with pytest.raises(p15_books.P15BookError, match="owned runtime state"):
        p15_books.activate_books(con, checkpoint)
    assert p15_books.activation_state(con) == "inactive"
    assert con.execute(
        "SELECT COUNT(*) FROM sim_equity WHERE portfolio_id IN (?,?,?)",
        list(p15_books.BOOK_IDS),
    ).fetchone() == (0,)


def test_activation_requires_one_common_active_checkpoint(con):
    checkpoint = date(2026, 9, 24)
    p15_books.initialize_books(con, checkpoint)
    con.executemany(
        "INSERT INTO portfolios VALUES (?,?,'noop','{}',?,TRUE,100,100,'baseline_v1')",
        [("a", "a", checkpoint), ("b", "b", checkpoint)],
    )
    con.executemany(
        "INSERT INTO sim_equity VALUES (?,?,?,?,0)",
        [("a", checkpoint, 100, 100), ("b", date(2026, 9, 23), 100, 100)],
    )
    with pytest.raises(p15_books.P15BookError, match="completed league date"):
        p15_books.activate_books(con, checkpoint)
    assert p15_books.activation_state(con) == "inactive"


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
    con.execute("UPDATE prices SET high=150,low=50 WHERE ticker='AAA'")

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
    assert all(row[2] == pytest.approx(1_500 / 101.5) for row in entries)
    assert all(row[2] * row[3] <= 1_500 for row in entries)
    assert all(row[3] == pytest.approx(101.5) for row in entries)
    sleeves = con.execute(
        "SELECT portfolio_id,qty FROM p15_order_intents "
        "WHERE order_role='spy_reinvest' ORDER BY portfolio_id"
    ).fetchall()
    assert sleeves == [(book_id, 70.0) for book_id in sorted(p15_books.BOOK_IDS)]
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)
    assert p15_books.queue_orders(
        con, market_date, created_at=datetime(2026, 9, 25, tzinfo=timezone.utc)
    ) == {"status": "queued", "created": 0}
    con.execute("UPDATE prices SET close=50 WHERE ticker='SPY' AND date=?", [market_date])
    with pytest.raises(p15_books.P15BookError, match="intent replay differs"):
        p15_books.queue_orders(
            con, market_date, created_at=datetime(2026, 9, 26, tzinfo=timezone.utc)
        )


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
    ) == {"status": "queued", "created": 3}
    assert con.execute(
        "SELECT COUNT(*) FROM p15_book_state WHERE entry_halted"
    ).fetchone() == (3,)
    assert con.execute(
        "SELECT COUNT(*) FROM p15_order_intents WHERE order_role='entry'"
    ).fetchone() == (0,)


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
        "SELECT COUNT(*) FROM sim_orders WHERE status='p15_filled'"
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
    assert sleeves == [(book_id, 70.0) for book_id in sorted(p15_books.BOOK_IDS)]
    assert con.execute(
        "SELECT COUNT(*) FROM sim_orders WHERE status='pending'"
    ).fetchone() == (0,)


def test_limit_miss_is_terminal_and_keeps_counterfactual_price(con):
    market_date, fill_date = SESSIONS[29:31]
    insert_bars(con, "SPY", SESSIONS[:35], open_=100, close=100, high=101, low=99)
    insert_bars(
        con, "AAA", SESSIONS[:30], open_=100, close=100, high=101, low=99
    )
    insert_bars(con, "AAA", [fill_date], open_=102, close=102, high=103, low=101)
    insert_bars(con, "AAA", SESSIONS[31:35], open_=102, close=105, high=106, low=101)
    labeled_at = datetime(2026, 9, 26, tzinfo=timezone.utc)
    con.execute("UPDATE prices SET fetched_at=?", [labeled_at.replace(tzinfo=None)])
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
    assert p15_books.label_limit_counterfactuals(con, labeled_at=labeled_at) == 3
    labels = con.execute(
        "SELECT attempt_date,entry_px,exit_date,net_return,net_excess_return "
        "FROM p15_limit_labels ORDER BY intent_id"
    ).fetchall()
    assert len(labels) == 3 and all(row[0] == fill_date for row in labels)
    assert all(row[1] > 102 and row[2] == SESSIONS[34] for row in labels)
    assert p15_books.label_limit_counterfactuals(con, labeled_at=labeled_at) == 0


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
    ).fetchall() == [(14.0,)]
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


def test_pending_entries_cannot_fill_after_drawdown_halt(con):
    signal_date, missing_date, resume_date = SESSIONS[29:32]
    insert_bars(con, "SPY", SESSIONS[:32], open_=100, close=100, high=101, low=99)
    insert_bars(con, "AAA", SESSIONS[:30], open_=100, close=100, high=101, low=99)
    _activate(con, signal_date)
    _seed_decisions(con, signal_date, [_decision("AAA", 1, 100)])
    p15_books.queue_orders(
        con, signal_date, created_at=datetime(2026, 9, 25, tzinfo=timezone.utc)
    )
    assert p15_books.process_pending(con, missing_date) == {
        "filled": 3, "rejected": 0, "pending": 3,
    }
    insert_bars(con, "AAA", [missing_date], open_=100, close=100, high=101, low=99)
    with pytest.raises(p15_books.P15BookError, match="limit-attempt replay differs"):
        p15_books.process_pending(con, missing_date)
    con.execute("UPDATE p15_book_state SET entry_halted=TRUE")
    insert_bars(con, "AAA", [resume_date], open_=100, close=100, high=101, low=99)

    assert p15_books.process_pending(con, resume_date) == {
        "filled": 0, "rejected": 3, "pending": 0,
    }
    assert con.execute(
        "SELECT COUNT(*) FROM sim_positions WHERE ticker='AAA' AND qty>0"
    ).fetchone() == (0,)
    assert con.execute(
        "SELECT COUNT(*) FROM p15_order_intents WHERE reason='drawdown_halt'"
    ).fetchone() == (3,)


def test_drawdown_halt_latches_without_a_scoring_window(con):
    checkpoint, loss_date, recovery_date = SESSIONS[29:32]
    insert_bars(con, "SPY", SESSIONS[:32], open_=100, close=100, high=101, low=99)
    insert_bars(con, "AAA", SESSIONS[:30], open_=100, close=100, high=101, low=99)
    insert_bars(con, "AAA", [loss_date], open_=100, close=100, high=101, low=99)
    insert_bars(con, "AAA", [recovery_date], open_=130, close=130, high=131, low=129)
    _activate(con, checkpoint)
    for index, book_id in enumerate(p15_books.BOOK_IDS, start=1):
        con.execute("UPDATE portfolios SET cash=0 WHERE id=?", [book_id])
        con.execute("INSERT INTO sim_positions VALUES (?, 'AAA', 79, 100)", [book_id])
        con.execute(
            "INSERT INTO p15_position_rules VALUES (?, 'AAA', ?, ?, ?, 2, 1, 'open')",
            [book_id, index, index, checkpoint],
        )

    loss = p15_books.run_window(
        con, loss_date, observed_at=datetime(2026, 9, 25, tzinfo=timezone.utc)
    )
    recovery = p15_books.run_window(
        con, recovery_date, observed_at=datetime(2026, 9, 26, tzinfo=timezone.utc)
    )

    assert loss["queued"] == recovery["queued"] == 0
    assert con.execute(
        "SELECT COUNT(*) FROM p15_book_state WHERE entry_halted"
    ).fetchone() == (3,)
    assert con.execute(
        "SELECT MIN(peak_equity),MAX(peak_equity) FROM p15_book_state"
    ).fetchone() == (10_270.0, 10_270.0)


def test_complete_window_is_replay_safe_and_does_not_touch_other_book(con, tmp_path):
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

    assert first["queued"] == 6 and first["filled"] == 0 and first["restored"] == 0
    assert second["filled"] == 6 and second["queued"] == second["restored"] == 0
    assert replay["filled"] == replay["rejected"] == replay["pending"] == 0
    assert replay["queued"] == 0
    assert sentinel_before == (
        con.execute("SELECT * FROM portfolios WHERE id='control'").fetchall(),
        con.execute("SELECT * FROM sim_equity WHERE portfolio_id='control'").fetchall(),
    )
    assert con.execute(
        "SELECT COUNT(DISTINCT portfolio_id) FROM sim_fills"
    ).fetchone() == (3,)
    assert league.step(con, signal_date, tmp_path, rerun=True, verbose=False) == 1
    assert con.execute(
        "SELECT COUNT(*) FROM sim_orders WHERE status='p15_filled'"
    ).fetchone() == (6,)
    assert league.step(con, fill_date, tmp_path, rerun=True, verbose=False) == 0
    assert con.execute(
        "SELECT COUNT(*) FROM sim_orders WHERE status='pending'"
    ).fetchone() == (0,)
    non_p15_after_rerun = (
        con.execute("SELECT * FROM portfolios WHERE id='control'").fetchall(),
        con.execute("SELECT * FROM sim_positions WHERE portfolio_id='control'").fetchall(),
        con.execute("SELECT * FROM sim_equity WHERE portfolio_id='control'").fetchall(),
    )
    restored = p15_books.run_window(
        con, fill_date, observed_at=datetime(2026, 9, 26, tzinfo=timezone.utc)
    )
    assert restored["restored"] == 6
    assert con.execute("SELECT COUNT(*) FROM sim_fills").fetchone() == (6,)
    assert non_p15_after_rerun == (
        con.execute("SELECT * FROM portfolios WHERE id='control'").fetchall(),
        con.execute("SELECT * FROM sim_positions WHERE portfolio_id='control'").fetchall(),
        con.execute("SELECT * FROM sim_equity WHERE portfolio_id='control'").fetchall(),
    )
    con.execute("UPDATE prices SET close=101 WHERE ticker='AAA' AND date=?", [fill_date])
    with pytest.raises(p15_books.P15BookError, match="equity replay differs"):
        p15_books.run_window(
            con, fill_date, observed_at=datetime(2026, 9, 27, tzinfo=timezone.utc)
        )


def test_fill_time_position_cap_handles_a_pending_exit(con):
    signal_date, fill_date = SESSIONS[29:31]
    for ticker in ("SPY", "NEW", *(f"H{i}" for i in range(1, 8))):
        insert_bars(con, ticker, SESSIONS[:31], open_=100, close=100, high=101, low=99)
    insert_bars(con, "H0", SESSIONS[:30], open_=100, close=100, high=101, low=99)
    _activate(con, signal_date)
    book_id = "p15_ai_ranked"
    con.execute("UPDATE portfolios SET cash=0 WHERE id=?", [book_id])
    con.execute("INSERT INTO sim_positions VALUES (?, 'SPY', 20, 100)", [book_id])
    for index in range(8):
        ticker = f"H{index}"
        con.execute("INSERT INTO sim_positions VALUES (?, ?, 10, 100)", [book_id, ticker])
        con.execute(
            "INSERT INTO p15_position_rules VALUES (?, ?, ?, ?, ?, 2, 50, 'open')",
            [book_id, ticker, 100 + index, 100 + index, signal_date],
        )
    _seed_decisions(con, signal_date, [
        {**_decision("H0", 2, -10, action="exit"), "tradeable": False,
         "stratum": "held_only"},
        _decision("NEW", 1, 100),
    ])

    p15_books.queue_orders(
        con, signal_date, created_at=datetime(2026, 9, 25, tzinfo=timezone.utc)
    )
    result = p15_books.process_pending(con, fill_date)

    assert result["pending"] == 1
    assert con.execute(
        "SELECT status,reason FROM p15_order_intents WHERE portfolio_id=? "
        "AND ticker='NEW'", [book_id],
    ).fetchone() == ("rejected", "position_cap")
    assert con.execute(
        "SELECT COUNT(*) FROM sim_positions WHERE portfolio_id=? "
        "AND ticker!='SPY' AND qty>0", [book_id],
    ).fetchone() == (8,)


def test_split_factor_adjusts_pending_entry_and_fixed_stop(con):
    signal_date, fill_date, split_date = SESSIONS[29:32]
    insert_bars(con, "SPY", SESSIONS[:32], open_=100, close=100, high=101, low=99)
    insert_bars(con, "AAA", SESSIONS[:30], open_=100, close=100, high=101, low=99)
    insert_bars(con, "AAA", [fill_date], open_=50, close=50, high=51, low=49)
    insert_bars(con, "AAA", [split_date], open_=23.7, close=23.7, high=24, low=23)
    con.execute(
        "CREATE TABLE split_adjustments "
        "(ticker VARCHAR,ex_date DATE,ratio DOUBLE,outcome VARCHAR)"
    )
    _activate(con, signal_date)
    _seed_decisions(con, signal_date, [_decision("AAA", 1, 100)])
    p15_books.queue_orders(
        con, signal_date, created_at=datetime(2026, 9, 25, tzinfo=timezone.utc)
    )
    con.execute(
        "INSERT INTO split_adjustments VALUES ('AAA',?,2,'applied')", [fill_date]
    )

    assert p15_books.process_pending(con, fill_date)["filled"] == 6
    assert con.execute(
        "SELECT DISTINCT qty FROM sim_orders WHERE ticker='AAA'"
    ).fetchone()[0] == pytest.approx(2 * 1_500 / 101.5)
    assert con.execute(
        "SELECT DISTINCT limit_px FROM p15_limit_attempts"
    ).fetchone()[0] == pytest.approx(50.75)
    assert con.execute(
        "SELECT DISTINCT stop_px FROM p15_position_rules"
    ).fetchone()[0] == pytest.approx(47.55)

    con.execute(
        "INSERT INTO split_adjustments VALUES ('AAA',?,2,'applied')", [split_date]
    )
    portfolio.rebuild_state(con)
    for book_id in p15_books.BOOK_IDS:
        portfolio.mark_to_market(con, book_id, split_date)
    _seed_decisions(con, split_date, [
        {**_decision("AAA", 1, 100, action="watch"), "tradeable": False}
    ])
    p15_books.queue_orders(
        con, split_date, created_at=datetime(2026, 9, 26, tzinfo=timezone.utc)
    )
    assert con.execute(
        "SELECT COUNT(*) FROM p15_order_intents WHERE signal_date=? AND order_role='stop'",
        [split_date],
    ).fetchone() == (3,)


def test_complete_dry_run_window_uses_copy_and_leaves_source_unchanged(tmp_path):
    database = tmp_path / "market.duckdb"
    con = db.connect(database)
    db.init_schema(con)
    db.init_screen_policy_schema(con)
    db.init_mining_schema(con)
    con.execute(PRICES_DDL)
    init_sim_schema(con)
    signal_date, fill_date = SESSIONS[29:31]
    for ticker in ("SPY", "AAA"):
        insert_bars(con, ticker, SESSIONS[:31], open_=100, close=100, high=101, low=99)
    con.execute(
        "INSERT INTO portfolios VALUES "
        "('control','control','noop','{}',?,TRUE,100,100,'baseline_v1')",
        [signal_date],
    )
    con.execute("INSERT INTO sim_equity VALUES ('control',?,100,100,0)", [signal_date])
    _seed_decisions(con, signal_date, [_decision("AAA", 1, 100)])
    con.close()
    before = database.read_bytes()

    result = p15_books.dry_run_window(
        database, signal_date, fill_date,
        observed_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
        lock_path=tmp_path / "nightly.lock",
    )

    assert result["dry_run"] is True and result["signal"]["queued"] == 6
    assert result["fill"]["filled"] == 6 and result["fill"]["pending"] == 0
    assert database.read_bytes() == before
    source = db.connect(database, read_only=True)
    assert source.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name='p15_book_contracts'"
    ).fetchone() == (0,)
    source.close()
