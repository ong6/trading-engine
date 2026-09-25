"""Provider admission and exact-response market-data tests."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from engine.lib import db
from server import market_data_sources, official_quote_source
from tools import market_data_source as source_cli

NOW = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)
ADMITTED = {
    "TRADING_ENGINE_ALPACA_DATA_TERMS_ACCEPTED":
        market_data_sources.ALPACA_TERMS_ACCEPTANCE,
    "APCA_API_KEY_ID": "test-key", "APCA_API_SECRET_KEY": "test-secret",
}


def _response(payload: dict, *, received_at: datetime = NOW, status: int = 200):
    return market_data_sources.SourceResponse(
        json.dumps(payload, separators=(",", ":")).encode(), "application/json", status,
        received_at - timedelta(seconds=1), received_at,
    )


def _secure_database(path):
    con = db.connect(path)
    db.init_schema(con)
    con.close()
    path.chmod(0o600)


def _snapshot(price: float = 100.0, *, event_at: datetime | None = None):
    return {"snapshots": {"AAPL": {
        "latestTrade": {"p": price, "t": (event_at or NOW).isoformat(), "x": "V"},
        "latestQuote": {"bp": price - 0.01, "ap": price + 0.01,
                        "t": (event_at or NOW).isoformat(),
                        "bx": "V", "ax": "V"},
    }}}


def test_source_registry_admits_tradingview_and_gates_alpaca():
    tradingview = market_data_sources.source_status(market_data_sources.TRADINGVIEW, {})
    missing = market_data_sources.source_status(market_data_sources.ALPACA, {})
    admitted = market_data_sources.source_status(market_data_sources.ALPACA, ADMITTED)

    assert tradingview["status"] == "admitted"
    assert tradingview["execution_authority"] == "none"
    assert tradingview["historical_authority"] == "retrieval_time_research_only"
    assert missing["status"] == "unavailable"
    assert admitted["status"] == "admitted"
    assert admitted["venue_scope"] == "IEX single-exchange"
    assert admitted["consolidated"] is False
    assert market_data_sources.source_status(
        market_data_sources.ALPACA, {**ADMITTED,
        "TRADING_ENGINE_ALPACA_DATA_TERMS_ACCEPTED": "accepted"})["status"] == "unavailable"


def test_observation_receipt_must_match_source_and_dataset(tmp_path):
    database = tmp_path / "market.duckdb"
    _secure_database(database)
    con = db.connect(database)
    db.init_schema(con)
    receipt = market_data_sources.retain_response(
        con, source_id=market_data_sources.ALPACA, dataset="realtime_snapshot",
        endpoint="https://example.test", request={}, response=_response(_snapshot()),
        environ=ADMITTED,
    )
    with pytest.raises(market_data_sources.MarketDataError, match="does not match"):
        market_data_sources.retain_observations(
            con, source_id=market_data_sources.ALPACA,
            receipt_sha256=receipt["receipt_sha256"], receipt_dataset="historical_daily_bars",
            received_at=NOW, observations=[{"ticker": "AAPL", "event_at": NOW,
                                          "payload": {"price": 100.0}}],
            fact_type="market.quote.realtime", source_version="test", environ=ADMITTED,
        )
    con.close()


def test_observation_receipt_time_must_match(tmp_path):
    database = tmp_path / "market.duckdb"
    _secure_database(database)
    con = db.connect(database)
    db.init_schema(con)
    receipt = market_data_sources.retain_response(
        con, source_id=market_data_sources.ALPACA, dataset="realtime_snapshot",
        endpoint="https://example.test", request={}, response=_response(_snapshot()),
        environ=ADMITTED)
    with pytest.raises(market_data_sources.MarketDataError, match="does not match"):
        market_data_sources.retain_observations(
            con, source_id=market_data_sources.ALPACA, receipt_sha256=receipt["receipt_sha256"],
            receipt_dataset="realtime_snapshot", received_at=NOW + timedelta(seconds=1),
            observations=[{"ticker": "AAPL", "event_at": NOW,
                          "payload": {"price": 100.0}}],
            fact_type="market.quote.realtime", source_version="test", environ=ADMITTED)
    con.close()


def test_missing_credentials_skip_network_and_database(tmp_path):
    called = []
    result = official_quote_source.capture_realtime(
        "AAPL", database=tmp_path / "missing.duckdb", environ={},
        fetch=lambda *_args: called.append(True),
    )
    assert result["status"] == "unavailable"
    assert called == []
    assert not (tmp_path / "missing.duckdb").exists()


def test_realtime_capture_retains_exact_bytes_and_revisions(tmp_path):
    database = tmp_path / "market.duckdb"
    _secure_database(database)
    first = _response(_snapshot())
    second = _response(_snapshot(101.0), received_at=NOW + timedelta(seconds=1))

    for response in (first, first, second):
        result = official_quote_source.capture_realtime(
            "AAPL", database=database, environ=ADMITTED,
            fetch=lambda *_, response=response: response,
        )
        assert result["status"] == "complete"
        assert result["observation"]["research_only"] is True
        assert result["observation"]["execution_authority"] == "none"

    con = db.connect(database, read_only=True)
    try:
        assert con.execute("SELECT COUNT(*) FROM source_response_receipts").fetchone() == (2,)
        assert con.execute("SELECT COUNT(*) FROM bitemporal_facts").fetchone() == (2,)
        assert con.execute(
            "SELECT MAX(revision) FROM bitemporal_facts WHERE entity_id='AAPL'"
        ).fetchone() == (2,)
        available, ingested = con.execute(
            "SELECT available_at,ingested_at FROM bitemporal_facts ORDER BY id LIMIT 1"
        ).fetchone()
        assert ingested > available
        assert bytes(con.execute(
            "SELECT response_body FROM source_response_receipts ORDER BY id LIMIT 1"
        ).fetchone()[0]) == first.body
        assert con.execute("SELECT COUNT(*) FROM prices").fetchone() == (0,)
    finally:
        con.close()


def test_batched_realtime_capture_uses_one_response(tmp_path):
    database = tmp_path / "market.duckdb"
    _secure_database(database)
    payload = _snapshot()
    payload["snapshots"]["MSFT"] = {
        "latestTrade": {"p": 200.0, "t": NOW.isoformat(), "x": "V"},
        "latestQuote": {"bp": 199.99, "ap": 200.01, "t": NOW.isoformat(),
                        "bx": "V", "ax": "V"},
    }
    calls = []
    observations = official_quote_source.capture_realtime_many(
        ["AAPL", "MSFT"], database=database, environ=ADMITTED,
        fetch=lambda symbols, _now: calls.append(symbols) or _response(payload),
    )
    assert calls == [["AAPL", "MSFT"]]
    assert [item["ticker"] for item in observations] == ["AAPL", "MSFT"]
    assert len({item["receipt_sha256"] for item in observations}) == 1
    con = db.connect(database, read_only=True)
    try:
        assert con.execute("SELECT COUNT(*) FROM source_response_receipts").fetchone() == (1,)
        assert con.execute("SELECT COUNT(*) FROM bitemporal_facts").fetchone() == (2,)
    finally:
        con.close()


def test_batched_malformed_response_retains_receipt_without_facts(tmp_path):
    database = tmp_path / "market.duckdb"
    _secure_database(database)
    with pytest.raises(official_quote_source.OfficialSourceError, match="shape"):
        official_quote_source.capture_realtime_many(
            ["AAPL", "MSFT"], database=database, environ=ADMITTED,
            fetch=lambda *_: _response(_snapshot()),
        )
    con = db.connect(database, read_only=True)
    try:
        assert con.execute("SELECT COUNT(*) FROM source_response_receipts").fetchone() == (1,)
        assert con.execute("SELECT COUNT(*) FROM bitemporal_facts").fetchone() == (0,)
    finally:
        con.close()


def test_error_without_content_type_is_retained_without_facts(tmp_path):
    database = tmp_path / "market.duckdb"
    _secure_database(database)
    response = market_data_sources.SourceResponse(
        b"upstream failure", "", 502, NOW - timedelta(seconds=1), NOW)
    with pytest.raises(official_quote_source.OfficialSourceError, match="metadata"):
        official_quote_source.capture_realtime_many(
            ["AAPL"], database=database, environ=ADMITTED, fetch=lambda *_: response)
    con = db.connect(database, read_only=True)
    try:
        assert con.execute(
            "SELECT http_status,content_type,response_body FROM source_response_receipts"
        ).fetchone() == (502, "application/octet-stream", b"upstream failure")
        assert con.execute("SELECT COUNT(*) FROM bitemporal_facts").fetchone() == (0,)
    finally:
        con.close()


@pytest.mark.parametrize("payload,received,match", [
    (_snapshot(0), NOW, "trade price"),
    (_snapshot(event_at=NOW - timedelta(minutes=16)), NOW, "stale"),
    ({}, NOW, "shape"),
])
def test_realtime_parser_fails_closed(payload, received, match):
    with pytest.raises(official_quote_source.OfficialSourceError, match=match):
        official_quote_source.parse_realtime("AAPL", _response(payload, received_at=received))


def test_invalid_realtime_response_retains_receipt_but_no_fact(tmp_path):
    database = tmp_path / "market.duckdb"
    _secure_database(database)
    with pytest.raises(official_quote_source.OfficialSourceError, match="JSON"):
        official_quote_source.capture_realtime(
            "AAPL", database=database, environ=ADMITTED,
            fetch=lambda *_: market_data_sources.SourceResponse(
                b"bad-json", "application/json", 200, NOW - timedelta(seconds=1), NOW),
        )
    con = db.connect(database, read_only=True)
    try:
        assert con.execute("SELECT COUNT(*) FROM source_response_receipts").fetchone() == (1,)
        assert con.execute("SELECT COUNT(*) FROM bitemporal_facts").fetchone() == (0,)
    finally:
        con.close()


def test_history_is_bounded_retrieval_time_staging_only(tmp_path):
    database = tmp_path / "market.duckdb"
    _secure_database(database)
    payload = {"symbol": "AAPL", "next_page_token": None, "bars": [{
        "t": "2022-09-01T04:00:00Z", "o": 156.64, "h": 158.42,
        "l": 154.67, "c": 157.96, "v": 74229900,
    }]}
    result = official_quote_source.capture_history(
        "AAPL", date(2022, 9, 1), date(2022, 9, 2), database=database,
        environ=ADMITTED, fetch=lambda *_: _response(payload),
    )
    assert result["fact_count"] == 1
    assert result["historical_authority"] == "retrieval_time_staging_only"
    con = db.connect(database, read_only=True)
    try:
        row = con.execute(
            "SELECT fact_type,published_at,available_at,normalized_payload "
            "FROM bitemporal_facts"
        ).fetchone()
        assert row[0] == "market.ohlcv.1d.retrieved" and row[1] is None
        assert row[2] == NOW.replace(tzinfo=None)
        assert json.loads(row[3])["historical_authority"] == "retrieval_time_staging_only"
        assert con.execute("SELECT COUNT(*) FROM prices").fetchone() == (0,)
    finally:
        con.close()

    with pytest.raises(official_quote_source.OfficialSourceError, match="bounded"):
        official_quote_source.history_request("AAPL", date(2020, 1, 1), date(2022, 1, 2))
    outside = {**payload, "bars": [{**payload["bars"][0], "t": "2022-08-31T04:00:00Z"}]}
    with pytest.raises(official_quote_source.OfficialSourceError, match="timestamp"):
        official_quote_source.parse_history(
            "AAPL", date(2022, 9, 1), date(2022, 9, 2), _response(outside))
    high_volume = {**payload, "bars": [{**payload["bars"][0], "v": 200_000_000}]}
    assert official_quote_source.parse_history(
        "AAPL", date(2022, 9, 1), date(2022, 9, 2), _response(high_volume)
    )[0]["payload"]["volume"] == 200_000_000


def test_cli_rejects_partial_history_and_unavailable_capture(capsys):
    with pytest.raises(SystemExit) as exc:
        source_cli.main(["--history", "AAPL", "--start", "2022-09-01"])
    assert exc.value.code == 2
    assert source_cli.main(["--realtime", "AAPL"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "unavailable"


def test_credential_file_is_owner_only_and_allowlisted(tmp_path, monkeypatch):
    path = tmp_path / "market-data.env"
    path.write_text("APCA_API_KEY_ID=test\nAPCA_API_SECRET_KEY=secret\n")
    path.chmod(0o644)
    assert source_cli.main(["--preflight", str(path)]) == 1
    path.chmod(0o600)
    loaded = source_cli._load_environment(path)
    assert loaded["APCA_API_KEY_ID"] == "test"
    path.write_text("PYTHONPATH=/tmp/evil\n")
    with pytest.raises(ValueError, match="invalid entry"):
        source_cli._load_environment(path)
