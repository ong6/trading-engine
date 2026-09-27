"""W4 historical-source collectors stay fixture-only until checkpoint acceptance."""
import gzip
import hashlib
import io
import json
import zipfile
from datetime import date, datetime, timezone

import duckdb
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
    parse_cc_news_warc,
    parse_gdelt_manifest,
    parse_gdelt_zip,
    parse_rss,
    parse_wayback_cdx,
    parse_wayback_memento,
    rss_url,
    urllib_stream,
    wayback_cdx_url,
    wayback_memento_tasks,
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
    cdx = wayback_cdx_url(
        "https://example.test/news", start=date(2024, 1, 1), end=date(2024, 2, 1)
    )
    assert all(item in cdx for item in (
        "output=json", "limit=1000", "showResumeKey=true", "collapse=digest"
    ))
    assert wayback_memento_url("20240102153000", "https://example.test/a").endswith(
        "id_/https://example.test/a"
    )
    assert "s=AAPL" in rss_url("yahoo", "aapl")
    assert "after%3A2024-01-01" in rss_url(
        "google", "aapl", start=date(2024, 1, 1), end=date(2024, 2, 1)
    )


def _zip_tsv(fields):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("fixture.csv", "\t".join(fields) + "\n")
    return output.getvalue()


def test_gdelt_manifest_md5_and_real_tsv_zip_parsers():
    event_fields = [""] * 61
    event_fields[0], event_fields[1] = "event-1", "20240102"
    event_fields[26], event_fields[59] = "010", "20240102153045"
    event_fields[60] = "https://example.test/story"
    event_zip = _zip_tsv(event_fields)
    digest = hashlib.md5(event_zip).hexdigest()
    manifest = parse_gdelt_manifest(
        f"{len(event_zip)} {digest} https://example.test/event.zip\n".encode()
    )
    assert manifest == [{
        "size": len(event_zip), "md5": digest,
        "url": "https://example.test/event.zip",
    }]
    event = parse_gdelt_zip(
        "gdelt_events", event_zip, expected_md5=manifest[0]["md5"]
    )[0]
    assert (event["source_id"], event["dateadded"], event["event_code"]) == (
        "event-1", "20240102153045", "010"
    )
    with pytest.raises(SourceError, match="md5"):
        parse_gdelt_zip("gdelt_events", event_zip, expected_md5="0" * 32)

    gkg_fields = [""] * 27
    gkg_fields[0], gkg_fields[1] = "gkg-1", "20240102154500"
    gkg_fields[4], gkg_fields[8], gkg_fields[14] = (
        "https://example.test/gkg", "ECON_GROWTH", "Example Corp"
    )
    gkg = parse_gdelt_zip("gdelt_gkg", _zip_tsv(gkg_fields))[0]
    assert gkg["gkg_date"] == "20240102154500"
    assert gkg["organizations"] == "Example Corp"


def _warc_member(record_id: str, title: str) -> bytes:
    html = (
        '<html><head><meta property="article:published_time" '
        'content="2024-01-02T12:00:00Z"><title>' + title
        + "</title></head><body>Exact archived body.</body></html>"
    ).encode()
    http = b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n" + html
    warc = (
        "WARC/1.0\r\nWARC-Type: response\r\n"
        f"WARC-Record-ID: <urn:uuid:{record_id}>\r\n"
        "WARC-Date: 2024-01-02T12:05:00Z\r\n"
        "WARC-Target-URI: https://example.test/story\r\n"
        "WARC-Payload-Digest: sha1:FIXTURE\r\n"
        f"Content-Length: {len(http)}\r\n\r\n"
    ).encode() + http + b"\r\n\r\n"
    return gzip.compress(warc)


def test_cc_news_reads_whole_concatenated_warc_gzip_members():
    rows = parse_cc_news_warc(
        _warc_member("first", "First headline")
        + _warc_member("second", "Second headline")
    )
    assert [row["headline"] for row in rows] == ["First headline", "Second headline"]
    normalized = normalize_source_record("cc_news", rows[0], retrieved_at_real=NOW)
    assert normalized["status"] == "capture_confirmed"
    assert normalized["body"] == "First headline Exact archived body."


def test_wayback_cdx_resume_and_id_memento_parser():
    parsed = parse_wayback_cdx(json.dumps([
        ["timestamp", "original", "digest"],
        ["20240102120500", "https://example.test/story", "ABC"],
        ["resume-token"],
    ]).encode())
    assert parsed["resume_key"] == "resume-token"
    assert parsed["records"][0]["memento_url"].endswith(
        "20240102120500id_/https://example.test/story"
    )
    task = wayback_memento_tasks(parsed)[0]
    assert task.byte_range is None and task.parser == "wayback_memento"
    assert task.url == parsed["records"][0]["memento_url"]
    row = parse_wayback_memento(
        b'<html><head><title>Archived</title></head><body>Body</body></html>',
        capture_at="20240102120500", memento_uri="memento-1",
        original_url="https://example.test/story", archive_digest="ABC",
    )
    assert normalize_source_record("wayback", row, retrieved_at_real=NOW)[
        "status"
    ] == "capture_confirmed"


@pytest.mark.parametrize("atom", (False, True))
def test_rss_and_atom_are_parsed_with_real_xml(atom):
    if atom:
        payload = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
        <id>atom-1</id><title>Atom headline</title><link href="https://example.test/a"/>
        <published>2024-01-02T12:00:00Z</published></entry></feed>"""
    else:
        payload = b"""<rss version="2.0"><channel><item><guid>rss-1</guid>
        <title>RSS headline</title><link>https://example.test/r</link>
        <pubDate>Tue, 02 Jan 2024 12:00:00 GMT</pubDate></item></channel></rss>"""
    row = parse_rss("google_news_rss", payload, ticker="AAA")[0]
    assert row["headline"] == ("Atom headline" if atom else "RSS headline")
    assert row["published_at"] == "2024-01-02T12:00:00+00:00"


def test_stdlib_transport_streams_to_partial_and_enforces_cap(monkeypatch, tmp_path):
    class Response:
        status = 200

        def __init__(self, payload):
            self.payload = io.BytesIO(payload)
            self.headers = {}

        def read(self, size):
            return self.payload.read(size)

        def getcode(self):
            return self.status

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    calls = []

    def open_url(request, timeout):
        calls.append((request.get_header("User-agent"), timeout))
        return Response(b"four")

    monkeypatch.setattr("farm.replay.sources.urllib.request.urlopen", open_url)
    result = urllib_stream(
        "https://example.test/file", {"User-Agent": "Fixture"}, None,
        partial_dir=tmp_path, max_bytes=3, timeout=7,
    )
    assert result["truncated"] is True and calls == [("Fixture", 7)]
    assert not list(tmp_path.glob("*.partial"))
    complete = urllib_stream(
        "https://example.test/file", {"User-Agent": "Fixture"}, None,
        partial_dir=tmp_path, max_bytes=4, timeout=7,
    )
    assert complete["bytes"] == 4
    assert complete["partial_path"].read_bytes() == b"four"
    complete["partial_path"].unlink()


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
        {
            "status": 429,
            "headers": {"Retry-After": "Sun, 27 Sep 2026 00:00:07 GMT"},
            "body": b"",
        },
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
    with duckdb.connect(str(root / "catalog.duckdb"), read_only=True) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM w4_evidence_records WHERE record_type='source_record'"
        ).fetchone() == (1,)
        assert con.execute(
            "SELECT COUNT(*) FROM w4_evidence_records WHERE record_type='ingestion_cursor'"
        ).fetchone() == (1,)


def test_fetch_loop_stops_before_advancing_an_oversize_shard(tmp_path):
    root = (tmp_path / "research").resolve()
    root.mkdir()
    live = (tmp_path / "live.duckdb").resolve()
    live.touch()
    task = FetchTask("cc_news", "shard", "https://data.commoncrawl.org/a", "next")
    result = collect_shards(
        [task], catalog_path=root / "catalog.duckdb", research_root=root,
        live_db_path=live,
        transport=lambda *_args: {"status": 206, "headers": {}, "body": b"four"},
        parse_rows=lambda _source, _body: [], user_agent="Fixture contact",
        now=lambda: NOW, pause=lambda _seconds: None, max_bytes=3,
    )
    assert result["status"] == "stopped_limit" and result["receipts"] == []


def test_cc_news_rejects_byte_range_tasks(tmp_path):
    root = (tmp_path / "research").resolve()
    root.mkdir()
    live = (tmp_path / "live.duckdb").resolve()
    live.touch()
    task = FetchTask(
        "cc_news", "shard", "https://data.commoncrawl.org/a", "next", (0, 3)
    )
    with pytest.raises(SourceError, match="byte_ranges_forbidden"):
        collect_shards(
            [task], catalog_path=root / "catalog.duckdb", research_root=root,
            live_db_path=live, transport=lambda *_args: pytest.fail("transport called"),
            parse_rows=lambda _source, _body: [], user_agent="Fixture contact",
            now=lambda: NOW, pause=lambda _seconds: None,
        )


def test_collector_uses_real_warc_parser_and_file_level_cursor(tmp_path):
    root = (tmp_path / "research").resolve()
    root.mkdir()
    live = (tmp_path / "live.duckdb").resolve()
    live.touch()
    task = FetchTask(
        "cc_news", "fixture.warc.gz", "https://data.commoncrawl.org/fixture.warc.gz",
        "fixture.warc.gz",
    )
    result = collect_shards(
        [task], catalog_path=root / "catalog.duckdb", research_root=root,
        live_db_path=live,
        transport=lambda *_args: {
            "status": 200, "headers": {}, "body": _warc_member("fixture", "Headline")
        },
        user_agent="Fixture contact", now=lambda: NOW, pause=lambda _seconds: None,
    )
    assert result["records"][0]["headline"] == "Headline"
    assert result["records"][0]["status"] == "capture_confirmed"
    skipped = collect_shards(
        [task], catalog_path=root / "catalog.duckdb", research_root=root,
        live_db_path=live, transport=lambda *_args: pytest.fail("resumed file refetched"),
        user_agent="Fixture contact", now=lambda: NOW, pause=lambda _seconds: None,
    )
    assert skipped["records"] == []
