"""Recorded-fixture tests for P3's isolated free SEC sources."""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pytest

from engine import free_sec, free_sources
from tools import free_sec as capture

ACCESSION = "0000001000-26-000001"
SECOND_ACCESSION = "0000001000-26-000002"
ALLOWED = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
BLOCKED = datetime(2026, 10, 1, 13, 0, tzinfo=timezone.utc)


def _form_index(form: str = "25-NSE", accession: str = ACCESSION) -> bytes:
    return (
        "Description:           Form Type Company Name CIK Date Filed File Name\n"
        "--------------------------------------------------------------------------------\n"
        f"{form:<12} Acme Holdings, Inc.                 1000 2026-01-05 "
        f"edgar/data/1000/{accession}.txt\n"
        "10-K         Not Included LLC                    2000 2026-01-05 "
        "edgar/data/2000/0000002000-26-000001.txt\n"
    ).encode()


FORM_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="https://www.sec.gov/edgar/form25">
  <formData><securityData><exchangeName>Nasdaq Stock Market LLC</exchangeName>
  <securityClassTitle>Common Stock, $0.01 par value</securityClassTitle>
  <tickerSymbol>ACME</tickerSymbol></securityData></formData>
</edgarSubmission>"""


def _insider_zip(
    *, accession: str = ACCESSION, accepted: str = "20260105123000",
    relationship: str = "Director,Officer",
) -> bytes:
    submission = (
        "ACCESSION_NUMBER\tFILING_DATE\tPERIOD_OF_REPORT\tISSUERCIK\tISSUERNAME\t"
        "ISSUERTRADINGSYMBOL\tDOCUMENT_TYPE\tACCEPTANCE_DATETIME\n"
        f"{accession}\t2026-01-05\t2025-12-31\t1000\tAcme Holdings\tACME\t4\t{accepted}\n"
    )
    owner = (
        "ACCESSION_NUMBER\tRPTOWNERCIK\tRPTOWNER_RELATIONSHIP\tRPTOWNER_TITLE\n"
        f"{accession}\t9000\t{relationship}\tChief Executive Officer\n"
    )
    transaction = (
        "ACCESSION_NUMBER\tTRANS_DATE\tTRANS_CODE\tTRANS_SHARES\t"
        "TRANS_PRICEPERSHARE\tTRANS_ACQUIRED_DISP_CD\tSHRS_OWND_FOLWNG_TRANS\t"
        "DIRECT_INDIRECT_OWNERSHIP\n"
        f"{accession}\t2025-12-31\tP\t100.5\t0\tA\t1100.5\tD\n"
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SUBMISSION.tsv", submission)
        archive.writestr("REPORTINGOWNER.tsv", owner)
        archive.writestr("NONDERIV_TRANS.tsv", transaction)
        archive.writestr("README.txt", "recorded fixture")
    return output.getvalue()


def test_form_index_and_primary_xml_parsers_keep_amendments_and_fields():
    rows = free_sec.parse_form_index(_form_index("25-NSE/A"))
    assert rows == [{
        "cik": 1000, "company": "Acme Holdings, Inc.", "form": "25-NSE/A",
        "filed_date": date(2026, 1, 5), "accession": ACCESSION,
    }]
    assert free_sec.parse_form25_xml(FORM_XML) == {
        "exchange": "Nasdaq Stock Market LLC",
        "security_class": "Common Stock, $0.01 par value", "symbol": "ACME",
    }
    assert free_sec.parse_form25_xml(
        FORM_XML.replace(b"Common Stock, $0.01 par value", b"")
    )["security_class"] is None


def test_insider_zip_parses_official_columns_and_availability_rule():
    parsed = free_sec.parse_insider_zip(_insider_zip())
    submission, owner, transaction = (
        parsed["submissions"][0], parsed["owners"][0], parsed["transactions"][0]
    )
    assert submission["filing_date"] == date(2026, 1, 5)
    assert submission["accepted_at"] == datetime(2026, 1, 5, 17, 30, tzinfo=timezone.utc)
    assert submission["available_on"] == date(2026, 1, 5)
    assert transaction["transaction_date"] == date(2025, 12, 31)
    assert transaction["price_per_share"] == 0
    assert owner["is_director"] is True

    legacy = free_sec.parse_insider_zip(
        _insider_zip(relationship="Director,Officer,TenPercentOwnerOther")
    )["owners"][0]
    assert legacy["is_ten_percent_owner"] is True and legacy["is_other"] is True

    no_clock = free_sec.parse_insider_zip(_insider_zip(accepted=""))["submissions"][0]
    assert no_clock["accepted_at"] is None
    assert no_clock["available_on"] == no_clock["filing_date"]
    assert no_clock["available_on"] != transaction["transaction_date"]
    assert not free_sec.insider_row_available(
        no_clock["filing_date"], None, datetime(2026, 1, 5, 23, tzinfo=timezone.utc)
    )
    assert free_sec.insider_row_available(
        no_clock["filing_date"], None, datetime(2026, 1, 6, 5, tzinfo=timezone.utc)
    )
    assert not free_sec.insider_row_available(
        submission["filing_date"], submission["accepted_at"],
        datetime(2026, 1, 5, 17, 29, 59, tzinfo=timezone.utc),
    )
    assert free_sec.insider_row_available(
        submission["filing_date"], submission["accepted_at"], submission["accepted_at"]
    )


def test_sec_loads_are_idempotent_and_build_ticker_history():
    con = duckdb.connect()
    try:
        first_index = free_sec.load_form_index(con, _form_index())
        second_index = free_sec.load_form_index(con, _form_index())
        assert free_sec.load_form_index(con, b"Form Type Company Name\n")["rows"] == 0
        first_detail = free_sec.load_form25_detail(con, ACCESSION, FORM_XML)
        second_detail = free_sec.load_form25_detail(con, ACCESSION, FORM_XML)
        first_zip = free_sec.load_insider_zip(con, _insider_zip())
        second_zip = free_sec.load_insider_zip(con, _insider_zip())
        ticker_body = json.dumps({
            "0": {"cik_str": 1000, "ticker": "ACME", "title": "Acme Holdings"}
        }).encode()
        free_sec.load_company_tickers(con, ticker_body, snapshot_date=date(2026, 10, 1))
        history = con.execute(
            "SELECT cik,ticker,first_seen,last_seen,source FROM free_cik_ticker_history ORDER BY source"
        ).fetchall()
    finally:
        con.close()
    assert (first_index["inserted"], second_index["inserted"]) == (1, 0)
    assert (first_detail["inserted"], second_detail["inserted"]) == (1, 0)
    assert first_zip["submissions_inserted"] == 1
    assert second_zip["submissions_inserted"] == 0
    assert history == [
        (1000, "ACME", date(2026, 10, 1), date(2026, 10, 1), "company_tickers"),
        (1000, "ACME", date(2026, 1, 5), date(2026, 1, 5), "insider_submissions"),
    ]


class _Clock:
    def __init__(self):
        self.value = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds


class _Response:
    status_code = 200

    def __init__(self, body: bytes):
        self.content = body


class _Session:
    def __init__(self, bodies: dict[str, bytes], clock: _Clock, *, fail_urls=()):
        self.bodies, self.clock, self.fail_urls = bodies, clock, set(fail_urls)
        self.started, self.headers = [], []

    def get(self, url: str, **kwargs):
        if url in self.fail_urls:
            raise AssertionError("cached URL attempted a network request")
        self.started.append(self.clock.monotonic())
        self.headers.append(kwargs["headers"])
        return _Response(self.bodies[url])


def test_sec_client_paces_parallel_requests_and_resumes_by_url_and_hash(tmp_path: Path):
    urls = ["https://www.sec.gov/a", "https://www.sec.gov/b"]
    clock, bodies = _Clock(), {urls[0]: b"first", urls[1]: b"second"}
    session = _Session(bodies, clock)
    client = capture.SecClient(
        "Fixture Contact fixture@example.com", tmp_path, session=session,
        now=lambda: ALLOWED, monotonic=clock.monotonic, sleep=clock.sleep,
    )
    assert [response.body for response in client.get_many(urls)] == [b"first", b"second"]
    assert session.started == [0.0, 0.2]
    assert clock.sleeps == [0.2]
    assert all(headers["Accept-Encoding"] == "gzip, deflate" for headers in session.headers)
    resumed = capture.SecClient(
        "Fixture Contact fixture@example.com", tmp_path,
        session=_Session(bodies, clock, fail_urls=urls), now=lambda: ALLOWED,
    )
    assert all(resumed.get(url).resumed for url in urls)


def test_insider_batch_stops_at_window_and_resumes_without_refetch(tmp_path: Path):
    quarters = [(2026, 1), (2026, 2)]
    urls = [capture.INSIDER_URL.format(year=y, quarter=q) for y, q in quarters]
    bodies = {urls[0]: _insider_zip(), urls[1]: _insider_zip(accession=SECOND_ACCESSION)}
    calls = iter([ALLOWED, ALLOWED, ALLOWED, BLOCKED])
    first_session, clock = _Session(bodies, _Clock()), _Clock()
    client = capture.SecClient(
        "Fixture Contact fixture@example.com", tmp_path / "raw", session=first_session,
        now=lambda: next(calls), monotonic=clock.monotonic, sleep=clock.sleep,
    )
    with pytest.raises(free_sources.FreeSourceError, match="no-call window"):
        capture.capture_insiders(client, tmp_path / "free.duckdb", quarters=quarters)
    assert first_session.started == [0.0]

    second_session = _Session(bodies, clock, fail_urls=[urls[0]])
    result = capture.capture_insiders(
        capture.SecClient(
            "Fixture Contact fixture@example.com", tmp_path / "raw", session=second_session,
            now=lambda: ALLOWED, monotonic=clock.monotonic, sleep=clock.sleep,
        ),
        tmp_path / "free.duckdb", quarters=quarters,
    )
    assert result["quarters"] == 2
    assert result["resumed"] == 1
    assert second_session.started == [clock.value]


def test_missing_contact_refuses_before_network_or_database(tmp_path: Path, monkeypatch, capsys):
    missing = tmp_path / "missing.env"
    monkeypatch.setattr(capture, "CONTACT_PATH", missing)
    database = tmp_path / "free.duckdb"
    result = capture.main([
        "tickers", "--database", str(database), "--data-dir", str(tmp_path / "raw")
    ])
    output = json.loads(capsys.readouterr().out)
    assert result == 2
    assert output["status"] == "failed"
    assert "contact identity" in output["reason"]
    assert not database.exists()


def test_audit_counts_mapping_overlap_and_quality(tmp_path: Path):
    free_database, store = tmp_path / "free.duckdb", tmp_path / "store.duckdb"
    con = duckdb.connect(str(free_database))
    try:
        free_sources.init_schema(con)
        con.execute("""INSERT INTO free_security_master VALUES
            ('tiingo_supported_tickers','hash',TIMESTAMP '2026-10-01',2,'ACME','NASDAQ',
             'Stock','USD',DATE '2020-01-01',DATE '2026-01-07')""")
        free_sec.load_form_index(con, _form_index())
        free_sec.load_form25_detail(con, ACCESSION, FORM_XML)
        free_sec.load_insider_zip(con, _insider_zip())
    finally:
        con.close()
    con = duckdb.connect(str(store))
    try:
        con.execute("CREATE TABLE prices(ticker VARCHAR,date DATE)")
        con.execute("""INSERT INTO prices VALUES ('ACME','2026-01-02'),('ACME','2026-01-05'),
            ('ACME','2026-01-06'),('ACME','2026-01-07')""")
    finally:
        con.close()
    result = capture.audit(free_database, store)
    assert result["notices"] == [{
        "year": 2026, "form25": 0, "form25_nse": 1, "total": 1,
        "mapped": 1, "mapped_share": 1.0,
    }]
    assert result["tiingo_end_overlap"][0]["within_10_sessions"] == 1
    assert result["insiders"][0]["purchases"] == 1
    assert result["insiders"][0]["store_share"] == 1.0
    assert result["insiders"][0]["purchase_store_share"] == 1.0
    assert result["quality"]["zero_or_missing_prices"] == 1
