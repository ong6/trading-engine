"""Vendor-neutral source receipt and bitemporal fact contracts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from server import bitemporal_facts

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
