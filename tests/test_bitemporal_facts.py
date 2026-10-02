"""Vendor-neutral source receipt and bitemporal fact contracts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from engine import bitemporal_facts

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


def _receipt(con):
    bitemporal_facts.init_schema(con)
    return bitemporal_facts.record_receipt(
        con, source="test", dataset="intraday_quote", endpoint="https://example.test/data",
        request={"ticker": "SPY"}, requested_at=NOW, received_at=NOW + timedelta(seconds=1),
        http_status=200, content_type="application/json", body=b'{"price":100}',
        license_class="public-test",
    )


def test_receipt_and_fact_are_replay_stable_and_revision_preserving(con):
    receipt = _receipt(con)
    replay = _receipt(con)
    first = bitemporal_facts.record_fact(
        con, entity_id="SPY", security_id="US-SPY", fact_type="quote.close",
        event_at=NOW - timedelta(minutes=1), published_at=NOW,
        available_at=NOW + timedelta(seconds=1), ingested_at=NOW + timedelta(seconds=2),
        payload={"value": 100.0}, source="test", source_version="v1",
        receipt_sha256=receipt["receipt_sha256"],
    )
    same = bitemporal_facts.record_fact(
        con, entity_id="SPY", security_id="US-SPY", fact_type="quote.close",
        event_at=NOW - timedelta(minutes=1), published_at=NOW,
        available_at=NOW + timedelta(seconds=1), ingested_at=NOW + timedelta(seconds=2),
        payload={"value": 100.0}, source="test", source_version="v1",
        receipt_sha256=receipt["receipt_sha256"],
    )
    revised = bitemporal_facts.record_fact(
        con, entity_id="SPY", security_id="US-SPY", fact_type="quote.close",
        event_at=NOW - timedelta(minutes=1), published_at=NOW,
        available_at=NOW + timedelta(seconds=3), ingested_at=NOW + timedelta(seconds=4),
        payload={"value": 100.1}, source="test", source_version="v1",
        receipt_sha256=receipt["receipt_sha256"],
    )
    assert receipt["replayed"] is False and replay["replayed"] is True
    assert first["revision"] == same["revision"] == 1
    assert same["replayed"] is True
    assert revised["revision"] == 2
    assert con.execute("SELECT COUNT(*) FROM bitemporal_facts").fetchone() == (2,)


def test_same_value_from_later_receipt_preserves_first_availability_only(con):
    first_receipt = _receipt(con)
    first = bitemporal_facts.record_fact(
        con, entity_id="SPY", security_id="US-SPY", fact_type="quote.close",
        event_at=NOW - timedelta(minutes=1), published_at=NOW,
        available_at=NOW + timedelta(seconds=1), ingested_at=NOW + timedelta(seconds=2),
        payload={"value": 100.0}, source="test", source_version="v1",
        receipt_sha256=first_receipt["receipt_sha256"],
    )
    later_receipt = bitemporal_facts.record_receipt(
        con, source="test", dataset="intraday_quote", endpoint="https://example.test/data",
        request={"ticker": "SPY"}, requested_at=NOW + timedelta(minutes=1),
        received_at=NOW + timedelta(minutes=1, seconds=1), http_status=200,
        content_type="application/json", body=b'{"price":100}',
        license_class="public-test",
    )
    second = bitemporal_facts.record_fact(
        con, entity_id="SPY", security_id="US-SPY", fact_type="quote.close",
        event_at=NOW - timedelta(minutes=1), published_at=NOW,
        available_at=NOW + timedelta(minutes=1, seconds=1),
        ingested_at=NOW + timedelta(minutes=1, seconds=2), payload={"value": 100.0},
        source="test", source_version="v1",
        receipt_sha256=later_receipt["receipt_sha256"],
    )
    assert first["revision"] == second["revision"] == 1
    assert second["replayed"] is True
    assert con.execute("SELECT COUNT(*) FROM source_response_receipts").fetchone() == (2,)
    assert con.execute("SELECT COUNT(*) FROM bitemporal_facts").fetchone() == (1,)
    known_before = bitemporal_facts.facts_as_known(con, NOW + timedelta(seconds=2))
    known_after = bitemporal_facts.facts_as_known(con, NOW + timedelta(minutes=2))
    assert len(known_before) == 1 and known_before[0]["revision"] == 1
    assert len(known_after) == 1 and known_after[0]["fact_sha256"] == first["fact_sha256"]


def test_security_master_event_is_typed_and_receipt_linked(con):
    receipt = _receipt(con)
    result = bitemporal_facts.record_security_event(
        con, entity_id="issuer-1", security_id="security-1", event_type="symbol_change",
        event_at=NOW, published_at=NOW, available_at=NOW + timedelta(seconds=1),
        ingested_at=NOW + timedelta(seconds=2),
        payload={"event_type": "symbol_change", "old_symbol": "OLD", "new_symbol": "NEW"},
        source="test", source_version="v1", receipt_sha256=receipt["receipt_sha256"],
    )
    assert result["revision"] == 1
    assert con.execute("SELECT fact_type FROM bitemporal_facts").fetchone() == ("security.symbol_change",)


def test_fact_rejects_future_availability_or_missing_receipt(con):
    bitemporal_facts.init_schema(con)
    with pytest.raises(bitemporal_facts.FactError, match="receipt"):
        bitemporal_facts.record_fact(
            con, entity_id="SPY", security_id=None, fact_type="quote.close",
            event_at=NOW, published_at=None, available_at=NOW, ingested_at=NOW,
            payload={"value": 100}, source="test", source_version="v1",
            receipt_sha256="0" * 64,
        )
    receipt = _receipt(con)
    with pytest.raises(bitemporal_facts.FactError, match="times are inconsistent"):
        bitemporal_facts.record_fact(
            con, entity_id="SPY", security_id=None, fact_type="quote.close",
            event_at=NOW + timedelta(seconds=1), published_at=None, available_at=NOW,
            ingested_at=NOW, payload={"value": 100}, source="test",
            source_version="v1", receipt_sha256=receipt["receipt_sha256"],
        )


def test_intraday_batch_retains_raw_receipt_and_event_availability_times(con):
    bitemporal_facts.init_schema(con)
    quote = {"ticker": "SPY", "event_at": NOW - timedelta(minutes=5),
             "open": 99.0, "high": 101.0, "low": 98.0, "close": 100.0,
             "volume": 10_000}
    result = bitemporal_facts.record_intraday_quote_batch(
        con, source="test", endpoint="https://example.test/quotes",
        request={"symbols": ["SPY"]}, requested_at=NOW,
        received_at=NOW + timedelta(seconds=1), content_type="application/json",
        body=b'{"bars":[]}', quotes=[quote], interval="5m", source_version="v1",
        license_class="public-test",
    )
    assert result["fact_count"] == 1
    assert con.execute("SELECT COUNT(*) FROM source_response_receipts").fetchone() == (1,)
    assert con.execute(
        "SELECT event_at,available_at,ingested_at FROM bitemporal_facts"
    ).fetchone() == (
        (NOW - timedelta(minutes=5)).replace(tzinfo=None),
        (NOW + timedelta(seconds=1)).replace(tzinfo=None),
        (NOW + timedelta(seconds=1)).replace(tzinfo=None),
    )
    receipt = _receipt(con)
    with pytest.raises(bitemporal_facts.FactError, match="after ingestion"):
        bitemporal_facts.record_fact(
            con, entity_id="SPY", security_id=None, fact_type="quote.close",
            event_at=NOW, published_at=None, available_at=NOW + timedelta(seconds=2),
            ingested_at=NOW + timedelta(seconds=1), payload={"value": 100},
            source="test", source_version="v1", receipt_sha256=receipt["receipt_sha256"],
        )


def test_repeated_intraday_response_retains_receipt_without_fact_revisions(con):
    bitemporal_facts.init_schema(con)
    quotes = [
        {"ticker": ticker, "event_at": NOW - timedelta(minutes=5),
         "open": 99.0, "high": 101.0, "low": 98.0, "close": 100.0,
         "volume": 10_000}
        for ticker in ("AAA", "SPY")
    ]
    first = bitemporal_facts.record_intraday_quote_batch(
        con, source="test", endpoint="https://example.test/quotes",
        request={"symbols": ["AAA", "SPY"]}, requested_at=NOW,
        received_at=NOW + timedelta(seconds=1), content_type="application/json",
        body=b'{"bars":"same"}', quotes=quotes, interval="5m", source_version="v1",
        license_class="public-test",
    )
    repeated = bitemporal_facts.record_intraday_quote_batch(
        con, source="test", endpoint="https://example.test/quotes",
        request={"symbols": ["AAA", "SPY"]}, requested_at=NOW + timedelta(minutes=1),
        received_at=NOW + timedelta(minutes=1, seconds=1),
        content_type="application/json", body=b'{"bars":"same"}', quotes=quotes,
        interval="5m", source_version="v1", license_class="public-test",
    )

    assert first["fact_count"] == 2 and repeated["fact_count"] == 0
    assert repeated["fact_sha256s"] == first["fact_sha256s"]
    assert con.execute("SELECT COUNT(*) FROM source_response_receipts").fetchone() == (2,)
    assert con.execute("SELECT COUNT(*) FROM bitemporal_facts").fetchone() == (2,)


def test_intraday_batch_allocates_once_and_only_revises_changed_bars(con):
    bitemporal_facts.init_schema(con)

    class TrackingConnection:
        def __init__(self, connection):
            self.connection = connection
            self.executed = []
            self.bulk = []

        def execute(self, statement, parameters=None):
            self.executed.append(statement)
            return (self.connection.execute(statement) if parameters is None
                    else self.connection.execute(statement, parameters))

        def executemany(self, statement, parameters):
            self.bulk.append(statement)
            return self.connection.executemany(statement, parameters)

    tracked = TrackingConnection(con)
    first_quotes = [
        {"ticker": "AAA", "event_at": NOW - timedelta(minutes=minutes),
         "open": 99.0, "high": 101.0, "low": 98.0, "close": 100.0,
         "volume": 10_000}
        for minutes in (10, 5)
    ]
    first = bitemporal_facts.record_intraday_quote_batch(
        tracked, source="test", endpoint="https://example.test/quotes",
        request={"symbol": "AAA"}, requested_at=NOW,
        received_at=NOW + timedelta(seconds=1), content_type="application/json",
        body=b'{"batch":1}', quotes=first_quotes, interval="5m", source_version="v1",
        license_class="public-test",
    )
    second_quotes = [
        first_quotes[0],
        {**first_quotes[1], "high": 102.0, "close": 101.0},
        {**first_quotes[1], "event_at": NOW},
    ]
    second = bitemporal_facts.record_intraday_quote_batch(
        tracked, source="test", endpoint="https://example.test/quotes",
        request={"symbol": "AAA"}, requested_at=NOW + timedelta(minutes=1),
        received_at=NOW + timedelta(minutes=1, seconds=1),
        content_type="application/json", body=b'{"batch":2}', quotes=second_quotes,
        interval="5m", source_version="v1", license_class="public-test",
    )

    assert first["fact_count"] == second["fact_count"] == 2
    assert con.execute(
        "SELECT id,event_at,revision FROM bitemporal_facts ORDER BY id"
    ).fetchall() == [
        (1, (NOW - timedelta(minutes=10)).replace(tzinfo=None), 1),
        (2, (NOW - timedelta(minutes=5)).replace(tzinfo=None), 1),
        (3, (NOW - timedelta(minutes=5)).replace(tzinfo=None), 2),
        (4, NOW.replace(tzinfo=None), 1),
    ]
    assert sum(
        "MAX(id)" in statement and "FROM bitemporal_facts" in statement
        for statement in tracked.executed
    ) == 2
    assert len(tracked.bulk) == 2


def test_intraday_batch_rolls_back_receipt_when_a_fact_is_invalid(con):
    bitemporal_facts.init_schema(con)
    quote = {"ticker": "SPY", "event_at": NOW + timedelta(minutes=5),
             "open": 99.0, "high": 101.0, "low": 98.0, "close": 100.0,
             "volume": 10_000}
    with pytest.raises(bitemporal_facts.FactError, match="times are inconsistent"):
        bitemporal_facts.record_intraday_quote_batch(
            con, source="test", endpoint="https://example.test/quotes",
            request={"symbols": ["SPY"]}, requested_at=NOW,
            received_at=NOW + timedelta(seconds=1), content_type="application/json",
            body=b'{"bars":[]}', quotes=[quote], interval="5m", source_version="v1",
            license_class="public-test",
        )
    assert con.execute("SELECT COUNT(*) FROM source_response_receipts").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM bitemporal_facts").fetchone() == (0,)
