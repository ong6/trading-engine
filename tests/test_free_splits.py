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


def _split_body(rows: list[dict], *, next_url: str | None = None) -> bytes:
    payload = {
        "status": "OK", "request_id": "recorded-split-page",
        "count": len(rows), "results": rows,
    }
    if next_url is not None:
        payload["next_url"] = next_url
    return json.dumps(payload, separators=(",", ":")).encode()


def _five_splits() -> list[dict]:
    return [
        {"ticker": f"S{index}", "execution_date": f"2026-01-0{index + 1}",
         "split_from": 1, "split_to": 2}
        for index in range(5)
    ]


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


def test_split_correction_updates_the_active_ratio():
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
        state = con.execute("SELECT split_to,status FROM free_splits").fetchone()
    finally:
        con.close()

    assert update["updated"] == 1
    assert adjusted["o"] == 50.0
    assert state == (2.0, "active")


class Response:
    def __init__(self, body=SPLIT_BODY, *, status_code=200):
        self.content = body
        self.status_code = status_code


class Session:
    def __init__(self, body=SPLIT_BODY, *, status_code=200):
        self.urls = []
        self.body = body
        self.status_code = status_code

    def get(self, url, **_kwargs):
        self.urls.append(url)
        return Response(self.body, status_code=self.status_code)


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


def _capture_splits(database, data_dir, body, day, *, status_code=200, max_pages=2):
    return capture.capture_massive_splits(
        database=database, data_dir=data_dir, api_key="fixture-key",
        session=Session(body, status_code=status_code),
        now=lambda: datetime(2026, 1, day, 7, 30, tzinfo=timezone.utc),
        rate_limit=lambda: None, max_pages=max_pages,
    )


def test_split_withdrawal_requires_two_safe_complete_absences_and_newer_reactivation(tmp_path):
    database, data_dir = tmp_path / "free.duckdb", tmp_path / "raw"
    all_rows = _five_splits()
    initial_body = _split_body(all_rows)
    absent_body = _split_body(all_rows[1:])
    con = duckdb.connect(str(database))
    try:
        free_sources.load_daily_bars(
            con, _bar_body("S0", date(2025, 12, 30)),
            session_date=date(2025, 12, 30),
            fetched_at=datetime(2025, 12, 30, 22, tzinfo=timezone.utc),
        )
    finally:
        con.close()
    _capture_splits(database, data_dir, initial_body, 6)
    first = _capture_splits(database, data_dir, absent_body, 7)
    con = duckdb.connect(str(database), read_only=True)
    try:
        pending_adjusted = free_sources.daily_panel(
            con, date(2025, 12, 30), date(2025, 12, 30), as_of=date(2026, 1, 7)
        ).iloc[0]["o"]
    finally:
        con.close()
    second = _capture_splits(database, data_dir, absent_body, 8)
    con = duckdb.connect(str(database))
    try:
        status = con.execute(
            "SELECT status FROM free_splits WHERE ticker='S0'"
        ).fetchone()[0]
        withdrawn_raw = free_sources.daily_panel(
            con, date(2025, 12, 30), date(2025, 12, 30), as_of=date(2026, 1, 8)
        ).iloc[0]["o"]
        old_replay = free_sources.load_splits(
            con, initial_body, fetched_at=datetime(2026, 1, 6, 7, 30, tzinfo=timezone.utc)
        )
        still_withdrawn = con.execute(
            "SELECT status FROM free_splits WHERE ticker='S0'"
        ).fetchone()[0]
        newer = free_sources.load_splits(
            con, initial_body, fetched_at=datetime(2026, 1, 9, 7, 30, tzinfo=timezone.utc)
        )
        reactivated = con.execute(
            "SELECT status FROM free_splits WHERE ticker='S0'"
        ).fetchone()[0]
    finally:
        con.close()

    assert (first["pending"], first["withdrawn"], first["alarm"]) == (1, 0, None)
    assert (second["pending"], second["withdrawn"], second["alarm"]) == (0, 1, None)
    assert pending_adjusted == 50.0
    assert withdrawn_raw == 100.0
    assert status == "withdrawn"
    assert old_replay["updated"] == 0 and still_withdrawn == "withdrawn"
    assert newer["updated"] == 5 and reactivated == "active"


def test_empty_complete_response_with_active_splits_alarms_without_pending(tmp_path, caplog):
    database, data_dir = tmp_path / "free.duckdb", tmp_path / "raw"
    _capture_splits(database, data_dir, _split_body(_five_splits()), 6)

    result = _capture_splits(database, data_dir, _split_body([]), 7)
    con = duckdb.connect(str(database), read_only=True)
    try:
        statuses = con.execute("SELECT DISTINCT status FROM free_splits").fetchall()
    finally:
        con.close()

    assert result["alarm"] and "empty complete response" in result["alarm"]
    assert statuses == [("active",)]
    assert "ALARM empty complete response" in caplog.text


def test_suspicious_absence_share_alarms_without_state_change(tmp_path):
    database, data_dir = tmp_path / "free.duckdb", tmp_path / "raw"
    rows = _five_splits()
    _capture_splits(database, data_dir, _split_body(rows), 6)

    result = _capture_splits(database, data_dir, _split_body(rows[2:]), 7)
    con = duckdb.connect(str(database), read_only=True)
    try:
        statuses = con.execute("SELECT DISTINCT status FROM free_splits").fetchall()
    finally:
        con.close()

    assert result["alarm"] and "exceeds 3 or 20%" in result["alarm"]
    assert statuses == [("active",)]


@pytest.mark.parametrize(
    ("body", "status_code", "match"),
    [
        (b'{"status":"OK","count":0}', 200, "envelope"),
        (_split_body([]), 429, "HTTP 429"),
    ],
)
def test_incomplete_or_http_failure_never_advances_withdrawal(
    tmp_path, body, status_code, match,
):
    database, data_dir = tmp_path / "free.duckdb", tmp_path / "raw"
    _capture_splits(database, data_dir, _split_body(_five_splits()), 6)

    with pytest.raises(free_sources.FreeSourceError, match=match):
        _capture_splits(database, data_dir, body, 7, status_code=status_code)
    con = duckdb.connect(str(database), read_only=True)
    try:
        statuses = con.execute("SELECT DISTINCT status FROM free_splits").fetchall()
    finally:
        con.close()
    assert statuses == [("active",)]


def test_page_cap_overflow_never_advances_withdrawal(tmp_path):
    database, data_dir = tmp_path / "free.duckdb", tmp_path / "raw"
    rows = _five_splits()
    _capture_splits(database, data_dir, _split_body(rows), 6)
    next_url = "https://api.massive.com/v3/reference/splits?cursor=next"

    with pytest.raises(free_sources.FreeSourceError, match="exceeded"):
        _capture_splits(
            database, data_dir, _split_body(rows[1:], next_url=next_url), 7,
            max_pages=1,
        )
    con = duckdb.connect(str(database), read_only=True)
    try:
        status = con.execute(
            "SELECT status FROM free_splits WHERE ticker='S0'"
        ).fetchone()[0]
    finally:
        con.close()
    assert status == "active"


def test_full_page_without_next_url_is_incomplete(tmp_path, monkeypatch):
    database, data_dir = tmp_path / "free.duckdb", tmp_path / "raw"
    rows = _five_splits()
    _capture_splits(database, data_dir, _split_body(rows), 6)
    monkeypatch.setattr(free_sources, "MAX_SPLIT_RESULTS", 4)

    with pytest.raises(free_sources.FreeSourceError, match="full page.*incomplete"):
        _capture_splits(database, data_dir, _split_body(rows[1:]), 7)
    con = duckdb.connect(str(database), read_only=True)
    try:
        status = con.execute(
            "SELECT status FROM free_splits WHERE ticker='S0'"
        ).fetchone()[0]
    finally:
        con.close()
    assert status == "active"


def test_out_of_window_split_is_never_marked_pending():
    con = duckdb.connect()
    try:
        free_sources.load_splits(con, SPLIT_BODY, fetched_at=FETCHED_AFTER)
        result = free_sources.reconcile_splits(
            con, observed=set(), start=date(2026, 1, 6), through=date(2026, 1, 7),
            fetched_at=FETCHED_AFTER + timedelta(days=1), source_sha256="c" * 64,
        )
        status = con.execute("SELECT status FROM free_splits").fetchone()[0]
    finally:
        con.close()

    assert result == {"pending": 0, "withdrawn": 0, "alarm": None}
    assert status == "active"


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
