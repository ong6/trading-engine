"""Deterministic 8-K item 2.02 corpus and acceptance-time label clocks."""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

from engine import p15_event_sources
from sim import nyse

ET = ZoneInfo("America/New_York")
YEARS = tuple(range(2015, 2026))


def _instant(value: object) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("naive_textlab_clock")
    return result.astimezone(timezone.utc)


def first_open_strictly_after(accepted_at: datetime) -> datetime:
    accepted = _instant(accepted_at)
    local = accepted.astimezone(ET)
    day = local.date()
    opening = datetime.combine(day, time(9, 30), ET)
    if not nyse.is_session(day) or local >= opening:
        day = nyse.next_session(day)
        opening = datetime.combine(day, time(9, 30), ET)
    return opening.astimezone(timezone.utc)


def label_clock(entry_session: date, horizon: int) -> datetime:
    if horizon not in {1, 5, 20} or not nyse.is_session(entry_session):
        raise ValueError("invalid_textlab_horizon")
    day = entry_session
    for _ in range(horizon - 1):
        day = nyse.next_session(day)
    closed = datetime.combine(day, p15_event_sources.session_close(day), ET)
    return (closed + timedelta(minutes=15)).astimezone(timezone.utc)


def build_corpus_inventory(rows: Sequence[Mapping]) -> dict:
    """Retain the full 2015-2025 item-2.02 accession population before labels."""
    retained, seen = [], set()
    for source in rows:
        form = str(source.get("form", "")).upper()
        items = set(re.findall(r"\d+\.\d+", str(source.get("items", ""))))
        if form not in {"8-K", "8-K/A"} or "2.02" not in items:
            continue
        accession = str(source.get("accession", ""))
        accepted = _instant(source.get("accepted_at"))
        if not accession or accession in seen or accepted.year not in YEARS:
            continue
        seen.add(accession)
        retained.append({
            "accession": accession,
            "cik": str(source.get("cik", "")).zfill(10),
            "accepted_at": accepted,
            "entry_at": first_open_strictly_after(accepted),
            "language": str(source.get("language", "unknown")),
            "content_sha256": str(source.get("content_sha256", "")),
        })
    retained.sort(key=lambda row: (row["accepted_at"], row["accession"]))
    counts = {str(year): 0 for year in YEARS}
    for row in retained:
        counts[str(row["accepted_at"].year)] += 1
    return {
        "status": "corpus_ready" if retained else "corpus_empty",
        "records": retained,
        "year_counts": counts,
        "years": list(YEARS),
    }
