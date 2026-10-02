from __future__ import annotations

import json
import multiprocessing
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest
import requests

from engine import free_massive_minute as minute
from engine import free_sources
from tools import free_massive_minute as capture
from tools import free_sources as daily_capture

ET = ZoneInfo("America/New_York")
ALLOWED = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
START, END = date(2026, 9, 28), date(2026, 9, 29)
MANIFEST_SHA = "f" * 64


def _millis(local: datetime) -> int:
    return int(local.replace(tzinfo=ET).astimezone(timezone.utc).timestamp() * 1000)


def _bar(local: datetime, **overrides) -> dict:
    result = {"t": _millis(local), "o": 10.0, "h": 11.0, "l": 9.0, "c": 10.5,
              "v": 1000.0, "vw": 10.2, "n": 25}
    result.update(overrides)
    return result


def _page(ticker: str, bars: list[dict], next_url: str | None = None) -> bytes:
    payload = {"status": "OK", "adjusted": True, "ticker": ticker,
               "resultsCount": len(bars), "results": bars}
    if next_url is not None:
        payload["next_url"] = next_url
    return json.dumps(payload).encode()


class _Response:
    status_code = 200

    def __init__(self, body: bytes):
        self.content = body


class _Session:
    def __init__(self, responses: list[bytes | Exception]):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return _Response(response)


def test_session_tagging_covers_extended_regular_early_close_and_holiday():
    assert minute.session_tag(datetime(2026, 9, 29, 8, 0, tzinfo=ET)) == "pre"
    assert minute.session_tag(datetime(2026, 9, 29, 9, 30, tzinfo=ET)) == "regular"
    assert minute.session_tag(datetime(2026, 9, 29, 16, 0, tzinfo=ET)) == "post"
    assert minute.session_tag(datetime(2026, 11, 27, 12, 59, tzinfo=ET)) == "regular"
    assert minute.session_tag(datetime(2026, 11, 27, 13, 0, tzinfo=ET)) == "post"
    with pytest.raises(free_sources.FreeSourceError, match="outside an NYSE session"):
        minute.session_tag(datetime(2026, 11, 26, 10, 0, tzinfo=ET))


def test_paginated_chunk_is_cached_loaded_and_key_stays_out_of_cache(tmp_path: Path):
    next_url = "https://api.massive.com/v2/aggs/ticker/ABC/range/1/minute/next"
    session = _Session([
        _page("ABC", [_bar(datetime(2026, 9, 28, 8, 0))], next_url),
        _page("ABC", [_bar(datetime(2026, 9, 29, 9, 30))]),
    ])
    con = duckdb.connect()
    calls = []
    try:
        result = capture.capture_chunk(
            con, manifest_sha256=MANIFEST_SHA, ticker="ABC", start=START, end=END,
            api_key="fixture-secret", data_dir=tmp_path, session=session,
            now=lambda: ALLOWED, rate_limit=lambda: calls.append("reserved"),
        )
        stored = con.execute(
            "SELECT ticker,session FROM massive_minute_bars ORDER BY ts_utc"
        ).fetchall()
    finally:
        con.close()
    assert (result["row_count"], result["inserted"]) == (2, 2)
    assert stored == [("ABC", "pre"), ("ABC", "regular")]
    assert [item[0] for item in session.calls] == [session.calls[0][0], next_url]
    assert len(calls) == 2
    assert all(call[1]["headers"]["Authorization"] == "Bearer fixture-secret"
               for call in session.calls)
    assert "fixture-secret" not in "".join(
        path.read_text(errors="ignore") for path in tmp_path.rglob("*") if path.is_file()
    )


def test_interrupted_pagination_resumes_at_saved_next_url(tmp_path: Path):
    next_url = "https://api.massive.com/v2/aggs/ticker/ABC/range/1/minute/next"
    first = _Session([
        _page("ABC", [_bar(datetime(2026, 9, 28, 8, 0))], next_url),
        requests.ConnectionError("interrupted"),
    ])
    con = duckdb.connect()
    try:
        with pytest.raises(free_sources.FreeSourceError, match="request failed"):
            capture.capture_chunk(
                con, manifest_sha256=MANIFEST_SHA, ticker="ABC", start=START, end=END,
                api_key="fixture-secret", data_dir=tmp_path, session=first,
                now=lambda: ALLOWED, rate_limit=lambda: None,
            )
        resumed = _Session([_page("ABC", [_bar(datetime(2026, 9, 29, 9, 30))])])
        result = capture.capture_chunk(
            con, manifest_sha256=MANIFEST_SHA, ticker="ABC", start=START, end=END,
            api_key="fixture-secret", data_dir=tmp_path, session=resumed,
            now=lambda: ALLOWED, rate_limit=lambda: None,
        )
    finally:
        con.close()
    assert result["row_count"] == 2
    assert len(first.calls) == 2
    assert [item[0] for item in resumed.calls] == [next_url]


def test_chunk_refuses_inside_window_before_reserving_or_sending(tmp_path: Path):
    blocked = datetime(2026, 10, 2, 17, 0, tzinfo=timezone.utc)
    session, reservations = _Session([]), []
    con = duckdb.connect()
    try:
        with pytest.raises(capture.MinuteWindowClosed, match="no-call window"):
            capture.capture_chunk(
                con, manifest_sha256=MANIFEST_SHA, ticker="ABC", start=START, end=END,
                api_key="fixture-secret", data_dir=tmp_path, session=session,
                now=lambda: blocked, rate_limit=lambda: reservations.append(1),
            )
    finally:
        con.close()
    assert session.calls == []
    assert reservations == []


def test_minute_main_refuses_missing_private_key_without_printing_it(
    tmp_path: Path, monkeypatch, capsys,
):
    manifest = {"manifest_sha256": MANIFEST_SHA, "ticker_count": 1,
                "requests_estimate": 1, "runtime_at_five_per_minute_hours": 1 / 300,
                "window": {"start": "2026-09-28", "end": "2026-09-29"},
                "chunks": [{"start": "2026-09-28", "end": "2026-09-29"}],
                "tickers": [{"ticker": "ABC"}]}
    monkeypatch.setattr(capture, "prepare_manifest", lambda **_kwargs: manifest)
    monkeypatch.setattr(daily_capture, "MASSIVE_KEY_PATH", tmp_path / "missing.key")
    result = capture.main(["--database", str(tmp_path / "minute.duckdb"),
                           "--data-dir", str(tmp_path / "raw")])
    output = capsys.readouterr().out
    assert result == 2
    assert "missing" in output
    assert "fixture-secret" not in output


def test_manifest_is_frozen_and_prioritized_from_daily_mdv(tmp_path: Path):
    daily_db, data_dir = tmp_path / "daily.duckdb", tmp_path / "minute"
    con = duckdb.connect(str(daily_db))
    try:
        free_sources.init_schema(con)
        con.execute(
            """INSERT INTO free_security_master VALUES
            ('tiingo','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
             '2026-01-01',1,'ABC','NYSE','Stock','USD','2020-01-01',NULL)"""
        )
        for index, session_date in enumerate((date(2026, 9, 25), date(2026, 9, 28))):
            con.execute(
                """INSERT INTO free_daily_bars VALUES
                (?, 'ABC', 2, 2, 2, 2, 1000000, 2, 'massive_grouped_daily',
                 '2026-10-01', ?)""",
                [session_date, f"{index + 1:064x}"],
            )
    finally:
        con.close()
    priority = tmp_path / "priority.txt"
    priority.write_text("ABC\n")
    fixed = datetime(2026, 10, 2, 17, 0, tzinfo=timezone.utc)
    first = capture.prepare_manifest(
        daily_database=daily_db, data_dir=data_dir, priority_tickers_path=priority,
        now=lambda: fixed,
    )
    priority.write_text("ZZZ\n")
    second = capture.prepare_manifest(
        daily_database=daily_db, data_dir=data_dir, priority_tickers_path=priority,
        now=lambda: fixed,
    )
    assert [item["ticker"] for item in first["tickers"][:4]] == ["SPY", "QQQ", "IWM", "ABC"]
    assert first["tickers"][3]["priority"] == "holdout"
    assert first == second


def _limiter_worker(lock_path: str, ready, start, output) -> None:
    ready.put(True)
    start.wait()
    reserved = free_sources.wait_for_massive_rate_limit(
        lock_path=Path(lock_path), interval_seconds=0.2,
    )
    output.put(reserved)


def test_shared_limiter_serializes_two_processes(tmp_path: Path):
    context = multiprocessing.get_context("spawn")
    ready, output, start = context.Queue(), context.Queue(), context.Event()
    processes = [context.Process(
        target=_limiter_worker,
        args=(str(tmp_path / "massive-rate.lock"), ready, start, output),
    ) for _ in range(2)]
    for process in processes:
        process.start()
    assert ready.get(timeout=5) is True
    assert ready.get(timeout=5) is True
    start.set()
    reservations = sorted([output.get(timeout=5), output.get(timeout=5)])
    for process in processes:
        process.join(timeout=5)
        assert process.exitcode == 0
    assert reservations[1] - reservations[0] >= 0.18


def test_existing_daily_capture_uses_shared_limiter(tmp_path: Path, monkeypatch):
    session_date = date(2026, 9, 29)
    monkeypatch.setattr(daily_capture, "massive_window", lambda _now: (session_date, session_date))
    body = json.dumps({
        "status": "OK", "adjusted": True, "resultsCount": 1,
        "results": [{"T": "ABC", "t": 1790640000000, "o": 10, "h": 11,
                     "l": 9, "c": 10.5, "v": 1000, "vw": 10.2}],
    }).encode()
    session, reservations = _Session([body]), []
    result = daily_capture.capture_massive_daily(
        database=tmp_path / "daily.duckdb", data_dir=tmp_path / "raw",
        api_key="fixture-secret", session=session, now=lambda: ALLOWED,
        rate_limit=lambda: reservations.append(1),
    )
    assert result["fetched_sessions"] == 1
    assert reservations == [1]
