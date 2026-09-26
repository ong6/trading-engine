"""Append-only compute-time screen snapshots for P16's universe version.

The screen producer records a snapshot when it computes it. Historical rows
without this record have unknown availability and cannot be retroactively dated.
This module is inert until explicitly called by the P16 activation integration.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

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
