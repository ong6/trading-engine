"""Bounded P15 RSS ingestion and deterministic event-trigger construction."""
from __future__ import annotations

import email.utils
import hashlib
import json
import os
import re
import stat
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

from engine import bitemporal_facts, daily_opportunities
from engine.lib import db
from engine.lib.db import REAL_BAR_SQL
from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists
from server import intraday_source
from sim import nyse

RSS_PATH = Path.home() / "news-scraper" / "data" / "news.jsonl"
RSS_SOURCE = "local_rss"
RSS_VERSION = "news-jsonl-v1"
MAX_READ_BYTES = 1_000_000
MAX_HEADLINE_BYTES = 8_192
MAX_TRIGGER_UNIVERSE = 300
TRIGGER_SCAN_PAGE_SIZE = 1_000
MAX_INTRADAY_WORKERS = 8
ET = ZoneInfo("America/New_York")
CASHTAG = re.compile(r"\$([A-Z][A-Z0-9.-]{0,15})(?![A-Z0-9.-])")


class EventSourceError(ValueError):
    """A P15 event source or trigger violates its bounded contract."""


def session_close(day: date) -> time:
    early = ((day.month, day.day) in {(7, 3), (12, 24)}
             or day.month == 11 and day.weekday() == 4 and 23 <= day.day <= 29)
    return time(13) if early else time(16)


def regular_session_open(observed_at: datetime) -> bool:
    if type(observed_at) is not datetime or observed_at.utcoffset() is None:
        return False
    local = observed_at.astimezone(ET)
    if not nyse.is_session(local.date()) or local.timetz().replace(tzinfo=None) < time(9, 30):
        return False
    return local.timetz().replace(tzinfo=None) < session_close(local.date())


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    bitemporal_facts.init_schema(con)
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_event_source_state (
        policy_id VARCHAR PRIMARY KEY, evidence_started_at TIMESTAMP NOT NULL,
        scanned_through_at TIMESTAMP NOT NULL, start_sha256 VARCHAR NOT NULL UNIQUE)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_rss_checkpoints (
        source_id VARCHAR PRIMARY KEY, byte_offset BIGINT NOT NULL,
        line_count BIGINT NOT NULL, file_identity VARCHAR NOT NULL,
        updated_at TIMESTAMP NOT NULL)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_rss_failures (
        id BIGINT PRIMARY KEY, source_id VARCHAR NOT NULL, byte_offset BIGINT NOT NULL,
        byte_count BIGINT NOT NULL, receipt_sha256 VARCHAR NOT NULL,
        response_sha256 VARCHAR NOT NULL, invalid_lines INTEGER NOT NULL,
        failure_payload VARCHAR NOT NULL, detected_at TIMESTAMP NOT NULL,
        failure_sha256 VARCHAR NOT NULL UNIQUE,
        UNIQUE(source_id,byte_offset,response_sha256))"""
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
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_event_windows (
        id BIGINT PRIMARY KEY, window_id VARCHAR NOT NULL UNIQUE,
        session_date DATE NOT NULL, observed_at TIMESTAMP NOT NULL,
        information_cutoff_at TIMESTAMP NOT NULL,
        completed_at TIMESTAMP, status VARCHAR NOT NULL, reason VARCHAR,
        source_summary VARCHAR NOT NULL, trigger_count INTEGER NOT NULL,
        decision_count INTEGER NOT NULL, skipped_count INTEGER NOT NULL,
        window_sha256 VARCHAR UNIQUE)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_event_calls (
        id BIGINT PRIMARY KEY, window_id VARCHAR NOT NULL, chunk_index INTEGER NOT NULL,
        request_payload VARCHAR NOT NULL, request_sha256 VARCHAR NOT NULL UNIQUE,
        response_payload VARCHAR, response_sha256 VARCHAR, status VARCHAR NOT NULL,
        error VARCHAR, started_at TIMESTAMP NOT NULL, completed_at TIMESTAMP,
        call_sha256 VARCHAR UNIQUE, UNIQUE(window_id,chunk_index))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_event_decisions (
        id BIGINT PRIMARY KEY, window_id VARCHAR NOT NULL, trigger_id BIGINT NOT NULL UNIQUE,
        ticker VARCHAR NOT NULL, event_type VARCHAR NOT NULL,
        scoring_status VARCHAR NOT NULL, decision_payload VARCHAR NOT NULL,
        decision_sha256 VARCHAR NOT NULL UNIQUE, triggered_at TIMESTAMP NOT NULL,
        decision_at TIMESTAMP NOT NULL, latency_ms DOUBLE NOT NULL)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_event_labels (
        id BIGINT PRIMARY KEY, decision_id BIGINT NOT NULL, horizon_sessions INTEGER NOT NULL,
        label_basis VARCHAR NOT NULL, entry_at TIMESTAMP NOT NULL, exit_date DATE NOT NULL,
        entry_px DOUBLE NOT NULL, exit_close DOUBLE NOT NULL, asset_return DOUBLE NOT NULL,
        spy_return DOUBLE NOT NULL, net_return DOUBLE NOT NULL, net_excess_return DOUBLE NOT NULL,
        missing_bar_status VARCHAR NOT NULL, price_prefix_sha256 VARCHAR NOT NULL,
        labeled_at TIMESTAMP NOT NULL, label_sha256 VARCHAR NOT NULL UNIQUE,
        UNIQUE(decision_id,horizon_sessions,label_basis))"""
    )


def initialize_event_evidence(con: duckdb.DuckDBPyConnection, *, now: datetime) -> dict:
    """Set the immutable lower bound for forward-only W5 source evidence."""
    if type(now) is not datetime or now.utcoffset() is None:
        raise EventSourceError("event evidence start timestamp is invalid")
    started = now.astimezone(timezone.utc)
    init_schema(con)
    existing = con.execute(
        "SELECT evidence_started_at,scanned_through_at,start_sha256 "
        "FROM p15_event_source_state WHERE policy_id=?",
        ["p15-events-v1"],
    ).fetchone()
    if existing is not None:
        identity = {"policy_id": "p15-events-v1",
                    "evidence_started_at": existing[0].replace(tzinfo=timezone.utc).isoformat()}
        if existing[2] != canonical_sha256(identity) or existing[1] < existing[0]:
            raise EventSourceError("event evidence start differs")
        return {"status": "ready", "evidence_started_at": identity["evidence_started_at"],
                "replayed": True}
    identity = {"policy_id": "p15-events-v1", "evidence_started_at": started.isoformat()}
    con.execute(
        "INSERT INTO p15_event_source_state VALUES (?,?,?,?)",
        ["p15-events-v1", started.replace(tzinfo=None), started.replace(tzinfo=None),
         canonical_sha256(identity)],
    )
    return {"status": "ready", "evidence_started_at": started.isoformat(),
            "replayed": False}


def initialize_rss_checkpoint(
    con: duckdb.DuckDBPyConnection, path: Path = RSS_PATH, *, now: datetime,
) -> dict:
    """Start forward RSS evidence at the current EOF without importing history."""
    init_schema(con)
    initialize_event_evidence(con, now=now)
    now = now.astimezone(timezone.utc)
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


def _universe_names(con, as_of: date | None = None) -> tuple[dict[str, str], dict[str, str]]:
    selected = []
    if table_exists(con, "p15_scoring_runs"):
        row = con.execute(
            "SELECT universe_payload FROM p15_scoring_runs WHERE status='completed' "
            + ("AND market_date<? " if as_of is not None else "")
            + "ORDER BY market_date DESC LIMIT 1", [] if as_of is None else [as_of],
        ).fetchone()
        if row is not None:
            selected.extend(item["ticker"] for item in json.loads(row[0])["candidates"])
    if table_exists(con, "screen_results"):
        selected.extend(row[0] for row in con.execute(
            "SELECT ticker FROM screen_results WHERE run_date=(SELECT MAX(run_date) "
            "FROM screen_results"
            + (" WHERE run_date<?" if as_of is not None else "")
            + ") AND passes_template ORDER BY rs_rank DESC NULLS LAST,ticker",
            [] if as_of is None else [as_of],
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
    name_matches: dict[str, set[str]] = {}
    for ticker, name in rows:
        if isinstance(name, str) and len(name.strip()) >= 5:
            name_matches.setdefault(name.casefold(), set()).add(ticker)
    by_name = {name: next(iter(symbols)) for name, symbols in name_matches.items()
               if len(symbols) == 1}
    return by_ticker, by_name


def _mapped_tickers(title: str, tickers: dict[str, str], names: dict[str, str]) -> list[str]:
    tagged = {value for value in CASHTAG.findall(title.upper()) if value in tickers}
    folded = title.casefold()
    named = {ticker for name, ticker in names.items()
             if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", folded)}
    return sorted(tagged | named)


def _rss_rows(body: bytes) -> tuple[list[dict], list[dict]]:
    rows, failures = [], []
    for line_number, raw in enumerate(body.splitlines(), 1):
        if not raw:
            continue
        line_sha = hashlib.sha256(raw).hexdigest()
        if len(raw) > MAX_HEADLINE_BYTES:
            failures.append({"line_number": line_number, "line_sha256": line_sha,
                             "reason": "line_too_large"})
            continue
        try:
            item = json.loads(raw)
            published = email.utils.parsedate_to_datetime(item["pubDate"]).astimezone(timezone.utc)
            scraped = datetime.fromisoformat(item["scraped_at"].replace("Z", "+00:00"))
        except (AttributeError, KeyError, TypeError, ValueError, UnicodeDecodeError):
            failures.append({"line_number": line_number, "line_sha256": line_sha,
                             "reason": "invalid_json_or_timestamp"})
            continue
        if (not isinstance(item.get("title"), str) or not item["title"].strip()
                or len(item["title"]) > 500 or not isinstance(item.get("guid"), str)
                or not item["guid"] or not isinstance(item.get("source"), str)
                or not item["source"] or published > scraped):
            failures.append({"line_number": line_number, "line_sha256": line_sha,
                             "reason": "invalid_headline_fields"})
            continue
        rows.append({"title": item["title"].strip(), "guid": item["guid"],
                     "publisher": item["source"], "published_at": published})
    return rows, failures


def ingest_rss(
    con: duckdb.DuckDBPyConnection, path: Path = RSS_PATH, *, now: datetime,
) -> dict:
    """Ingest one complete bounded append-only segment; availability is ingest time."""
    if type(now) is not datetime or now.utcoffset() is None:
        raise EventSourceError("RSS ingest timestamp is invalid")
    now = now.astimezone(timezone.utc)
    init_schema(con)
    initialize_event_evidence(con, now=now)
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
        opened = os.fstat(descriptor)
        if ((opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)
                or opened.st_size != info.st_size
                or not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.getuid()):
            raise EventSourceError("RSS source changed while opening")
        os.lseek(descriptor, offset, os.SEEK_SET)
        raw = os.read(descriptor, min(MAX_READ_BYTES + 1, opened.st_size - offset))
        after = os.fstat(descriptor)
        if ((opened.st_dev, opened.st_ino) != (after.st_dev, after.st_ino)
                or after.st_size < opened.st_size):
            raise EventSourceError("RSS source changed while reading")
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
    parsed, invalid = _rss_rows(raw)
    tickers, names = _universe_names(con)
    facts, unmapped = 0, 0
    with db.transaction(con):
        receipt = bitemporal_facts.record_receipt(
            con, source=RSS_SOURCE, dataset="headline_jsonl", endpoint="news.jsonl",
            request={"byte_offset": offset, "byte_count": len(raw)}, requested_at=now,
            received_at=now, http_status=200, content_type="application/x-ndjson",
            body=raw, license_class="local-retained-public-feed",
        )
        if invalid:
            failure = {
                "source_id": RSS_SOURCE, "byte_offset": offset, "byte_count": len(raw),
                "receipt_sha256": receipt["receipt_sha256"],
                "response_sha256": hashlib.sha256(raw).hexdigest(),
                "invalid_lines": invalid, "detected_at": now.isoformat(),
            }
            con.execute(
                "INSERT INTO p15_rss_failures VALUES (?,?,?,?,?,?,?,?,?,?)",
                [int(con.execute(
                    "SELECT COALESCE(MAX(id),0)+1 FROM p15_rss_failures"
                ).fetchone()[0]), RSS_SOURCE, offset, len(raw), receipt["receipt_sha256"],
                 failure["response_sha256"], len(invalid),
                 json.dumps(invalid, sort_keys=True, separators=(",", ":")),
                 now.replace(tzinfo=None), canonical_sha256(failure)],
            )
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
    return {"status": "partial_invalid" if invalid else "complete", "lines": len(parsed),
            "facts": facts,
            "unmapped": unmapped, "byte_offset": offset + len(raw)}


def _trigger_session(available_at: datetime) -> date:
    local = available_at.replace(tzinfo=timezone.utc).astimezone(ET)
    if nyse.is_session(local.date()) and local.timetz().replace(tzinfo=None) < session_close(
        local.date()
    ):
        return local.date()
    return nyse.next_session(local.date())


def create_text_triggers(
    con: duckdb.DuckDBPyConnection, session_date: date, *, triggered_at: datetime,
) -> dict:
    """Recover eligible facts into at most one trigger per ticker/source/session."""
    init_schema(con)
    if (triggered_at.utcoffset() is None
            or triggered_at.astimezone(ET).date() != session_date
            or not nyse.is_session(session_date)):
        raise EventSourceError("event trigger session timestamp is invalid")
    cutoff = triggered_at.astimezone(timezone.utc)
    state = con.execute(
        "SELECT evidence_started_at,scanned_through_at,start_sha256 "
        "FROM p15_event_source_state WHERE policy_id=?",
        ["p15-events-v1"],
    ).fetchone()
    if state is None:
        raise EventSourceError("P15 event evidence start is unavailable")
    start_identity = {"policy_id": "p15-events-v1",
                      "evidence_started_at": state[0].replace(tzinfo=timezone.utc).isoformat()}
    if state[2] != canonical_sha256(start_identity) or state[1] < state[0]:
        raise EventSourceError("P15 event evidence start differs")
    cutoff_naive = cutoff.replace(tzinfo=None)
    if cutoff_naive < state[1]:
        raise EventSourceError("event fact scan cutoff moved backward")
    created, examined, seen, allowed_by_session = 0, 0, set(), {}
    cursor_at, cursor_sha = state[1], ""
    with db.transaction(con):
        while True:
            rows = con.execute(
                "SELECT security_id,fact_type,event_at,available_at,fact_sha256 "
                "FROM bitemporal_facts WHERE security_id IS NOT NULL "
                "AND (available_at>? OR (available_at=? AND fact_sha256>?)) "
                "AND available_at<=? AND ingested_at<=? "
                "AND ((fact_type='news.headline' AND source='local_rss') "
                "OR (fact_type='p15.event.intraday_mover' AND source='yfinance') "
                "OR (fact_type LIKE 'sec.filing:%' AND source='sec_edgar' AND "
                "json_extract_string(normalized_payload,'$.form') IN ('8-K','8-K/A'))) "
                "ORDER BY available_at,fact_sha256 LIMIT ?",
                [cursor_at, cursor_at, cursor_sha, cutoff_naive, cutoff_naive,
                 TRIGGER_SCAN_PAGE_SIZE],
            ).fetchall()
            if not rows:
                break
            examined += len(rows)
            for ticker, fact_type, event_at, available_at, fact_sha in rows:
                source = ("rss" if fact_type == "news.headline" else "intraday_mover"
                          if fact_type == "p15.event.intraday_mover" else "sec_8k")
                target_session = _trigger_session(available_at)
                allowed = allowed_by_session.setdefault(
                    target_session, set(_universe_names(con, target_session)[0])
                )
                if ticker not in allowed:
                    continue
                dedup_key = (target_session, ticker, source)
                if dedup_key in seen:
                    continue
                identity = {"session_date": target_session.isoformat(), "ticker": ticker,
                            "source": source, "event_type": fact_type,
                            "fact_sha256": fact_sha, "triggered_at": cutoff.isoformat()}
                prior = con.execute(
                    "SELECT trigger_sha256 FROM p15_event_triggers "
                    "WHERE session_date=? AND ticker=? AND source=?",
                    [target_session, ticker, source],
                ).fetchone()
                if prior is None:
                    trigger_id = int(con.execute(
                        "SELECT COALESCE(MAX(id),0)+1 FROM p15_event_triggers"
                    ).fetchone()[0])
                    con.execute(
                        "INSERT INTO p15_event_triggers VALUES "
                        "(?,?,?,?,?,?,?,?,?,'pending',NULL,?)",
                        [trigger_id, target_session, ticker, source, fact_type, event_at,
                         available_at, cutoff_naive, fact_sha, canonical_sha256(identity)],
                    )
                    created += 1
                seen.add(dedup_key)
            cursor_at, cursor_sha = rows[-1][3], rows[-1][4]
        con.execute(
            "UPDATE p15_event_source_state SET scanned_through_at=? WHERE policy_id=?",
            [cutoff_naive, "p15-events-v1"],
        )
    return {"created": created, "examined": examined}


def _mover_universe(con, observed_at: datetime) -> list[tuple[str, str, float, float, float]]:
    session_date = observed_at.astimezone(ET).date()
    selected = list(_universe_names(con, session_date)[0])
    selected = list(dict.fromkeys(["SPY", *selected]))[:MAX_TRIGGER_UNIVERSE]
    if not selected:
        return []
    rows = con.execute(
        f"SELECT ticker,yf_ticker FROM universe WHERE ticker IN "
        f"({','.join('?' for _ in selected)})", selected,
    ).fetchall()
    provider = {row[0]: row[1] for row in rows}
    provider.setdefault("SPY", "SPY")
    result = []
    for ticker in selected:
        daily = con.execute(
            f"SELECT date,close FROM prices WHERE ticker=? AND date<? AND fetched_at IS NOT NULL "
            f"AND fetched_at<=? AND close>0 AND {REAL_BAR_SQL} ORDER BY date DESC LIMIT 1",
            [ticker, session_date, observed_at.replace(tzinfo=None)],
        ).fetchone()
        volumes = con.execute(
            f"SELECT volume FROM prices WHERE ticker=? AND date<=? "
            f"AND fetched_at IS NOT NULL AND fetched_at<=? AND {REAL_BAR_SQL} "
            "ORDER BY date DESC LIMIT 20",
            [ticker, daily[0] if daily else date.min, observed_at.replace(tzinfo=None)],
        ).fetchall()
        atr = None if daily is None else daily_opportunities._p15_atr(
            con, ticker, daily[0], observed_at
        )
        if daily is None or atr is None or not volumes or not provider.get(ticker):
            continue
        ordered = sorted(float(row[0]) for row in volumes)
        middle = len(ordered) // 2
        median_volume = (ordered[middle] if len(ordered) % 2
                         else (ordered[middle - 1] + ordered[middle]) / 2)
        result.append((ticker, provider[ticker], float(daily[1]), median_volume, atr))
    return result


def scan_intraday(
    con: duckdb.DuckDBPyConnection, *, observed_at: datetime,
    capture=intraday_source.capture, workers: int = MAX_INTRADAY_WORKERS,
) -> dict:
    """Capture the bounded universe and retain threshold-crossing mover triggers."""
    if type(observed_at) is not datetime or observed_at.utcoffset() is None:
        raise EventSourceError("intraday scan timestamp is invalid")
    init_schema(con)
    local = observed_at.astimezone(ET)
    observed_at = observed_at.astimezone(timezone.utc)
    if not regular_session_open(observed_at):
        raise EventSourceError("intraday scan is outside the regular session")
    initialize_event_evidence(con, now=observed_at)
    universe = _mover_universe(con, observed_at)
    captures, failures = [], []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, MAX_INTRADAY_WORKERS))) as pool:
        futures = {pool.submit(capture, ticker, provider, observed_at): ticker
                   for ticker, provider, _close, _volume, _atr in universe}
        for future in as_completed(futures):
            try:
                captures.append(future.result())
            except (intraday_source.IntradaySourceError, OSError, ValueError) as exc:
                failures.append({"ticker": futures[future], "reason": str(exc)[:200]})
    inputs = {row[0]: row[2:] for row in universe}
    created, retained = 0, 0
    elapsed = max(1.0, (local.hour * 60 + local.minute) - (9 * 60 + 30)) / 390
    for capture_result in sorted(captures, key=lambda item: item["quotes"][0]["ticker"]):
        response = capture_result["response"]
        ingested_at = max(observed_at.astimezone(timezone.utc),
                          response.received_at.astimezone(timezone.utc))
        stored = bitemporal_facts.record_intraday_quote_batch(
            con, source="yfinance", endpoint=capture_result["endpoint"],
            request=capture_result["request"], requested_at=response.requested_at,
            received_at=response.received_at, content_type=response.content_type,
            body=response.body, quotes=capture_result["quotes"],
            interval=intraday_source.INTERVAL, source_version=intraday_source.source_version(),
            license_class="provider-terms-research", ingested_at=ingested_at,
        )
        retained += len(capture_result["quotes"])
        ticker = capture_result["quotes"][0]["ticker"]
        prior_close, median_volume, atr = inputs[ticker]
        current = [item for item in capture_result["quotes"]
                   if item["event_at"].astimezone(ET).date() == local.date()
                   and item["event_at"] <= observed_at]
        if not current:
            continue
        latest = max(current, key=lambda item: item["event_at"])
        fact_by_event = dict(zip(
            (quote["event_at"] for quote in capture_result["quotes"]),
            stored["fact_sha256s"], strict=True,
        ))
        session_return = float(latest["close"]) / prior_close - 1
        relative_volume = sum(float(item["volume"]) for item in current) / (median_volume * elapsed)
        threshold = max(0.04, 2 * float(atr) / prior_close)
        if ticker == "SPY" or abs(session_return) < threshold or relative_volume < 2:
            continue
        payload = {"ticker": ticker, "event_type": "intraday_mover",
                   "session_return": session_return, "relative_volume": relative_volume,
                   "threshold": threshold, "source_fact_sha256": fact_by_event[latest["event_at"]]}
        fact = bitemporal_facts.record_fact(
            con, entity_id=ticker, security_id=ticker, fact_type="p15.event.intraday_mover",
            event_at=latest["event_at"], published_at=None,
            available_at=response.received_at, ingested_at=ingested_at,
            payload=payload, source="yfinance", source_version=intraday_source.source_version(),
            receipt_sha256=stored["receipt_sha256"],
        )
        identity = {"session_date": local.date().isoformat(), "ticker": ticker,
                    "source": "intraday_mover", "event_type": "intraday_mover",
                    "fact_sha256": fact["fact_sha256"],
                    "triggered_at": ingested_at.isoformat()}
        prior = con.execute(
            "SELECT 1 FROM p15_event_triggers WHERE session_date=? AND ticker=? "
            "AND source='intraday_mover'", [local.date(), ticker],
        ).fetchone()
        if prior is None:
            trigger_id = int(con.execute(
                "SELECT COALESCE(MAX(id),0)+1 FROM p15_event_triggers"
            ).fetchone()[0])
            con.execute(
                "INSERT INTO p15_event_triggers VALUES (?,?,?,?,?,?,?,?,?,'pending',NULL,?)",
                [trigger_id, local.date(), ticker, "intraday_mover", "intraday_mover",
                 latest["event_at"], response.received_at, ingested_at.replace(tzinfo=None),
                 fact["fact_sha256"], canonical_sha256(identity)],
            )
            created += 1
    return {"status": "complete" if not failures else "partial",
            "universe": len(universe), "captured": len(captures),
            "facts": retained, "triggers": created, "failures": failures}
