"""Resumable TradingView history archive and authority isolation."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from engine import queue_runner
from engine import tradingview_history_archive as archive
from engine.lib import db

NOW = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)


def _database(path):
    con = db.connect(path)
    db.init_schema(con)
    con.executemany(
        "INSERT INTO universe (ticker,yf_ticker,name,exchange,active,liquid) "
        "VALUES (?,?,?,?,TRUE,TRUE)",
        [("AAPL", "AAPL", "Apple", "Q"), ("IBM", "IBM", "IBM", "N"),
         ("SPY", "SPY", "SPY ETF", "P")],
    )
    con.close()
    path.chmod(0o600)


def _success(provider_symbol, start, end, *, database):
    con = db.connect(database)
    try:
        archive.init_schema(con)
        receipt = f"receipt-{provider_symbol}-{start}-{end}"
        con.execute(
            "INSERT INTO source_response_receipts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [con.execute("SELECT COALESCE(MAX(id),0)+1 FROM source_response_receipts").fetchone()[0],
             1, "tradingview_unofficial", "historical_daily_bars", "fixture", "{}",
             "request", NOW.replace(tzinfo=None), NOW.replace(tzinfo=None), 200,
             "application/json", 2, "response", b"{}", "test", receipt],
        )
        ticker = provider_symbol.split(":", 1)[1]
        event = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
        from engine import bitemporal_facts
        bitemporal_facts.record_fact(
            con, entity_id=ticker, security_id=ticker, fact_type="market.ohlcv.1d.retrieved",
            event_at=event, published_at=None, available_at=NOW, ingested_at=NOW,
            payload={"close": 100, "execution_authority": "none"},
            source="tradingview_unofficial", source_version="fixture",
            receipt_sha256=receipt,
        )
    finally:
        con.close()
    return {"status": "complete", "fact_count": 1, "receipt_sha256": receipt}


def test_freezes_exact_current_liquid_cohort_and_rejects_drift(tmp_path):
    path = tmp_path / "market.duckdb"
    _database(path)
    con = db.connect(path)
    first = archive.ensure_cohort(
        con, cohort_id="canary-v1", start=date(2022, 1, 1), selected_at=NOW,
        symbols=["IBM", "AAPL"],
    )
    replay = archive.ensure_cohort(
        con, cohort_id="canary-v1", start=date(2022, 1, 1), selected_at=NOW,
        symbols=["AAPL", "IBM"],
    )
    assert first["symbol_count"] == 2 and replay["replayed"] is True
    assert con.execute(
        "SELECT ticker,provider_symbol FROM tradingview_history_symbols ORDER BY ordinal"
    ).fetchall() == [("AAPL", "NASDAQ:AAPL"), ("IBM", "NYSE:IBM")]
    with pytest.raises(archive.ArchiveError, match="differ"):
        archive.ensure_cohort(
            con, cohort_id="canary-v1", start=date(2022, 1, 1), selected_at=NOW,
            symbols=["AAPL"],
        )
    con.close()


def test_exchange_map_uses_tradingview_provider_prefixes(tmp_path):
    path = tmp_path / "market.duckdb"
    _database(path)
    con = db.connect(path)
    archive.ensure_cohort(
        con, cohort_id="etf-v1", start=date(2022, 1, 1), selected_at=NOW, symbols=["SPY"]
    )
    assert con.execute(
        "SELECT provider_symbol FROM tradingview_history_symbols"
    ).fetchone() == ("AMEX:SPY",)
    con.close()


def test_run_checkpoints_success_and_resumes_next_window(tmp_path):
    path = tmp_path / "market.duckdb"
    _database(path)
    params = {"cohort_id": "canary-v1", "start": "2022-01-01",
              "through": "2025-01-01", "max_chunks": 1,
              "pause_seconds": 0, "symbols": ["AAPL"]}
    first = archive.run_connection_narrowed(params, path, capture=_success, clock=lambda: NOW)
    second = archive.run_connection_narrowed(params, path, capture=_success, clock=lambda: NOW)
    con = db.connect(path, read_only=True)
    try:
        windows = con.execute(
            "SELECT start_date,end_date,status FROM tradingview_history_attempts ORDER BY id"
        ).fetchall()
        assert windows == [(date(2022, 1, 1), date(2023, 7, 5), "complete"),
                           (date(2023, 7, 6), date(2025, 1, 1), "complete")]
        assert con.execute("SELECT COUNT(*) FROM prices").fetchone() == (0,)
    finally:
        con.close()
    assert first["attempted_this_run"] == second["attempted_this_run"] == 1
    assert second["fact_count"] == 2 and second["operational_price_mutation"] is False
    assert second["symbols_checkpointed"] == 1
    assert second["checkpoint_end"] == "2025-01-01"


def test_failed_window_retries_then_all_failure_is_visible(tmp_path):
    path = tmp_path / "market.duckdb"
    _database(path)
    calls = []

    def fail(*args, **kwargs):
        calls.append((args, kwargs))
        raise RuntimeError("provider unavailable")

    params = {"cohort_id": "failure-v1", "start": "2022-01-01",
              "through": "2022-01-31", "max_chunks": 1,
              "max_attempts": 2, "pause_seconds": 0, "symbols": ["IBM"]}
    for _ in range(2):
        with pytest.raises(archive.ArchiveError, match="all 1"):
            archive.run_connection_narrowed(params, path, capture=fail, clock=lambda: NOW)
    result = archive.run_connection_narrowed(params, path, capture=fail, clock=lambda: NOW)
    assert len(calls) == 2 and result["attempted_this_run"] == 0
    assert result["attempts"]["failed"] == 2
    assert result["unresolved_failed_windows"] == 1


def test_queue_registers_bounded_archive_after_core_miners():
    spec = queue_runner.JOB_TYPES["tradingview_history"]
    assert spec["archive"] is True and spec["releases_writer"] is True
    plan = queue_runner.nightly_plan(weekday=2)
    assert [kind for kind, _priority, _params in plan] == [
        "intraday", "signals", "earnings", "tradingview_history"]
    params = next(value for kind, _priority, value in plan if kind == "tradingview_history")
    assert queue_runner._parse_params(params)["max_chunks"] == 50


def test_production_cohort_cannot_be_accidentally_frozen_as_subset(tmp_path):
    path = tmp_path / "market.duckdb"
    _database(path)
    with pytest.raises(archive.ArchiveError, match="cannot use"):
        archive.run_connection_narrowed(
            {"cohort_id": "liquid-current-v1", "start": "2022-01-01",
             "through": "2022-01-02", "symbols": ["AAPL"]},
            path, capture=_success, clock=lambda: NOW,
        )


def test_run_publishes_monitorable_archive_metadata(tmp_path):
    path = tmp_path / "market.duckdb"
    meta = tmp_path / "meta.json"
    _database(path)
    archive.run_connection_narrowed(
        {"cohort_id": "meta-v1", "start": "2022-01-01",
         "through": "2022-01-02", "max_chunks": 1,
         "pause_seconds": 0, "symbols": ["AAPL"]},
        path, meta, capture=_success, clock=lambda: NOW,
    )
    payload = __import__("json").loads(meta.read_text())["tradingview_history"]
    assert payload["attempted_this_run"] == payload["completed_this_run"] == 1
    assert payload["failed_this_run"] == 0
    assert payload["last_run"] == NOW.isoformat()
