"""Reg T, financing, margin calls and both R10 account settings."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from sim import margin
from sim.schema import set_portfolio_account
from tests.conftest import insert_bars

DAY = date(2026, 10, 12)


def _set_account(con, portfolio_id, *, rule="pdt_25k_legacy", profile="baseline_v1"):
    set_portfolio_account(
        con,
        portfolio_id,
        engine="account",
        cost_profile=profile,
        account_type="margin",
        visibility="private",
        status="active",
        price_source="prices",
        day_trade_rule=rule,
        allow_short=True,
        updated_at=datetime(2026, 10, 12, 20),
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


def test_intraday_margin_marks_without_future_daily_close(con, book):
    _set_account(con, book, rule="intraday_margin_2026")
    prior = date(2026, 10, 9)
    insert_bars(con, "OLD", [prior], close=10)
    insert_bars(con, "OLD", [DAY], close=1_000)
    con.execute("INSERT INTO sim_positions VALUES (?, 'OLD', 10, 10)", [book])
    at_open = datetime(2026, 10, 12, 13, 30, tzinfo=timezone.utc)
    state = margin.margin_state(con, book, DAY, as_of=at_open)
    assert state.long_market_value == 100


def test_intraday_margin_uses_only_completed_minute_bars(con, book):
    _set_account(con, book, rule="intraday_margin_2026")
    prior = date(2026, 10, 9)
    insert_bars(con, "OLD", [prior], close=10)
    con.execute("INSERT INTO sim_positions VALUES (?, 'OLD', 10, 10)", [book])
    con.execute(
        "CREATE TABLE intraday_prices (ticker VARCHAR,ts TIMESTAMP,interval VARCHAR,"
        "open DOUBLE,high DOUBLE,low DOUBLE,close DOUBLE,volume BIGINT,source VARCHAR,"
        "as_of DATE)"
    )
    con.execute(
        "INSERT INTO intraday_prices VALUES "
        "('OLD','2026-10-12 14:18:00','1m',1000,1000,1000,1000,100,'fixture',?)",
        [DAY],
    )

    during = margin.margin_state(
        con, book, DAY, as_of=datetime(2026, 10, 12, 14, 18, 59),
    )
    complete = margin.margin_state(
        con, book, DAY, as_of=datetime(2026, 10, 12, 14, 19),
    )

    assert during.long_market_value == 100
    assert complete.long_market_value == 10_000


def test_margin_marks_use_accounts_own_massive_source(con, book):
    _set_account(con, book, rule="intraday_margin_2026")
    con.execute(
        "CREATE TABLE free_daily_bars (date DATE,ticker VARCHAR,o DOUBLE,h DOUBLE,"
        "l DOUBLE,c DOUBLE,volume DOUBLE,vwap DOUBLE,source VARCHAR,fetched_at TIMESTAMP,"
        "source_sha256 VARCHAR)"
    )
    con.execute(
        "INSERT INTO free_daily_bars VALUES "
        "('2026-10-09','OLD',10,10,10,10,1000000,10,'massive',"
        "'2026-10-10 07:00:00','raw')"
    )
    insert_bars(con, "OLD", [date(2026, 10, 9)], close=999)
    con.execute("INSERT INTO sim_positions VALUES (?, 'OLD', 10, 10)", [book])
    state = margin.margin_state(
        con, book, DAY, price_source="massive_daily",
        as_of=datetime(2026, 10, 12, 13, 30, tzinfo=timezone.utc),
        available_at=datetime(2026, 10, 12, 22, tzinfo=timezone.utc),
    )
    assert state.long_market_value == 100


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
    insert_bars(con, "XYZ", [DAY], open_=100, close=100)
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


def test_day_trade_match_prioritises_overnight_lot(con, book):
    _set_account(con, book)
    con.execute("INSERT INTO sim_positions VALUES (?, 'XYZ', 3, 100)", [book])
    con.executemany(
        "INSERT INTO sim_position_lots VALUES (?, 'XYZ', ?, ?, ?, 100)",
        [
            (book, date(2026, 10, 9), 90, 2.0),
            (book, DAY, 100, 1.0),
        ],
    )
    assert not margin.would_create_day_trade(con, book, "XYZ", "sell", 0.5, DAY)
    assert margin.matched_day_trade_open(con, book, "XYZ", "sell", 2.5, DAY) == 100


def test_recorded_day_trade_depletes_same_session_lot_before_next_close(con, book):
    _set_account(con, book)
    con.execute("INSERT INTO sim_positions VALUES (?, 'XYZ', 2, 100)", [book])
    con.executemany(
        "INSERT INTO sim_position_lots VALUES (?, 'XYZ', ?, ?, 1, 100)",
        [(book, date(2026, 10, 9), 90), (book, DAY, 100)],
    )
    from sim import ledger

    assert margin.matched_day_trade_open(con, book, "XYZ", "sell", 1, DAY) is None
    ledger.apply_fill(con, dict(order_id=201, portfolio_id=book, ticker='XYZ', side='sell',
                                qty=1, fill_px=100, fill_date=DAY))
    assert margin.matched_day_trade_open(con, book, "XYZ", "sell", 1, DAY) == 100
    ledger.apply_fill(con, dict(order_id=202, portfolio_id=book, ticker='XYZ', side='sell',
                                qty=1, fill_px=100, fill_date=DAY))
    assert margin.matched_day_trade_open(con, book, "XYZ", "sell", 1, DAY) is None
    assert con.execute('SELECT open_order_id,close_order_id FROM sim_day_trades').fetchall() == [(100, 202)]


def test_margin_interest_uses_verified_rate_and_is_idempotent(con, book):
    _set_account(con, book, profile="ibkr_pro_tiered_v1")
    con.execute("UPDATE portfolios SET cash=-2000 WHERE id=?", [book])
    first = margin.accrue_interest(con, DAY, days=30)
    assert first["events"] == 1
    assert first["charged"] == pytest.approx(
        2_000 * (0.0583 * 19 + 0.0538 * 11) / 360
    )
    assert margin.accrue_interest(con, DAY, days=30) == {
        "events": 0, "charged": 0.0,
    }
    assert con.execute(
        "SELECT amount FROM sim_cash_events WHERE kind='margin_interest'"
    ).fetchone() == (pytest.approx(-first["charged"]),)


def test_maintenance_breach_queues_proportional_reduction(con, book):
    _set_account(con, book)
    con.execute(
        "CREATE TABLE IF NOT EXISTS account_events (id BIGINT PRIMARY KEY,portfolio_id VARCHAR,"
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
    con.execute(
        "UPDATE sim_order_details SET state_reason='margin_call|bar_missing' "
        "WHERE order_id=?",
        [queued[0]],
    )
    assert margin.queue_margin_reductions(con, book, DAY) == []


def test_margin_call_receipt_uses_new_york_close_not_fixed_utc(con, book):
    winter_day = date(2026, 11, 30)
    _set_account(con, book)
    con.execute("UPDATE portfolios SET cash=-9000,initial_cash=1000 WHERE id=?", [book])
    con.execute("INSERT INTO sim_positions VALUES (?, 'XYZ', 100, 100)", [book])
    insert_bars(con, "XYZ", [winter_day], close=100)
    order_id, = margin.queue_margin_reductions(con, book, winter_day)
    assert con.execute(
        "SELECT received_at FROM sim_order_details WHERE order_id=?", [order_id]
    ).fetchone() == (datetime(2026, 11, 30, 21),)


def test_legacy_pdt_does_not_apply_to_cash_legacy_account(con, book):
    _set_account(con, book)
    set_portfolio_account(con, book, account_type="cash_legacy")
    con.execute("UPDATE portfolios SET initial_cash=10000,cash=9750 WHERE id=?", [book])
    _same_day_lot(con, book)
    _three_prior_day_trades(con, book)
    assert margin.pdt_check(
        con, book, "XYZ", "sell", 1, DAY, price=100,
    ).allowed
