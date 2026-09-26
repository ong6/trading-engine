"""Bounded P15 RSS ingestion and deterministic event-trigger construction."""
from __future__ import annotations

import email.utils
import json
import os
import re
import stat
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

from engine import bitemporal_facts
from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists
from sim import nyse

RSS_PATH = Path.home() / "news-scraper" / "data" / "news.jsonl"
RSS_SOURCE = "local_rss"
RSS_VERSION = "news-jsonl-v1"
MAX_READ_BYTES = 1_000_000
MAX_HEADLINE_BYTES = 8_192
MAX_TRIGGER_UNIVERSE = 300
ET = ZoneInfo("America/New_York")
CASHTAG = re.compile(r"\$([A-Z][A-Z0-9.-]{0,15})(?![A-Z0-9.-])")


class EventSourceError(ValueError):
    """A P15 event source or trigger violates its bounded contract."""


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    bitemporal_facts.init_schema(con)
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_rss_checkpoints (
        source_id VARCHAR PRIMARY KEY, byte_offset BIGINT NOT NULL,
        line_count BIGINT NOT NULL, file_identity VARCHAR NOT NULL,
        updated_at TIMESTAMP NOT NULL)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_event_triggers (
        id BIGINT PRIMARY KEY, session_date DATE NOT NULL, ticker VARCHAR NOT NULL,
        source VARCHAR NOT NULL, event_type VARCHAR NOT NULL,
        event_at TIMESTAMP NOT NULL, available_at TIMESTAMP NOT NULL,
        triggered_at TIMESTAMP NOT NULL, fact_sha256 VARCHAR NOT NULL,
        status VARCHAR NOT NULL, reason VARCHAR,
        trigger_sha256 VARCHAR NOT NULL UNIQUE, UNIQUE(session_date,ticker,source))"""
    )


def initialize_rss_checkpoint(
    con: duckdb.DuckDBPyConnection, path: Path = RSS_PATH, *, now: datetime,
) -> dict:
    """Start forward RSS evidence at the current EOF without importing history."""
    init_schema(con)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise EventSourceError("RSS source must be an owner-controlled regular file")
    identity = f"{info.st_dev}:{info.st_ino}"
    existing = con.execute(
        "SELECT byte_offset,line_count,file_identity FROM p15_rss_checkpoints "
        "WHERE source_id=?", [RSS_SOURCE],
    ).fetchone()
    expected = (info.st_size, 0, identity)
    if existing is not None:
        if existing != expected:
            raise EventSourceError("RSS checkpoint already differs")
        return {"status": "ready", "byte_offset": int(existing[0]), "replayed": True}
    con.execute(
        "INSERT INTO p15_rss_checkpoints VALUES (?,?,?,?,?)",
        [RSS_SOURCE, info.st_size, 0, identity, now.replace(tzinfo=None)],
    )
    return {"status": "ready", "byte_offset": info.st_size, "replayed": False}


def _universe_names(con) -> tuple[dict[str, str], dict[str, str]]:
    selected = []
    if table_exists(con, "p15_scoring_runs"):
        row = con.execute(
            "SELECT universe_payload FROM p15_scoring_runs WHERE status='completed' "
            "ORDER BY market_date DESC LIMIT 1"
        ).fetchone()
        if row is not None:
            selected.extend(item["ticker"] for item in json.loads(row[0])["candidates"])
    if table_exists(con, "screen_results"):
        selected.extend(row[0] for row in con.execute(
            "SELECT ticker FROM screen_results WHERE run_date=(SELECT MAX(run_date) "
            "FROM screen_results) AND passes_template ORDER BY rs_rank DESC NULLS LAST,ticker"
        ).fetchall())
    selected = list(dict.fromkeys(selected))[:MAX_TRIGGER_UNIVERSE]
    if not selected:
        return {}, {}
    rows = con.execute(
        f"SELECT ticker,name FROM universe WHERE ticker IN "
        f"({','.join('?' for _ in selected)}) ORDER BY ticker", selected,
    ).fetchall()
    by_ticker = {ticker: None for ticker in selected}
    by_ticker.update({ticker: name for ticker, name in rows})
    by_name = {name.casefold(): ticker for ticker, name in rows
               if isinstance(name, str) and len(name.strip()) >= 5}
    return by_ticker, by_name


def _mapped_tickers(title: str, tickers: dict[str, str], names: dict[str, str]) -> list[str]:
    tagged = {value for value in CASHTAG.findall(title.upper()) if value in tickers}
    folded = title.casefold()
    named = {ticker for name, ticker in names.items()
             if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", folded)}
    return sorted(tagged | named)


def _rss_rows(body: bytes) -> list[dict]:
    rows = []
    for raw in body.splitlines():
        if not raw or len(raw) > MAX_HEADLINE_BYTES:
            continue
        try:
            item = json.loads(raw)
            published = email.utils.parsedate_to_datetime(item["pubDate"]).astimezone(timezone.utc)
            scraped = datetime.fromisoformat(item["scraped_at"].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
            raise EventSourceError("RSS line is invalid") from exc
        if (not isinstance(item.get("title"), str) or not item["title"].strip()
                or len(item["title"]) > 500 or not isinstance(item.get("guid"), str)
                or not item["guid"] or not isinstance(item.get("source"), str)
                or not item["source"] or published > scraped):
            raise EventSourceError("RSS headline fields are invalid")
        rows.append({"title": item["title"].strip(), "guid": item["guid"],
                     "publisher": item["source"], "published_at": published})
    return rows


def ingest_rss(
    con: duckdb.DuckDBPyConnection, path: Path = RSS_PATH, *, now: datetime,
) -> dict:
    """Ingest one complete bounded append-only segment; availability is ingest time."""
    init_schema(con)
    checkpoint = con.execute(
        "SELECT byte_offset,line_count,file_identity FROM p15_rss_checkpoints "
        "WHERE source_id=?", [RSS_SOURCE],
    ).fetchone()
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise EventSourceError("RSS source must be an owner-controlled regular file")
    identity = f"{info.st_dev}:{info.st_ino}"
    offset, line_count = (0, 0) if checkpoint is None else (int(checkpoint[0]), int(checkpoint[1]))
    if checkpoint is not None and checkpoint[2] != identity or info.st_size < offset:
        raise EventSourceError("RSS source rotated or truncated")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.lseek(descriptor, offset, os.SEEK_SET)
        raw = os.read(descriptor, MAX_READ_BYTES + 1)
    finally:
        os.close(descriptor)
    if not raw:
        return {"status": "current", "lines": 0, "facts": 0, "unmapped": 0}
    if len(raw) > MAX_READ_BYTES:
        boundary = raw.rfind(b"\n", 0, MAX_READ_BYTES + 1)
        if boundary < 0:
            raise EventSourceError("RSS line exceeds the bounded read size")
        raw = raw[:boundary + 1]
    elif not raw.endswith(b"\n"):
        boundary = raw.rfind(b"\n")
        raw = b"" if boundary < 0 else raw[:boundary + 1]
    if not raw:
        return {"status": "partial_line", "lines": 0, "facts": 0, "unmapped": 0}
    parsed = _rss_rows(raw)
    tickers, names = _universe_names(con)
    receipt = bitemporal_facts.record_receipt(
        con, source=RSS_SOURCE, dataset="headline_jsonl", endpoint="news.jsonl",
        request={"byte_offset": offset, "byte_count": len(raw)}, requested_at=now,
        received_at=now, http_status=200, content_type="application/x-ndjson",
        body=raw, license_class="local-retained-public-feed",
    )
    facts, unmapped = 0, 0
    for item in parsed:
        mapped = _mapped_tickers(item["title"], tickers, names)
        targets = mapped or [None]
        unmapped += not mapped
        for ticker in targets:
            bitemporal_facts.record_fact(
                con, entity_id=f"rss:{item['guid']}:{ticker or 'unmapped'}",
                security_id=ticker, fact_type="news.headline", event_at=item["published_at"],
                published_at=item["published_at"], available_at=now, ingested_at=now,
                payload={"title": item["title"]}, source=RSS_SOURCE,
                source_version=RSS_VERSION, receipt_sha256=receipt["receipt_sha256"],
            )
            facts += 1
    con.execute(
        "INSERT OR REPLACE INTO p15_rss_checkpoints VALUES (?,?,?,?,?)",
        [RSS_SOURCE, offset + len(raw), line_count + len(parsed), identity,
         now.replace(tzinfo=None)],
    )
    return {"status": "complete", "lines": len(parsed), "facts": facts,
            "unmapped": unmapped, "byte_offset": offset + len(raw)}


def _previous_session(day: date) -> date:
    current = day
    while True:
        current = current.fromordinal(current.toordinal() - 1)
        if nyse.is_session(current):
            return current


def create_text_triggers(
    con: duckdb.DuckDBPyConnection, session_date: date, *, triggered_at: datetime,
) -> dict:
    """Create at most one RSS and one 8-K trigger per ticker/session."""
    init_schema(con)
    if (triggered_at.utcoffset() is None
            or triggered_at.astimezone(ET).date() != session_date
            or not nyse.is_session(session_date)):
        raise EventSourceError("event trigger session timestamp is invalid")
    allowed = set(_universe_names(con)[0])
    lower = datetime.combine(_previous_session(session_date), time(16), ET).astimezone(timezone.utc)
    cutoff = triggered_at.astimezone(timezone.utc)
    rows = con.execute(
        "SELECT security_id,fact_type,event_at,available_at,fact_sha256 FROM bitemporal_facts "
        "WHERE security_id IS NOT NULL AND available_at>? AND available_at<=? "
        "AND (fact_type='news.headline' OR fact_type LIKE 'sec.filing:%') "
        "ORDER BY available_at,fact_sha256", [lower.replace(tzinfo=None), cutoff.replace(tzinfo=None)],
    ).fetchall()
    created, seen = 0, set()
    for ticker, fact_type, event_at, available_at, fact_sha in rows:
        if ticker not in allowed:
            continue
        source = "rss" if fact_type == "news.headline" else "sec_8k"
        if (ticker, source) in seen:
            continue
        if source == "sec_8k":
            payload = con.execute(
                "SELECT normalized_payload FROM bitemporal_facts WHERE fact_sha256=?", [fact_sha]
            ).fetchone()[0]
            if json.loads(payload).get("form") not in {"8-K", "8-K/A"}:
                continue
        identity = {"session_date": session_date.isoformat(), "ticker": ticker,
                    "source": source, "event_type": fact_type,
                    "fact_sha256": fact_sha,
                    "triggered_at": cutoff.isoformat()}
        prior = con.execute(
            "SELECT trigger_sha256 FROM p15_event_triggers "
            "WHERE session_date=? AND ticker=? AND source=?",
            [session_date, ticker, source],
        ).fetchone()
        if prior is not None:
            if prior[0] != canonical_sha256(identity):
                raise EventSourceError("event trigger replay differs")
            seen.add((ticker, source))
            continue
        trigger_id = int(con.execute(
            "SELECT COALESCE(MAX(id),0)+1 FROM p15_event_triggers"
        ).fetchone()[0])
        changed = con.execute(
            "INSERT INTO p15_event_triggers VALUES (?,?,?,?,?,?,?,?,?,'pending',NULL,?) "
            "RETURNING id",
            [trigger_id, session_date, ticker, source, fact_type, event_at, available_at,
             triggered_at.replace(tzinfo=None), fact_sha, canonical_sha256(identity)],
        ).fetchone()
        created += changed is not None
        seen.add((ticker, source))
    return {"created": created, "examined": len(rows)}
