"""Intraday parsing, append-only storage, and bounded DB-connection tests."""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from engine import intraday
from engine.lib import db


def _raw_frame(ts: str = "2026-09-08 09:30", *, tz: str = "America/New_York") -> pd.DataFrame:
    index = pd.DatetimeIndex([ts], tz=tz, name="Datetime")
    return pd.DataFrame(
        {
            "Open": [100.0],
            "High": [101.0],
            "Low": [99.0],
            "Close": [100.5],
            "Volume": [1_000],
        },
        index=index,
    )


def test_extract_long_normalizes_timestamps_to_naive_utc():
    frame, got = intraday._extract_long(_raw_frame(), {"AAA": "CANON"}, "1m")

    assert got == {"AAA"}
    assert frame[["ticker", "ts", "interval"]].to_dict("records") == [
        {
            "ticker": "CANON",
            "ts": pd.Timestamp("2026-09-08 13:30:00"),
            "interval": "1m",
        }
    ]
    assert frame["ts"].dt.tz is None


def test_archive_universe_excludes_inactive_or_nonliquid_price_leaders(con):
    db.init_schema(con)
    dates = pd.date_range("2026-08-01", periods=5).date
    for ticker, active, liquid, price in (
        ("ACTIVE", True, True, 100.0),
        ("INACTIVE", False, True, 1_000.0),
        ("ILLIQUID", True, False, 900.0),
        ("PASSER", True, True, 10.0),
    ):
        con.execute(
            "INSERT INTO universe "
            "(ticker, yf_ticker, active, liquid) VALUES (?, ?, ?, ?)",
            [ticker, ticker, active, liquid],
        )
        for day in dates:
            con.execute(
                "INSERT INTO prices (ticker, date, close, volume) VALUES (?, ?, ?, 1000)",
                [ticker, day, price],
            )
    con.execute(
        "INSERT INTO screen_results "
        "(run_date, ticker, passes_template) VALUES (?, 'PASSER', TRUE)",
        [dates[-1]],
    )

    selected = intraday._select_universe(con)

    assert {"ACTIVE", "PASSER", *intraday.BENCHMARKS} <= set(selected)
    assert {"INACTIVE", "ILLIQUID"}.isdisjoint(selected)


def test_connection_narrowed_run_releases_db_and_appends_batches(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    con = db.connect(db_path)
    db.init_schema(con)
    db.init_queue_schema(con)
    con.close()

    observed: list[int] = []

    def download_while_reading(_tickers, *, interval, period):
        assert period == intraday.INTERVALS[interval]
        reader = db.connect(db_path, read_only=True, wait_s=0)
        try:
            observed.append(
                reader.execute("SELECT COUNT(*) FROM intraday_prices").fetchone()[0]
            )
        finally:
            reader.close()
        return _raw_frame()

    monkeypatch.setattr(intraday, "_select_universe", lambda _con: ["AAA"])
    monkeypatch.setattr(intraday, "_yf_map", lambda _con, _tickers: {"AAA": "AAA"})
    monkeypatch.setattr(intraday, "_download", download_while_reading)
    monkeypatch.setattr(intraday, "BATCH_SLEEP", 0)
    monkeypatch.setattr(intraday.rsc, "dir_size_gb", lambda _path: 0.0)

    result = intraday.run_connection_narrowed(
        {}, db_path=db_path, meta_path=tmp_path / "meta.json"
    )

    assert observed == [0, 1]
    assert result["new_rows_1m"] == 1
    assert result["new_rows_5m"] == 1
    assert result["tickers_with_data"] == 1
    check = db.connect(db_path, read_only=True)
    try:
        assert check.execute(
            "SELECT ticker, ts, interval FROM intraday_prices ORDER BY interval"
        ).fetchall() == [
            ("AAA", datetime(2026, 9, 8, 13, 30), "1m"),
            ("AAA", datetime(2026, 9, 8, 13, 30), "5m"),
        ]
    finally:
        check.close()


def test_limit_zero_makes_no_http_request(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"

    def unexpected_download(*_args, **_kwargs):
        raise AssertionError("limit=0 must not make an HTTP request")

    monkeypatch.setattr(intraday, "_download", unexpected_download)
    monkeypatch.setattr(intraday.rsc, "dir_size_gb", lambda _path: 0.0)
    result = intraday.run_connection_narrowed(
        {"limit": 0}, db_path=db_path, meta_path=tmp_path / "meta.json"
    )

    assert result["tickers_requested"] == 0
    assert result["tickers_with_data"] == 0
    assert result["new_rows_1m"] == 0
    assert result["new_rows_5m"] == 0
    assert result["failed_batches"] == 0
