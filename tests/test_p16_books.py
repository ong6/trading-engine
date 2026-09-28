"""P16-only simulator parity, atomicity, and retry checks."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import pytest

from engine.lib import db
from engine.lib.provenance import canonical_sha256
from server import p15_price_fetch_attempts, p16_book_store
from sim import p16_book_mechanics, p16_books
from tests.conftest import SESSIONS, insert_bars, record_p16_calibration

NOW = datetime.combine(SESSIONS[29], time(20), tzinfo=timezone.utc)


def _observed(session):
    return datetime.combine(session, time(16), tzinfo=timezone.utc)


def _price_fetch_cutoff(session):
    return datetime.combine(session, time(22, 45), tzinfo=timezone.utc)


REGISTRATION = "a" * 64
SOURCE = "b" * 64


def _book(con):
    p15_price_fetch_attempts.init_schema(con)
    rows = []
    for index, session in enumerate(SESSIONS, start=1):
        attempted = _price_fetch_cutoff(session)
        identity = {
            "market_date": session.isoformat(), "attempted_at": attempted.isoformat(),
            "source": "yfinance", "requested_count": 0, "failed_count": 0,
            "present_count": 0, "missing_count": 0, "missing_tickers": [],
        }
        rows.append([
            index, session, attempted.replace(tzinfo=None), "yfinance", 0, 0, 0, 0,
            canonical_sha256(identity),
        ])
    con.executemany("INSERT INTO p15_price_fetch_batches VALUES (?,?,?,?,?,?,?,?,?)", rows)
    con.execute(
        "UPDATE prices SET fetched_at=COALESCE(fetched_at, ?) WHERE date<=?",
        [_observed(SESSIONS[30]).replace(tzinfo=None), SESSIONS[30]],
    )
    calibration = record_p16_calibration(con, REGISTRATION, NOW)
    [instance, _] = p16_book_store.initialize_contracts(
        con, registration_sha256=REGISTRATION, activation_date=None,
        calibration_sha256=calibration, created_at=NOW,
    )
    con.execute("UPDATE portfolios SET active=TRUE WHERE id=?", [instance])
    return instance


def _queue(con, instance, *, limit=101.5, qty=10):
    created = p16_books.queue_plan(
        con, book_instance_id=instance, signal_date=SESSIONS[29],
        plan={"status": "planned", "orders": [{
            "ticker": "AAA", "side": "buy", "qty": qty,
            "order_role": "rebalance", "target_weight": 0.1, "entry_atr": 2.0,
        }]},
        limit_prices={"AAA": limit}, source_sha256=SOURCE, created_at=NOW,
        entry_gates={"AAA": "eligible"},
    )
    previous = con.execute(
        "SELECT state_sha256 FROM p16_book_state WHERE book_instance_id=? "
        "AND market_date<=? ORDER BY market_date DESC LIMIT 1",
        [instance, SESSIONS[29]],
    ).fetchone()
    p16_book_store.claim_window(
        con, book_instance_id=instance, market_date=SESSIONS[30],
        information_cutoff_at=NOW, risk_sha256="c" * 64,
        score_sha256="d" * 64,
        previous_state_sha256=None if previous is None else previous[0],
        target_sha256=SOURCE, started_at=NOW,
    )
    return created


def test_filled_limit_attempt_writes_all_parity_ledgers_and_exact_retry(con):
    insert_bars(con, "AAA", SESSIONS[:31], open_=100, close=100, high=101, low=99)
    instance = _book(con)
    assert _queue(con, instance) == 1
    p16_book_store.claim_window(
        con, book_instance_id=instance, market_date=SESSIONS[30],
        information_cutoff_at=NOW, risk_sha256="c" * 64,
        score_sha256="d" * 64, previous_state_sha256=None,
        target_sha256=SOURCE, started_at=NOW,
    )

    result = p16_books.process_window(
        con, book_instance_id=instance, market_date=SESSIONS[30],
        observed_at=_observed(SESSIONS[30]),
    )

    assert result["status"] == "completed" and result["filled"] == 1
    for table in (
        "sim_orders", "sim_execution_attempts", "sim_fills", "sim_fill_costs",
        "p16_limit_attempts", "p16_book_fills", "p16_position_rules",
        "p16_book_state", "sim_equity",
    ):
        assert con.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (1,)
    assert con.execute(
        "SELECT status FROM sim_orders"
    ).fetchone() == (p16_book_mechanics.SIM_FILLED_STATUS,)
    assert con.execute(
        "SELECT qty FROM sim_positions WHERE portfolio_id=? AND ticker='AAA'", [instance],
    ).fetchone()[0] == pytest.approx(10)
    assert con.execute(
        "SELECT stop_px FROM p16_position_rules"
    ).fetchone()[0] == pytest.approx(95.1)
    assert con.execute(
        "SELECT status FROM p16_book_windows WHERE book_instance_id=?",
        [instance],
    ).fetchone() == ("completed",)

    replay = p16_books.process_window(
        con, book_instance_id=instance, market_date=SESSIONS[30],
        observed_at=_observed(SESSIONS[30]).replace(minute=1),
    )
    assert replay["status"] == "already_complete"
    assert replay["filled"] == 0
    assert con.execute("SELECT COUNT(*) FROM sim_fills").fetchone() == (1,)


def test_window_rejects_intent_from_a_different_target(con):
    insert_bars(con, "AAA", SESSIONS[:31], open_=100, close=100, high=101, low=99)
    instance = _book(con)
    p16_books.queue_plan(
        con, book_instance_id=instance, signal_date=SESSIONS[29],
        plan={"status": "planned", "orders": [{
            "ticker": "AAA", "side": "buy", "qty": 10,
            "order_role": "rebalance", "target_weight": 0.1, "entry_atr": 2.0,
        }]},
        limit_prices={"AAA": 101.5}, source_sha256="e" * 64,
        created_at=NOW, entry_gates={"AAA": "eligible"},
    )
    p16_book_store.claim_window(
        con, book_instance_id=instance, market_date=SESSIONS[30],
        information_cutoff_at=NOW, risk_sha256="c" * 64,
        score_sha256="d" * 64, previous_state_sha256=None,
        target_sha256=SOURCE, started_at=NOW,
    )

    with pytest.raises(p16_book_store.P16BookError, match="intent authority differs"):
        p16_books.process_window(
            con, book_instance_id=instance, market_date=SESSIONS[30],
            observed_at=_observed(SESSIONS[30]),
        )
    assert con.execute("SELECT COUNT(*) FROM sim_fills").fetchone() == (0,)


def test_successor_rejects_mutated_simulator_predecessor_state(con):
    insert_bars(con, "AAA", SESSIONS[:32], open_=100, close=100, high=101, low=99)
    instance = _book(con)
    _queue(con, instance)
    p16_books.process_window(
        con, book_instance_id=instance, market_date=SESSIONS[30],
        observed_at=_observed(SESSIONS[30]),
    )
    p16_books.queue_plan(
        con, book_instance_id=instance, signal_date=SESSIONS[30],
        plan={"status": "planned", "orders": []}, limit_prices={},
        source_sha256=SOURCE, created_at=_observed(SESSIONS[30]),
    )
    previous = con.execute(
        "SELECT state_sha256 FROM p16_book_state WHERE book_instance_id=? "
        "ORDER BY market_date DESC LIMIT 1",
        [instance],
    ).fetchone()[0]
    p16_book_store.claim_window(
        con, book_instance_id=instance, market_date=SESSIONS[31],
        information_cutoff_at=_observed(SESSIONS[30]), risk_sha256="c" * 64,
        score_sha256="d" * 64, previous_state_sha256=previous,
        target_sha256=SOURCE, started_at=_observed(SESSIONS[30]),
    )
    con.execute("UPDATE portfolios SET cash=5000 WHERE id=?", [instance])

    with pytest.raises(p16_book_store.P16BookError, match="mutable position state differs"):
        p16_books.process_window(
            con, book_instance_id=instance, market_date=SESSIONS[31],
            observed_at=_observed(SESSIONS[31]),
        )
    assert con.execute(
        "SELECT COUNT(*) FROM p16_book_state WHERE market_date=?", [SESSIONS[31]],
    ).fetchone() == (0,)


def test_limit_miss_records_attempt_and_terminal_order_without_fill(con):
    insert_bars(con, "AAA", SESSIONS[:30], open_=100, close=100, high=101, low=99)
    insert_bars(con, "AAA", [SESSIONS[30]], open_=102, close=102, high=103, low=101)
    instance = _book(con)
    _queue(con, instance, limit=101.5)

    result = p16_books.process_window(
        con, book_instance_id=instance, market_date=SESSIONS[30],
        observed_at=_observed(SESSIONS[30]),
    )

    assert result["rejected"] == 1 and result["filled"] == 0
    assert con.execute(
        "SELECT outcome,reject_reason,counterfactual_fill_px FROM p16_limit_attempts"
    ).fetchone()[:2] == ("limit_not_reached", "limit_not_reached")
    assert con.execute("SELECT COUNT(*) FROM sim_execution_attempts").fetchone() == (1,)
    assert con.execute("SELECT COUNT(*) FROM sim_fills").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM p16_book_fills").fetchone() == (0,)


def test_missing_next_open_keeps_window_running_until_atomic_retry(con):
    instance = _book(con)
    _queue(con, instance)
    p16_book_store.claim_window(
        con, book_instance_id=instance, market_date=SESSIONS[30],
        information_cutoff_at=NOW, risk_sha256="c" * 64,
        score_sha256="d" * 64, previous_state_sha256=None,
        target_sha256=SOURCE, started_at=NOW,
    )

    pending = p16_books.process_window(
        con, book_instance_id=instance, market_date=SESSIONS[30],
        observed_at=_observed(SESSIONS[30]),
    )

    assert pending["status"] == "pending" and pending["pending"] == 1
    assert con.execute("SELECT status FROM p16_book_windows").fetchone() == ("running",)
    assert con.execute("SELECT COUNT(*) FROM p16_book_state").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM sim_execution_attempts").fetchone() == (0,)

    insert_bars(
        con, "AAA", [SESSIONS[30]], open_=100, close=100, high=101, low=99,
    )
    con.execute("UPDATE prices SET fetched_at=? WHERE ticker='AAA' AND date=?", [
        _observed(SESSIONS[30]).replace(tzinfo=None), SESSIONS[30],
    ])
    completed = p16_books.process_window(
        con, book_instance_id=instance, market_date=SESSIONS[30],
        observed_at=_observed(SESSIONS[30]),
    )

    assert completed["status"] == "completed" and completed["filled"] == 1
    assert con.execute("SELECT status FROM p16_book_windows").fetchone() == ("completed",)
    assert con.execute("SELECT COUNT(*) FROM p16_book_state").fetchone() == (1,)


def test_window_cannot_fill_before_its_modeled_open(con):
    insert_bars(con, "AAA", SESSIONS[:31], open_=100, close=100, high=101, low=99)
    instance = _book(con)
    _queue(con, instance)
    preopen = datetime.combine(SESSIONS[30], time(13), tzinfo=timezone.utc)
    con.execute(
        "UPDATE prices SET fetched_at=? WHERE ticker='AAA' AND date=?",
        [preopen.replace(tzinfo=None), SESSIONS[30]],
    )

    result = p16_books.process_window(
        con, book_instance_id=instance, market_date=SESSIONS[30],
        observed_at=preopen,
    )
    assert result["status"] == "pending"
    assert con.execute("SELECT COUNT(*) FROM sim_fills").fetchone() == (0,)
    assert con.execute("SELECT status FROM p16_book_windows").fetchone() == ("running",)


def test_missing_next_open_rejects_after_three_session_observation_grace(con):
    instance = _book(con)
    _queue(con, instance)

    result = p16_books.process_through(
        con, book_instance_id=instance, market_date=SESSIONS[33],
        observed_at=_observed(SESSIONS[33]),
    )

    assert result["status"] == "completed" and result["rejected"] == 1
    assert result["sessions"] == [
        session.isoformat() for session in SESSIONS[30:34]
    ]
    assert con.execute(
        "SELECT status,reason FROM p16_order_intents",
    ).fetchone() == ("rejected", "no_bar")
    assert con.execute(
        "SELECT COUNT(*) FROM p16_book_windows WHERE status='completed'",
    ).fetchone() == (4,)
    assert con.execute("SELECT COUNT(*) FROM p16_book_state").fetchone() == (4,)

    insert_bars(
        con, "AAA", [SESSIONS[34]], open_=100, close=100, high=101, low=99,
    )
    con.execute(
        "UPDATE prices SET fetched_at=? WHERE ticker='AAA' AND date=?",
        [_observed(SESSIONS[34]).replace(tzinfo=None), SESSIONS[34]],
    )
    p16_books.queue_plan(
        con, book_instance_id=instance, signal_date=SESSIONS[33],
        plan={"status": "planned", "orders": []}, limit_prices={},
        source_sha256=SOURCE, created_at=_observed(SESSIONS[33]),
    )
    previous = con.execute(
        "SELECT state_sha256 FROM p16_book_state WHERE book_instance_id=? "
        "ORDER BY market_date DESC LIMIT 1", [instance],
    ).fetchone()[0]
    p16_book_store.claim_window(
        con, book_instance_id=instance, market_date=SESSIONS[34],
        information_cutoff_at=_observed(SESSIONS[33]), risk_sha256="c" * 64,
        score_sha256="d" * 64, previous_state_sha256=previous,
        target_sha256=SOURCE, started_at=_observed(SESSIONS[33]),
    )
    recovered = p16_books.process_through(
        con, book_instance_id=instance, market_date=SESSIONS[34],
        observed_at=_observed(SESSIONS[34]),
    )
    assert recovered["status"] == "completed"
    assert recovered["sessions"] == [SESSIONS[34].isoformat()]


def test_ordered_recovery_queues_detected_exit_in_the_recovery_window(con):
    insert_bars(
        con, "AAA", SESSIONS[:33], open_=100,
        close=[100] * 31 + [90, 90], high=101, low=89,
    )
    instance = _book(con)
    _queue(con, instance)
    assert p16_books.process_window(
        con, book_instance_id=instance, market_date=SESSIONS[30],
        observed_at=_observed(SESSIONS[30]),
    )["filled"] == 1
    for session in SESSIONS[31:33]:
        con.execute(
            "UPDATE prices SET fetched_at=? WHERE ticker='AAA' AND date=?",
            [_observed(session).replace(tzinfo=None), session],
        )

    recovered = p16_books.process_through(
        con, book_instance_id=instance, market_date=SESSIONS[32],
        observed_at=_observed(SESSIONS[32]),
    )

    assert recovered["sessions"] == [
        SESSIONS[31].isoformat(), SESSIONS[32].isoformat(),
    ]
    assert recovered["filled"] == 1
    assert con.execute(
        "SELECT side,fill_date FROM p16_book_fills ORDER BY fill_date",
    ).fetchall() == [("buy", SESSIONS[30]), ("sell", SESSIONS[32])]
    assert con.execute(
        "SELECT signal_date,expected_session,order_role,status FROM p16_order_intents "
        "WHERE side='sell'",
    ).fetchone() == (SESSIONS[31], SESSIONS[32], "stop", "filled")
    assert con.execute(
        "SELECT market_date,reason FROM p16_book_windows ORDER BY market_date",
    ).fetchall() == [
        (SESSIONS[30], None),
        (SESSIONS[31], "ordered_recovery"),
        (SESSIONS[32], "ordered_recovery"),
    ]
    assert p16_books.deferred_mandatory_exits(
        con, book_instance_id=instance, held_tickers={"AAA"},
        signal_date=SESSIONS[32], information_cutoff_at=_observed(SESSIONS[32]),
    ) == {}
    assert con.execute(
        "SELECT COALESCE(SUM(qty),0) FROM sim_positions WHERE portfolio_id=?", [instance],
    ).fetchone() == (0,)


def test_recovery_waits_until_the_missing_windows_construction_deadline(con):
    insert_bars(con, "AAA", SESSIONS[:32], open_=100, close=100, high=101, low=99)
    instance = _book(con)
    _queue(con, instance)
    assert p16_books.process_window(
        con, book_instance_id=instance, market_date=SESSIONS[30],
        observed_at=_observed(SESSIONS[30]),
    )["status"] == "completed"

    before_open = datetime.combine(SESSIONS[31], time(13), tzinfo=timezone.utc)
    result = p16_books.process_through(
        con, book_instance_id=instance, market_date=SESSIONS[31],
        observed_at=before_open,
    )

    assert result["status"] == "already_complete" and result["sessions"] == []
    assert con.execute(
        "SELECT COUNT(*) FROM p16_book_windows WHERE market_date=?", [SESSIONS[31]],
    ).fetchone() == (0,)
    assert con.execute(
        "SELECT COUNT(*) FROM p16_construct_targets WHERE signal_date=?", [SESSIONS[30]],
    ).fetchone() == (0,)


def test_recovery_waits_when_held_close_missed_the_price_fetch_cutoff(con):
    insert_bars(con, "AAA", SESSIONS[:32], open_=100, close=100, high=101, low=99)
    instance = _book(con)
    _queue(con, instance)
    assert p16_books.process_window(
        con, book_instance_id=instance, market_date=SESSIONS[30],
        observed_at=_observed(SESSIONS[30]),
    )["filled"] == 1
    con.execute(
        "UPDATE prices SET fetched_at=? WHERE ticker='AAA' AND date=?",
        [(_price_fetch_cutoff(SESSIONS[30]).replace(tzinfo=None)
          + timedelta(minutes=1)), SESSIONS[30]],
    )

    result = p16_books.process_through(
        con, book_instance_id=instance, market_date=SESSIONS[31],
        observed_at=_observed(SESSIONS[31]),
    )

    assert result["status"] == "already_complete" and result["sessions"] == []
    assert con.execute(
        "SELECT COUNT(*) FROM p16_book_windows WHERE market_date=?", [SESSIONS[31]],
    ).fetchone() == (0,)


def test_recovery_precedes_and_invalidates_a_stale_later_claim(con):
    instance = _book(con)
    _queue(con, instance)
    assert p16_books.process_through(
        con, book_instance_id=instance, market_date=SESSIONS[30],
        observed_at=_observed(SESSIONS[33]),
    )["status"] == "completed"
    stale_previous = con.execute(
        "SELECT state_sha256 FROM p16_book_state WHERE book_instance_id=?",
        [instance],
    ).fetchone()[0]
    p16_book_store.claim_window(
        con, book_instance_id=instance, market_date=SESSIONS[32],
        information_cutoff_at=_observed(SESSIONS[31]), risk_sha256="c" * 64,
        score_sha256="d" * 64, previous_state_sha256=stale_previous,
        target_sha256=SOURCE, started_at=_observed(SESSIONS[31]),
    )

    with pytest.raises(p16_book_store.P16BookError, match="previous state differs"):
        p16_books.process_through(
            con, book_instance_id=instance, market_date=SESSIONS[32],
            observed_at=_observed(SESSIONS[32]),
        )
    assert con.execute(
        "SELECT COUNT(*) FROM p16_book_state WHERE market_date=?", [SESSIONS[31]],
    ).fetchone() == (1,)
    assert con.execute(
        "SELECT status FROM p16_book_windows WHERE market_date=?", [SESSIONS[32]],
    ).fetchone() == ("running",)


def test_retry_uses_quarantine_state_at_historical_open(con):
    instance = _book(con)
    _queue(con, instance)
    assert p16_books.process_window(
        con, book_instance_id=instance, market_date=SESSIONS[30],
        observed_at=_observed(SESSIONS[30]),
    )["status"] == "pending"
    insert_bars(con, "AAA", [SESSIONS[30]], open_=100, close=100, high=101, low=99)
    later = _observed(SESSIONS[31]).replace(tzinfo=None)
    con.execute(
        "UPDATE prices SET fetched_at=? WHERE ticker='AAA' AND date=?",
        [later, SESSIONS[30]],
    )
    con.execute(
        "INSERT INTO price_quarantine VALUES "
        "('AAA','active','later finding','evidence',?,NULL,NULL)", [later],
    )

    result = p16_books.process_window(
        con, book_instance_id=instance, market_date=SESSIONS[30],
        observed_at=_observed(SESSIONS[31]),
    )

    assert result["status"] == "completed" and result["filled"] == 1


def test_intent_creation_after_expected_open_is_rejected(con):
    instance = _book(con)
    with pytest.raises(p16_book_store.P16BookError, match="after.*open"):
        p16_books.queue_plan(
            con, book_instance_id=instance, signal_date=SESSIONS[29],
            plan={"status": "planned", "orders": [{
                "ticker": "AAA", "side": "buy", "qty": 1,
                "order_role": "rebalance", "target_weight": 0.01, "entry_atr": 1,
            }]},
            limit_prices={"AAA": 101}, source_sha256=SOURCE,
            created_at=_observed(SESSIONS[30]), entry_gates={"AAA": "eligible"},
        )


def test_running_window_blocks_later_claim_and_mismatched_predecessor(con):
    insert_bars(con, "AAA", SESSIONS[:32], open_=100, close=100, high=101, low=99)
    instance = _book(con)
    p16_book_store.claim_window(
        con, book_instance_id=instance, market_date=SESSIONS[30],
        information_cutoff_at=NOW, risk_sha256="c" * 64,
        score_sha256="d" * 64, previous_state_sha256=None,
        target_sha256=SOURCE, started_at=NOW,
    )
    with pytest.raises(p16_book_store.P16BookError, match="earlier.*remains running"):
        p16_book_store.claim_window(
            con, book_instance_id=instance, market_date=SESSIONS[31],
            information_cutoff_at=NOW, risk_sha256="c" * 64,
            score_sha256="d" * 64, previous_state_sha256=None,
            target_sha256=SOURCE, started_at=NOW,
        )

    assert p16_books.process_window(
        con, book_instance_id=instance, market_date=SESSIONS[30],
        observed_at=_observed(SESSIONS[30]),
    )["status"] == "completed"
    p16_book_store.claim_window(
        con, book_instance_id=instance, market_date=SESSIONS[31],
        information_cutoff_at=NOW, risk_sha256="c" * 64,
        score_sha256="d" * 64, previous_state_sha256=None,
        target_sha256=SOURCE, started_at=NOW,
    )
    with pytest.raises(p16_book_store.P16BookError, match="previous state differs"):
        p16_books.process_window(
            con, book_instance_id=instance, market_date=SESSIONS[31],
            observed_at=_observed(SESSIONS[31]),
        )
    assert con.execute(
        "SELECT status FROM p16_book_windows WHERE market_date=?", [SESSIONS[31]],
    ).fetchone() == ("running",)
    assert con.execute("SELECT COUNT(*) FROM p16_book_state").fetchone() == (1,)


def test_gap_cost_cannot_turn_a_whole_share_buy_into_fractional_fill(con):
    insert_bars(con, "AAA", SESSIONS[:31], open_=100, close=100, high=101, low=99)
    instance = _book(con)
    _queue(con, instance, limit=110, qty=100)

    result = p16_books.process_window(
        con, book_instance_id=instance, market_date=SESSIONS[30],
        observed_at=_observed(SESSIONS[30]),
    )

    assert result["filled"] == 0 and result["rejected"] == 1
    assert con.execute(
        "SELECT status,reason FROM p16_order_intents",
    ).fetchone() == ("rejected", "insufficient_cash")
    assert con.execute("SELECT COUNT(*) FROM sim_positions").fetchone() == (0,)


def test_limit_miss_label_waits_for_h5_and_replays_without_duplicate(con):
    dates = SESSIONS[30:35]
    insert_bars(con, "AAA", dates, open_=102, close=[102, 103, 104, 105, 106],
                high=[103, 104, 105, 106, 107], low=[101, 102, 103, 104, 105])
    insert_bars(con, "SPY", dates, open_=100, close=[100, 100, 101, 101, 102],
                high=103, low=99)
    con.execute(
        "UPDATE prices SET fetched_at=? WHERE date=?",
        [_observed(dates[0]).replace(tzinfo=None), dates[0]],
    )
    instance = _book(con)
    _queue(con, instance, limit=101.5)
    first = p16_books.process_window(
        con, book_instance_id=instance, market_date=dates[0],
        observed_at=_observed(dates[0]),
    )
    assert first["counterfactual_labels"] == 0

    labeled_at = _observed(dates[-1])
    con.execute("UPDATE prices SET fetched_at=?", [labeled_at.replace(tzinfo=None)])
    assert p16_books.label_limit_counterfactuals(
        con, book_instance_id=instance, labeled_at=labeled_at,
    ) == 1
    assert p16_books.label_limit_counterfactuals(
        con, book_instance_id=instance, labeled_at=labeled_at,
    ) == 0
    row = con.execute(
        "SELECT attempt_date,horizon_sessions,entry_px,exit_date,net_excess_return "
        "FROM p16_limit_labels",
    ).fetchone()
    counterfactual = con.execute(
        "SELECT counterfactual_fill_px FROM p16_limit_attempts",
    ).fetchone()[0]
    assert row[:2] == (dates[0], 5)
    assert row[2] == pytest.approx(counterfactual)
    assert row[3] == dates[-1]
    spy_net = 102 * 0.999 / (100 * 1.001) - 1
    assert row[4] == pytest.approx((106 * 0.999 / counterfactual - 1) - spy_net)
    p16_book_store.validate_limit_labels(con)
    con.execute("UPDATE p16_limit_labels SET net_return=net_return+0.01")
    with pytest.raises(p16_book_store.P16BookError, match="evidence differs"):
        p16_book_store.validate_limit_labels(con)


def test_split_adjusts_quantity_and_limit_before_the_next_open(con):
    insert_bars(con, "AAA", SESSIONS[:30], open_=100, close=100, high=101, low=99)
    insert_bars(con, "AAA", [SESSIONS[30]], open_=50, close=50, high=51, low=49)
    db.init_actions_schema(con)
    con.execute(
        "INSERT INTO split_adjustments (ticker,ex_date,ratio,outcome) "
        "VALUES ('AAA',?,2,'applied')", [SESSIONS[30]],
    )
    instance = _book(con)
    _queue(con, instance, limit=101.5, qty=10)

    result = p16_books.process_window(
        con, book_instance_id=instance, market_date=SESSIONS[30],
        observed_at=_observed(SESSIONS[30]),
    )

    assert result["filled"] == 1
    assert con.execute("SELECT qty FROM sim_fills").fetchone()[0] == pytest.approx(20)
    assert con.execute("SELECT limit_px FROM p16_limit_attempts").fetchone()[0] \
        == pytest.approx(50.75)
    entry_atr, stop_px = con.execute(
        "SELECT entry_atr,stop_px FROM p16_position_rules",
    ).fetchone()
    fill_px = con.execute("SELECT fill_px FROM sim_fills").fetchone()[0]
    assert entry_atr == pytest.approx(1.0)
    assert stop_px == pytest.approx(fill_px - 2.5)


def test_failure_inside_terminal_accounting_rolls_back_every_ledger(con, monkeypatch):
    insert_bars(con, "AAA", SESSIONS[:31], open_=100, close=100, high=101, low=99)
    instance = _book(con)
    _queue(con, instance)

    def fail_apply(*_args, **_kwargs):
        raise RuntimeError("injected accounting failure")

    monkeypatch.setattr(p16_book_mechanics, "apply_fill", fail_apply)
    with pytest.raises(RuntimeError, match="injected accounting failure"):
        p16_books.process_window(
            con, book_instance_id=instance, market_date=SESSIONS[30],
            observed_at=_observed(SESSIONS[30]),
        )
    assert con.execute("SELECT status FROM p16_order_intents").fetchone() == ("pending",)
    for table in (
        "sim_orders", "sim_execution_attempts", "sim_fills", "sim_fill_costs",
        "p16_limit_attempts", "p16_book_fills", "p16_book_state", "sim_equity",
    ):
        assert con.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (0,)


def test_inactive_book_never_processes_or_marks(con):
    insert_bars(con, "AAA", SESSIONS[:31], open_=100, close=100, high=101, low=99)
    [instance, _] = p16_book_store.initialize_contracts(
        con, registration_sha256=REGISTRATION, activation_date=None,
        calibration_sha256=record_p16_calibration(con, REGISTRATION, NOW), created_at=NOW,
    )
    assert p16_books.process_window(
        con, book_instance_id=instance, market_date=SESSIONS[30],
        observed_at=_observed(SESSIONS[30]),
    ) == {"status": "inactive", "filled": 0, "rejected": 0, "pending": 0}


def test_drawdown_halt_rejects_discretionary_stock_buy(con):
    insert_bars(con, "AAA", SESSIONS[:31], open_=100, close=100, high=101, low=99)
    instance = _book(con)
    p16_book_store.append_state(
        con, book_instance_id=instance, market_date=SESSIONS[29], peak_equity=10_000,
        entry_halted=True, equity=7_900, cash=10_000, spy_mark=None, stock_marks={},
        position_state_sha256=p16_book_mechanics.current_position_state(
            con, instance,
        )["position_state_sha256"], previous_state_sha256=None, recorded_at=NOW,
    )
    _queue(con, instance)

    result = p16_books.process_through(
        con, book_instance_id=instance, market_date=SESSIONS[30],
        observed_at=_observed(SESSIONS[30]),
    )

    assert result["filled"] == 0 and result["rejected"] == 1
    assert con.execute(
        "SELECT outcome,reject_reason FROM p16_limit_attempts"
    ).fetchone() == ("rejected", "drawdown_halt")


def test_first_window_drawdown_is_measured_from_initial_capital(con):
    insert_bars(con, "AAA", SESSIONS[:30], open_=100, close=100, high=101, low=99)
    insert_bars(con, "AAA", [SESSIONS[30]], open_=100, close=70, high=101, low=69)
    instance = _book(con)
    _queue(con, instance, limit=110, qty=90)

    result = p16_books.process_window(
        con, book_instance_id=instance, market_date=SESSIONS[30],
        observed_at=_observed(SESSIONS[30]),
    )

    assert result["status"] == "completed" and result["filled"] == 1
    peak, halted = con.execute(
        "SELECT peak_equity,entry_halted FROM p16_book_state",
    ).fetchone()
    assert peak == pytest.approx(10_000)
    assert halted is True


def test_partial_rebalance_sell_keeps_open_position_rule(con):
    insert_bars(con, "AAA", SESSIONS[:32], open_=100, close=100, high=101, low=99)
    instance = _book(con)
    _queue(con, instance, qty=10)
    p16_books.process_window(
        con, book_instance_id=instance, market_date=SESSIONS[30],
        observed_at=_observed(SESSIONS[30]),
    )
    p16_book_store.add_intent(
        con, book_instance_id=instance, signal_date=SESSIONS[30], ticker="AAA",
        side="sell", order_role="rebalance", target_weight=0.05, rounded_qty=5,
        source_sha256=SOURCE, limit_px=None, expected_session=SESSIONS[31], created_at=NOW,
    )
    previous = con.execute(
        "SELECT state_sha256 FROM p16_book_state WHERE book_instance_id=? "
        "ORDER BY market_date DESC LIMIT 1", [instance],
    ).fetchone()[0]
    p16_book_store.claim_window(
        con, book_instance_id=instance, market_date=SESSIONS[31],
        information_cutoff_at=_observed(SESSIONS[30]), risk_sha256="c" * 64,
        score_sha256="d" * 64, previous_state_sha256=previous,
        target_sha256=SOURCE, started_at=_observed(SESSIONS[30]),
    )
    con.execute(
        "UPDATE prices SET fetched_at=? WHERE ticker='AAA' AND date=?",
        [_observed(SESSIONS[31]).replace(tzinfo=None), SESSIONS[31]],
    )

    result = p16_books.process_window(
        con, book_instance_id=instance, market_date=SESSIONS[31],
        observed_at=_observed(SESSIONS[31]),
    )

    assert result["filled"] == 1
    assert con.execute(
        "SELECT qty FROM sim_positions WHERE portfolio_id=? AND ticker='AAA'", [instance],
    ).fetchone()[0] == pytest.approx(5)
    assert con.execute(
        "SELECT status FROM p16_position_rules WHERE book_instance_id=? AND ticker='AAA'",
        [instance],
    ).fetchone() == ("open",)
