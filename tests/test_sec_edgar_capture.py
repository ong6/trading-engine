"""SEC acceptance-time forward capture tests."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from server import sec_edgar_capture
from tools import sec_edgar_capture as sec_tool

NOW = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)


def _response(payload, *, seconds=0):
    return sec_edgar_capture.Response(
        json.dumps(payload).encode(), "application/json", 200, NOW,
        NOW + timedelta(seconds=seconds),
    )


def _mapping():
    return _response({"0": {"cik_str": 320193, "ticker": "AAPL",
                            "title": "Apple Inc."}})


def _submissions(*, accepted="2026-09-22T16:30:01.000Z"):
    return _response({
        "cik": "0000320193", "filings": {"recent": {
            "accessionNumber": ["0000320193-26-000001", "0000320193-26-000002"],
            "filingDate": ["2026-09-22", "2026-09-22"],
            "reportDate": ["2026-06-30", "2026-09-22"],
            "acceptanceDateTime": [accepted, "2026-09-22T17:00:00.000Z"],
            "form": ["10-Q", "4"],
            "primaryDocument": ["aapl-20260630.htm", "ownership.xml"],
        }},
    }, seconds=1)


def test_sec_capture_retains_acceptance_time_and_current_map_limit(con):
    calls = []

    def fetch(url):
        calls.append(url)
        return _mapping() if url == sec_edgar_capture.TICKERS_URL else _submissions()

    result = sec_edgar_capture.capture(
        con, ["AAPL"], fetch=fetch, sleep=lambda _seconds: None,
        ingested_at=NOW + timedelta(seconds=2),
    )

    assert result == {
        "status": "complete", "ticker_count": 1, "request_count": 2,
        "filing_fact_count": 1, "failures": [],
        "historical_membership_authority": False, "execution_authority": "none",
    }
    assert len(calls) == 2
    filing = con.execute(
        "SELECT event_at,published_at,available_at,normalized_payload "
        "FROM bitemporal_facts WHERE fact_type LIKE 'sec.filing:%'"
    ).fetchone()
    assert filing[:3] == (datetime(2026, 6, 30), datetime(2026, 9, 22, 16, 30, 1),
                          NOW.replace(tzinfo=None) + timedelta(seconds=1))
    assert json.loads(filing[3])["accession"] == "0000320193-26-000001"
    assert con.execute("SELECT COUNT(*) FROM source_response_receipts").fetchone() == (2,)


def test_sec_capture_keeps_invalid_response_receipt_but_no_filing(con):
    def fetch(url):
        return _mapping() if url == sec_edgar_capture.TICKERS_URL else _response({"bad": True}, seconds=1)

    result = sec_edgar_capture.capture(
        con, ["AAPL"], fetch=fetch, sleep=lambda _seconds: None,
        ingested_at=NOW + timedelta(seconds=2),
    )

    assert result["status"] == "partial" and len(result["failures"]) == 1
    assert "receipt_sha256" in result["failures"][0]
    assert con.execute(
        "SELECT COUNT(*) FROM bitemporal_facts WHERE fact_type LIKE 'sec.filing:%'"
    ).fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM source_response_receipts").fetchone() == (2,)


def test_sec_filing_rejects_acceptance_date_mismatch():
    bad = _submissions(accepted="2026-09-23T00:00:00Z")
    try:
        sec_edgar_capture.filing_facts(bad, "AAPL", "0000320193")
    except sec_edgar_capture.SecCaptureError as exc:
        assert "identity" in str(exc)
    else:
        raise AssertionError("acceptance outside filing date must fail")


def test_sec_fetch_requires_operator_contact_identity(monkeypatch):
    monkeypatch.delenv("TRADING_ENGINE_SEC_USER_AGENT", raising=False)
    try:
        sec_edgar_capture._user_agent()
    except sec_edgar_capture.SecCaptureError as exc:
        assert "contact identity is required" in str(exc)
    else:
        raise AssertionError("SEC fetch must not run without an operator contact identity")
    monkeypatch.setenv("TRADING_ENGINE_SEC_USER_AGENT", "unmonitored-identity")
    try:
        sec_edgar_capture._user_agent()
    except sec_edgar_capture.SecCaptureError:
        pass
    else:
        raise AssertionError("SEC identity must include a monitored email contact")
    monkeypatch.setenv("TRADING_ENGINE_SEC_USER_AGENT", "Research Example contact@example.test")
    assert sec_edgar_capture._user_agent() == os.environ["TRADING_ENGINE_SEC_USER_AGENT"]


def test_sec_cli_waits_without_a_candidate_cohort(tmp_path, capsys):
    database = tmp_path / "empty.duckdb"
    from engine.lib import db

    con = db.connect(database)
    con.close()
    assert sec_tool.main(["--database", str(database)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "waiting"
    assert result["historical_membership_authority"] is False
