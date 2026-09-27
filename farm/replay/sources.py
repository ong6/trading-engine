"""Bounded stdlib collectors and source normalization for W4 replay evidence."""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import os
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib.parse import quote, urlencode, urlsplit
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from engine.lib import db
from engine.lib.provenance import canonical_sha256
from farm.replay.corpus import (
    capture_sha256,
    latest_completed_cursor,
    put_content_object,
    record_task_attempt,
)
from farm.replay.store import append_exact, checked_store_path, open_store
from sim import nyse

UTC = timezone.utc
ET = ZoneInfo("America/New_York")
SEC_CONTACT_ENV = "TRADING_ENGINE_SEC_USER_AGENT"

SOURCE_LIMITS = {
    "gdelt_events": {"workers": 1, "minimum_interval_seconds": 1},
    "gdelt_gkg": {"workers": 1, "minimum_interval_seconds": 1},
    "cc_news": {"workers": 1, "minimum_interval_seconds": 1},
    "pr_newswire": {"workers": 1, "minimum_interval_seconds": 2},
    "google_news_rss": {"workers": 1, "minimum_interval_seconds": 2},
    "yahoo_rss": {"workers": 1, "minimum_interval_seconds": 600},
    "wayback": {"workers": 1, "minimum_interval_seconds": 2},
    "edgar": {"workers": 1, "minimum_interval_seconds": 0.5},
    "issuer_ir": {"workers": 1, "minimum_interval_seconds": 2},
}
RETRY_DELAYS = (5, 30, 120)
DEFAULT_MAX_SECONDS = 30 * 60
DEFAULT_MAX_BYTES = 2 * 1024**3
DEFAULT_TIMEOUT_SECONDS = 30.0
STREAM_CHUNK_BYTES = 64 * 1024
_HOST_LOCKS: dict[str, threading.Lock] = {}


class SourceError(ValueError):
    """A historical source row cannot meet its registered availability rule."""


@dataclass(frozen=True)
class FetchTask:
    source: str
    shard_id: str
    url: str
    cursor_after: str
    byte_range: tuple[int, int] | None = None
    expected_md5: str | None = None
    parser: str | None = None
    parser_options: Mapping[str, str] | None = None


def _instant(value: object, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise SourceError(f"invalid_{field}") from exc
    if parsed.tzinfo is None:
        raise SourceError(f"naive_{field}")
    return parsed.astimezone(UTC)


def _compact_utc(value: object, field: str) -> datetime:
    try:
        return datetime.strptime(str(value), "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError as exc:
        raise SourceError(f"invalid_{field}") from exc


def edgar_acceptance_at(value: object) -> datetime:
    """Parse an EDGAR acceptance clock and reject ambiguous local instants."""
    if isinstance(value, str) and value.isdigit() and len(value) == 14:
        naive = datetime.strptime(value, "%Y%m%d%H%M%S")
        first, second = naive.replace(tzinfo=ET, fold=0), naive.replace(tzinfo=ET, fold=1)
        if first.utcoffset() != second.utcoffset():
            raise SourceError("ambiguous_edgar_acceptance")
        return first.astimezone(UTC)
    return _instant(value, "edgar_acceptance")


def fnspid_available_at(value: object) -> datetime:
    try:
        day = date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise SourceError("invalid_fnspid_date") from exc
    return datetime.combine(nyse.next_session(day), time(9, 30), ET).astimezone(UTC)


def edgar_readiness(environ: Mapping[str, str] | None = None) -> dict:
    contact = (environ or os.environ).get(SEC_CONTACT_ENV, "").strip()
    if not contact:
        return {"status": "unconfigured", "reason": "sec_contact_missing"}
    return {
        "status": "ready",
        "headers": {"User-Agent": contact},
        "maximum_requests_per_second": 2,
    }


def _captured(row: Mapping, *, captured_at: datetime, identity_field: str) -> dict:
    body = row.get("body")
    if not isinstance(body, str) or not body or not row.get(identity_field):
        raise SourceError("capture_identity_incomplete")
    archive_digest = str(row.get("archive_payload_digest", ""))
    extractor = str(row.get("extractor_version", ""))
    if not archive_digest or not extractor:
        raise SourceError("capture_identity_incomplete")
    return {
        "body": body,
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "capture_sha256": capture_sha256(archive_digest, extractor),
        "capture_at": captured_at,
    }


def normalize_source_record(
    source: str, row: Mapping, *, retrieved_at_real: datetime
) -> dict:
    """Apply a source-specific historical availability rule to one exact payload."""
    retrieved = _instant(retrieved_at_real, "retrieved_at_real")
    result = {
        "source": source,
        "source_id": str(row.get("source_id", "")),
        "headline": str(row.get("headline", "")).strip(),
        "body": None,
        "retrieved_at_real": retrieved,
        "status": "headline_only",
        "event_at": row.get("event_at"),
        "published_at": row.get("published_at"),
        "precision": str(row.get("precision", "unknown")),
        "confidence": str(row.get("confidence", "unknown")),
        "source_timezone": str(row.get("source_timezone", "unknown")),
        "published_after_capture": False,
    }
    if not result["source_id"]:
        raise SourceError("source_id_missing")
    if source == "gdelt_events":
        available = _compact_utc(row.get("dateadded"), "gdelt_dateadded")
        rule = "gdelt_events_dateadded_v1"
    elif source == "gdelt_gkg":
        available = _compact_utc(row.get("gkg_date"), "gdelt_gkg_date")
        rule = "gdelt_gkg_update_v1"
    elif source == "fnspid":
        available = fnspid_available_at(row.get("event_date"))
        rule = "fnspid_next_session_open_v1"
    elif source == "edgar":
        available = edgar_acceptance_at(row.get("accepted_at"))
        result.update(_captured(row, captured_at=available, identity_field="accession"))
        result["status"] = "capture_confirmed"
        rule = "edgar_acceptance_v1"
    elif source == "cc_news":
        captured = _instant(row.get("warc_date"), "warc_date")
        published = _instant(row["published_at"], "published_at") if row.get(
            "published_at"
        ) else captured
        available = max(captured, published)
        result.update(_captured(row, captured_at=captured, identity_field="warc_record_id"))
        result["status"] = "capture_confirmed"
        rule = "cc_news_warc_v1"
    elif source == "wayback":
        captured = _instant(row.get("capture_at"), "capture_at")
        published = _instant(row["published_at"], "published_at") if row.get(
            "published_at"
        ) else captured
        available = max(captured, published)
        result.update(_captured(row, captured_at=captured, identity_field="memento_uri"))
        result["status"] = "capture_confirmed"
        rule = "wayback_memento_v1"
    elif source in {"pr_newswire", "google_news_rss", "yahoo_rss", "issuer_ir"}:
        published = _instant(row.get("published_at"), "published_at")
        if row.get("capture_at"):
            captured = _instant(row["capture_at"], "capture_at")
            available = max(published, captured)
            result.update(_captured(row, captured_at=captured, identity_field="capture_id"))
            result["status"] = "capture_confirmed"
            rule = "wire_capture_v1"
        else:
            available = published + timedelta(minutes=15)
            result["status"] = "publish_only_weak"
            rule = "wire_headline_publish_plus_15m_v1"
    else:
        raise SourceError("source_not_registered")
    result.update(
        available_at_replay=available,
        availability_rule=rule,
        historical_backfill=True,
    )
    if result["event_at"] is None:
        result["event_at"] = available
    if result["published_at"] is not None:
        result["published_after_capture"] = (
            _instant(result["published_at"], "published_at")
            > result.get("capture_at", available)
        )
    result["evidence_id"] = canonical_sha256({
        "source": source, "source_id": result["source_id"],
        "available_at_replay": available.isoformat(),
        "availability_rule": rule, "headline": result["headline"],
        "body_sha256": result.get("body_sha256"),
    })
    return result


def collect_edgar(
    fetch: Callable[[Mapping[str, str]], Sequence[Mapping]],
    *,
    retrieved_at_real: datetime,
    environ: Mapping[str, str] | None = None,
) -> dict:
    """Return unconfigured without invoking transport when SEC contact is absent."""
    readiness = edgar_readiness(environ)
    if readiness["status"] != "ready":
        return {**readiness, "records": []}
    records = [
        normalize_source_record("edgar", row, retrieved_at_real=retrieved_at_real)
        for row in fetch(readiness["headers"])
    ]
    return {"status": "completed", "records": records}


def gdelt_manifest_url(*, historical: bool = False) -> str:
    leaf = "masterfilelist.txt" if historical else "lastupdate.txt"
    return f"https://data.gdeltproject.org/gdeltv2/{leaf}"


def gdelt_shard_urls(timestamp: str) -> tuple[str, str]:
    if len(timestamp) != 14 or not timestamp.isdigit():
        raise SourceError("invalid_gdelt_shard")
    base = "https://data.gdeltproject.org/gdeltv2"
    return (
        f"{base}/{timestamp}.export.CSV.zip",
        f"{base}/{timestamp}.gkg.csv.zip",
    )


def cc_news_paths_url(year: int, month: int) -> str:
    if not 2016 <= year <= 2100 or month not in range(1, 13):
        raise SourceError("invalid_cc_news_month")
    return f"https://data.commoncrawl.org/crawl-data/CC-NEWS/{year}/{month:02d}/warc.paths.gz"


def wayback_cdx_url(
    target_url: str, *, start: date, end: date, limit: int = 1_000,
    resume_key: str | None = None,
) -> str:
    if (
        not target_url.startswith(("http://", "https://"))
        or end < start or not 1 <= limit <= 10_000
    ):
        raise SourceError("invalid_wayback_window")
    parameters = {
        "url": target_url, "from": start.strftime("%Y%m%d"),
        "to": end.strftime("%Y%m%d"), "output": "json",
        "filter": "statuscode:200", "fl": "timestamp,original,digest",
        "collapse": "digest", "limit": str(limit), "showResumeKey": "true",
    }
    if resume_key:
        parameters["resumeKey"] = resume_key
    query = urlencode(parameters)
    return f"https://web.archive.org/cdx/search/cdx?{query}"


def wayback_memento_url(timestamp: str, original_url: str) -> str:
    if len(timestamp) != 14 or not timestamp.isdigit():
        raise SourceError("invalid_wayback_capture")
    return f"https://web.archive.org/web/{timestamp}id_/{quote(original_url, safe=':/?=&%')}"


def rss_url(provider: str, ticker: str, *, start: date | None = None, end: date | None = None) -> str:
    symbol = ticker.strip().upper()
    if not symbol or not symbol.replace(".", "").replace("-", "").isalnum():
        raise SourceError("invalid_rss_ticker")
    if provider == "yahoo":
        return "https://feeds.finance.yahoo.com/rss/2.0/headline?" + urlencode(
            {"s": symbol, "region": "US", "lang": "en-US"}
        )
    if provider == "google" and start is not None and end is not None and start < end:
        query = f"{symbol} after:{start.isoformat()} before:{end.isoformat()}"
        return "https://news.google.com/rss/search?" + urlencode(
            {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
        )
    raise SourceError("invalid_rss_provider_or_window")


def parse_gdelt_manifest(payload: bytes) -> list[dict]:
    """Parse the GDELT size/md5/url manifest without guessing missing fields."""
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceError("invalid_gdelt_manifest_encoding") from exc
    entries = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split(maxsplit=2)
        if len(parts) != 3:
            raise SourceError("invalid_gdelt_manifest_row")
        size_text, md5, url = parts
        try:
            size = int(size_text)
        except ValueError as exc:
            raise SourceError("invalid_gdelt_manifest_size") from exc
        if size < 0 or len(md5) != 32 or any(char not in "0123456789abcdefABCDEF" for char in md5):
            raise SourceError("invalid_gdelt_manifest_identity")
        if not url.startswith(("http://", "https://")):
            raise SourceError("invalid_gdelt_manifest_url")
        entries.append({"size": size, "md5": md5.lower(), "url": url})
    return entries


def _payload_bytes(payload: bytes | Path) -> bytes:
    return payload if isinstance(payload, bytes) else payload.read_bytes()


def parse_gdelt_zip(
    source: str, payload: bytes | Path, *, expected_md5: str | None = None
) -> list[dict]:
    """Unpack and map the fixed-width GDELT Events 2.0 or GKG 2.1 TSV."""
    if expected_md5 is not None:
        digest = hashlib.md5()
        if isinstance(payload, bytes):
            digest.update(payload)
        else:
            with payload.open("rb") as source_handle:
                for chunk in iter(lambda: source_handle.read(STREAM_CHUNK_BYTES), b""):
                    digest.update(chunk)
        if digest.hexdigest() != expected_md5.lower():
            raise SourceError("gdelt_md5_mismatch")
    if source not in {"gdelt_events", "gdelt_gkg"}:
        raise SourceError("invalid_gdelt_source")
    width = 61 if source == "gdelt_events" else 27
    rows = []
    try:
        archive_source = io.BytesIO(payload) if isinstance(payload, bytes) else payload
        with zipfile.ZipFile(archive_source) as archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
            if len(members) != 1:
                raise SourceError("invalid_gdelt_zip_members")
            with archive.open(members[0]) as handle:
                reader = csv.reader(
                    io.TextIOWrapper(handle, encoding="utf-8", errors="replace", newline=""),
                    delimiter="\t",
                )
                for fields in reader:
                    if len(fields) != width:
                        raise SourceError(f"invalid_gdelt_{source}_column_count")
                    if source == "gdelt_events":
                        event_day = datetime.strptime(fields[1], "%Y%m%d").replace(tzinfo=UTC)
                        rows.append({
                            "source_id": fields[0], "headline": "",
                            "dateadded": fields[59], "event_at": event_day.isoformat(),
                            "published_at": None, "precision": "day",
                            "confidence": "archive_metadata", "source_timezone": "UTC",
                            "source_url": fields[60], "event_code": fields[26],
                        })
                    else:
                        updated = _compact_utc(fields[1], "gdelt_gkg_date")
                        rows.append({
                            "source_id": fields[0], "headline": "", "gkg_date": fields[1],
                            "event_at": updated.isoformat(), "published_at": None,
                            "precision": "second", "confidence": "archive_metadata",
                            "source_timezone": "UTC", "source_url": fields[4],
                            "organizations": fields[14], "themes": fields[8],
                        })
    except (zipfile.BadZipFile, UnicodeError) as exc:
        raise SourceError("invalid_gdelt_zip") from exc
    return rows


class _ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: list[str] = []
        self.text: list[str] = []
        self.published_at: str | None = None
        self._in_title = False
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        values = {str(key).lower(): value for key, value in attrs}
        if tag.lower() == "title":
            self._in_title = True
        if tag.lower() in {"script", "style", "noscript"}:
            self._ignored += 1
        if tag.lower() == "meta":
            name = str(values.get("property") or values.get("name") or "").lower()
            if name in {
                "article:published_time", "date", "datepublished", "pubdate",
                "publish-date", "sailthru.date",
            } and values.get("content"):
                self.published_at = str(values["content"])

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False
        if tag.lower() in {"script", "style", "noscript"} and self._ignored:
            self._ignored -= 1

    def handle_data(self, data: str) -> None:
        clean = " ".join(data.split())
        if clean and self._in_title:
            self.title.append(clean)
        if clean and not self._ignored:
            self.text.append(clean)


def _article_fields(payload: bytes, content_type: str = "") -> tuple[str, str, str | None]:
    charset = "utf-8"
    for item in content_type.split(";")[1:]:
        if item.strip().lower().startswith("charset="):
            charset = item.split("=", 1)[1].strip(" \"'")
    try:
        text = payload.decode(charset, errors="replace")
    except LookupError:
        text = payload.decode("utf-8", errors="replace")
    parser = _ArticleParser()
    parser.feed(text)
    return " ".join(parser.title), " ".join(parser.text), parser.published_at


def _header_block(handle) -> tuple[str, dict[str, str]] | None:
    first = handle.readline()
    while first in {b"\r\n", b"\n"}:
        first = handle.readline()
    if not first:
        return None
    start = first.decode("ascii", errors="replace").strip()
    headers = {}
    while True:
        line = handle.readline()
        if not line or line in {b"\r\n", b"\n"}:
            break
        key, separator, value = line.decode("utf-8", errors="replace").partition(":")
        if not separator:
            raise SourceError("invalid_warc_header")
        headers[key.strip().lower()] = value.strip()
    return start, headers


def parse_cc_news_warc(payload: bytes | Path) -> list[dict]:
    """Stream response records from a whole gzip WARC using only stdlib readers."""
    raw_handle = io.BytesIO(payload) if isinstance(payload, bytes) else payload.open("rb")
    rows = []
    try:
        with raw_handle, gzip.GzipFile(fileobj=raw_handle, mode="rb") as handle:
            while True:
                parsed = _header_block(handle)
                if parsed is None:
                    break
                start, headers = parsed
                if not start.startswith("WARC/"):
                    raise SourceError("invalid_warc_version")
                try:
                    length = int(headers["content-length"])
                except (KeyError, ValueError) as exc:
                    raise SourceError("invalid_warc_content_length") from exc
                content = handle.read(length)
                if len(content) != length:
                    raise SourceError("truncated_warc_record")
                if headers.get("warc-type") != "response":
                    continue
                http = io.BytesIO(content)
                response_headers = _header_block(http)
                if response_headers is None or not response_headers[0].startswith("HTTP/"):
                    raise SourceError("invalid_warc_http_response")
                body = http.read()
                title, text, published = _article_fields(
                    body, response_headers[1].get("content-type", "")
                )
                record_id = headers.get("warc-record-id")
                if not record_id:
                    raise SourceError("warc_record_id_missing")
                rows.append({
                    "source_id": record_id, "warc_record_id": record_id,
                    "warc_date": headers.get("warc-date"),
                    "archive_payload_digest": headers.get("warc-payload-digest")
                    or f"sha256:{hashlib.sha256(body).hexdigest()}",
                    "extractor_version": "stdlib-html-v1", "headline": title,
                    "body": text, "published_at": published, "event_at": published,
                    "precision": "second", "confidence": "archive_capture",
                    "source_timezone": "UTC", "source_url": headers.get("warc-target-uri"),
                })
    except (OSError, EOFError) as exc:
        raise SourceError("invalid_cc_news_gzip") from exc
    return rows


def parse_wayback_cdx(payload: bytes) -> dict:
    """Parse a CDX JSON page and its optional resume key."""
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceError("invalid_wayback_cdx_json") from exc
    resume_key = None
    if isinstance(decoded, dict):
        rows = decoded.get("rows")
        resume_key = decoded.get("resumeKey")
    else:
        rows = decoded
    if not isinstance(rows, list) or not rows:
        raise SourceError("invalid_wayback_cdx_shape")
    header = rows[0]
    if not isinstance(header, list) or not {"timestamp", "original", "digest"} <= set(header):
        raise SourceError("invalid_wayback_cdx_header")
    records = []
    for values in rows[1:]:
        if isinstance(values, list) and len(values) == 1:
            resume_key = values[0]
            continue
        if not isinstance(values, list) or len(values) != len(header):
            raise SourceError("invalid_wayback_cdx_row")
        row = dict(zip(header, values, strict=True))
        timestamp = str(row["timestamp"])
        _compact_utc(timestamp, "wayback_capture")
        records.append({
            "timestamp": timestamp, "original": str(row["original"]),
            "digest": str(row["digest"]),
            "memento_url": wayback_memento_url(timestamp, str(row["original"])),
        })
    return {"records": records, "resume_key": resume_key}


def parse_wayback_memento(
    payload: bytes, *, capture_at: str, memento_uri: str,
    original_url: str, archive_digest: str,
) -> dict:
    """Map exact ``id_`` memento bytes to a capture-confirmed source row."""
    title, text, published = _article_fields(payload, "text/html; charset=utf-8")
    return {
        "source_id": memento_uri, "memento_uri": memento_uri,
        "capture_at": _compact_utc(capture_at, "wayback_capture").isoformat(),
        "archive_payload_digest": archive_digest,
        "extractor_version": "stdlib-html-v1", "headline": title, "body": text,
        "published_at": published, "event_at": published,
        "precision": "second", "confidence": "archive_capture",
        "source_timezone": "UTC", "source_url": original_url,
    }


def wayback_memento_tasks(cdx_page: Mapping) -> list[FetchTask]:
    """Turn one parsed CDX page into exact ``id_`` memento fetch tasks."""
    rows = cdx_page.get("records")
    if not isinstance(rows, list):
        raise SourceError("invalid_wayback_cdx_records")
    tasks = []
    for row in rows:
        timestamp = str(row.get("timestamp", ""))
        original = str(row.get("original", ""))
        digest = str(row.get("digest", ""))
        url = str(row.get("memento_url", ""))
        if not timestamp or not original or not digest or not url:
            raise SourceError("invalid_wayback_capture_record")
        tasks.append(FetchTask(
            source="wayback", shard_id=f"{timestamp}:{digest}", url=url,
            cursor_after=timestamp, parser="wayback_memento",
            parser_options={
                "capture_at": timestamp, "memento_uri": url,
                "original_url": original, "archive_digest": digest,
            },
        ))
    return tasks


def _published_at(value: str) -> datetime:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise SourceError("invalid_rss_published_at") from exc
    if parsed.tzinfo is None:
        raise SourceError("naive_rss_published_at")
    return parsed.astimezone(UTC)


def parse_rss(source: str, payload: bytes, *, ticker: str | None = None) -> list[dict]:
    """Parse RSS 2.0 and Atom feeds into the common publish-only row shape."""
    if source not in {"pr_newswire", "google_news_rss", "yahoo_rss", "issuer_ir"}:
        raise SourceError("invalid_rss_source")
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise SourceError("invalid_rss_xml") from exc

    def local(element) -> str:
        return element.tag.rsplit("}", 1)[-1].lower()

    entries = [element for element in root.iter() if local(element) in {"item", "entry"}]
    rows = []
    for index, entry in enumerate(entries):
        values: dict[str, str] = {}
        for child in entry:
            name = local(child)
            if name == "link" and child.attrib.get("href"):
                values[name] = child.attrib["href"]
            elif child.text and name in {"title", "link", "guid", "id", "pubdate", "published", "updated"}:
                values[name] = child.text.strip()
        published_text = values.get("pubdate") or values.get("published") or values.get("updated")
        if not published_text:
            raise SourceError("rss_published_at_missing")
        published = _published_at(published_text)
        canonical_source_id = values.get("guid") or values.get("id") or values.get("link")
        if not canonical_source_id:
            canonical_source_id = hashlib.sha256(
                f"{values.get('title', '')}:{published.isoformat()}:{index}".encode()
            ).hexdigest()
        rows.append({
            "source_id": canonical_source_id, "headline": values.get("title", ""),
            "published_at": published.isoformat(), "event_at": published.isoformat(),
            "precision": "second", "confidence": "feed_publish_time",
            "source_timezone": "UTC", "source_url": values.get("link"),
            "ticker": ticker,
        })
    return rows


def _retry_after(headers: Mapping, fallback: int, *, observed_at: datetime) -> float:
    value = headers.get("Retry-After") or headers.get("retry-after")
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        if value is None:
            return float(fallback)
        try:
            retry_at = parsedate_to_datetime(str(value)).astimezone(UTC)
        except (TypeError, ValueError, OverflowError):
            return float(fallback)
        seconds = math.ceil((retry_at - _instant(observed_at, "retry_clock")).total_seconds())
    return float(max(fallback, seconds, 0))


def _receipt_suffix(task: FetchTask) -> str:
    if task.source in {"gdelt_events", "gdelt_gkg"}:
        return ".zip"
    if task.source == "cc_news":
        return ".warc.gz"
    if task.source in {"pr_newswire", "google_news_rss", "yahoo_rss", "issuer_ir"}:
        return ".xml"
    if task.parser == "wayback_cdx":
        return ".json"
    return ".raw"


def _install_partial(root: Path, source: str, partial: Path, digest: str, size: int,
                     suffix: str) -> dict:
    destination = root / "receipts" / source / digest[:2] / f"{digest}{suffix}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.stat().st_size != size:
            raise SourceError("content_object_hash_conflict")
        partial.unlink()
    else:
        os.replace(partial, destination)
    return {"sha256": digest, "bytes": size, "path": str(destination)}


def urllib_stream(
    url: str,
    headers: Mapping[str, str],
    byte_range: tuple[int, int] | None,
    *,
    partial_dir: Path,
    max_bytes: int,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    """Download one response to a partial file while enforcing the byte bound."""
    request_headers = dict(headers)
    if byte_range is not None:
        request_headers["Range"] = f"bytes={byte_range[0]}-{byte_range[1]}"
    request = urllib.request.Request(url, headers=request_headers)
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "headers": dict(exc.headers.items()), "body": b""}
    except urllib.error.URLError as exc:
        return {"status": 0, "headers": {}, "body": b"", "reason": str(exc.reason)}
    partial_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".download.", suffix=".partial", dir=partial_dir)
    path = Path(name)
    digest, size, complete = hashlib.sha256(), 0, False
    try:
        with response, os.fdopen(fd, "wb") as output:
            response_headers = dict(response.headers.items())
            declared = response.headers.get("Content-Length")
            if declared is not None:
                try:
                    if int(declared) > max_bytes:
                        return {
                            "status": int(getattr(response, "status", response.getcode())),
                            "headers": response_headers, "truncated": True,
                        }
                except ValueError:
                    pass
            while True:
                chunk = response.read(STREAM_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    return {
                        "status": int(getattr(response, "status", response.getcode())),
                        "headers": response_headers, "truncated": True,
                    }
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        complete = True
        return {
            "status": int(getattr(response, "status", response.getcode())),
            "headers": response_headers, "partial_path": path,
            "bytes": size, "sha256": digest.hexdigest(),
        }
    finally:
        if path.exists() and not complete:
            path.unlink()


def _default_rows(task: FetchTask, payload: bytes | Path) -> Sequence[Mapping]:
    parser = task.parser or task.source
    if parser in {"gdelt_events", "gdelt_gkg"}:
        return parse_gdelt_zip(parser, payload, expected_md5=task.expected_md5)
    if parser == "cc_news":
        return parse_cc_news_warc(payload)
    if parser in {"pr_newswire", "google_news_rss", "yahoo_rss", "issuer_ir"}:
        return parse_rss(parser, _payload_bytes(payload))
    if parser == "wayback_memento" and task.parser_options is not None:
        return [parse_wayback_memento(_payload_bytes(payload), **task.parser_options)]
    raise SourceError("source_parser_missing")


def _jsonable(value):
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def collect_shards(
    tasks: Sequence[FetchTask],
    *,
    catalog_path: Path,
    research_root: Path,
    live_db_path: Path,
    user_agent: str,
    now: Callable[[], datetime],
    pause: Callable[[float], None],
    transport: Callable[[str, Mapping[str, str], tuple[int, int] | None], Mapping]
    | None = None,
    parse_rows: Callable[[str, bytes | Path], Sequence[Mapping]] | None = None,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    environ: Mapping[str, str] | None = None,
) -> dict:
    """Fetch bounded shards serially, checkpointing only durable valid receipts."""
    if not user_agent.strip() or max_seconds <= 0 or max_bytes <= 0:
        raise SourceError("invalid_fetch_contract")
    checked_store_path(
        research_root / "receipts" / ".guard", research_root=research_root,
        live_db_path=live_db_path,
    )
    started = now()
    receipts, records, quarantined = [], [], []
    raw_bytes = 0
    with open_store(
        catalog_path, research_root=research_root, live_db_path=live_db_path, kind="catalog"
    ) as con:
        for task in tasks:
            if task.source not in SOURCE_LIMITS:
                raise SourceError("source_not_registered")
            if task.source == "cc_news" and task.byte_range is not None:
                raise SourceError("cc_news_byte_ranges_forbidden")
            if task.source == "edgar" and edgar_readiness(environ)["status"] != "ready":
                return {
                    "status": "unconfigured", "reason": "sec_contact_missing",
                    "receipts": receipts, "records": records, "quarantined": quarantined,
                    "raw_bytes": raw_bytes,
                }
            task_key = f"{task.source}:{task.shard_id}"
            prior_attempts = int(con.execute(
                "SELECT COUNT(*) FROM w4_evidence_records WHERE record_type='ingestion_attempt' "
                "AND record_key LIKE ?", [f"{task_key}:%"],
            ).fetchone()[0])
            if latest_completed_cursor(con, task_key, prior_attempts) == task.cursor_after:
                continue
            if (now() - started).total_seconds() >= max_seconds or raw_bytes >= max_bytes:
                return {
                    "status": "stopped_limit", "receipts": receipts, "records": records,
                    "quarantined": quarantined, "raw_bytes": raw_bytes,
                }
            headers = {"User-Agent": user_agent}
            if task.byte_range is not None:
                headers["Range"] = f"bytes={task.byte_range[0]}-{task.byte_range[1]}"
            host_lock = _HOST_LOCKS.setdefault(urlsplit(task.url).netloc, threading.Lock())
            response = None
            with host_lock:
                for retry in range(len(RETRY_DELAYS) + 1):
                    if transport is None:
                        response = urllib_stream(
                            task.url, headers, task.byte_range,
                            partial_dir=research_root / "receipts" / task.source / ".incoming",
                            max_bytes=max_bytes - raw_bytes, timeout=timeout,
                        )
                    else:
                        response = transport(task.url, headers, task.byte_range)
                    status = int(response.get("status", 0))
                    if status not in {429, *range(500, 600)} or retry == len(RETRY_DELAYS):
                        break
                    pause(_retry_after(
                        response.get("headers", {}), RETRY_DELAYS[retry], observed_at=now()
                    ))
            attempt = prior_attempts + 1
            cursor_before = latest_completed_cursor(con, task_key, prior_attempts)
            if response is not None and response.get("truncated"):
                with db.transaction(con):
                    record_task_attempt(
                        con, task_key=task_key, attempt=attempt, status="truncated",
                        cursor_before=cursor_before, cursor_after=None,
                        receipt_sha256=None, recorded_at=now(),
                    )
                return {
                    "status": "stopped_limit", "receipts": receipts, "records": records,
                    "quarantined": quarantined, "raw_bytes": raw_bytes,
                }
            if response is None or int(response.get("status", 0)) not in {200, 206}:
                failed_partial = None if response is None else response.get("partial_path")
                if failed_partial is not None and Path(failed_partial).exists():
                    Path(failed_partial).unlink()
                with db.transaction(con):
                    record_task_attempt(
                        con, task_key=task_key, attempt=attempt, status="failed",
                        cursor_before=cursor_before, cursor_after=None,
                        receipt_sha256=None, recorded_at=now(),
                    )
                pause(float(SOURCE_LIMITS[task.source]["minimum_interval_seconds"]))
                continue
            partial_value = response.get("partial_path")
            partial = Path(partial_value) if partial_value is not None else None
            body = response.get("body")
            if partial is None and not isinstance(body, bytes):
                raise SourceError("fetch_body_not_bytes")
            response_bytes = int(response.get("bytes", len(body) if isinstance(body, bytes) else 0))
            raw_bytes += response_bytes
            if raw_bytes > max_bytes:
                if partial is not None and partial.exists():
                    partial.unlink()
                with db.transaction(con):
                    record_task_attempt(
                        con, task_key=task_key, attempt=attempt, status="truncated",
                        cursor_before=cursor_before, cursor_after=None,
                        receipt_sha256=None, recorded_at=now(),
                    )
                return {
                    "status": "stopped_limit", "receipts": receipts, "records": records,
                    "quarantined": quarantined, "raw_bytes": raw_bytes,
                }
            receipt = (
                _install_partial(
                    research_root, task.source, partial, str(response["sha256"]),
                    response_bytes, _receipt_suffix(task),
                )
                if partial is not None else put_content_object(
                    research_root, source=task.source, payload=body,
                    suffix=_receipt_suffix(task),
                )
            )
            receipts.append(receipt)
            payload = Path(receipt["path"]) if partial is not None else body
            try:
                parsed_rows = (
                    parse_rows(task.source, payload) if parse_rows is not None
                    else _default_rows(task, payload)
                )
            except (SourceError, KeyError, TypeError, ValueError) as exc:
                quarantined.append({
                    "source": task.source, "shard_id": task.shard_id,
                    "row": None, "reason": str(exc),
                })
                with db.transaction(con):
                    record_task_attempt(
                        con, task_key=task_key, attempt=attempt, status="failed",
                        cursor_before=cursor_before, cursor_after=None,
                        receipt_sha256=receipt["sha256"], recorded_at=now(),
                    )
                pause(float(SOURCE_LIMITS[task.source]["minimum_interval_seconds"]))
                continue
            normalized = []
            retrieved_at = now()
            for index, row in enumerate(parsed_rows):
                try:
                    normalized.append(normalize_source_record(
                        task.source, row, retrieved_at_real=retrieved_at
                    ))
                except (SourceError, KeyError, TypeError, ValueError) as exc:
                    quarantined.append({
                        "source": task.source, "shard_id": task.shard_id,
                        "row": index, "reason": str(exc),
                    })
            recorded_at = now()
            with db.transaction(con):
                for index, record in enumerate(normalized):
                    append_exact(
                        con, record_type="source_record",
                        record_key=f"{task_key}:{index}:{record['source_id']}",
                        payload=_jsonable(record), recorded_at=recorded_at,
                    )
                record_task_attempt(
                    con, task_key=task_key, attempt=attempt, status="completed",
                    cursor_before=cursor_before, cursor_after=task.cursor_after,
                    receipt_sha256=receipt["sha256"], recorded_at=recorded_at,
                )
            records.extend(normalized)
            pause(float(SOURCE_LIMITS[task.source]["minimum_interval_seconds"]))
    return {
        "status": "completed", "receipts": receipts, "records": records,
        "quarantined": quarantined, "raw_bytes": raw_bytes,
    }
