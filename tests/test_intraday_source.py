"""Exact-response agent intraday source and persistence tests."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from engine.lib import db
from server import agent_evaluation, hourly_opportunity_observer, intraday_source
from tests.test_daily_opportunities import _connector, _database, _news_response

NOW = datetime(2026, 9, 23, 15, 5, tzinfo=timezone.utc)


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
    stale = intraday_source.Response(
        _body(), "application/json", 200, NOW + timedelta(days=1), NOW + timedelta(days=1))
    with pytest.raises(intraday_source.IntradaySourceError, match="fresh"):
        intraday_source.parse("SPY", "SPY", stale)
    incomplete_body = json.loads(_body())
    incomplete_body["chart"]["result"][0]["timestamp"] = [
        int((NOW - timedelta(minutes=3)).timestamp()),
        int((NOW - timedelta(minutes=1)).timestamp()),
    ]
    incomplete = intraday_source.Response(
        json.dumps(incomplete_body).encode(), "application/json", 200,
        NOW - timedelta(minutes=2), NOW)
    with pytest.raises(intraday_source.IntradaySourceError, match="fresh"):
        intraday_source.parse("SPY", "SPY", incomplete)


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
        "variant_id": "hourly_market_watch_v5", "cadence": "hourly",
        "prompt_role": "rapid_catalyst_watch", "market_date": "2026-09-23",
        "observed_at": NOW.isoformat(), "completed_at": NOW.isoformat(),
        "information_cutoff_at": NOW.isoformat(), "window": "2026-09-23T15",
        "observation_sha256": "b" * 64,
        "quotes": [{"ticker": "SPY", "receipt_sha256": receipt_sha256}],
        "realtime_cross_checks": [{"ticker": "SPY", "source_id": "alpaca_iex",
                                    "receipt_sha256": "1" * 64}],
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
    assert {"kind": "realtime_cross_check_receipt", "ticker": "SPY",
            "source_id": "alpaca_iex", "sha256": "1" * 64,
            "execution_authority": "none"} in trace["source_refs"]


def test_cross_check_unavailable_never_calls_capture(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        hourly_opportunity_observer.official_quote_source.market_data_sources,
        "source_status", lambda *_: {"status": "unavailable", "reason": "no key"},
    )
    observations, failures, status = hourly_opportunity_observer._capture_cross_checks(
        ["SPY"], database=tmp_path / "never.duckdb", observed_at=NOW,
        capture=lambda *_args, **_kwargs: calls.append(True),
    )
    assert observations == [] and failures == [] and status["status"] == "unavailable"
    assert calls == [] and not (tmp_path / "never.duckdb").exists()


def test_tradingview_symbol_uses_provider_exchange_names():
    assert hourly_opportunity_observer._tradingview_symbol("SPY", "P") == "AMEX:SPY"
    assert hourly_opportunity_observer._tradingview_symbol("AAPL", "Q") == "NASDAQ:AAPL"


def test_cross_check_persistence_error_degrades_to_missing(monkeypatch, tmp_path):
    from engine import bitemporal_facts
    from server import market_data_sources

    monkeypatch.setattr(
        hourly_opportunity_observer.official_quote_source.market_data_sources,
        "source_status", lambda *_: {"status": "admitted"},
    )
    observations, failures, status = hourly_opportunity_observer._capture_cross_checks(
        ["SPY"], database=tmp_path / "never.duckdb", observed_at=NOW,
        capture=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            bitemporal_facts.FactError("invalid provenance")),
    )
    assert observations == [] and status["status"] == "admitted"
    assert failures == [{"ticker": "*", "reason": "invalid provenance"}]

    observations, failures, _ = hourly_opportunity_observer._capture_cross_checks(
        ["SPY"], database=tmp_path / "never.duckdb", observed_at=NOW,
        capture=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            market_data_sources.MarketDataError("wrong receipt")),
    )
    assert observations == [] and failures[0]["reason"] == "wrong receipt"


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
        "hourly_market_watch_v5", database=database, now=NOW, generate=_connector,
        fetch_news=_news_response, fetch_quote=fetch,
        clock=lambda: NOW + timedelta(seconds=1),
    )
    second = hourly_opportunity_observer.observe(
        "hourly_market_watch_v5", database=database, now=NOW, generate=_connector,
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


def test_admitted_cross_check_reaches_prompt_artifact_and_trace(monkeypatch, tmp_path):
    database = tmp_path / "market.duckdb"
    _database(database)
    monkeypatch.setattr(hourly_opportunity_observer, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(intraday_source, "source_version", lambda: "test-v1")
    receipt = "7" * 64
    cross_check = {
        "ticker": "FAST", "source_id": "alpaca_iex", "price": 160.1,
        "bid": 160.09, "ask": 160.11, "event_at": NOW.isoformat(),
        "received_at": NOW.isoformat(), "venue_scope": "IEX single-exchange",
        "consolidated": False, "delay_class": "provider-reported realtime",
        "receipt_sha256": receipt, "research_only": True,
        "execution_authority": "none", "evidence_id": "8" * 64,
    }
    seen = {}

    def generate(payload):
        seen.update(payload)
        return _connector(payload)

    result = hourly_opportunity_observer.observe(
        "hourly_market_watch_v5", database=database, now=NOW, generate=generate,
        fetch_news=_news_response,
        fetch_quote=lambda provider_ticker, _now: _response(_body(symbol=provider_ticker)),
        capture_cross_checks=lambda *_args, **_kwargs: (
            [cross_check], [], {"status": "admitted", "source_id": "alpaca_iex"}),
        clock=lambda: NOW + timedelta(seconds=1),
    )

    assert result["status"] == "completed"
    assert seen["candidates"][0]["realtime_cross_check"] == cross_check
    assert cross_check["evidence_id"] in seen["allowed_evidence_ids"]
    artifact = json.loads((tmp_path / "logs/hourly_market_watch_v5.jsonl").read_text())
    assert artifact["realtime_cross_checks"] == [cross_check]
    con = db.connect(database, read_only=True)
    try:
        refs = json.loads(con.execute(
            "SELECT source_refs FROM agent_evaluation_traces"
        ).fetchone()[0])
        assert any(item.get("sha256") == receipt for item in refs)
    finally:
        con.close()


def test_missing_fresh_quote_skips_without_model_or_trace(monkeypatch, tmp_path):
    database = tmp_path / "market.duckdb"
    _database(database)
    monkeypatch.setattr(hourly_opportunity_observer, "REPO_ROOT", tmp_path)
    model_calls = []
    result = hourly_opportunity_observer.observe(
        "hourly_market_watch_v5", database=database, now=NOW,
        generate=lambda payload: model_calls.append(payload), fetch_news=_news_response,
        fetch_quote=lambda *_: intraday_source.Response(
            _body(), "application/json", 200, NOW + timedelta(days=1),
            NOW + timedelta(days=1)),
        capture_cross_checks=lambda *_args, **_kwargs: (
            [], [], {"status": "admitted", "source_id": "tradingview_unofficial"}),
    )
    assert result["status"] == "skipped"
    assert result["execution_authority"] == "none" and model_calls == []
    assert not (tmp_path / "logs/hourly_market_watch_v5.jsonl").exists()
    con = db.connect(database, read_only=True)
    try:
        assert con.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name='agent_evaluation_traces'"
        ).fetchone() == (0,)
    finally:
        con.close()


@pytest.mark.parametrize(
    "variant_id",
    ["hourly_market_watch_v5", "four_hour_opportunity_review_v5"],
)
def test_one_stale_quote_records_unavailable_without_skipping_window(
    monkeypatch, tmp_path, variant_id
):
    database = tmp_path / "market.duckdb"
    _database(database)
    con = db.connect(database)
    con.execute(
        "UPDATE prices SET open=149,high=151,low=148,close=150,volume=6000000 "
        "WHERE ticker='QUIET' AND date=?",
        [NOW.date() - timedelta(days=2)],
    )
    con.close()
    monkeypatch.setattr(hourly_opportunity_observer, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(intraday_source, "source_version", lambda: "test-v1")
    seen = {}

    def generate(payload):
        seen.update(payload)
        return _connector(payload)

    def fetch(provider_ticker, _observed_at):
        if provider_ticker == "QUIET":
            return intraday_source.Response(
                _body(symbol=provider_ticker), "application/json", 200,
                NOW + timedelta(days=1), NOW + timedelta(days=1),
            )
        return _response(_body(symbol=provider_ticker))

    result = hourly_opportunity_observer.observe(
        variant_id, database=database, now=NOW, generate=generate,
        fetch_news=_news_response, fetch_quote=fetch,
        capture_cross_checks=lambda *_args, **_kwargs: (
            [], [], {"status": "admitted", "source_id": "tradingview_unofficial"}
        ),
        clock=lambda: NOW + timedelta(seconds=1),
    )

    assert result["status"] == "completed"
    assert result["quote_count"] == 1
    assert result["required_quote_count"] == 2
    assert result["unavailable_count"] == 1
    assert result["unavailable_ratio"] == 0.5
    assert [item["ticker"] for item in seen["candidates"]] == ["FAST"]
    artifact = json.loads((tmp_path / "logs" / f"{variant_id}.jsonl").read_text())
    unavailable = next(
        item for item in artifact["assessments"] if item["ticker"] == "QUIET"
    )
    assert unavailable["decision"] == "unavailable"
    assert unavailable["availability_status"] == "unavailable"
    con = db.connect(database, read_only=True)
    try:
        assert con.execute(
            "SELECT decision,action FROM agent_evaluation_decisions WHERE ticker='QUIET'"
        ).fetchone() == ("unavailable", "none")
        assert con.execute(
            "SELECT COUNT(*) FROM agent_evaluation_labels l "
            "JOIN agent_evaluation_decisions d ON d.id=l.decision_id "
            "WHERE d.ticker='QUIET'"
        ).fetchone() == (0,)
    finally:
        con.close()
