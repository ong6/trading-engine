"""Resumable TradingView history archive and authority isolation."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from engine import queue_runner
from engine import tradingview_history_archive as archive
from engine.lib import db

NOW = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def enable_collection_for_archive_tests(monkeypatch):
    monkeypatch.setattr(archive, "collection_enabled", lambda: True)


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


def test_incremental_tail_waits_for_two_sessions_and_caps_request_at_four(tmp_path):
    path = tmp_path / "market.duckdb"
    _database(path)
    con = db.connect(path)
    archive.ensure_cohort(
        con, cohort_id="tail-v1", start=date(2026, 9, 1), selected_at=NOW,
        symbols=["AAPL"],
    )
    archive._record_attempt(
        con,
        cohort_id="tail-v1",
        chunk={"ticker": "AAPL", "provider_symbol": "NASDAQ:AAPL",
               "start": date(2026, 9, 1), "end": date(2026, 9, 23)},
        status="empty",
        fact_count=0,
        receipt_sha256=None,
        error=None,
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
    )
    for day in (date(2026, 9, 24), date(2026, 9, 25), date(2026, 9, 28),
                date(2026, 9, 29), date(2026, 9, 30)):
        con.execute(
            "INSERT INTO prices (ticker,date,close,volume) VALUES ('AAPL',?,100,1000)",
            [day],
        )

    assert archive._pending_chunks(con, "tail-v1", date(2026, 9, 24), 1, 3) == []
    chunks = archive._pending_chunks(con, "tail-v1", date(2026, 9, 30), 1, 3)
    con.close()

    assert chunks == [{
        "ticker": "AAPL",
        "provider_symbol": "NASDAQ:AAPL",
        "start": date(2026, 9, 24),
        "end": date(2026, 9, 29),
    }]


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


def _failing_window(tmp_path, error):
    """A one-window archive whose every request fails with `error`, run at NOW+hours."""
    path = tmp_path / "market.duckdb"
    _database(path)

    def fail(*_args, **_kwargs):
        raise RuntimeError(error)

    params = {"cohort_id": "retry-v1", "start": "2022-01-01", "through": "2022-01-31",
              "max_chunks": 1, "pause_seconds": 0, "symbols": ["IBM"]}

    def run(hours, capture=fail):
        return archive.run_connection_narrowed(
            params, path, capture=capture, clock=lambda: NOW + timedelta(hours=hours))

    for hours in (0, 4, 8):
        with pytest.raises(archive.ArchiveError, match="all 1"):
            run(hours)
    return path, run


def test_exhausted_window_retries_after_cooldown_until_refused_on_three_days(tmp_path):
    # Production 2026-10-15: nine windows spent their three attempts within 14 hours and
    # were never tried again, so unresolved_failed_windows stayed at 9 and the miner at issues.
    path, run = _failing_window(tmp_path, "TradingView provider unavailable: symbol_error")

    assert run(31)["attempted_this_run"] == 0
    retry = run(32)
    assert retry["attempted_this_run"] == retry["failed_this_run"] == 1
    assert retry["unresolved_failed_windows"] == 1 and retry["refused_windows"] == 0
    assert run(55)["attempted_this_run"] == 0
    refused = run(56)
    assert refused["attempted_this_run"] == refused["refused_this_run"] == 1
    assert refused["failed_this_run"] == 0
    assert refused["unresolved_failed_windows"] == 0 and refused["refused_windows"] == 1
    assert refused["attempts"] == {"complete": 0, "empty": 0, "failed": 4, "refused": 1}
    assert run(200)["attempted_this_run"] == 0
    con = db.connect(path, read_only=True)
    try:
        rows = con.execute(
            "SELECT id,status,started_at FROM tradingview_history_attempts ORDER BY id"
        ).fetchall()
    finally:
        con.close()
    assert [status for _id, status, _at in rows] == ["failed"] * 4 + ["refused"]
    assert [at for _id, _status, at in rows] == [
        (NOW + timedelta(hours=hours)).replace(tzinfo=None) for hours in (0, 4, 8, 32, 56)]


def test_transport_failures_keep_retrying_daily_and_are_never_refused(tmp_path):
    _path, run = _failing_window(tmp_path, "TradingView request failed")

    for hours in (32, 56, 80):
        retry = run(hours)
        assert retry["attempted_this_run"] == retry["failed_this_run"] == 1
        assert retry["unresolved_failed_windows"] == 1 and retry["refused_windows"] == 0


def test_exhausted_window_that_succeeds_after_cooldown_resolves(tmp_path):
    _path, run = _failing_window(tmp_path, "TradingView provider unavailable: symbol_error")

    result = run(32, capture=_success)
    assert result["completed_this_run"] == 1
    assert result["unresolved_failed_windows"] == result["refused_windows"] == 0


def test_queue_registers_bounded_archive_after_core_miners():
    spec = queue_runner.JOB_TYPES["tradingview_history"]
    assert spec["archive"] is True and spec["releases_writer"] is True
    original = queue_runner._tradingview_history_collection_enabled
    queue_runner._tradingview_history_collection_enabled = lambda: False
    assert [kind for kind, _priority, _params in queue_runner.nightly_plan(weekday=2)] == [
        "intraday", "signals", "earnings"]
    queue_runner._tradingview_history_collection_enabled = lambda: True
    plan = queue_runner.nightly_plan(weekday=2)
    assert [kind for kind, _priority, _params in plan] == [
        "intraday", "signals", "earnings", "tradingview_history"]
    params = next(value for kind, _priority, value in plan if kind == "tradingview_history")
    assert queue_runner._parse_params(params)["max_chunks"] == 50
    queue_runner._tradingview_history_collection_enabled = original


def test_paused_collection_records_status_without_store_or_network(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "collection_enabled", lambda: False)
    path = tmp_path / "market.duckdb"
    meta = tmp_path / "meta.json"
    result = archive.run_connection_narrowed(
        {"cohort_id": "liquid-current-v1", "start": "2022-01-01"},
        path, meta, capture=lambda *_args, **_kwargs: pytest.fail("network capture called"),
        clock=lambda: NOW,
    )
    assert result["status"] == "paused" and result["reason"] == "no_registered_reader"
    assert not path.exists()
    assert __import__("json").loads(meta.read_text())["tradingview_history"] == result


def test_publish_paused_writes_monitorable_evidence_without_store(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "collection_enabled", lambda: False)
    meta = tmp_path / "meta.json"
    result = archive.publish_paused(meta, clock=lambda: NOW)
    assert result == {
        "status": "paused", "reason": "no_registered_reader",
        "collection_enabled": False, "cohort_id": "liquid-current-v1",
        "last_run": NOW.isoformat(),
    }
    assert __import__("json").loads(meta.read_text())["tradingview_history"] == result


def test_publish_paused_cli_writes_meta_without_opening_database(
    tmp_path, monkeypatch, capsys,
):
    monkeypatch.setattr(archive, "collection_enabled", lambda: False)
    meta = tmp_path / "meta.json"
    database = tmp_path / "must-not-open.duckdb"
    assert archive.main([
        "--publish-paused", "--meta", str(meta), "--db", str(database),
    ]) == 0
    output = __import__("json").loads(capsys.readouterr().out)
    assert output["status"] == "paused"
    assert __import__("json").loads(meta.read_text())["tradingview_history"] == output
    assert not database.exists()


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


def test_failed_tail_window_resolves_when_a_wider_window_completes(tmp_path):
    # A symbol's last backfill window ends at the newest session, so the retry after a
    # failure asks for a wider window; the old exact-window match kept the failure
    # unresolved forever and pinned the miner at issues.
    path = tmp_path / "market.duckdb"
    _database(path)

    def fail(*_args, **_kwargs):
        raise RuntimeError("TradingView request failed")

    base = {"cohort_id": "tail-retry-v1", "start": "2022-01-01", "max_chunks": 1,
            "pause_seconds": 0, "symbols": ["IBM"]}
    with pytest.raises(archive.ArchiveError, match="all 1"):
        archive.run_connection_narrowed({**base, "through": "2022-01-31"}, path,
                                        capture=fail, clock=lambda: NOW)
    result = archive.run_connection_narrowed({**base, "through": "2022-02-07"}, path,
                                             capture=_success, clock=lambda: NOW)

    assert result["completed_this_run"] == 1 and result["checkpoint_end"] == "2022-02-07"
    assert result["attempts"]["failed"] == 1
    assert result["unresolved_failed_windows"] == 0


def test_corrected_provider_retries_refused_window_without_editing_cohort(tmp_path, monkeypatch):
    path, run = _failing_window(tmp_path, 'TradingView provider unavailable: symbol_error')
    run(32)
    run(56)
    con = db.connect(path)
    before = con.execute('SELECT * FROM tradingview_history_attempts ORDER BY id').fetchall()
    monkeypatch.setattr(archive, 'CORRECTED_PROVIDER_SYMBOLS', {'NYSE:IBM': 'AMEX:IBM'}, raising=False)
    chunks = archive._pending_chunks(con, 'retry-v1', date(2022, 1, 31), 1, 3, NOW + timedelta(hours=80))
    assert len(chunks) == 1
    assert chunks[0]['provider_symbol'] == 'AMEX:IBM'
    archive._record_attempt(con, cohort_id='retry-v1', chunk=chunks[0], status='complete',
                            fact_count=1, receipt_sha256='corrected', error=None,
                            started_at=NOW + timedelta(hours=80), completed_at=NOW + timedelta(hours=80))
    assert con.execute('SELECT * FROM tradingview_history_attempts ORDER BY id').fetchall()[:-1] == before
    assert con.execute('SELECT provider_symbol FROM tradingview_history_symbols').fetchone() == ('NYSE:IBM',)
    assert archive._pending_chunks(con, 'retry-v1', date(2022, 1, 31), 1, 3, NOW + timedelta(hours=104)) == []
    con.close()


@pytest.mark.parametrize('stored,accepted', [(100.0, True), (100.5, False), (None, False)])
def test_corrected_response_proof_precedes_facts_and_keeps_standard_receipt(tmp_path, stored, accepted):
    import json

    from server import official_quote_source
    from server import tradingview_source as tv

    day = date(2022, 1, 3)
    event = int(datetime(2022, 1, 3, 14, 30, tzinfo=timezone.utc).timestamp())
    packets = [
        {'m': 'symbol_resolved', 'p': ['cs_fixture', 'ser_1', {'source_id': 'BATS', 'exchange': 'AMEX'}]},
        {'m': 'timescale_update', 'p': ['cs_fixture', {'$prices': {'s': [{'v': [event, 100, 101, 99, 100, 1000]}]}}]},
        {'m': 'series_completed', 'p': ['cs_fixture', '$prices']},
    ]
    body = json.dumps({'received': [tv._packet(p['m'], p['p']) for p in packets]}).encode()
    transcript = tv.Transcript(body, NOW, NOW)
    path = tmp_path / 'market.duckdb'
    _database(path)
    con = db.connect(path)
    archive.init_schema(con)
    archive.ensure_cohort(con, cohort_id='proof-v1', start=day, selected_at=NOW, symbols=['IBM'])
    con.close()
    calls = []

    def fetch(symbol, **kwargs):
        # The network call has no DuckDB lease; a separate writer can open here.
        writer = db.connect(path, wait_s=0)
        writer.close()
        calls.append((symbol, kwargs))
        return transcript

    result = archive._capture_corrected_history('AMEX:IBM', day, day, database=path,
                                                stored={day: stored}, fetch=fetch)
    con = db.connect(path, read_only=True)
    receipt = con.execute('SELECT request_payload,response_body FROM source_response_receipts').fetchone()
    count = con.execute('SELECT COUNT(*) FROM bitemporal_facts').fetchone()[0]
    con.close()
    assert calls == [('AMEX:IBM', {'mode': 'history', 'bars': 10, 'reference': event + 34200})]
    assert receipt[1] == body
    assert json.loads(receipt[0])['provider_symbol'] == 'AMEX:IBM'
    assert result['status'] == ('complete' if accepted else 'refused')
    assert count == int(accepted)
    # The unchanged standard collector creates exactly the same receipt identity.
    standard = official_quote_source.capture_tradingview_history('AMEX:IBM', day, day,
                                                                database=path, fetch=fetch)
    assert result['receipt_sha256'] == standard['receipt_sha256']


def test_close_proof_keeps_existing_absolute_floor_and_requires_overlap():
    observations = [{'event_at': datetime(2022, 1, 3, tzinfo=timezone.utc), 'payload': {'close': 0.9925}}]
    assert archive._close_proof(observations, {date(2022, 1, 3): 0.99}) is None
    assert archive._close_proof(observations, {}) == 'corrected TradingView symbol has no overlapping stored closes'
