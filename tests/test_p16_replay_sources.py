"""W4 historical-source collectors stay fixture-only until checkpoint acceptance."""
from datetime import datetime, timezone

import pytest

from farm.replay.sources import (
    SourceError,
    collect_edgar,
    edgar_acceptance_at,
    normalize_source_record,
)

NOW = datetime(2026, 9, 27, tzinfo=timezone.utc)


def test_edgar_without_contact_is_disabled_before_transport():
    calls = []
    result = collect_edgar(
        lambda headers: calls.append(headers), retrieved_at_real=NOW, environ={}
    )
    assert result == {
        "status": "unconfigured",
        "reason": "sec_contact_missing",
        "records": [],
    }
    assert calls == []


def test_gdelt_clocks_use_the_registered_fields_not_event_date():
    event = normalize_source_record(
        "gdelt_events",
        {"source_id": "event-1", "headline": "Fixture", "dateadded": "20240102153045"},
        retrieved_at_real=NOW,
    )
    gkg = normalize_source_record(
        "gdelt_gkg",
        {"source_id": "gkg-1", "headline": "Fixture", "gkg_date": "20240102154500"},
        retrieved_at_real=NOW,
    )
    assert event["available_at_replay"].isoformat() == "2024-01-02T15:30:45+00:00"
    assert gkg["available_at_replay"].isoformat() == "2024-01-02T15:45:00+00:00"
    with pytest.raises(SourceError, match="dateadded"):
        normalize_source_record(
            "gdelt_events", {"source_id": "bad"}, retrieved_at_real=NOW
        )


def test_capture_and_publish_only_body_rules_are_separate():
    weak = normalize_source_record(
        "pr_newswire",
        {
            "source_id": "wire-1",
            "published_at": "2024-01-02T12:00:00Z",
            "headline": "Fixture",
            "body": "present page is not historical evidence",
        },
        retrieved_at_real=NOW,
    )
    assert weak["available_at_replay"].isoformat() == "2024-01-02T12:15:00+00:00"
    assert weak["body"] is None and weak["status"] == "publish_only_weak"

    captured = normalize_source_record(
        "cc_news",
        {
            "source_id": "cc-1",
            "warc_date": "2024-01-02T12:10:00Z",
            "published_at": "2024-01-02T12:20:00Z",
            "warc_record_id": "<urn:uuid:fixture>",
            "archive_payload_digest": "sha1:FIXTURE",
            "extractor_version": "html-v1",
            "headline": "Fixture",
            "body": "captured bytes",
        },
        retrieved_at_real=NOW,
    )
    assert captured["available_at_replay"].isoformat() == "2024-01-02T12:20:00+00:00"
    assert captured["body"] == "captured bytes"
    assert len(captured["capture_sha256"]) == 64


def test_fnspid_date_is_available_at_next_exchange_open():
    row = normalize_source_record(
        "fnspid",
        {"source_id": "f-1", "event_date": "2024-03-08", "headline": "Fixture"},
        retrieved_at_real=NOW,
    )
    assert row["available_at_replay"].isoformat() == "2024-03-11T13:30:00+00:00"


def test_edgar_acceptance_uses_new_york_clock_and_rejects_dst_ambiguity():
    assert edgar_acceptance_at("20240308155900").isoformat() == "2024-03-08T20:59:00+00:00"
    with pytest.raises(SourceError, match="ambiguous"):
        edgar_acceptance_at("20241103013000")


def test_configured_edgar_normalizes_exact_accession_capture():
    seen = []

    def fetch(headers):
        seen.append(headers)
        return [{
            "source_id": "filing-1",
            "accession": "0000000000-24-000001",
            "accepted_at": "20240308155900",
            "archive_payload_digest": "sha256:fixture",
            "extractor_version": "edgar-html-v1",
            "headline": "Fixture 8-K",
            "body": "exact filing text",
        }]

    result = collect_edgar(
        fetch,
        retrieved_at_real=NOW,
        environ={"TRADING_ENGINE_SEC_USER_AGENT": "Research contact@example.com"},
    )
    assert seen == [{"User-Agent": "Research contact@example.com"}]
    assert result["status"] == "completed"
    assert result["records"][0]["status"] == "capture_confirmed"
