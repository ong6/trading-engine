"""Exact-response agent intraday source and persistence tests."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from engine import intraday_source
from engine.lib import db
from server import agent_evaluation, hourly_opportunity_observer
from tests.test_daily_opportunities import _connector, _database, _news_response

NOW = datetime(2026, 9, 23, 15, 1, tzinfo=timezone.utc)


def _body(*, symbol: str = "SPY", future: bool = False) -> bytes:
    epochs = [
        int((NOW - timedelta(minutes=10)).timestamp()),
        int((NOW + timedelta(minutes=6) if future else NOW - timedelta(minutes=5)).timestamp()),
    ]
    return json.dumps({
        "chart": {"error": None, "result": [{
            "meta": {"symbol": symbol}, "timestamp": epochs,
            "indicators": {"quote": [{
                "open": [99.0, 100.0], "high": [101.0, 102.0],
                "low": [98.0, 99.0], "close": [100.0, 101.0],
                "volume": [1_000, 2_000],
            }]},
        }]},
    }, separators=(",", ":")).encode()


def _response(body: bytes | None = None) -> intraday_source.Response:
    return intraday_source.Response(
        body or _body(), "application/json;charset=utf-8", 200,
        NOW - timedelta(seconds=2), NOW,
    )


def test_parse_preserves_event_times_and_rejects_future_bars():
    bars = intraday_source.parse("SPY", "SPY", _response())
    assert [bar["event_at"] for bar in bars] == [
        NOW - timedelta(minutes=10), NOW - timedelta(minutes=5),
    ]
    assert bars[-1]["close"] == 101.0
    with pytest.raises(intraday_source.IntradaySourceError, match="timestamp"):
        intraday_source.parse("SPY", "SPY", _response(_body(future=True)))


def test_capture_quotes_uses_same_bytes_for_prompt_and_fact_ledger(monkeypatch, tmp_path):
    database = tmp_path / "market.duckdb"
    con = db.connect(database)
    db.init_schema(con)
    con.close()
    monkeypatch.setattr(intraday_source, "source_version", lambda: "test-v1")
    calls = []

    def fetch(provider_ticker, observed_at):
        calls.append((provider_ticker, observed_at))
        return _response()

    quotes, failures = hourly_opportunity_observer._capture_quotes(
        [("SPY", "SPY")], database=database, observed_at=NOW, fetch=fetch,
        clock=lambda: NOW + timedelta(seconds=1),
    )

    assert calls == [("SPY", NOW)]
    assert failures == []
    assert quotes[0]["last"] == 101.0
    con = db.connect(database, read_only=True)
    try:
        assert con.execute(
            "SELECT COUNT(*),COUNT(DISTINCT receipt_sha256) FROM bitemporal_facts"
        ).fetchone() == (2, 1)
        assert con.execute(
            "SELECT COUNT(*) FROM source_response_receipts WHERE response_body=?",
            [_body()],
        ).fetchone() == (1,)
        assert quotes[0]["receipt_sha256"] == con.execute(
            "SELECT receipt_sha256 FROM source_response_receipts"
        ).fetchone()[0]
    finally:
        con.close()


def test_capture_quotes_fails_closed_without_model_evidence(monkeypatch, tmp_path):
    database = tmp_path / "market.duckdb"
    con = db.connect(database)
    db.init_schema(con)
    con.close()
    monkeypatch.setattr(intraday_source, "source_version", lambda: "test-v1")

    quotes, failures = hourly_opportunity_observer._capture_quotes(
        [("SPY", "SPY")], database=database, observed_at=NOW,
        fetch=lambda *_args: _response(b"not-json"),
        clock=lambda: NOW + timedelta(seconds=1),
    )

    assert quotes == []
    assert len(failures) == 1
    assert failures[0]["ticker"] == "SPY"
    assert failures[0]["reason"] == "intraday response JSON is invalid"
    con = db.connect(database, read_only=True)
    try:
        assert con.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name IN ('source_response_receipts','bitemporal_facts')"
        ).fetchone() == (2,)
        assert con.execute("SELECT COUNT(*) FROM source_response_receipts").fetchone() == (1,)
        assert con.execute("SELECT COUNT(*) FROM bitemporal_facts").fetchone() == (0,)
        assert failures[0]["receipt_sha256"] == con.execute(
            "SELECT receipt_sha256 FROM source_response_receipts"
        ).fetchone()[0]
    finally:
        con.close()


def test_hourly_trace_links_the_exact_intraday_receipt():
    receipt_sha256 = "a" * 64
    artifact = {
        "variant_id": "hourly_market_watch_v1", "cadence": "hourly",
        "prompt_role": "rapid_catalyst_watch", "market_date": "2026-09-23",
        "observed_at": NOW.isoformat(), "completed_at": NOW.isoformat(),
        "information_cutoff_at": NOW.isoformat(), "window": "2026-09-23T15",
        "observation_sha256": "b" * 64,
        "quotes": [{"ticker": "SPY", "receipt_sha256": receipt_sha256}],
        "news_receipts": [], "model_input": {"task": "test"},
        "assessments": [{"ticker": "SPY", "decision": "watch"}],
        "model_response": {
            "output": {"schema_version": 1}, "request_sha256": "c" * 64,
            "response_id": "response-test", "model": "test",
            "model_version": "test", "instructions_sha256": "d" * 64,
            "toolset_sha256": "e" * 64, "model_catalog_entry_sha256": "f" * 64,
            "proxy_source_sha256": "0" * 64, "traecli_runtime": "test",
            "upstream_model_family": "test", "upstream_request_id": "test",
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        },
    }

    trace = agent_evaluation.artifact_trace(
        artifact, source_identifier="test.jsonl:window", latency_ms=1.0
    )

    assert {"kind": "intraday_receipt", "ticker": "SPY",
            "sha256": receipt_sha256} in trace["source_refs"]


def test_hourly_observer_retains_and_replays_exact_quote_evidence(monkeypatch, tmp_path):
    database = tmp_path / "market.duckdb"
    _database(database)
    monkeypatch.setattr(hourly_opportunity_observer, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(intraday_source, "source_version", lambda: "test-v1")
    calls = []

    def fetch(provider_ticker, observed_at):
        calls.append((provider_ticker, observed_at))
        return _response(_body(symbol=provider_ticker))

    first = hourly_opportunity_observer.observe(
        "hourly_market_watch_v1", database=database, now=NOW, generate=_connector,
        fetch_news=_news_response, fetch_quote=fetch,
        clock=lambda: NOW + timedelta(seconds=1),
    )
    second = hourly_opportunity_observer.observe(
        "hourly_market_watch_v1", database=database, now=NOW, generate=_connector,
        fetch_news=_news_response, fetch_quote=fetch,
        clock=lambda: NOW + timedelta(seconds=1),
    )

    assert first["replayed"] is False and second["replayed"] is True
    assert calls == [("FAST", NOW)]
    con = db.connect(database, read_only=True)
    try:
        receipt = con.execute(
            "SELECT receipt_sha256 FROM source_response_receipts"
        ).fetchone()[0]
        refs = json.loads(con.execute(
            "SELECT source_refs FROM agent_evaluation_traces"
        ).fetchone()[0])
        assert {"kind": "intraday_receipt", "ticker": "FAST",
                "sha256": receipt} in refs
        assert con.execute("SELECT COUNT(*) FROM agent_evaluation_traces").fetchone() == (1,)
    finally:
        con.close()
