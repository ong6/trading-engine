"""Reg T, financing, margin calls and both R10 account settings."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from sim import margin
from tests.conftest import insert_bars

DAY = date(2026, 10, 12)


def _set_account(con, portfolio_id, *, rule="pdt_25k_legacy", profile="baseline_v1"):
    con.execute(
        "CREATE TABLE IF NOT EXISTS portfolio_accounts ("
        "portfolio_id VARCHAR PRIMARY KEY,engine VARCHAR,cost_profile VARCHAR,"
        "account_type VARCHAR,visibility VARCHAR,status VARCHAR,price_source VARCHAR,"
        "day_trade_rule VARCHAR,allow_short BOOLEAN,updated_at TIMESTAMP)"
    )
    con.execute(
        "INSERT OR REPLACE INTO portfolio_accounts VALUES "
        "(?, 'account', ?, 'margin', 'private', 'active', 'prices', ?, TRUE, ?)",
        [portfolio_id, profile, rule, datetime(2026, 10, 12, 20)],
    )


def test_reg_t_initial_and_maintenance_for_long_and_short(con, book):
    _set_account(con, book)
    con.execute("UPDATE portfolios SET cash=9000 WHERE id=?", [book])
    con.execute("INSERT INTO sim_positions VALUES (?, 'LONG', 10, 100)", [book])
    con.execute("INSERT INTO sim_positions VALUES (?, 'SHORT', -20, 50)", [book])
    insert_bars(con, "LONG", [DAY], close=100)
    insert_bars(con, "SHORT", [DAY], close=50)
    state = margin.margin_state(con, book, DAY)
    assert state.equity == 9000
    assert state.initial_requirement == 1000
    assert state.maintenance_requirement == 550
    assert state.maintenance_excess == 8450


def test_initial_margin_refuses_exposure_above_reg_t(con, book):
    _set_account(con, book)
    con.execute("UPDATE portfolios SET cash=10000,initial_cash=10000 WHERE id=?", [book])
    assert margin.initial_margin_allows(con, book, "XYZ", "buy", 200, 100, DAY)
    assert not margin.initial_margin_allows(con, book, "XYZ", "buy", 201, 100, DAY)


def _same_day_lot(con, book):
    con.execute("INSERT INTO sim_positions VALUES (?, 'XYZ', 2.5, 100)", [book])
    con.execute(
        "INSERT INTO sim_position_lots VALUES (?, 'XYZ', ?, 100, 2.5, 100)",
        [book, DAY],
    )


def _three_prior_day_trades(con, book):
    con.executemany(
        "INSERT INTO sim_day_trades VALUES (?,?,'OLD',?,?)",
        [
            (book, date(2026, 10, 7), 1, 11),
            (book, date(2026, 10, 8), 2, 12),
            (book, date(2026, 10, 9), 3, 13),
        ],
    )


def test_legacy_pdt_refuses_fourth_day_trade_under_25k(con, book):
    _set_account(con, book)
    con.execute("UPDATE portfolios SET initial_cash=10000,cash=9750 WHERE id=?", [book])
    _same_day_lot(con, book)
    _three_prior_day_trades(con, book)
    result = margin.pdt_check(con, book, "XYZ", "sell", 1.25, DAY, price=100)
    assert not result.allowed
    assert result.reason == "pdt_limit"
    assert result.creates_day_trade
    assert result.trailing_day_trades == 3


def test_legacy_pdt_does_not_refuse_at_50k(con, book):
    _set_account(con, book)
    con.execute("UPDATE portfolios SET initial_cash=50000,cash=49750 WHERE id=?", [book])
    _same_day_lot(con, book)
    _three_prior_day_trades(con, book)
    result = margin.pdt_check(con, book, "XYZ", "sell", 1, DAY, price=100)
    assert result.allowed


def test_intraday_margin_rule_never_count_refuses_but_enforces_reg_t(con, book):
    _set_account(con, book, rule="intraday_margin_2026")
    con.execute("UPDATE portfolios SET initial_cash=10000,cash=9750 WHERE id=?", [book])
    _same_day_lot(con, book)
    _three_prior_day_trades(con, book)
    close = margin.pdt_check(con, book, "XYZ", "sell", 1, DAY, price=100)
    opening = margin.pdt_check(con, book, "BIG", "buy", 300, DAY, price=100)
    assert close.allowed
    assert close.trailing_day_trades == 3
    assert not opening.allowed
    assert opening.reason == "reg_t_initial"


def test_record_day_trade_preserves_fractional_open_lot_identity(con, book):
    _set_account(con, book, rule="intraday_margin_2026")
    _same_day_lot(con, book)
    assert margin.record_day_trade(con, book, "XYZ", 200, "sell", DAY)
    assert con.execute("SELECT * FROM sim_day_trades").fetchone() == (
        book, DAY, "XYZ", 100, 200,
    )


def test_margin_interest_uses_verified_rate_and_is_idempotent(con, book):
    _set_account(con, book, profile="ibkr_pro_tiered_v1")
    con.execute("UPDATE portfolios SET cash=-2000 WHERE id=?", [book])
    assert margin.accrue_interest(con, DAY, days=30) == {
        "events": 1, "charged": 8.97,
    }
    assert margin.accrue_interest(con, DAY, days=30) == {
        "events": 0, "charged": 0.0,
    }
    assert con.execute(
        "SELECT amount FROM sim_cash_events WHERE kind='margin_interest'"
    ).fetchone() == (-8.97,)


def test_maintenance_breach_queues_proportional_reduction(con, book):
    _set_account(con, book)
    con.execute(
        "CREATE TABLE account_events (id BIGINT PRIMARY KEY,portfolio_id VARCHAR,"
        "kind VARCHAR,payload VARCHAR,created_at TIMESTAMP)"
    )
    con.execute("UPDATE portfolios SET cash=-9000,initial_cash=1000 WHERE id=?", [book])
    con.execute("INSERT INTO sim_positions VALUES (?, 'XYZ', 100, 100)", [book])
    insert_bars(con, "XYZ", [DAY], close=100)
    state = margin.margin_state(con, book, DAY)
    assert state.equity == 1000
    assert state.maintenance_requirement == 2500
    queued = margin.queue_margin_reductions(con, book, DAY)
    assert len(queued) == 1
    assert con.execute(
        "SELECT side,qty,status FROM sim_orders WHERE id=?", [queued[0]]
    ).fetchone() == ("sell", pytest.approx(60), "pending")
    assert con.execute(
        "SELECT kind FROM account_events WHERE portfolio_id=?", [book]
    ).fetchone() == ("margin_call",)
    assert margin.queue_margin_reductions(con, book, DAY) == []
