"""Point-in-time stock locates, financing and threshold-list buy-ins."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from sim import ledger, shorts
from sim.schema import set_portfolio_account
from tests.conftest import insert_bars

DAY = date(2026, 10, 12)


def _set_account(con, portfolio_id, *, profile="ibkr_pro_tiered_v1"):
    set_portfolio_account(
        con,
        portfolio_id,
        engine="account",
        cost_profile=profile,
        account_type="margin",
        visibility="private",
        status="active",
        price_source="prices",
        day_trade_rule="pdt_25k_legacy",
        allow_short=True,
        updated_at=datetime(2026, 10, 12, 20),
    )


def _short_tables(con):
    con.execute(
        "CREATE TABLE regsho_threshold "
        "(ticker VARCHAR,session_date DATE,publication_date DATE)"
    )
    con.execute(
        "CREATE TABLE finra_short_interest "
        "(ticker VARCHAR,settlement_date DATE,days_to_cover DOUBLE,publication_date DATE)"
    )


def _liquid_market(con, ticker="XYZ"):
    con.execute("CREATE TABLE universe (ticker VARCHAR,liquid BOOLEAN)")
    con.execute("INSERT INTO universe VALUES (?,TRUE)", [ticker])
    dates = []
    cursor = DAY - timedelta(days=45)
    while cursor < DAY:
        if cursor.weekday() < 5:
            dates.append(cursor)
        cursor += timedelta(days=1)
    insert_bars(con, ticker, dates, open_=10, close=10, volume=1_000_000)


def test_regsho_and_high_days_to_cover_refuse_locates(con):
    _short_tables(con)
    _liquid_market(con)
    con.execute("INSERT INTO regsho_threshold VALUES ('XYZ',?,?)", [DAY, DAY])
    result = shorts.locate(con, "XYZ", DAY)
    assert not result.available
    assert result.reason == "regsho_threshold"

    con.execute("DELETE FROM regsho_threshold")
    con.execute(
        "INSERT INTO finra_short_interest VALUES ('XYZ',?,?,?)",
        [DAY, 10.0, DAY],
    )
    result = shorts.locate(con, "XYZ", DAY)
    assert not result.available
    assert result.reason == "days_to_cover"


def test_stale_short_data_uses_conservative_market_fallback(con):
    _short_tables(con)
    _liquid_market(con)
    old = date(2026, 9, 1)
    con.execute("INSERT INTO regsho_threshold VALUES ('XYZ',?,?)", [old, old])
    result = shorts.locate(con, "XYZ", DAY)
    assert result.available
    assert result.classification == "ETB"
    assert result.data_stale


def test_locate_uses_dated_liquidity_before_current_flag(con):
    _short_tables(con)
    _liquid_market(con)
    con.execute(
        "CREATE TABLE universe_snapshot "
        "(snapshot_date DATE,ticker VARCHAR,liquid BOOLEAN)"
    )
    con.execute("INSERT INTO universe_snapshot VALUES (?, 'XYZ', FALSE)", [DAY])
    result = shorts.locate(con, "XYZ", DAY)
    assert not result.available
    assert result.reason == "not_liquid"


def test_locate_prices_and_liquidity_use_availability_cutoff(con):
    _short_tables(con)
    con.execute("CREATE TABLE universe (ticker VARCHAR,liquid BOOLEAN)")
    con.execute("INSERT INTO universe VALUES ('XYZ',TRUE)")
    con.execute(
        "INSERT INTO finra_short_interest VALUES ('XYZ',?,?,?)",
        [date(2026, 10, 1), 1.0, DAY],
    )
    con.executemany(
        "INSERT INTO prices (ticker,date,open,high,low,close,volume,fetched_at) "
        "VALUES ('XYZ',?,?,?,?,?,?,?)",
        [
            (date(2026, 10, 8), 4, 4, 4, 4, 2_000_000,
             datetime(2026, 10, 8, 22)),
            (date(2026, 10, 9), 10, 10, 10, 10, 1_000_000,
             datetime(2026, 10, 12, 23)),
        ],
    )
    cutoff = datetime(2026, 10, 12, 22)
    result = shorts.locate(con, "XYZ", DAY, available_at=cutoff)
    assert not result.available
    assert result.reason == "price_below_5"


@pytest.mark.parametrize(
    ("price", "volume", "liquid", "reason"),
    [(4.99, 2_000_000, True, "price_below_5"),
     (10.0, 400_000, True, "mdv_below_5m"),
     (10.0, 1_000_000, False, "not_liquid")],
)
def test_conservative_locate_filters(con, price, volume, liquid, reason):
    _short_tables(con)
    con.execute("CREATE TABLE universe (ticker VARCHAR,liquid BOOLEAN)")
    con.execute("INSERT INTO universe VALUES ('XYZ',?)", [liquid])
    dates = [DAY - timedelta(days=value) for value in range(1, 31)]
    insert_bars(con, "XYZ", dates, open_=price, close=price, volume=volume)
    result = shorts.locate(con, "XYZ", DAY)
    assert not result.available
    assert result.reason == reason


def test_borrow_fee_debits_cash_once_with_fractional_short(con, book):
    _set_account(con, book)
    insert_bars(con, "XYZ", [date(2026, 10, 9), DAY], open_=20, close=20, volume=1_000_000)
    ledger.apply_fill(con, {
        "order_id": 1, "portfolio_id": book, "ticker": "XYZ", "side": "short",
        "qty": 250.5, "fill_px": 20, "fill_date": date(2026, 10, 9),
    })
    before = con.execute("SELECT cash FROM portfolios WHERE id=?", [book]).fetchone()[0]
    first = shorts.accrue_borrow(con, DAY, days=10)
    second = shorts.accrue_borrow(con, DAY, days=10)
    assert first["events"] == 1
    assert first["charged"] == pytest.approx(5_010 * 0.0025 * 10 / 360)
    assert second == {"events": 0, "charged": 0.0}
    assert con.execute(
        "SELECT cash FROM portfolios WHERE id=?", [book]
    ).fetchone()[0] == pytest.approx(before - first["charged"])


def test_first_borrow_accrual_starts_at_lot_open_after_prior_accrual(con, book):
    _set_account(con, book)
    insert_bars(con, "XYZ", [date(2026, 10, 9), DAY], open_=20, close=20, volume=1_000_000)
    ledger.apply_cash_event(con, {
        "portfolio_id": book, "event_date": date(2026, 10, 8),
        "kind": "borrow_fee", "amount": 0, "instrument_id": "XYZ",
    })
    ledger.apply_fill(con, {
        "order_id": 1, "portfolio_id": book, "ticker": "XYZ", "side": "short",
        "qty": 250, "fill_px": 20, "fill_date": date(2026, 10, 9),
    })
    result = shorts.accrue_borrow(con, DAY)
    assert result["events"] == 1
    assert result["charged"] == pytest.approx(5_000 * 0.0025 * 3 / 360)


def test_five_threshold_sessions_queue_one_buy_in_cover(con, book):
    _set_account(con, book)
    _short_tables(con)
    ledger.apply_fill(con, {
        "order_id": 1, "portfolio_id": book, "ticker": "XYZ", "side": "short",
        "qty": 12.5, "fill_px": 10, "fill_date": date(2026, 10, 5),
    })
    sessions = [date(2026, 10, value) for value in (6, 7, 8, 9, 12)]
    con.executemany(
        "INSERT INTO regsho_threshold VALUES ('XYZ',?,?)",
        [(value, value) for value in sessions],
    )
    queued = shorts.queue_buy_ins(con, con, DAY)
    assert len(queued) == 1
    con.execute(
        "UPDATE sim_order_details SET state_reason='buy_in|bar_missing' WHERE order_id=?",
        [queued[0]],
    )
    assert shorts.queue_buy_ins(con, con, DAY) == []
    assert con.execute(
        "SELECT side,qty,signal_date,status FROM sim_orders WHERE id=?", [queued[0]]
    ).fetchone() == ("cover", 12.5, DAY, "pending")
    assert con.execute(
        "SELECT order_type,state_reason FROM sim_order_details WHERE order_id=?",
        [queued[0]],
    ).fetchone() == ("next_open", "buy_in|bar_missing")


def test_buy_in_receipt_uses_actual_early_close(con, book):
    early = date(2026, 11, 27)
    _set_account(con, book)
    _short_tables(con)
    ledger.apply_fill(con, {
        "order_id": 1, "portfolio_id": book, "ticker": "XYZ", "side": "short",
        "qty": 1, "fill_px": 10, "fill_date": date(2026, 11, 19),
    })
    sessions = [date(2026, 11, value) for value in (20, 23, 24, 25, 27)]
    con.executemany(
        "INSERT INTO regsho_threshold VALUES ('XYZ',?,?)",
        [(value, value) for value in sessions],
    )
    order_id, = shorts.queue_buy_ins(con, con, early)
    assert con.execute(
        "SELECT received_at FROM sim_order_details WHERE order_id=?", [order_id]
    ).fetchone() == (datetime(2026, 11, 27, 18),)
