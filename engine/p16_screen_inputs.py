"""Append-only compute-time screen snapshots for P16's universe version.

The screen producer records a snapshot when it computes it. Historical rows
without this record have unknown availability and cannot be retroactively dated.
This module is inert until explicitly called by the P16 activation integration.
"""
from __future__ import annotations

import json
import math
import statistics
from datetime import date, datetime, timezone

from engine.lib import db
from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists


def _timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("screen availability must have an explicit timezone")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def init_schema(con) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS p16_screen_versions (
        screen_date DATE NOT NULL, computed_at TIMESTAMP NOT NULL,
        rows_payload VARCHAR NOT NULL, content_sha256 VARCHAR NOT NULL,
        snapshot_sha256 VARCHAR NOT NULL UNIQUE,
        PRIMARY KEY(screen_date,computed_at))""")


def _decode(row: tuple) -> dict:
    day, computed, raw, content_sha, snapshot_sha = row
    rows = json.loads(raw)
    body = {"screen_date": day.isoformat(),
            "computed_at": computed.replace(tzinfo=timezone.utc).isoformat(),
            "rows": rows, "content_sha256": content_sha}
    if canonical_sha256(rows) != content_sha or canonical_sha256(body) != snapshot_sha:
        raise ValueError("retained screen snapshot differs")
    return {**body, "snapshot_sha256": snapshot_sha}


def record_computed_screen(con, screen_date: date, *, computed_at: datetime) -> dict:
    """Call at computation, inside the producer transaction; never backfill times."""
    timestamp = _timestamp(computed_at)
    if screen_date > timestamp.date():
        raise ValueError("screen date is after its computation")
    cursor = con.execute("SELECT * FROM screen_results WHERE run_date=? ORDER BY ticker",
                         [screen_date])
    fields = [item[0] for item in cursor.description]
    rows = [{key: value.isoformat() if isinstance(value, (date, datetime)) else value
             for key, value in zip(fields, row, strict=True)} for row in cursor.fetchall()]
    if not rows:
        raise ValueError("computed screen is empty")
    content_sha = canonical_sha256(rows)
    existing = con.execute(
        "SELECT * FROM p16_screen_versions WHERE screen_date=? ORDER BY computed_at DESC LIMIT 1",
        [screen_date],
    ).fetchone()
    if existing is not None:
        retained = _decode(existing)
        if timestamp < existing[1]:
            raise ValueError("cannot backdate a retained screen")
        if existing[3] == content_sha:
            return {**retained, "replayed": True}
        if timestamp == existing[1]:
            raise ValueError("ambiguous screen computation")
    body = {"screen_date": screen_date.isoformat(),
            "computed_at": timestamp.replace(tzinfo=timezone.utc).isoformat(),
            "rows": rows, "content_sha256": content_sha}
    snapshot_sha = canonical_sha256(body)
    con.execute("INSERT INTO p16_screen_versions VALUES (?,?,?,?,?)",
                [screen_date, timestamp, json.dumps(rows, sort_keys=True, allow_nan=False),
                 content_sha, snapshot_sha])
    return {**body, "snapshot_sha256": snapshot_sha, "replayed": False}


def screen_as_known(con, market_date: date, *, information_cutoff_at: datetime) -> dict:
    """Use the latest screen actually computed by this cutoff; flag stale dates."""
    cutoff = _timestamp(information_cutoff_at)
    unavailable = {"status": "unavailable", "reason": "screen_availability_unknown", "rows": []}
    if not table_exists(con, "p16_screen_versions"):
        return unavailable
    rows = con.execute(
        "SELECT * FROM p16_screen_versions WHERE screen_date<=? AND computed_at<=? "
        "ORDER BY screen_date DESC,computed_at DESC,snapshot_sha256 LIMIT 2",
        [market_date, cutoff],
    ).fetchall()
    if not rows:
        return unavailable
    if len(rows) == 2 and rows[0][:2] == rows[1][:2]:
        raise ValueError("ambiguous screen computation")
    result = _decode(rows[0])
    return {"status": "available", **result,
            "screen_date_mismatch": rows[0][0] != market_date}


def security_liquidity_as_known(
    con, tickers, *, market_date: date, information_cutoff_at: datetime,
) -> dict:
    """Derive 60-session liquidity from a retained security master and price rows."""
    cutoff = _timestamp(information_cutoff_at)
    master = {row[0] for row in con.execute(
        "SELECT ticker FROM universe_snapshot WHERE snapshot_date=(SELECT MAX(snapshot_date) "
        "FROM universe_snapshot WHERE snapshot_date<=?) AND active=TRUE", [market_date],
    ).fetchall()}
    if not master:
        raise ValueError("cutoff-bounded filing security master is unavailable")
    result = {}
    for ticker in sorted(set(tickers) & master):
        rows = con.execute(
            "SELECT date,close,volume,source,fetched_at FROM prices WHERE ticker=? "
            f"AND date<? AND fetched_at<=? AND {db.REAL_BAR_SQL} "
            "ORDER BY date DESC LIMIT 60", [ticker, market_date, cutoff],
        ).fetchall()
        values = [float(row[1]) * int(row[2]) for row in rows]
        if len(rows) != 60 or any(not math.isfinite(value) or value <= 0 for value in values):
            continue
        evidence = [{"date": row[0].isoformat(), "close": row[1], "volume": row[2],
                     "source": row[3], "fetched_at": row[4].replace(
                         tzinfo=timezone.utc).isoformat()} for row in rows]
        result[ticker] = {"median_dollar_volume_60d": float(statistics.median(values)),
                          "price_rows_sha256": canonical_sha256(evidence)}
    return result
