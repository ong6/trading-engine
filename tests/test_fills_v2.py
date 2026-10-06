"""Auction and deferred intraday fills for account-engine orders."""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from sim import bar_sources, fills
from tests.conftest import insert_bars

SESSION = date(2026, 10, 12)
NEW_YORK = ZoneInfo("America/New_York")


def _at(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 10, 12, hour, minute, second, tzinfo=NEW_YORK)


def _daily_history(con) -> None:
    history = [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 6)]
    insert_bars(con, "XYZ", history, open_=100, close=100, volume=1_000_000)
    insert_bars(
        con, "XYZ", [SESSION], open_=102, high=111, low=99, close=110,
        volume=1_000_000,
    )


def _intraday(con, rows) -> None:
    con.execute(
        "CREATE TABLE intraday_prices (ticker VARCHAR,ts TIMESTAMP,interval VARCHAR,"
        "open DOUBLE,high DOUBLE,low DOUBLE,close DOUBLE,volume BIGINT,source VARCHAR,"
        "as_of DATE,PRIMARY KEY(ticker,ts,interval))"
    )
    if rows:
        con.executemany(
            "INSERT INTO intraday_prices VALUES (?,?,?,?,?,?,?,?,?,?)",
            rows,
        )


def test_moo_cutoff_and_auction_price(con):
    _daily_history(con)
    accepted = fills.attempt_auction_fill(
        con, "XYZ", "buy", 10.5, SESSION, _at(9, 27, 59), "moo",
    )
    refused = fills.attempt_auction_fill(
        con, "XYZ", "buy", 10.5, SESSION, _at(9, 28, 1), "moo",
    )
    assert accepted.status == "filled"
    assert accepted.reference_px == accepted.open_px == 102
    assert accepted.fill_px == pytest.approx(102 * (1 + 2.5 / 10_000))
    assert accepted.fill_kind == "open_auction"
    assert accepted.price_source == "prices"
    assert refused.status == "rejected"
    assert refused.reject_reason == "cutoff"


def test_moc_cutoff_and_close_price(con):
    _daily_history(con)
    accepted = fills.attempt_auction_fill(
        con, "XYZ", "sell", 3, SESSION, _at(15, 50), "moc",
    )
    refused = fills.attempt_auction_fill(
        con, "XYZ", "sell", 3, SESSION, _at(15, 50, 1), "moc",
    )
    assert accepted.status == "filled"
    assert accepted.reference_px == 110
    assert accepted.fill_px == pytest.approx(110 * (1 - 2.5 / 10_000))
    assert accepted.fill_kind == "close_auction"
    assert refused.reject_reason == "cutoff"


def test_market_uses_first_bar_after_full_minute_and_vwap(con):
    _daily_history(con)
    _intraday(con, [
        ("XYZ", datetime(2026, 10, 12, 14, 17), "1m", 1, 999, 1, 999, 10,
         "fixture", SESSION),
        ("XYZ", datetime(2026, 10, 12, 14, 18), "1m", 100, 104, 98, 102, 20,
         "fixture", SESSION),
    ])
    result = fills.attempt_intraday_market_fill(
        con, "XYZ", "buy", 2.5, SESSION, _at(10, 17),
    )
    assert result.status == "filled"
    assert result.reference_px == pytest.approx(101)
    assert result.fill_px == pytest.approx(101 * 1.001)
    assert result.fill_ts == datetime(2026, 10, 12, 14, 18)
    assert "14:18:00" in result.bar_ref


def test_market_prefers_vwap_from_massive_minute(con):
    _daily_history(con)
    con.execute(
        "CREATE TABLE massive_minute_bars (ticker VARCHAR,ts_utc TIMESTAMP,o DOUBLE,"
        "h DOUBLE,l DOUBLE,c DOUBLE,v DOUBLE,vw DOUBLE,n BIGINT,session VARCHAR,"
        "source_sha256 VARCHAR,fetched_at TIMESTAMP)"
    )
    con.execute(
        "INSERT INTO massive_minute_bars VALUES "
        "('XYZ','2026-10-12 14:18:00',100,104,98,102,20,103,5,'regular','x',"
        "'2026-10-13 07:00:00')"
    )
    result = fills.attempt_intraday_market_fill(
        con, "XYZ", "sell", 2, SESSION, _at(10, 17),
        price_source="massive_minute",
    )
    assert result.reference_px == 103
    assert result.fill_px == pytest.approx(103 * 0.999)


def test_limit_requires_one_tick_cross_and_expires(con):
    _daily_history(con)
    _intraday(con, [
        ("XYZ", datetime(2026, 10, 12, 14, 18), "1m", 100, 100.5, 99.995,
         100, 20, "fixture", SESSION),
        ("XYZ", datetime(2026, 10, 12, 14, 19), "1m", 100, 101, 99.99,
         100, 20, "fixture", SESSION),
        ("XYZ", datetime(2026, 10, 12, 19, 59), "1m", 100, 101, 100,
         100, 20, "fixture", SESSION),
    ])
    result = fills.attempt_intraday_limit_fill(
        con, "XYZ", "buy", 1.25, SESSION, _at(10, 17), 100,
    )
    expired = fills.attempt_intraday_limit_fill(
        con, "XYZ", "buy", 1.25, SESSION, _at(10, 17), 99,
    )
    assert result.status == "filled"
    assert result.fill_px == 100
    assert result.fill_ts == datetime(2026, 10, 12, 14, 19)
    assert result.slippage_bps == 0
    assert expired.status == "expired"
    assert expired.reject_reason == "day_limit_not_touched"


def test_missing_intraday_data_stays_pending_for_late_settlement(con):
    _daily_history(con)
    _intraday(con, [])
    result = fills.attempt_intraday_market_fill(
        con, "XYZ", "buy", 1, SESSION, _at(10, 17),
    )
    assert result.status == "pending"


def test_partial_limit_session_stays_pending_until_close_is_known(con):
    _daily_history(con)
    _intraday(con, [
        ("XYZ", datetime(2026, 10, 12, 14, 18), "1m", 100, 101, 100,
         100, 20, "fixture", SESSION),
    ])
    result = fills.attempt_intraday_limit_fill(
        con, "XYZ", "buy", 1, SESSION, _at(10, 17), 99,
    )
    assert result.status == "pending"


def test_available_time_after_close_finalises_missing_intraday_orders(con):
    _daily_history(con)
    _intraday(con, [])
    available = datetime(2026, 10, 12, 20, 1, tzinfo=timezone.utc)
    market = fills.attempt_intraday_market_fill(
        con, "XYZ", "buy", 1, SESSION, _at(10, 17), available_at=available,
    )
    limit = fills.attempt_intraday_limit_fill(
        con, "XYZ", "buy", 1, SESSION, _at(10, 17), 99,
        available_at=available,
    )
    assert (market.status, market.reject_reason) == ("rejected", "no_bar")
    assert (limit.status, limit.reject_reason) == (
        "expired", "day_limit_not_touched",
    )


def test_market_without_possible_later_minute_rejects_no_bar(con):
    _daily_history(con)
    _intraday(con, [
        ("XYZ", datetime(2026, 10, 12, 19, 59), "1m", 100, 101, 99,
         100, 20, "fixture", SESSION),
    ])
    result = fills.attempt_intraday_market_fill(
        con, "XYZ", "buy", 1, SESSION, _at(15, 59, 30),
    )
    assert (result.status, result.reject_reason) == ("rejected", "no_bar")


def test_early_close_uses_actual_close_for_moc_market_and_limit(con):
    early = date(2026, 11, 27)
    history = [date(2026, 11, 23), date(2026, 11, 24), date(2026, 11, 25)]
    insert_bars(con, "XYZ", history, open_=100, close=100, volume=1_000_000)
    insert_bars(con, "XYZ", [early], open_=100, close=101, volume=1_000_000)
    _intraday(con, [])
    moc = fills.attempt_auction_fill(
        con, "XYZ", "sell", 1, early,
        datetime(2026, 11, 27, 14, 0, tzinfo=NEW_YORK), "moc",
    )
    market = fills.attempt_intraday_market_fill(
        con, "XYZ", "buy", 1, early,
        datetime(2026, 11, 27, 14, 30, tzinfo=NEW_YORK),
    )
    limit = fills.attempt_intraday_limit_fill(
        con, "XYZ", "buy", 1, early,
        datetime(2026, 11, 27, 14, 30, tzinfo=NEW_YORK), 99,
    )
    assert (moc.status, moc.reject_reason) == ("rejected", "cutoff")
    assert (market.status, market.reject_reason) == ("rejected", "market_closed")
    assert (limit.status, limit.reject_reason) == ("rejected", "market_closed")


def test_massive_daily_execution_reads_unadjusted_as_of_bar(con):
    con.execute(
        "CREATE TABLE free_daily_bars (date DATE,ticker VARCHAR,o DOUBLE,h DOUBLE,"
        "l DOUBLE,c DOUBLE,volume DOUBLE,vwap DOUBLE,source VARCHAR,fetched_at TIMESTAMP,"
        "source_sha256 VARCHAR)"
    )
    con.execute(
        "INSERT INTO free_daily_bars VALUES "
        "(?,'XYZ',100,101,99,100,1000,100,'massive','2026-10-12 21:00:00','raw')",
        [SESSION],
    )
    con.execute(
        "CREATE VIEW free_daily_bars_adjusted AS SELECT date,ticker,o/4 o,h/4 h,"
        "l/4 l,c/4 c,volume*4 volume,vwap/4 vwap,source,fetched_at,source_sha256 "
        "FROM free_daily_bars"
    )
    bar = bar_sources.daily_bar(
        con, "XYZ", SESSION, source="massive_daily",
        available_at=datetime(2026, 10, 12, 22, tzinfo=timezone.utc),
    )
    assert bar.open == 100


def test_daily_reader_enforces_first_availability_stamp(con):
    con.execute("ALTER TABLE prices ADD COLUMN IF NOT EXISTS first_fetched_at TIMESTAMP")
    con.execute(
        "INSERT INTO prices (ticker,date,open,high,low,close,volume,first_fetched_at) "
        "VALUES ('XYZ',?,10,11,9,10,100,'2026-10-13 07:00:00')",
        [SESSION],
    )
    before = datetime(2026, 10, 13, 6, 59, tzinfo=timezone.utc)
    after = datetime(2026, 10, 13, 7, 1, tzinfo=timezone.utc)
    assert bar_sources.daily_bar(
        con, "XYZ", SESSION, available_at=before,
    ) is None
    assert bar_sources.daily_bar(
        con, "XYZ", SESSION, available_at=after,
    ).close == 10


def test_legacy_attempt_fill_adds_no_v2_metadata(con):
    signal = date(2026, 10, 9)
    insert_bars(con, "XYZ", [signal, SESSION], open_=100, close=100, volume=1_000_000)
    result = fills.attempt_fill(con, "XYZ", "buy", 1, signal, SESSION)
    assert result.status == "filled"
    assert (result.fill_kind, result.price_source, result.bar_ref, result.fill_ts) == (
        None, None, None, None,
    )
