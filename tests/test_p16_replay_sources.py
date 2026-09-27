"""W4 historical-source collectors stay fixture-only until checkpoint acceptance."""
import json
from datetime import date, datetime, timezone

import pytest

from farm.replay.sources import (
    FetchTask,
    SourceError,
    cc_news_paths_url,
    collect_edgar,
    collect_shards,
    edgar_acceptance_at,
    gdelt_manifest_url,
    gdelt_shard_urls,
    normalize_source_record,
    rss_url,
    wayback_cdx_url,
    wayback_memento_url,
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


def test_registered_archive_url_builders_are_exact():
    assert gdelt_manifest_url() == "https://data.gdeltproject.org/gdeltv2/lastupdate.txt"
    assert gdelt_manifest_url(historical=True).endswith("/masterfilelist.txt")
    assert gdelt_shard_urls("20240102153000") == (
        "https://data.gdeltproject.org/gdeltv2/20240102153000.export.CSV.zip",
        "https://data.gdeltproject.org/gdeltv2/20240102153000.gkg.csv.zip",
    )
    assert cc_news_paths_url(2024, 1).endswith("/CC-NEWS/2024/01/warc.paths.gz")
    assert "output=json" in wayback_cdx_url(
        "https://example.test/news", start=date(2024, 1, 1), end=date(2024, 2, 1)
    )
    assert wayback_memento_url("20240102153000", "https://example.test/a").endswith(
        "id_/https://example.test/a"
    )
    assert "s=AAPL" in rss_url("yahoo", "aapl")
    assert "after%3A2024-01-01" in rss_url(
        "google", "aapl", start=date(2024, 1, 1), end=date(2024, 2, 1)
    )


def test_fetch_loop_retries_stores_resumes_and_quarantines_fixture_rows(tmp_path):
    root = (tmp_path / "research").resolve()
    root.mkdir()
    live = (tmp_path / "live.duckdb").resolve()
    live.touch()
    body = json.dumps([
        {"source_id": "ok", "headline": "Fixture", "dateadded": "20240102153045",
         "event_at": "2024-01-02T15:00:00Z", "precision": "second",
         "confidence": "archive", "source_timezone": "UTC"},
        {"source_id": "bad", "headline": "Bad"},
    ]).encode()
    responses = [
        {"status": 429, "headers": {"Retry-After": "7"}, "body": b""},
        {"status": 503, "headers": {}, "body": b""},
        {"status": 200, "headers": {}, "body": body},
    ]
    calls, pauses = [], []

    def transport(url, headers, byte_range):
        calls.append((url, dict(headers), byte_range))
        return responses.pop(0)

    task = FetchTask(
        "gdelt_events", "20240102153000", gdelt_shard_urls("20240102153000")[0],
        "done",
    )
    arguments = dict(
        catalog_path=root / "catalog.duckdb", research_root=root, live_db_path=live,
        transport=transport, parse_rows=lambda _source, payload: json.loads(payload),
        user_agent="Trading research contact@example.test", now=lambda: NOW,
        pause=pauses.append,
    )
    first = collect_shards([task], **arguments)
    second = collect_shards([task], **arguments)
    assert first["status"] == second["status"] == "completed"
    assert len(first["records"]) == 1 and len(first["quarantined"]) == 1
    assert first["records"][0]["event_at"] == "2024-01-02T15:00:00Z"
    assert len(first["receipts"]) == 1 and second["receipts"] == []
    assert len(calls) == 3 and all(call[1]["User-Agent"] for call in calls)
    assert pauses == [7, 30, 1.0]
    assert not list(root.rglob("*.partial"))


def test_fetch_loop_stops_before_advancing_an_oversize_shard(tmp_path):
    root = (tmp_path / "research").resolve()
    root.mkdir()
    live = (tmp_path / "live.duckdb").resolve()
    live.touch()
    task = FetchTask("cc_news", "shard", "https://data.commoncrawl.org/a", "next", (0, 3))
    result = collect_shards(
        [task], catalog_path=root / "catalog.duckdb", research_root=root,
        live_db_path=live,
        transport=lambda *_args: {"status": 206, "headers": {}, "body": b"four"},
        parse_rows=lambda _source, _body: [], user_agent="Fixture contact",
        now=lambda: NOW, pause=lambda _seconds: None, max_bytes=3,
    )
    assert result["status"] == "stopped_limit" and result["receipts"] == []
