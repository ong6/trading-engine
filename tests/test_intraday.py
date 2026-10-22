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
    monkeypatch.setattr(intraday.rsc, "dir_size_gb", lambda _path, **_kwargs: 0.0)

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
    monkeypatch.setattr(intraday.rsc, "dir_size_gb", lambda _path, **_kwargs: 0.0)
    result = intraday.run_connection_narrowed(
        {"limit": 0}, db_path=db_path, meta_path=tmp_path / "meta.json"
    )

    assert result["tickers_requested"] == 0
    assert result["tickers_with_data"] == 0
    assert result["new_rows_1m"] == 0
    assert result["new_rows_5m"] == 0
    assert result["failed_batches"] == 0


def test_coverage_windows_recover_gaps_and_preserve_first_capture(con, monkeypatch, tmp_path):
    import json
    from datetime import timedelta, timezone

    db.init_schema(con)
    db.init_queue_schema(con)
    now = datetime(2026, 10, 16, 22, tzinfo=timezone.utc)
    days = pd.bdate_range('2026-08-17', '2026-10-16')
    # Only exchange sessions, including the Labor Day holiday.
    days = [d for d in days if intraday.nyse.is_session(d.date())]
    frames = {}
    for interval in intraday.INTERVALS:
        times = [d + pd.Timedelta(hours=19, minutes=55 if interval == '5m' else 59)
                 for d in days]
        frames[interval] = pd.DataFrame({
            'ticker': 'AAA', 'ts': times, 'interval': interval,
            'open': 10., 'high': 11., 'low': 9., 'close': 10., 'volume': 100,
        })
    saved = {}
    for iv, frame in frames.items():
        floor = now - timedelta(days=int(intraday.INTERVALS[iv][:-1]))
        old = frame[(frame.ts >= floor.replace(tzinfo=None)) & (frame.ts.dt.date < now.date())]
        db.insert_intraday(con, old)
        saved[iv] = {'AAA': intraday._completed_coverage(
            old, iv, floor, now - timedelta(days=1), None)}
    assert all(v['AAA'] for v in saved.values())
    meta = tmp_path / 'meta.json'
    meta.write_text(json.dumps({'intraday': {'coverage': saved}}))
    valid = intraday._coverage(con, {'AAA': 'AAA'}, meta, now)
    assert set(valid) == {'1m', '5m'}
    # A resident interior day deleted after completion invalidates the watermark.
    con.execute("DELETE FROM intraday_prices WHERE interval='5m' AND CAST(ts AS DATE)='2026-10-12'")
    assert 'AAA' not in intraday._coverage(con, {'AAA': 'AAA'}, meta, now).get('5m', {})
    before = con.execute('SELECT * FROM intraday_prices ORDER BY ALL').fetchall()
    calls = []
    def download(names, *, interval, period=None, start=None, end=None):
        calls.append((interval, tuple(names), period, start))
        # Inject a failed incremental batch. Recovery must request full window.
        if start is not None:
            return pd.DataFrame()
        floor = now - timedelta(days=int(period[:-1]))
        frame = frames[interval]
        frame = frame[frame.ts >= floor.replace(tzinfo=None)].copy()
        # Provider revises an old close: anti-join keeps its first captured value/as_of.
        frame.loc[frame.ts.dt.date < now.date(), 'close'] = 10.5
        return pd.concat({name: frame.set_index('ts')[['open','high','low','close','volume']]
                          .rename(columns={v:k for k,v in intraday._YF_FIELDS.items()})
                          for name in names}, axis=1)
    monkeypatch.setattr(intraday, '_download', download)
    monkeypatch.setattr(intraday, 'BATCH_SLEEP', 0)
    monkeypatch.setattr(intraday.rsc, 'dir_size_gb', lambda _path, **_kwargs: 0.0)
    coverage = intraday._coverage(con, {'AAA':'AAA', 'NEW':'NEW'}, meta, now)
    result = intraday._pull_batches({'AAA':'AAA', 'NEW':'NEW'}, lambda f: db.insert_intraday(con,f), meta, coverage, now)
    assert any(iv=='1m' and start is not None for iv,names,p,start in calls)
    assert any(iv=='1m' and p=='7d' and names==('AAA',) for iv,names,p,start in calls)
    assert any(iv=='5m' and p=='60d' for iv,names,p,start in calls)
    assert any('NEW' in names and p is not None for iv,names,p,start in calls)
    after = con.execute('SELECT * FROM intraday_prices ORDER BY ALL').fetchall()
    assert set(before).issubset(set(after))
    # Reference path downloads the entire windows for both names; compare every
    # field, including immutable capture dates and the recovered interior day.
    import duckdb
    reference = duckdb.connect()
    db.init_schema(reference)
    db.init_queue_schema(reference)
    reference.executemany("INSERT INTO intraday_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", before)
    for iv, period in intraday.INTERVALS.items():
        raw = download(['AAA', 'NEW'], interval=iv, period=period)
        full, _ = intraday._extract_long(raw, {'AAA':'AAA', 'NEW':'NEW'}, iv)
        db.insert_intraday(reference, full)
    assert after == reference.execute('SELECT * FROM intraday_prices ORDER BY ALL').fetchall()
    reference.close()
    report = tmp_path / intraday.COVERAGE_REPORT
    saved = json.loads(report.read_text())['coverage']
    assert saved['5m']['AAA']['days']['2026-10-12'] == 1
    # _meta.json keeps only the summary and a pointer; the next run resumes from the report.
    stored = json.loads(meta.read_text())['intraday']
    assert 'coverage' not in stored and 'coverage' not in result
    assert stored['coverage_report'] == {'path': intraday.COVERAGE_REPORT,
                                         'tickers': {iv: len(saved.get(iv, {}))
                                                     for iv in intraday.INTERVALS}}
    meta.write_text(json.dumps({'intraday': stored}))
    assert intraday._coverage(con, {'AAA': 'AAA', 'NEW': 'NEW'}, meta, now)['5m']['AAA'] == \
        saved['5m']['AAA']
    assert con.execute("SELECT COUNT(*) FROM intraday_prices WHERE ticker='NEW'").fetchone()[0]>0


def test_partial_full_window_never_marks_gap_complete():
    from datetime import timezone
    frame = pd.DataFrame({'ts': pd.to_datetime(['2026-10-12 19:59', '2026-10-14 19:59'])})
    assert intraday._completed_coverage(frame, '1m', datetime(2026,10,12,tzinfo=timezone.utc),
                                        datetime(2026,10,14,22,tzinfo=timezone.utc), None) is None
