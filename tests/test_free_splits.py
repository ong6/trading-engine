"""Recorded-response coverage for Massive split re-adjustment."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone

import duckdb
import pytest

from engine import free_sources
from tools import free_sources as capture

FETCHED_BEFORE = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
FETCHED_AFTER = datetime(2026, 1, 5, 12, tzinfo=timezone.utc)
SPLIT_BODY = json.dumps({
    "status": "OK",
    "request_id": "recorded-split-page",
    "count": 1,
    "results": [{
        "ticker": "XYZ",
        "execution_date": "2026-01-05",
        "split_from": 1,
        "split_to": 4,
    }],
}, separators=(",", ":")).encode()


def _bar_body(ticker: str, day: date) -> bytes:
    stamp = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000)
    return json.dumps({
        "adjusted": True, "status": "OK", "queryCount": 1, "resultsCount": 1,
        "request_id": f"bar-{ticker}",
        "results": [{
            "T": ticker, "o": 100.0, "h": 104.0, "l": 96.0, "c": 102.0,
            "v": 1000.0, "vw": 101.0, "t": stamp,
        }],
    }, separators=(",", ":")).encode()


def test_adjusted_view_applies_only_splits_unknown_when_bar_was_fetched():
    con = duckdb.connect()
    try:
        free_sources.load_daily_bars(
            con, _bar_body("XYZ", date(2026, 1, 2)),
            session_date=date(2026, 1, 2), fetched_at=FETCHED_BEFORE,
        )
        free_sources.load_daily_bars(
            con, _bar_body("XYZ", date(2026, 1, 3)),
            session_date=date(2026, 1, 3), fetched_at=FETCHED_AFTER,
        )
        result = free_sources.load_splits(con, SPLIT_BODY, fetched_at=FETCHED_AFTER)
        rows = con.execute(
            "SELECT date,o,h,l,c,volume,vwap FROM free_daily_bars_adjusted ORDER BY date"
        ).fetchall()
    finally:
        con.close()

    assert result["inserted"] == 1
    assert rows == [
        (date(2026, 1, 2), 25.0, 26.0, 24.0, 25.5, 4000.0, 25.25),
        (date(2026, 1, 3), 100.0, 104.0, 96.0, 102.0, 1000.0, 101.0),
    ]


class Response:
    status_code = 200
    content = SPLIT_BODY


class Session:
    def __init__(self):
        self.urls = []

    def get(self, url, **_kwargs):
        self.urls.append(url)
        return Response()


def test_split_capture_uses_shared_limiter_and_retains_exact_body(tmp_path):
    calls = []
    session = Session()
    result = capture.capture_massive_splits(
        database=tmp_path / "free.duckdb",
        data_dir=tmp_path / "raw",
        api_key="fixture-key",
        session=session,
        now=lambda: datetime(2026, 1, 6, 7, 30, tzinfo=timezone.utc),
        rate_limit=lambda: calls.append("reserved"),
    )
    digest = hashlib.sha256(SPLIT_BODY).hexdigest()

    assert result["status"] == "complete"
    assert calls == ["reserved"]
    assert len(session.urls) == 1
    assert (tmp_path / "raw" / "massive" / "splits" / f"{digest}.json").read_bytes() == SPLIT_BODY


def test_split_parser_rejects_invalid_ratios():
    body = SPLIT_BODY.replace(b'"split_to":4', b'"split_to":0')
    with pytest.raises(free_sources.FreeSourceError, match="split row"):
        free_sources.parse_massive_splits(body)
