"""Recorded-ZIP tests for SEC bulk point-in-time facts and earnings events."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pytest
import requests

from engine import free_sec_bulk, free_sources
from tools import free_sec_bulk as capture

CIK = 1000
CIK_NAME = "CIK0000001000.json"
FIRST = "0000001000-26-000001"
RESTATED = "0000001000-26-000002"
UNMATCHED = "0000001000-26-000003"
AMENDED = "0000001000-26-000004"
OLD = "0000001000-04-000001"
ALLOWED = datetime(2026, 10, 2, 20, 30, tzinfo=timezone.utc)


def _zip(members: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in members.items():
            archive.writestr(name, body)
    return output.getvalue()


def _write(path: Path, body: bytes) -> Path:
    path.write_bytes(body)
    return path


def _main_submissions() -> bytes:
    payload = {
        "cik": str(CIK),
        "filings": {
            "recent": {
                "accessionNumber": [FIRST, RESTATED, UNMATCHED, AMENDED, "0000001000-26-000005"],
                "filingDate": ["2026-01-10", "2026-02-10", "2026-01-11", "2026-03-10", "2026-03-11"],
                "acceptanceDateTime": [
                    "2026-01-10T15:00:00-05:00", "2026-02-10T16:30:00-05:00", "",
                    "2026-03-10T17:00:00-04:00", "2026-03-11T17:00:00-04:00",
                ],
                "form": ["10-K", "10-K/A", "10-Q", "8-K/A", "8-K"],
                "items": ["", "", "", "2.02,9.01", "5,7,12.02"],
            },
            "files": [{
                "name": "CIK0000001000-submissions-001.json",
                "filingFrom": "2004-01-01", "filingTo": "2004-12-31", "filingCount": 1,
            }],
        },
    }
    return json.dumps(payload).encode()


def _empty_submissions() -> bytes:
    return json.dumps({
        "cik": "2000",
        "filings": {"recent": {
            "accessionNumber": [], "filingDate": [], "acceptanceDateTime": [],
            "form": [], "items": [],
        }, "files": []},
    }).encode()


def _old_submissions() -> bytes:
    return json.dumps({
        "accessionNumber": [OLD, "0000001000-03-000001"],
        "filingDate": ["2004-05-05", "2003-05-05"],
        "acceptanceDateTime": ["2004-05-05T16:01:02-04:00", "2003-05-05T16:01:02-04:00"],
        "form": ["8-K", "8-K"],
        "items": ["2.02", "2.02"],
    }).encode()


def _companyfacts() -> bytes:
    observations = [
        {"start": "2025-01-01", "end": "2025-12-31", "val": 100,
         "accn": FIRST, "fy": 2025, "fp": "FY", "form": "10-K",
         "filed": "2026-01-10", "frame": "CY2025"},
        {"start": "2025-01-01", "end": "2025-12-31", "val": 110,
         "accn": RESTATED, "fy": 2025, "fp": "FY", "form": "10-K/A",
         "filed": "2026-02-10", "frame": "CY2025"},
    ]
    payload = {
        "cik": CIK, "entityName": "Acme",
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {"USD": observations},
                },
                "Assets": {"units": {"USD": [{
                    "end": "2025-12-31", "val": 500, "accn": UNMATCHED,
                    "fy": 2025, "fp": "Q1", "form": "10-Q", "filed": "2026-01-11",
                }]}},
                "InventoryNet": {"units": {"USD": [{
                    "end": "2025-12-31", "val": 5, "accn": FIRST,
                    "fy": 2025, "fp": "FY", "form": "10-K", "filed": "2026-01-10",
                }]}},
            },
        },
    }
    return json.dumps(payload).encode()


def test_recorded_zips_keep_restatements_and_enforce_point_in_time(tmp_path: Path):
    submissions = _write(tmp_path / "submissions.zip", _zip({
        CIK_NAME: _main_submissions(), "CIK0000002000.json": _empty_submissions(),
    }))
    facts = _write(tmp_path / "companyfacts.zip", _zip({CIK_NAME: _companyfacts()}))
    page = _write(tmp_path / "old.json", _old_submissions())
    con = duckdb.connect()
    try:
        loaded = free_sec_bulk.load_submissions_zip(con, submissions)
        assert loaded["page_references"] == 1
        assert free_sec_bulk.pending_submission_pages(con) == [
            ("CIK0000001000-submissions-001.json", CIK)
        ]
        page_result = free_sec_bulk.load_submission_page(
            con, page, name="CIK0000001000-submissions-001.json", cik=CIK,
        )
        assert page_result["events_inserted"] == 1
        fact_result = free_sec_bulk.load_companyfacts_zip(con, facts)
        assert fact_result["facts"] == 3
        assert con.execute("SELECT COUNT(*) FROM sec_facts WHERE concept='revenue'").fetchone()[0] == 2

        assert con.execute(
            "SELECT COUNT(*) FROM sec_fundamentals_asof(?)", ["2026-01-10T19:59:59Z"]
        ).fetchone()[0] == 0
        first = con.execute(
            "SELECT value,accn FROM sec_fundamentals_asof(?) WHERE concept='revenue'",
            ["2026-01-10T20:00:00Z"],
        ).fetchone()
        assert first == (100.0, FIRST)
        restated = con.execute(
            "SELECT value,accn FROM sec_fundamentals_asof(?) WHERE concept='revenue'",
            ["2026-02-10T21:30:00Z"],
        ).fetchone()
        assert restated == (110.0, RESTATED)

        assert con.execute(
            "SELECT COUNT(*) FROM sec_fundamentals_asof(?) WHERE concept='total_assets'",
            ["2026-01-12T04:59:59Z"],
        ).fetchone()[0] == 0
        assert con.execute(
            "SELECT value FROM sec_fundamentals_asof(?) WHERE concept='total_assets'",
            ["2026-01-12T05:00:00Z"],
        ).fetchone()[0] == 500.0
    finally:
        con.close()


def test_item_202_filter_keeps_amendment_and_2004_paged_history(tmp_path: Path):
    path = _write(tmp_path / "submissions.zip", _zip({CIK_NAME: _main_submissions()}))
    con = duckdb.connect()
    try:
        free_sec_bulk.load_submissions_zip(con, path)
        free_sec_bulk.load_submission_page(
            con, _write(tmp_path / "page.json", _old_submissions()),
            name="CIK0000001000-submissions-001.json", cik=CIK,
        )
        events = con.execute(
            "SELECT accession,form,items,acceptance_datetime FROM sec_earnings_events ORDER BY accession"
        ).fetchall()
    finally:
        con.close()
    assert [row[:3] for row in events] == [
        (OLD, "8-K", "2.02"), (AMENDED, "8-K/A", "2.02,9.01"),
    ]
    assert all(row[3].utcoffset() is not None for row in events)


def test_ticker_history_is_copied_read_only_and_attached_to_asof(tmp_path: Path):
    free_database = tmp_path / "free.duckdb"
    free_con = duckdb.connect(str(free_database))
    try:
        free_con.execute("""CREATE TABLE free_cik_ticker_history(
            cik BIGINT,ticker VARCHAR,first_seen DATE,last_seen DATE,source VARCHAR)""")
        free_con.execute("""INSERT INTO free_cik_ticker_history VALUES
            (1000,'ACME','2020-01-01','2026-12-31','insider_submissions')""")
    finally:
        free_con.close()
    con = duckdb.connect()
    try:
        free_sec_bulk.load_submissions_zip(
            con, _write(tmp_path / "submissions.zip", _zip({CIK_NAME: _main_submissions()})),
        )
        free_sec_bulk.load_companyfacts_zip(
            con, _write(tmp_path / "facts.zip", _zip({CIK_NAME: _companyfacts()})),
        )
        assert free_sec_bulk.copy_ticker_history(con, free_database)["inserted"] == 1
        assert con.execute(
            "SELECT ticker FROM sec_fundamentals_asof(?) WHERE concept='revenue'",
            ["2026-02-11T00:00:00Z"],
        ).fetchone()[0] == "ACME"
    finally:
        con.close()
    check = duckdb.connect(str(free_database), read_only=True)
    try:
        assert check.execute("SELECT COUNT(*) FROM free_cik_ticker_history").fetchone()[0] == 1
    finally:
        check.close()


class _Clock:
    def __init__(self):
        self.value = 0.0
        self.sleeps: list[float] = []

    def monotonic(self):
        return self.value

    def sleep(self, seconds: float):
        self.sleeps.append(seconds)
        self.value += seconds


class _Response:
    def __init__(self, body: bytes = b"", *, status: int = 200, headers=None, error=False):
        self.body, self.status_code = body, status
        self.headers, self.error = headers or {}, error
        self.closed = False

    def iter_content(self, _size: int):
        yield self.body
        if self.error:
            raise requests.ConnectionError("fixture interruption")

    def close(self):
        self.closed = True


class _Session:
    def __init__(self, heads=(), gets=()):
        self.heads, self.gets = iter(heads), iter(gets)
        self.started: list[tuple[str, float, dict]] = []
        self.clock: _Clock | None = None

    def head(self, url: str, **kwargs):
        self.started.append(("HEAD", self.clock.monotonic(), kwargs["headers"]))
        return next(self.heads)

    def get(self, url: str, **kwargs):
        self.started.append(("GET", self.clock.monotonic(), kwargs["headers"]))
        return next(self.gets)


def test_bulk_client_paces_head_and_resumes_partial_with_one_session(tmp_path: Path):
    clock = _Clock()
    first_session = _Session(
        heads=[_Response(headers={"Content-Length": "6"}), _Response(headers={"Content-Length": "7"})],
        gets=[_Response(b"abc", headers={"Content-Length": "6"}, error=True)],
    )
    first_session.clock = clock
    client = capture.BulkClient(
        "Fixture Contact fixture@example.com", tmp_path, session=first_session,
        now=lambda: ALLOWED, monotonic=clock.monotonic, sleep=clock.sleep,
    )
    client.head("https://www.sec.gov/first.zip")
    client.head("https://www.sec.gov/second.zip")
    with pytest.raises(free_sources.FreeSourceError, match="interrupted"):
        client.download("https://www.sec.gov/archive.zip", suffix=".zip")
    assert [started for _method, started, _headers in first_session.started] == [0.0, 0.2, 0.4]
    assert clock.sleeps == [0.2, 0.2]
    assert all(call[2]["User-Agent"].endswith("fixture@example.com") for call in first_session.started)
    assert all(call[2]["Accept-Encoding"] == "identity" for call in first_session.started)

    second_session = _Session(gets=[_Response(
        b"def", status=206, headers={"Content-Range": "bytes 3-5/6"},
    )])
    second_session.clock = clock
    resumed = capture.BulkClient(
        "Fixture Contact fixture@example.com", tmp_path, session=second_session,
        now=lambda: ALLOWED, monotonic=clock.monotonic, sleep=clock.sleep,
    ).download("https://www.sec.gov/archive.zip", suffix=".zip")
    assert resumed.path.read_bytes() == b"abcdef"
    assert resumed.source_sha256 == hashlib.sha256(b"abcdef").hexdigest()
    assert resumed.resumed is True
    assert second_session.started[0][2]["Range"] == "bytes=3-"


def test_missing_contact_refuses_before_network_or_database(tmp_path: Path, monkeypatch, capsys):
    def missing():
        raise free_sources.FreeSourceError("SEC contact identity is missing")

    monkeypatch.setattr(capture, "_load_contact", missing)
    database = tmp_path / "sec-bulk.duckdb"
    result = capture.main([
        "capture", "--database", str(database), "--data-dir", str(tmp_path / "raw"),
        "--free-database", str(tmp_path / "free.duckdb"),
    ])
    output = json.loads(capsys.readouterr().out)
    assert result == 2
    assert output["status"] == "failed"
    assert "contact identity" in output["reason"]
    assert not database.exists()
