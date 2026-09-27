"""P16-only simulator parity, atomicity, and retry checks."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from engine.lib import db
from server import p16_book_store
from sim import p16_book_mechanics, p16_books
from tests.conftest import SESSIONS, insert_bars

NOW = datetime(2026, 9, 27, 16, tzinfo=timezone.utc)
REGISTRATION = "a" * 64
SOURCE = "b" * 64


def _book(con):
    [instance, _] = p16_book_store.initialize_contracts(
        con, registration_sha256=REGISTRATION, activation_date=SESSIONS[29],
        risk_aversion=5, cost_per_turnover=0.0005, created_at=NOW,
    )
    con.execute("UPDATE portfolios SET active=TRUE WHERE id=?", [instance])
    return instance


def _queue(con, instance, *, limit=101.5, qty=10):
    return p16_books.queue_plan(
        con, book_instance_id=instance, signal_date=SESSIONS[29],
        plan={"status": "planned", "orders": [{
            "ticker": "AAA", "side": "buy", "qty": qty,
            "order_role": "rebalance", "target_weight": 0.1, "entry_atr": 2.0,
        }]},
        limit_prices={"AAA": limit}, source_sha256=SOURCE, created_at=NOW,
    )


def test_filled_limit_attempt_writes_all_parity_ledgers_and_exact_retry(con):
    insert_bars(con, "AAA", SESSIONS[:31], open_=100, close=100, high=101, low=99)
    instance = _book(con)
    assert _queue(con, instance) == 1

    result = p16_books.process_window(
        con, book_instance_id=instance, market_date=SESSIONS[30], observed_at=NOW,
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

    replay = p16_books.process_window(
        con, book_instance_id=instance, market_date=SESSIONS[30], observed_at=NOW,
    )
    assert replay["filled"] == 0
    assert con.execute("SELECT COUNT(*) FROM sim_fills").fetchone() == (1,)


def test_limit_miss_records_attempt_and_terminal_order_without_fill(con):
    insert_bars(con, "AAA", SESSIONS[:30], open_=100, close=100, high=101, low=99)
    insert_bars(con, "AAA", [SESSIONS[30]], open_=102, close=102, high=103, low=101)
    instance = _book(con)
    _queue(con, instance, limit=101.5)

    result = p16_books.process_window(
        con, book_instance_id=instance, market_date=SESSIONS[30], observed_at=NOW,
    )

    assert result["rejected"] == 1 and result["filled"] == 0
    assert con.execute(
        "SELECT outcome,reject_reason,counterfactual_fill_px FROM p16_limit_attempts"
    ).fetchone()[:2] == ("limit_not_reached", "limit_not_reached")
    assert con.execute("SELECT COUNT(*) FROM sim_execution_attempts").fetchone() == (1,)
    assert con.execute("SELECT COUNT(*) FROM sim_fills").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM p16_book_fills").fetchone() == (0,)


def test_limit_miss_label_waits_for_h5_and_replays_without_duplicate(con):
    dates = SESSIONS[30:35]
    insert_bars(con, "AAA", dates, open_=102, close=[102, 103, 104, 105, 106],
                high=[103, 104, 105, 106, 107], low=[101, 102, 103, 104, 105])
    insert_bars(con, "SPY", dates, open_=100, close=[100, 100, 101, 101, 102],
                high=103, low=99)
    con.execute(
        "UPDATE prices SET fetched_at=? WHERE date=?",
        [NOW.replace(tzinfo=None), dates[0]],
    )
    instance = _book(con)
    _queue(con, instance, limit=101.5)
    first = p16_books.process_window(
        con, book_instance_id=instance, market_date=dates[0], observed_at=NOW,
    )
    assert first["counterfactual_labels"] == 0

    con.execute("UPDATE prices SET fetched_at=?", [NOW.replace(tzinfo=None)])
    assert p16_books.label_limit_counterfactuals(
        con, book_instance_id=instance, labeled_at=NOW,
    ) == 1
    assert p16_books.label_limit_counterfactuals(
        con, book_instance_id=instance, labeled_at=NOW,
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
        con, book_instance_id=instance, market_date=SESSIONS[30], observed_at=NOW,
    )

    assert result["filled"] == 1
    assert con.execute("SELECT qty FROM sim_fills").fetchone()[0] == pytest.approx(20)
    assert con.execute("SELECT limit_px FROM p16_limit_attempts").fetchone()[0] \
        == pytest.approx(50.75)


def test_failure_inside_terminal_accounting_rolls_back_every_ledger(con, monkeypatch):
    insert_bars(con, "AAA", SESSIONS[:31], open_=100, close=100, high=101, low=99)
    instance = _book(con)
    _queue(con, instance)

    def fail_apply(*_args, **_kwargs):
        raise RuntimeError("injected accounting failure")

    monkeypatch.setattr(p16_book_mechanics, "apply_fill", fail_apply)
    with pytest.raises(RuntimeError, match="injected accounting failure"):
        p16_books.process_window(
            con, book_instance_id=instance, market_date=SESSIONS[30], observed_at=NOW,
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
        risk_aversion=5, cost_per_turnover=0.0005, created_at=NOW,
    )
    assert p16_books.process_window(
        con, book_instance_id=instance, market_date=SESSIONS[30], observed_at=NOW,
    ) == {"status": "inactive", "filled": 0, "rejected": 0, "pending": 0}


def test_drawdown_halt_rejects_discretionary_stock_buy(con):
    insert_bars(con, "AAA", SESSIONS[:31], open_=100, close=100, high=101, low=99)
    instance = _book(con)
    p16_book_store.append_state(
        con, book_instance_id=instance, market_date=SESSIONS[28], peak_equity=10_000,
        entry_halted=True, equity=7_900, cash=10_000, spy_mark=None, stock_marks={},
        position_state_sha256="c" * 64, previous_state_sha256=None, recorded_at=NOW,
    )
    _queue(con, instance)

    result = p16_books.process_window(
        con, book_instance_id=instance, market_date=SESSIONS[30], observed_at=NOW,
    )

    assert result["filled"] == 0 and result["rejected"] == 1
    assert con.execute(
        "SELECT outcome,reject_reason FROM p16_limit_attempts"
    ).fetchone() == ("rejected", "drawdown_halt")


def test_partial_rebalance_sell_keeps_open_position_rule(con):
    insert_bars(con, "AAA", SESSIONS[:32], open_=100, close=100, high=101, low=99)
    instance = _book(con)
    _queue(con, instance, qty=10)
    p16_books.process_window(
        con, book_instance_id=instance, market_date=SESSIONS[30], observed_at=NOW,
    )
    p16_book_store.add_intent(
        con, book_instance_id=instance, signal_date=SESSIONS[30], ticker="AAA",
        side="sell", order_role="rebalance", target_weight=0.05, rounded_qty=5,
        source_sha256=SOURCE, limit_px=None, expected_session=SESSIONS[31], created_at=NOW,
    )

    result = p16_books.process_window(
        con, book_instance_id=instance, market_date=SESSIONS[31], observed_at=NOW,
    )

    assert result["filled"] == 1
    assert con.execute(
        "SELECT qty FROM sim_positions WHERE portfolio_id=? AND ticker='AAA'", [instance],
    ).fetchone()[0] == pytest.approx(5)
    assert con.execute(
        "SELECT status FROM p16_position_rules WHERE book_instance_id=? AND ticker='AAA'",
        [instance],
    ).fetchone() == ("open",)
