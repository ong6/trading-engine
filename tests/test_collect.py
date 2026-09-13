"""EOD collection releases DuckDB around network work and checkpoints batches."""

from __future__ import annotations

import json
from datetime import date

import pandas as pd

from engine import collect
from engine.lib import db


def _raw_frame(day: str = "2026-09-08", *, volume: int = 1_000_000) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [100.0],
            "High": [101.0],
            "Low": [99.0],
            "Close": [100.5],
            "Volume": [volume],
        },
        index=pd.DatetimeIndex([day], name="Date"),
    )


def _setup_store(path, *, liquid: bool, backfill_done: bool = False) -> None:
    con = db.connect(path)
    try:
        db.init_schema(con)
        con.execute(
            "INSERT INTO universe (ticker, yf_ticker, active, liquid, backfill_done) "
            "VALUES ('AAA', 'AAA', TRUE, ?, ?)",
            [liquid, backfill_done],
        )
    finally:
        con.close()


def _read(path, sql: str):
    con = db.connect(path, read_only=True, wait_s=0)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def _stored_frame(day: str = "2026-09-08") -> pd.DataFrame:
    frame, got = collect._extract_long(_raw_frame(day), {"AAA": "AAA"})
    assert got == {"AAA"}
    return frame


def test_incremental_releases_db_during_download_and_sleep(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=True)
    observed: list[tuple[str, int]] = []

    def download_while_reading(tickers, *, period, start):
        assert tickers == ["AAA"] and period == "5d" and start is None
        count = _read(db_path, "SELECT COUNT(*) FROM prices")[0][0]
        observed.append(("download", count))
        return _raw_frame()

    def sleep_while_reading(seconds):
        assert seconds == 2
        count = _read(db_path, "SELECT COUNT(*) FROM prices")[0][0]
        observed.append(("sleep", count))

    monkeypatch.setattr(collect, "_download", download_while_reading)
    monkeypatch.setattr(collect.time, "sleep", sleep_while_reading)

    assert collect.mode_incremental(db_path, force=True) == (1, 0)
    assert observed == [("download", 0), ("sleep", 1)]
    assert _read(db_path, "SELECT ticker, date, close FROM prices") == [
        ("AAA", date(2026, 9, 8), 100.5)
    ]


def test_backfill_checkpoints_state_and_releases_db(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=True)
    observed: list[tuple[str, list[tuple]]] = []

    def download_while_reading(tickers, *, period, start):
        assert tickers == ["AAA"] and period == "max" and start is None
        observed.append(("download", _read(db_path, "SELECT state, progress FROM jobs")))
        return _raw_frame()

    def sleep_while_reading(seconds):
        assert seconds == 2
        observed.append(
            (
                "sleep",
                _read(
                    db_path,
                    "SELECT backfill_done, state, progress FROM universe, jobs",
                ),
            )
        )

    monkeypatch.setattr(collect, "_download", download_while_reading)
    monkeypatch.setattr(collect.time, "sleep", sleep_while_reading)

    assert collect.mode_backfill(db_path, None) == (1, 0)
    assert observed == [
        ("download", [("running", "0/1")]),
        ("sleep", [(True, "done", "1/1")]),
    ]


def test_bootstrap_releases_db_during_download_and_sleep(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=False)
    observed: list[tuple[str, int]] = []

    def download_while_reading(tickers, *, period, start):
        assert tickers == ["AAA"] and period is None and start is not None
        observed.append(("download", _read(db_path, "SELECT COUNT(*) FROM prices")[0][0]))
        return _raw_frame()

    def sleep_while_reading(seconds):
        assert seconds == 2
        observed.append(("sleep", _read(db_path, "SELECT COUNT(*) FROM prices")[0][0]))

    monkeypatch.setattr(collect, "_download", download_while_reading)
    monkeypatch.setattr(collect.time, "sleep", sleep_while_reading)

    assert collect.mode_bootstrap_floor(db_path, None) == (1, 0)
    assert observed == [("download", 0), ("sleep", 1)]
    assert _read(db_path, "SELECT liquid FROM universe WHERE ticker='AAA'") == [(True,)]


def test_refresh_releases_db_during_download_and_sleep(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=False)
    observed: list[tuple[str, int]] = []

    def download_while_reading(tickers, *, period, start):
        assert tickers == ["AAA"] and period is None and start is not None
        observed.append(("download", _read(db_path, "SELECT COUNT(*) FROM prices")[0][0]))
        return _raw_frame(volume=1_000)

    def sleep_while_reading(seconds):
        assert seconds == 2
        observed.append(("sleep", _read(db_path, "SELECT COUNT(*) FROM prices")[0][0]))

    monkeypatch.setattr(collect, "_download", download_while_reading)
    monkeypatch.setattr(collect.time, "sleep", sleep_while_reading)

    requested, failed, summary = collect.mode_refresh_liquid(db_path, None, False)
    assert (requested, failed) == (1, 0)
    assert summary["admitted"] == []
    assert summary["backfill"] == {"processed": 0, "failed": 0}
    assert observed == [("download", 0), ("sleep", 1)]


def test_refresh_retries_pending_backfill_without_new_admission(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=True)
    con = db.connect(db_path)
    try:
        db.upsert_prices(con, _stored_frame())
    finally:
        con.close()
    calls: list[tuple[list[str], str | None, str | None]] = []

    def download(tickers, *, period, start):
        calls.append((tickers, period, start))
        return _raw_frame(day="2026-09-09")

    monkeypatch.setattr(collect, "_download", download)
    monkeypatch.setattr(collect.time, "sleep", lambda _seconds: None)

    requested, failed, summary = collect.mode_refresh_liquid(db_path, None, False)

    assert (requested, failed) == (0, 0)
    assert summary["admitted"] == []
    assert summary["backfill"] == {"processed": 1, "failed": 0}
    assert calls == [(["AAA"], "max", None)]
    assert _read(db_path, "SELECT backfill_done FROM universe") == [(True,)]


def test_refresh_keeps_failed_pending_backfill_resumable(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=True)
    con = db.connect(db_path)
    try:
        db.upsert_prices(con, _stored_frame())
    finally:
        con.close()
    monkeypatch.setattr(collect, "_download", lambda *_args, **_kwargs: pd.DataFrame())
    monkeypatch.setattr(collect.time, "sleep", lambda _seconds: None)

    requested, failed, summary = collect.mode_refresh_liquid(db_path, None, False)

    assert (requested, failed) == (0, 0)
    assert summary["admitted"] == []
    assert summary["backfill"] == {"processed": 1, "failed": 1}
    assert _read(db_path, "SELECT backfill_done FROM universe") == [(False,)]


def test_refresh_with_no_pending_backfill_reports_zero_without_network(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=True, backfill_done=True)
    con = db.connect(db_path)
    try:
        db.upsert_prices(con, _stored_frame())
    finally:
        con.close()

    def unexpected_download(*_args, **_kwargs):
        raise AssertionError("no candidates or pending backfills must not make a network request")

    monkeypatch.setattr(collect, "_download", unexpected_download)

    requested, failed, summary = collect.mode_refresh_liquid(db_path, None, False)

    assert (requested, failed) == (0, 0)
    assert summary["admitted"] == []
    assert summary["backfill"] == {"processed": 0, "failed": 0}


def test_backfill_batch_state_rolls_back_with_price_rows(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=True)
    monkeypatch.setattr(collect, "_download", lambda *_args, **_kwargs: _raw_frame())

    def fail_progress(*_args, **_kwargs):
        raise RuntimeError("checkpoint failure")

    monkeypatch.setattr(collect, "_update_job", fail_progress)

    try:
        collect.mode_backfill(db_path, None)
    except RuntimeError as exc:
        assert str(exc) == "checkpoint failure"
    else:  # pragma: no cover - assertion branch
        raise AssertionError("failed checkpoint was accepted")
    assert _read(db_path, "SELECT COUNT(*) FROM prices") == [(0,)]
    assert _read(db_path, "SELECT backfill_done FROM universe") == [(False,)]
    assert _read(db_path, "SELECT state, progress FROM jobs") == [("running", "0/1")]


def test_limit_zero_is_an_explicit_no_network_path(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=True)

    def unexpected_download(*_args, **_kwargs):
        raise AssertionError("limit=0 must not make an HTTP request")

    monkeypatch.setattr(collect, "_download", unexpected_download)

    assert collect.mode_incremental(db_path, force=True, limit=0) == (0, 0)
    assert collect.mode_backfill(db_path, limit=0) == (0, 0)


def test_negative_limit_is_rejected_before_network(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=True)

    def unexpected_download(*_args, **_kwargs):
        raise AssertionError("invalid limits must not make an HTTP request")

    monkeypatch.setattr(collect, "_download", unexpected_download)

    try:
        collect.mode_incremental(db_path, force=True, limit=-1)
    except ValueError as exc:
        assert str(exc) == "limit must be non-negative"
    else:  # pragma: no cover - assertion branch
        raise AssertionError("negative limit was accepted")


def test_collection_metadata_preserves_other_producers(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    meta_path = tmp_path / "_meta.json"
    _setup_store(db_path, liquid=True)
    meta_path.write_text(
        json.dumps(
            {
                "regime": "risk-on",
                "last_screen": "2026-09-04T22:35:00+00:00",
                "fundamentals": {"last_run": "2026-09-05T00:33:22+00:00"},
                "price_verify": {"last_run": "2026-09-05T05:00:00+00:00"},
            }
        )
    )
    monkeypatch.setattr(collect, "_stale_cutoff", lambda _n=3: date(2026, 9, 1))

    collect.write_meta(db_path, "incremental", requested=1, failed=0, meta_path=meta_path)

    result = json.loads(meta_path.read_text())
    assert result["regime"] == "risk-on"
    assert result["last_screen"] == "2026-09-04T22:35:00+00:00"
    assert result["fundamentals"] == {"last_run": "2026-09-05T00:33:22+00:00"}
    assert result["price_verify"] == {"last_run": "2026-09-05T05:00:00+00:00"}
    assert result["mode"] == "incremental"
    assert result["universe_size"] == 1
    assert result["liquid_count"] == 1
    assert result["failed_this_run"] == 0
