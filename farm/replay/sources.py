"""Fixture-testable W4 source normalization; network transports are injected."""
from __future__ import annotations

import hashlib
import os
import threading
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib.parse import quote, urlencode, urlsplit
from zoneinfo import ZoneInfo

from farm.replay.corpus import (
    capture_sha256,
    latest_completed_cursor,
    put_content_object,
    record_task_attempt,
)
from farm.replay.store import checked_store_path, open_store
from sim import nyse

UTC = timezone.utc
ET = ZoneInfo("America/New_York")
SEC_CONTACT_ENV = "TRADING_ENGINE_SEC_USER_AGENT"

SOURCE_LIMITS = {
    "gdelt_events": {"workers": 1, "minimum_interval_seconds": 1},
    "gdelt_gkg": {"workers": 1, "minimum_interval_seconds": 1},
    "cc_news": {"workers": 1, "minimum_interval_seconds": 0},
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


def wayback_cdx_url(target_url: str, *, start: date, end: date) -> str:
    if not target_url.startswith(("http://", "https://")) or end < start:
        raise SourceError("invalid_wayback_window")
    query = urlencode({
        "url": target_url, "from": start.strftime("%Y%m%d"),
        "to": end.strftime("%Y%m%d"), "output": "json",
        "filter": "statuscode:200", "fl": "timestamp,original,digest",
    })
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


def _retry_after(headers: Mapping, fallback: int) -> int:
    value = headers.get("Retry-After") or headers.get("retry-after")
    try:
        return max(fallback, int(value)) if value is not None else fallback
    except (TypeError, ValueError):
        return fallback


def collect_shards(
    tasks: Sequence[FetchTask],
    *,
    catalog_path: Path,
    research_root: Path,
    live_db_path: Path,
    transport: Callable[[str, Mapping[str, str], tuple[int, int] | None], Mapping],
    parse_rows: Callable[[str, bytes], Sequence[Mapping]],
    user_agent: str,
    now: Callable[[], datetime],
    pause: Callable[[float], None],
    max_seconds: float = DEFAULT_MAX_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
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
                    response = transport(task.url, headers, task.byte_range)
                    status = int(response.get("status", 0))
                    if status not in {429, *range(500, 600)} or retry == len(RETRY_DELAYS):
                        break
                    pause(_retry_after(response.get("headers", {}), RETRY_DELAYS[retry]))
            attempt = prior_attempts + 1
            if response is None or int(response.get("status", 0)) not in {200, 206}:
                record_task_attempt(
                    con, task_key=task_key, attempt=attempt, status="failed",
                    cursor_before=latest_completed_cursor(con, task_key, prior_attempts),
                    cursor_after=None, receipt_sha256=None, recorded_at=now(),
                )
                continue
            body = response.get("body")
            if not isinstance(body, bytes):
                raise SourceError("fetch_body_not_bytes")
            raw_bytes += len(body)
            if raw_bytes > max_bytes:
                record_task_attempt(
                    con, task_key=task_key, attempt=attempt, status="truncated",
                    cursor_before=latest_completed_cursor(con, task_key, prior_attempts),
                    cursor_after=None, receipt_sha256=None, recorded_at=now(),
                )
                return {
                    "status": "stopped_limit", "receipts": receipts, "records": records,
                    "quarantined": quarantined, "raw_bytes": raw_bytes,
                }
            receipt = put_content_object(
                research_root, source=task.source, payload=body, suffix=".raw"
            )
            receipts.append(receipt)
            for index, row in enumerate(parse_rows(task.source, body)):
                try:
                    records.append(
                        normalize_source_record(task.source, row, retrieved_at_real=now())
                    )
                except (SourceError, KeyError, TypeError, ValueError) as exc:
                    quarantined.append({
                        "source": task.source, "shard_id": task.shard_id,
                        "row": index, "reason": str(exc),
                    })
            record_task_attempt(
                con, task_key=task_key, attempt=attempt, status="completed",
                cursor_before=latest_completed_cursor(con, task_key, prior_attempts),
                cursor_after=task.cursor_after, receipt_sha256=receipt["sha256"],
                recorded_at=now(),
            )
            pause(float(SOURCE_LIMITS[task.source]["minimum_interval_seconds"]))
    return {
        "status": "completed", "receipts": receipts, "records": records,
        "quarantined": quarantined, "raw_bytes": raw_bytes,
    }
