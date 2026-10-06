"""Recorded-response coverage for Massive split re-adjustment."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone

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


def _split_body(rows: list[dict]) -> bytes:
    return json.dumps({
        "status": "OK", "request_id": "recorded-split-page",
        "count": len(rows), "results": rows,
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


def test_adjusted_asof_compounds_forward_splits_and_handles_reverse_and_future():
    con = duckdb.connect()
    try:
        for ticker in ("XYZ", "REV", "FUT"):
            free_sources.load_daily_bars(
                con, _bar_body(ticker, date(2026, 1, 2)),
                session_date=date(2026, 1, 2), fetched_at=FETCHED_BEFORE,
            )
        free_sources.load_splits(con, _split_body([
            {"ticker": "XYZ", "execution_date": "2026-01-05",
             "split_from": 1, "split_to": 2},
            {"ticker": "XYZ", "execution_date": "2026-01-06",
             "split_from": 1, "split_to": 3},
            {"ticker": "REV", "execution_date": "2026-01-05",
             "split_from": 10, "split_to": 1},
            {"ticker": "FUT", "execution_date": "2026-01-10",
             "split_from": 1, "split_to": 5},
        ]), fetched_at=FETCHED_AFTER)
        before = free_sources.daily_panel(
            con, date(2026, 1, 2), date(2026, 1, 2), as_of=date(2026, 1, 4)
        ).set_index("ticker")
        through = free_sources.daily_panel(
            con, date(2026, 1, 2), date(2026, 1, 2), as_of=date(2026, 1, 6)
        ).set_index("ticker")
    finally:
        con.close()

    assert before.loc["XYZ", "o"] == 100.0
    assert through.loc["XYZ", "o"] == pytest.approx(100.0 / 6.0)
    assert through.loc["XYZ", "volume"] == 6000.0
    assert through.loc["REV", "o"] == 1000.0
    assert through.loc["REV", "volume"] == 100.0
    assert through.loc["FUT", "o"] == 100.0
    assert through.loc["FUT", "volume"] == 1000.0


def test_split_correction_updates_and_complete_absence_withdraws():
    corrected = _split_body([{
        "ticker": "XYZ", "execution_date": "2026-01-05",
        "split_from": 1, "split_to": 2,
    }])
    con = duckdb.connect()
    try:
        free_sources.load_daily_bars(
            con, _bar_body("XYZ", date(2026, 1, 2)),
            session_date=date(2026, 1, 2), fetched_at=FETCHED_BEFORE,
        )
        free_sources.load_splits(con, SPLIT_BODY, fetched_at=FETCHED_AFTER)
        update = free_sources.load_splits(
            con, corrected, fetched_at=FETCHED_AFTER + timedelta(days=1)
        )
        adjusted = free_sources.daily_panel(
            con, date(2026, 1, 2), date(2026, 1, 2), as_of=date(2026, 1, 6)
        ).iloc[0]
        withdrawn = free_sources.reconcile_splits(
            con, observed=set(), start=date(2025, 12, 1), through=date(2026, 1, 6),
            fetched_at=FETCHED_AFTER + timedelta(days=2), source_sha256="a" * 64,
        )
        raw = free_sources.daily_panel(
            con, date(2026, 1, 2), date(2026, 1, 2), as_of=date(2026, 1, 6)
        ).iloc[0]
        state = con.execute(
            "SELECT split_to,status,withdrawn_source_sha256 FROM free_splits"
        ).fetchone()
    finally:
        con.close()

    assert update["updated"] == 1
    assert adjusted["o"] == 50.0
    assert withdrawn == 1
    assert raw["o"] == 100.0
    assert state == (2.0, "withdrawn", "a" * 64)


class Response:
    status_code = 200

    def __init__(self, body=SPLIT_BODY):
        self.content = body


class Session:
    def __init__(self, body=SPLIT_BODY):
        self.urls = []
        self.body = body

    def get(self, url, **_kwargs):
        self.urls.append(url)
        return Response(self.body)


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


def test_split_capture_withdraws_a_past_split_missing_from_complete_refresh(tmp_path):
    database, data_dir = tmp_path / "free.duckdb", tmp_path / "raw"
    capture.capture_massive_splits(
        database=database, data_dir=data_dir, api_key="fixture-key", session=Session(),
        now=lambda: datetime(2026, 1, 6, 7, 30, tzinfo=timezone.utc),
        rate_limit=lambda: None,
    )
    empty = _split_body([])
    result = capture.capture_massive_splits(
        database=database, data_dir=data_dir, api_key="fixture-key", session=Session(empty),
        now=lambda: datetime(2026, 1, 7, 7, 30, tzinfo=timezone.utc),
        rate_limit=lambda: None,
    )
    con = duckdb.connect(str(database), read_only=True)
    try:
        status = con.execute("SELECT status FROM free_splits").fetchone()[0]
    finally:
        con.close()

    assert result["withdrawn"] == 1
    assert status == "withdrawn"


def test_split_cursor_clamps_future_observation_and_overlaps_thirty_days(tmp_path):
    database = tmp_path / "free.duckdb"
    con = duckdb.connect(str(database))
    try:
        free_sources.init_schema(con)
        con.execute(
            """INSERT INTO free_splits
            (ticker,ex_date,split_from,split_to,fetched_at,source_sha256)
            VALUES ('XYZ','2026-02-01',1,2,'2026-01-01',?)""",
            ["b" * 64],
        )
    finally:
        con.close()

    assert capture._split_start(database, date(2026, 1, 6)) == date(2025, 12, 7)


def test_split_parser_rejects_invalid_ratios():
    body = SPLIT_BODY.replace(b'"split_to":4', b'"split_to":0')
    with pytest.raises(free_sources.FreeSourceError, match="split row"):
        free_sources.parse_massive_splits(body)
