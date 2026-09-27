"""Fixture-testable W4 source normalization; network transports are injected."""
from __future__ import annotations

import hashlib
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from farm.replay.corpus import capture_sha256
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
}


class SourceError(ValueError):
    """A historical source row cannot meet its registered availability rule."""


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
