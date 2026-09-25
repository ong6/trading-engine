"""TradingView protocol, exact transcript, and authority-isolation tests."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from engine.lib import db
from server import market_data_sources, official_quote_source, tradingview_source

NOW = datetime(2026, 9, 25, 4, 0, tzinfo=timezone.utc)
SYMBOL = "NASDAQ:AAPL"


def _frame(packet: dict | str) -> str:
    value = packet if isinstance(packet, str) else json.dumps(packet, separators=(",", ":"))
    return f"~m~{len(value)}~m~{value}"


def _transcript(received: list[str]) -> tradingview_source.Transcript:
    body = json.dumps({
        "schema_version": 1, "endpoint": tradingview_source.ENDPOINT,
        "mode": "fixture", "symbol": SYMBOL, "sent": [], "received": received,
    }, sort_keys=True, separators=(",", ":")).encode()
    return tradingview_source.Transcript(body, NOW - timedelta(seconds=1), NOW)


def _quote_transcript(*, price=100.0, event_at=NOW - timedelta(seconds=2), spread=True):
    key = "=" + json.dumps({"session": "regular", "symbol": SYMBOL},
                            separators=(",", ":"))
    qsd = {"m": "qsd", "p": ["qs_fixture", {"n": key, "s": "ok", "v": {
        "lp": price, "lp_time": int(event_at.timestamp()),
        "bid": price - 0.01 if spread else 0, "ask": price + 0.01 if spread else 0,
        "volume": 1_000_000, "exchange": "Cboe One",
        "provider_id": "ice", "current_session": "market", "status": "ok",
    }}]}
    done = {"m": "quote_completed", "p": ["qs_fixture", key]}
    return _transcript([_frame(qsd) + _frame(done)])


def _history_transcript():
    resolved = {"m": "symbol_resolved", "p": ["cs_fixture", "ser_1", {
        "source_id": "BATS", "exchange": "NASDAQ", "full_name": SYMBOL,
    }]}
    times = [datetime(2026, 9, 23, 1, 30, tzinfo=timezone.utc),
             datetime(2026, 9, 24, 1, 30, tzinfo=timezone.utc)]
    update = {"m": "timescale_update", "p": ["cs_fixture", {"$prices": {"s": [
        {"i": index, "v": [int(when.timestamp()), 99 + index, 102 + index,
                                98 + index, 101 + index, 1_000_000 + index]}
        for index, when in enumerate(times)
    ]}}]}
    done = {"m": "series_completed", "p": ["cs_fixture", "$prices", "streaming"]}
    return _transcript([_frame(resolved), _frame(update) + _frame(done)])


def _secure_database(path):
    con = db.connect(path)
    db.init_schema(con)
    con.close()
    path.chmod(0o600)


def test_frame_parser_handles_multiple_packets_and_heartbeat():
    raw = _frame({"m": "one", "p": []}) + _frame("~h~4")
    assert tradingview_source.parse_frames(raw) == [{"m": "one", "p": []}, 4]
    with pytest.raises(tradingview_source.TradingViewSourceError, match="prefix"):
        tradingview_source.parse_frames("bad")


def test_tradingview_is_admitted_under_owner_asserted_rights():
    status = market_data_sources.source_status(market_data_sources.TRADINGVIEW, {})
    assert status["status"] == "admitted"
    assert status["realtime_authority"] == "research_cross_check_only"
    assert status["historical_authority"] == "retrieval_time_research_only"
    assert status["execution_authority"] == "none" and status["consolidated"] is False


def test_realtime_parser_preserves_resolved_feed_and_rejects_stale_quote():
    result = tradingview_source.parse_realtime(SYMBOL, _quote_transcript())
    assert result["ticker"] == "AAPL"
    assert result["payload"]["resolved_exchange"] == "Cboe One"
    assert result["payload"]["provider_id"] == "ice"
    stale = tradingview_source.parse_realtime(
        SYMBOL, _quote_transcript(event_at=NOW - timedelta(minutes=16)))
    assert stale["payload"]["fresh"] is False
    parsed = tradingview_source.parse_realtime(SYMBOL, _quote_transcript(spread=False))
    assert parsed["payload"]["bid"] is None and parsed["payload"]["spread_available"] is False


def test_realtime_capture_retains_exact_transcript_without_mutating_prices(tmp_path):
    database = tmp_path / "market.duckdb"
    _secure_database(database)
    transcript = _quote_transcript()
    result = official_quote_source.capture_tradingview_realtime(
        SYMBOL, database=database, fetch=lambda *_args, **_kwargs: transcript)
    assert result["status"] == "complete"
    assert result["observation"]["source_id"] == market_data_sources.TRADINGVIEW
    assert result["observation"]["execution_authority"] == "none"
    con = db.connect(database, read_only=True)
    try:
        assert bytes(con.execute(
            "SELECT response_body FROM source_response_receipts"
        ).fetchone()[0]) == transcript.body
        assert con.execute(
            "SELECT source,fact_type FROM bitemporal_facts"
        ).fetchone() == (market_data_sources.TRADINGVIEW, "market.quote.realtime")
        assert con.execute("SELECT COUNT(*) FROM prices").fetchone() == (0,)
    finally:
        con.close()


def test_historical_capture_is_range_bounded_and_research_only(tmp_path):
    database = tmp_path / "market.duckdb"
    _secure_database(database)
    transcript = _history_transcript()
    result = official_quote_source.capture_tradingview_history(
        SYMBOL, date(2026, 9, 24), date(2026, 9, 24), database=database,
        fetch=lambda *_args, **_kwargs: transcript)
    assert result["fact_count"] == 1
    assert result["historical_authority"] == "retrieval_time_research_only"
    con = db.connect(database, read_only=True)
    try:
        event_at, payload = con.execute(
            "SELECT event_at,normalized_payload FROM bitemporal_facts"
        ).fetchone()
        assert event_at.date() == date(2026, 9, 24)
        normalized = json.loads(payload)
        assert normalized["provider_id"] == "BATS"
        assert normalized["historical_authority"] == "retrieval_time_research"
        assert normalized["execution_authority"] == "none"
        assert con.execute("SELECT COUNT(*) FROM prices").fetchone() == (0,)
    finally:
        con.close()
    with pytest.raises(official_quote_source.OfficialSourceError, match="bounded"):
        official_quote_source.capture_tradingview_history(
            SYMBOL, date(2020, 1, 1), date(2022, 1, 1), database=database,
            fetch=lambda *_args, **_kwargs: transcript)
