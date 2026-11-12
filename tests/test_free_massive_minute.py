from __future__ import annotations

import hashlib
import json
import multiprocessing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest
import requests

from engine import free_massive_minute as minute
from engine import free_sources, raw_payload
from tools import free_massive_minute as capture
from tools import free_sources as daily_capture

# These writers are tested on a converted store; tests/test_raw_payload_legacy.py covers
# the legacy plain encoding they use until the conversion flag is set.
pytestmark = pytest.mark.usefixtures("zstd_raw_payloads")

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
    sealed = list((tmp_path / "raw").glob("*.json.zst"))
    assert len(sealed) == 2
    assert not list((tmp_path / "raw").glob("*.json"))
    assert all(raw_payload.decode(path.read_bytes()) for path in sealed)


def test_interrupted_pagination_resumes_at_saved_next_url(tmp_path: Path):
    next_url = "https://api.massive.com/v2/aggs/ticker/ABC/range/1/minute/next"
    first = _Session([
        _page("ABC", [_bar(datetime(2026, 9, 28, 8, 0))], next_url),
        *[requests.ConnectionError("interrupted") for _ in range(3)],
    ])
    con = duckdb.connect()
    try:
        with pytest.raises(free_sources.FreeSourceError, match="request failed"):
            capture.capture_chunk(
                con, manifest_sha256=MANIFEST_SHA, ticker="ABC", start=START, end=END,
                api_key="fixture-secret", data_dir=tmp_path, session=first,
                now=lambda: ALLOWED, rate_limit=lambda: None, sleep=lambda _s: None,
            )
        resumed = _Session([_page("ABC", [_bar(datetime(2026, 9, 29, 9, 30))])])
        result = capture.capture_chunk(
            con, manifest_sha256=MANIFEST_SHA, ticker="ABC", start=START, end=END,
            api_key="fixture-secret", data_dir=tmp_path, session=resumed,
            now=lambda: ALLOWED + timedelta(seconds=capture.CHUNK_RETRY_SECONDS),
            rate_limit=lambda: None, sleep=lambda _s: None,
        )
    finally:
        con.close()
    assert result["row_count"] == 2
    assert len(first.calls) == 4
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


def test_transient_page_failure_retries_with_rate_limit_and_no_duplicate_receipt(tmp_path):
    client = _Session([requests.Timeout("transient"), _page("ABC", [])])
    reservations, sleeps = [], []
    con = duckdb.connect()
    try:
        result = capture.capture_chunk(
            con, manifest_sha256=MANIFEST_SHA, ticker="ABC", start=START, end=END,
            api_key="fixture-secret", data_dir=tmp_path, session=client,
            now=lambda: ALLOWED, rate_limit=lambda: reservations.append(True), sleep=sleeps.append,
        )
    finally:
        con.close()
    assert result["row_count"] == 0
    assert len(reservations) == len(client.calls) == 2
    assert sleeps == [3.0]
    receipt = capture._read_progress(tmp_path, "ABC", START, END)
    assert receipt["complete"] and len(receipt["pages"]) == 1


def test_retry_rechecks_no_call_window_before_sending():
    instants = iter([ALLOWED, ALLOWED, datetime(2026, 10, 2, 17, tzinfo=timezone.utc)])
    client = _Session([requests.Timeout("transient")])
    with pytest.raises(capture.MinuteWindowClosed):
        capture._request_page(
            client, url="https://api.massive.com/v2/aggs/ticker/ABC", first_url="same",
            api_key="fixture-secret", now=lambda: next(instants),
            rate_limit=lambda: None, sleep=lambda _s: None,
        )
    assert len(client.calls) == 1


def _fake_run(monkeypatch, tmp_path: Path, chunks: int = 3) -> list:
    manifest = {"manifest_sha256": "a" * 64, "tickers": [{"ticker": "ABC"}],
                "chunks": [{"start": f"2026-0{i + 1}-01", "end": f"2026-0{i + 1}-20"}
                           for i in range(chunks)],
                "requests_estimate": chunks, "ticker_count": 1,
                "runtime_at_five_per_minute_hours": 0.0, "window": {}}
    calls = []
    monkeypatch.setattr(capture, "prepare_manifest", lambda **_kwargs: manifest)
    monkeypatch.setattr(daily_capture, "_load_massive_key", lambda: "k")
    monkeypatch.setattr(capture, "_minute_network_permitted", lambda _now: True)

    def chunk(_con, **kwargs):
        calls.append(kwargs["start"])
        return {"ticker": "ABC", "start": str(kwargs["start"]), "inserted": 0}

    monkeypatch.setattr(capture, "capture_chunk", chunk)
    return calls


def _args(tmp_path: Path, *extra: str) -> list[str]:
    return ["--database", str(tmp_path / "minute.duckdb"), "--data-dir", str(tmp_path / "data"),
            "--daily-database", str(tmp_path / "daily.duckdb"), *extra]


def _reject_at(con, tmp_path, body, hours):
    return capture.capture_chunk(
        con, manifest_sha256=MANIFEST_SHA, ticker="ABC", start=START, end=END,
        api_key="fixture-secret", data_dir=tmp_path, session=_Session([body]),
        now=lambda: ALLOWED + timedelta(hours=hours), rate_limit=lambda: None,
    )


def test_cooldown_only_remainder_pauses_with_exit_75(tmp_path, monkeypatch, capsys):
    manifest = {"manifest_sha256": MANIFEST_SHA, "tickers": [{"ticker": "ABC"}],
                "chunks": [{"start": START.isoformat(), "end": END.isoformat()}],
                "requests_estimate": 1, "ticker_count": 1,
                "runtime_at_five_per_minute_hours": 0.0, "window": {}}
    con = duckdb.connect()
    try:
        with pytest.raises(free_sources.FreeSourceError):
            _reject_at(con, tmp_path / "data", _page("ABC", [_bar(
                datetime(2026, 9, 28, 9, 30), o=0)]), 0)
    finally:
        con.close()
    monkeypatch.setattr(capture, "prepare_manifest", lambda **_kwargs: manifest)
    monkeypatch.setattr(daily_capture, "_load_massive_key", lambda: "k")
    monkeypatch.setattr(capture, "_minute_network_permitted", lambda _now: True)
    actual_capture = capture.capture_manifest
    client, sleeps = _Session([]), []

    def run(*args, **kwargs):
        return actual_capture(*args, **kwargs, session=client, now=lambda: ALLOWED,
                              sleep=sleeps.append)

    monkeypatch.setattr(capture, "capture_manifest", run)
    assert capture.main(_args(tmp_path, "--max-runtime-hours", "0.01")) == 75
    result = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert result["status"] == "paused" and result["failed_chunks"] == 1
    assert client.calls == sleeps == []
    assert not (tmp_path / "data" / capture.COMPLETE_FILE).exists()


def test_cooldown_waits_for_earliest_retry_that_fits_runtime(tmp_path, monkeypatch):
    invalid = _page("ABC", [_bar(datetime(2026, 9, 28, 9, 30), o=0)])
    con = duckdb.connect()
    try:
        with pytest.raises(free_sources.FreeSourceError):
            _reject_at(con, tmp_path / "data", invalid, 0)
    finally:
        con.close()
    manifest = {"manifest_sha256": MANIFEST_SHA, "tickers": [{"ticker": "ABC"}],
                "chunks": [{"start": START.isoformat(), "end": END.isoformat()}],
                "requests_estimate": 1}
    clock, sleeps = [ALLOWED], []

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += timedelta(seconds=seconds)

    monkeypatch.setattr(capture, "_minute_network_permitted", lambda _now: True)
    client = _Session([_page("ABC", [_bar(datetime(2026, 9, 28, 9, 30))])])
    result = capture.capture_manifest(
        manifest, database=tmp_path / "minute.duckdb", data_dir=tmp_path / "data",
        api_key="k", session=client, now=lambda: clock[0], sleep=sleep,
        monotonic=lambda: (clock[0] - ALLOWED).total_seconds(), max_runtime_seconds=7200,
        rate_limit=lambda: None,
    )
    assert result["status"] == "complete" and result["failed_chunks"] == 0
    assert sleeps == [3600.0] and len(client.calls) == 1


def test_identical_parser_rejections_need_three_attempts_over_48_hours(tmp_path):
    invalid = _page("ABC", [_bar(datetime(2026, 9, 28, 9, 30), o=0)])
    con = duckdb.connect()
    minute.init_schema(con)
    try:
        for hours in (0, 24, 47):
            with pytest.raises(free_sources.FreeSourceError, match="open is invalid"):
                _reject_at(con, tmp_path, invalid, hours)
            assert "rejected_terminal" not in capture._read_progress(tmp_path, "ABC", START, END)
        result = _reject_at(con, tmp_path, invalid, 48)
        assert result["status"] == "rejected_terminal"
        receipt = capture._read_progress(tmp_path, "ABC", START, END)
        decision = receipt["rejected_terminal"]
        evidence_path = capture._chunk_directory(tmp_path, "ABC", START, END) / (
            f"rejections/{decision['evidence_sha256']}.json")
        evidence_bytes = evidence_path.read_bytes()
        assert hashlib.sha256(evidence_bytes).hexdigest() == decision["evidence_sha256"]
        evidence = json.loads(evidence_bytes)
        assert evidence["reason"] == "Massive minute open is invalid"
        assert [a["attempted_at"] for a in evidence["attempts"]] == [
            (ALLOWED + timedelta(hours=h)).isoformat() for h in (0, 24, 47, 48)]
        assert {a["source_sha256"] for a in evidence["attempts"]} == {
            hashlib.sha256(invalid).hexdigest()}
        for attempt in evidence["attempts"]:
            path = evidence_path.parent.parent / "failures" / (
                f"{attempt['failure_evidence_sha256']}.json")
            assert hashlib.sha256(path.read_bytes()).hexdigest() == attempt["failure_evidence_sha256"]
        skipped = capture.capture_chunk(
            con, manifest_sha256=MANIFEST_SHA, ticker="ABC", start=START, end=END,
            api_key="k", data_dir=tmp_path, session=_Session([]),
            now=lambda: ALLOWED + timedelta(hours=100), rate_limit=lambda: None,
        )
        assert skipped["status"] == "rejected_terminal"
        assert evidence_path.read_bytes() == evidence_bytes
        assert con.execute("SELECT COUNT(*) FROM massive_minute_bars").fetchone() == (0,)
        assert con.execute("SELECT COUNT(*) FROM massive_minute_chunks").fetchone() == (0,)
    finally:
        con.close()


def test_changed_response_or_reason_resets_rejection_attempts(tmp_path):
    bodies = [_page("ABC", [_bar(datetime(2026, 9, 28, 9, 30), o=0, v=v)])
              for v in (1000, 2000)]
    con = duckdb.connect()
    try:
        for hours, body in ((0, bodies[0]), (24, bodies[0]), (48, bodies[1]), (72, bodies[1])):
            with pytest.raises(free_sources.FreeSourceError):
                _reject_at(con, tmp_path, body, hours)
            assert "rejected_terminal" not in capture._read_progress(tmp_path, "ABC", START, END)
        receipt = capture._read_progress(tmp_path, "ABC", START, END)
        assert len(receipt["rejection_attempts"]) == 2
        # A different parser reason also starts a new series.
        changed = _page("ABC", [_bar(datetime(2026, 9, 28, 9, 30), h=0)])
        with pytest.raises(free_sources.FreeSourceError, match="high is invalid"):
            _reject_at(con, tmp_path, changed, 96)
        assert len(capture._read_progress(tmp_path, "ABC", START, END)["rejection_attempts"]) == 1
    finally:
        con.close()


def test_terminal_marker_and_operator_retry_can_load_a_later_valid_response(
    tmp_path, monkeypatch, capsys,
):
    invalid = _page("ABC", [_bar(datetime(2026, 9, 28, 9, 30), o=0)])
    con = duckdb.connect()
    try:
        for hours in (0, 24):
            with pytest.raises(free_sources.FreeSourceError):
                _reject_at(con, tmp_path / "data", invalid, hours)
        assert _reject_at(con, tmp_path / "data", invalid, 48)["status"] == "rejected_terminal"
    finally:
        con.close()
    manifest = {"manifest_sha256": MANIFEST_SHA, "tickers": [{"ticker": "ABC"}],
                "chunks": [{"start": START.isoformat(), "end": END.isoformat()}],
                "requests_estimate": 1, "ticker_count": 1,
                "runtime_at_five_per_minute_hours": 0.0, "window": {}}
    monkeypatch.setattr(capture, "prepare_manifest", lambda **_kwargs: manifest)
    monkeypatch.setattr(daily_capture, "_load_massive_key", lambda: "k")
    monkeypatch.setattr(capture, "_minute_network_permitted", lambda _now: True)
    monkeypatch.setattr(free_sources, "wait_for_massive_rate_limit", lambda **_kwargs: None)
    client = _Session([])
    monkeypatch.setattr(capture.requests, "Session", lambda: client)
    monkeypatch.setattr(client, "close", lambda: None, raising=False)
    assert capture.main(_args(tmp_path)) == 0
    marker = json.loads((tmp_path / "data" / capture.COMPLETE_FILE).read_text())
    assert marker["status"] == "complete_with_rejections"
    assert marker["completed_chunks"] == 0 and marker["rejected_terminal_chunks"] == 1
    assert len(marker["rejections"]) == 1
    rejection = marker["rejections"][0]
    assert {k: rejection[k] for k in ("ticker", "start", "end", "reason")} == {
        "ticker": "ABC", "start": START.isoformat(), "end": END.isoformat(),
        "reason": "Massive minute open is invalid"}
    assert len(rejection["evidence_sha256"]) == 64
    assert capture.completed_manifest(tmp_path / "data") is None
    assert capture.main(_args(tmp_path)) == 0
    summaries = [json.loads(line) for line in capsys.readouterr().out.splitlines()
                 if json.loads(line)["status"] != "prepared"]
    assert all(s["status"] == "complete_with_rejections" and s["rejections"] == [rejection]
               for s in summaries)
    assert client.calls == []
    evidence_paths = list((tmp_path / "data" / "chunks").glob("*/rejections/*.json"))
    original_evidence = [p.read_bytes() for p in evidence_paths]
    client.responses = [_page("ABC", [_bar(datetime(2026, 9, 28, 9, 30))])]
    assert capture.main(_args(tmp_path, "--retry-terminal")) == 0
    assert len(client.calls) == 1
    receipt = capture._read_progress(tmp_path / "data", "ABC", START, END)
    assert receipt["complete"] and "failure" not in receipt
    assert "rejected_terminal" not in receipt
    assert [p.read_bytes() for p in evidence_paths] == original_evidence
    assert capture.completed_manifest(tmp_path / "data") == MANIFEST_SHA


def test_invalid_middle_chunk_preserves_evidence_and_allows_later_chunks(tmp_path):
    manifest = {"manifest_sha256": MANIFEST_SHA,
                "tickers": [{"ticker": ticker} for ticker in ("ABC", "BAD", "XYZ")],
                "chunks": [{"start": START.isoformat(), "end": END.isoformat()}],
                "requests_estimate": 3}
    invalid = _page("BAD", [_bar(datetime(2026, 9, 28, 9, 30)),
                            _bar(datetime(2026, 9, 28, 9, 31), o=0)])
    client = _Session([_page("ABC", [_bar(datetime(2026, 9, 28, 9, 30))]), invalid,
                       _page("XYZ", [_bar(datetime(2026, 9, 28, 9, 30))])])
    reservations, events = [], []
    database, data_dir = tmp_path / "minute.duckdb", tmp_path / "data"
    result = capture.capture_manifest(
        manifest, database=database, data_dir=data_dir, api_key="fixture-secret",
        session=client, now=lambda: ALLOWED, rate_limit=lambda: reservations.append(True),
        progress=events.append, max_runtime_seconds=60,
    )
    assert result["status"] == "paused"
    assert result["completed_chunks"] == 2
    assert result["failed_chunks"] == 1
    assert len(client.calls) == len(reservations) == 3
    receipt = capture._read_progress(data_dir, "BAD", START, END)
    failure = receipt["failure"]
    assert not receipt["complete"] and receipt["pages"] == []
    assert failure["reason"] == "Massive minute open is invalid"
    assert failure["manifest_sha256"] == MANIFEST_SHA
    assert raw_payload.read(data_dir / "raw" / f"{failure['source_sha256']}.json") == invalid
    assert any(event.get("status") == "failed" and event["ticker"] == "BAD" for event in events)
    con = duckdb.connect(str(database), read_only=True)
    try:
        assert con.execute("SELECT ticker FROM massive_minute_chunks ORDER BY ticker").fetchall() == [
            ("ABC",), ("XYZ",),
        ]
        assert con.execute("SELECT ticker FROM massive_minute_bars ORDER BY ticker").fetchall() == [
            ("ABC",), ("XYZ",),
        ]
    finally:
        con.close()
    assert capture.completed_manifest(data_dir) is None

    # A rapid restart skips successful loads and makes no provider calls for the bad chunk.
    restarted, restarted_events = _Session([]), []
    result = capture.capture_manifest(
        manifest, database=database, data_dir=data_dir, api_key="fixture-secret",
        session=restarted, now=lambda: ALLOWED, rate_limit=lambda: reservations.append(True),
        progress=restarted_events.append, max_runtime_seconds=60,
    )
    assert result["status"] == "paused" and result["failed_chunks"] == 1
    assert result["completed_chunks"] == result["skipped_chunks"] == 2
    assert restarted.calls == [] and len(reservations) == 3
    assert len(restarted_events) == 2
    assert restarted_events[0]["status"] == "resumed"
    assert restarted_events[1]["deferred"] is True

    # The next eligible run tries the bad chunk once, then pauses during its cooldown.
    retried = _Session([invalid])
    result = capture.capture_manifest(
        manifest, database=database, data_dir=data_dir, api_key="fixture-secret",
        session=retried, now=lambda: ALLOWED + timedelta(seconds=capture.CHUNK_RETRY_SECONDS),
        rate_limit=lambda: reservations.append(True), max_runtime_seconds=60,
    )
    assert result["status"] == "paused" and result["failed_chunks"] == 1
    assert len(retried.calls) == 1 and len(reservations) == 4
    failures = list(capture._chunk_directory(data_dir, "BAD", START, END).glob("failures/*.json"))
    assert len(failures) == 2
    assert all(json.loads(path.read_text())["reason"] == failure["reason"] for path in failures)

    # A corrected provider response clears the active failure while retaining its evidence.
    corrected = _Session([_page("BAD", [_bar(datetime(2026, 9, 28, 9, 30))])])
    result = capture.capture_manifest(
        manifest, database=database, data_dir=data_dir, api_key="fixture-secret",
        session=corrected, now=lambda: ALLOWED + timedelta(seconds=2 * capture.CHUNK_RETRY_SECONDS),
        rate_limit=lambda: reservations.append(True),
    )
    assert result["status"] == "complete" and result["failed_chunks"] == 0
    assert result["completed_chunks"] == 3 and len(corrected.calls) == 1
    assert len(reservations) == 5
    receipt = capture._read_progress(data_dir, "BAD", START, END)
    assert receipt["complete"] and "failure" not in receipt
    assert all(path.exists() for path in failures)


def test_failed_second_page_resumes_without_loading_any_rejected_chunk_bars(tmp_path):
    next_url = "https://api.massive.com/v2/aggs/ticker/ABC/range/1/minute/next"
    invalid = _page("ABC", [_bar(datetime(2026, 9, 29, 9, 30), o=0)])
    client = _Session([_page("ABC", [_bar(datetime(2026, 9, 28, 9, 30))], next_url), invalid])
    con = duckdb.connect()
    minute.init_schema(con)
    try:
        with pytest.raises(free_sources.FreeSourceError, match="open is invalid"):
            capture.capture_chunk(
                con, manifest_sha256=MANIFEST_SHA, ticker="ABC", start=START, end=END,
                api_key="fixture-secret", data_dir=tmp_path, session=client,
                now=lambda: ALLOWED, rate_limit=lambda: None,
            )
        receipt = capture._read_progress(tmp_path, "ABC", START, END)
        assert len(receipt["pages"]) == 1 and receipt["next_url"] == next_url
        assert receipt["failure"]["url"] == next_url
        assert con.execute("SELECT COUNT(*) FROM massive_minute_bars").fetchone() == (0,)
        resumed = _Session([_page("ABC", [_bar(datetime(2026, 9, 29, 9, 30))])])
        result = capture.capture_chunk(
            con, manifest_sha256=MANIFEST_SHA, ticker="ABC", start=START, end=END,
            api_key="fixture-secret", data_dir=tmp_path, session=resumed,
            now=lambda: ALLOWED + timedelta(seconds=capture.CHUNK_RETRY_SECONDS),
            rate_limit=lambda: None,
        )
    finally:
        con.close()
    assert result["row_count"] == 2
    assert [call[0] for call in resumed.calls] == [next_url]


def test_incomplete_capture_has_distinct_exit_and_no_completion_marker(tmp_path, monkeypatch, capsys):
    _fake_run(monkeypatch, tmp_path)
    result = {"status": "incomplete", "manifest_sha256": MANIFEST_SHA,
              "completed_chunks": 2, "failed_chunks": 1, "reason": "finished with 1 failed chunks"}
    monkeypatch.setattr(capture, "capture_manifest", lambda *_args, **_kwargs: result)
    assert capture.main(_args(tmp_path)) == capture.EXIT_INCOMPLETE == 1
    assert capture.completed_manifest(tmp_path / "data") is None
    assert json.loads(capsys.readouterr().out.splitlines()[-1]) == result


def test_completed_capture_is_marked_and_a_later_start_exits_at_once(tmp_path, monkeypatch, capsys):
    calls = _fake_run(monkeypatch, tmp_path)
    (tmp_path / "data").mkdir()

    assert capture.main(_args(tmp_path)) == 0
    assert len(calls) == 3
    assert capture.completed_manifest(tmp_path / "data") == "a" * 64
    marker = tmp_path / "data" / capture.COMPLETE_FILE
    assert json.loads(marker.read_text())["status"] == "complete"
    assert "rejections" not in json.loads(marker.read_text())
    assert oct(marker.stat().st_mode & 0o777) == "0o600"

    assert capture.main(_args(tmp_path)) == 0
    assert len(calls) == 3
    assert '"reason": "capture already complete"' in capsys.readouterr().out


def test_runtime_bound_pauses_between_chunks_with_exit_75_and_no_marker(tmp_path, monkeypatch):
    calls = _fake_run(monkeypatch, tmp_path)
    (tmp_path / "data").mkdir()
    clock = iter([0.0, 10.0, 7200.0, 7200.0])
    monkeypatch.setattr(capture.time, "monotonic", lambda: next(clock))

    assert capture.main(_args(tmp_path, "--max-runtime-hours", "1")) == capture.EXIT_PAUSED
    assert len(calls) == 1
    assert capture.completed_manifest(tmp_path / "data") is None


def test_runtime_bound_pauses_instead_of_sleeping_through_a_window(tmp_path, monkeypatch):
    calls = _fake_run(monkeypatch, tmp_path)
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(capture, "_minute_network_permitted", lambda _now: False)
    monkeypatch.setattr(capture, "_next_permitted",
                        lambda now: now.replace(year=now.year + 1))
    slept = []
    monkeypatch.setattr(capture.time, "sleep", slept.append)

    assert capture.main(_args(tmp_path, "--max-runtime-hours", "1")) == capture.EXIT_PAUSED
    assert calls == [] and slept == []
