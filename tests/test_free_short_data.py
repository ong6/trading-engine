from __future__ import annotations

import io
import json
import zipfile
from datetime import date, datetime, timezone

import duckdb
import pytest

from engine import free_short_data
from tools import free_short_data as tool

INGESTED = datetime(2026, 10, 2, 20, 0, tzinfo=timezone.utc)


def _zip(name: str, text: str) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(name, text)
    return output.getvalue()


def _finra_current() -> bytes:
    return (
        "accountingYearMonthNumber|symbolCode|issueName|issuerServicesGroupExchangeCode|"
        "marketClassCode|currentShortPositionQuantity|previousShortPositionQuantity|"
        "stockSplitFlag|averageDailyVolumeQuantity|daysToCoverQuantity|revisionFlag|"
        "changePercent|changePreviousNumber|settlementDate\n"
        "20260915|TEST|Synthetic Corporation|Q|NASDAQ|1200|1000||300|4.0|||200|2026-09-15\n"
    ).encode()


def test_finra_current_and_legacy_parsing_uses_official_lag():
    current = free_short_data.parse_finra_short_interest(_finra_current())
    legacy = free_short_data.parse_finra_short_interest(
        b"Security Name|Security Symbol|OTC Market|Current Shares Short|"
        b"Previous Report Shares Short|Change in Shares Short from Previous Report|"
        b"Percent Change from Previous Report|Average Daily Share Volume|Days to Cover\n"
        b"Synthetic Old|OLDX|u|30|20|10|50|5|6\n",
        settlement_date=date(2014, 11, 14),
    )
    assert current[0] == {
        "source_row": 2,
        "settlement_date": date(2026, 9, 15),
        "publication_date": date(2026, 9, 24),
        "symbol": "TEST",
        "issue_name": "Synthetic Corporation",
        "exchange": "Q",
        "market_class": "NASDAQ",
        "current_short": 1200,
        "previous_short": 1000,
        "average_daily_volume": 300,
        "days_to_cover": 4,
        "revision_flag": None,
    }
    assert legacy[0]["settlement_date"] == date(2014, 11, 14)
    assert legacy[0]["publication_date"] == date(2014, 11, 25)
    assert legacy[0]["market_class"] == "u"

    standardized = free_short_data.parse_finra_short_interest(
        b"issueName|issueSymbolIdentifier|marketCategoryCode|currentShortShareNumber|"
        b"previousShortShareNumber|percentageChangefromPreviousShort|changePercent|"
        b"averageShortShareNumber|daysToCoverNumber\n"
        b"Synthetic Middle|MIDX|u|40|30|10|33.33|8|5.00\n",
        settlement_date=date(2019, 6, 14),
    )
    assert standardized[0]["current_short"] == 40
    assert standardized[0]["days_to_cover"] == 5


def test_sec_ftd_parser_supports_archive_trailer_and_missing_price():
    body = _zip(
        "fails.txt",
        "SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE\n"
        "20260901|SYNTH0001|TEST|25|Synthetic Corporation|1.25\n"
        "20260916|SYNTH0002|GONE\x00\x00|40|Synthetic | Delisted|.\n"
        "Trailer record count 2\nTrailer total quantity of shares 65\n",
    )
    rows = free_short_data.parse_sec_ftd(body)
    assert [row["publication_date"] for row in rows] == [date(2026, 9, 30), date(2026, 10, 15)]
    assert rows[0]["quantity"] == 25
    assert rows[1]["symbol"] == "GONE"
    assert rows[1]["issuer_name"] == "Synthetic | Delisted"
    assert rows[1]["price"] is None
    assert free_short_data.ftd_publication_date(date(2008, 4, 3)) == date(2008, 6, 30)


@pytest.mark.parametrize(
    ("venue", "header", "row", "published"),
    [
        ("Nasdaq", "Symbol|Security Name|Market Category|Reg SHO Threshold Flag|Rule 3210|Filler",
         "TEST|Synthetic Corporation|Q|Y|N|", date(2026, 10, 1)),
        ("NYSE", "Symbol|Security Name|Market Category|Reg SHO Threshold Flag|Filler|Filler",
         "TEST|Synthetic Corporation|NYSE|Y||||", date(2026, 10, 1)),
        ("Cboe", "Symbol|CompanyName", "TEST|Synthetic Corporation", date(2026, 10, 2)),
    ],
)
def test_exchange_regsho_parsers(venue, header, row, published):
    stamp = "20261002030418" if venue == "Cboe" else "20261001230024|||||"
    rows = free_short_data.parse_regsho_text(
        f"{header}\r\n{row}\r\n{stamp}\r\n".encode(), venue=venue,
        trade_date=date(2026, 10, 1),
    )
    assert rows[0]["venue"] == venue
    assert rows[0]["symbol"] == "TEST"
    assert rows[0]["publication_date"] == published


def test_exchange_regsho_preserves_missing_security_name():
    rows = free_short_data.parse_regsho_text(
        b"Symbol|Security Name|Market Category|Reg SHO Threshold Flag|Filler|Filler\n"
        b"AHD||NYSE|Y||\n20110223000000\n",
        venue="NYSE", trade_date=date(2011, 2, 22),
    )
    assert rows[0]["security_name"] is None


def test_finra_otc_threshold_parser():
    body = json.dumps([{
        "tradeDate": "2026-10-01", "issueSymbolIdentifier": "TEST",
        "issueName": "Synthetic Corporation", "marketCategoryDescription": "Other OTC",
        "regShoThresholdFlag": "N", "rule4320Flag": "Y",
    }]).encode()
    row = free_short_data.parse_finra_otc_threshold(body, trade_date=date(2026, 10, 1))[0]
    assert (row["venue"], row["reg_sho_flag"], row["rule_4320_flag"]) == (
        "FINRA OTC", "N", "Y"
    )


def test_asof_macro_never_exposes_a_row_before_publication():
    con = duckdb.connect(":memory:")
    try:
        rows = free_short_data.parse_finra_short_interest(_finra_current())
        first = free_short_data.load_rows(
            con, "finra_short_interest", _finra_current(), rows, ingested_at=INGESTED
        )
        second = free_short_data.load_rows(
            con, "finra_short_interest", _finra_current(), rows, ingested_at=INGESTED
        )
        assert first["inserted"] == 1
        assert second["inserted"] == 0
        ftd_body = _zip(
            "fails.txt",
            "SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE\n"
            "20260901|SYNTH0001|TEST|25|Synthetic Corporation|1.25\n",
        )
        free_short_data.load_rows(
            con, "sec_fails_to_deliver", ftd_body,
            free_short_data.parse_sec_ftd(ftd_body), ingested_at=INGESTED,
        )
        threshold_body = b"Symbol|CompanyName\nTEST|Synthetic Corporation\n20261002030418\n"
        free_short_data.load_rows(
            con, "regsho_threshold", threshold_body,
            free_short_data.parse_regsho_text(
                threshold_body, venue="Cboe", trade_date=date(2026, 10, 1)
            ), ingested_at=INGESTED,
        )
        assert con.execute("SELECT COUNT(*) FROM short_data_asof(DATE '2026-09-23')").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM short_data_asof(DATE '2026-09-24')").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM short_data_asof(DATE '2026-09-30')").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM short_data_asof(DATE '2026-10-02')").fetchone()[0] == 3
    finally:
        con.close()


def test_symbol_date_mapping_flags_reference_collisions(tmp_path):
    short_db, reference_db = tmp_path / "short.duckdb", tmp_path / "reference.duckdb"
    con = duckdb.connect(str(short_db))
    rows = free_short_data.parse_finra_short_interest(_finra_current())
    free_short_data.load_rows(con, "finra_short_interest", _finra_current(), rows, ingested_at=INGESTED)
    con.close()
    ref = duckdb.connect(str(reference_db))
    ref.execute("""CREATE TABLE free_security_master (
        source VARCHAR,source_sha256 VARCHAR,fetched_at TIMESTAMP,source_row BIGINT,
        ticker VARCHAR,exchange VARCHAR,asset_type VARCHAR,price_currency VARCHAR,
        start_date DATE,end_date DATE)""")
    ref.execute("""INSERT INTO free_security_master VALUES
        ('tiingo','hash',TIMESTAMP '2026-10-01',1,'TEST','NASDAQ','Stock','USD',
         DATE '2020-01-01',DATE '2026-10-01')""")
    ref.execute("""CREATE VIEW free_cik_ticker_history AS
        SELECT * FROM (VALUES
          (1::BIGINT,'TEST',DATE '2020-01-01',DATE '2026-10-01','insider_submissions'),
          (2::BIGINT,'TEST',DATE '2021-01-01',DATE '2026-10-01','insider_submissions'))
        t(cik,ticker,first_seen,last_seen,source)""")
    ref.execute("""CREATE TABLE free_company_tickers (
        cik BIGINT,ticker VARCHAR,company VARCHAR,snapshot_date DATE,
        source_sha256 VARCHAR,source_row BIGINT)""")
    ref.close()
    result = free_short_data.map_tickers(short_db, reference_db)
    assert result == {"total": 1, "matched": 1, "collisions": 1, "match_rate": 1.0}
    con = duckdb.connect(str(short_db), read_only=True)
    try:
        assert con.execute("SELECT mapped_ticker,ticker_collision FROM short_data_asof(DATE '2026-10-01')").fetchone() == ("TEST", True)
    finally:
        con.close()


def test_symbol_normalization_maps_only_inside_reference_interval(tmp_path):
    assert free_short_data.normalize_symbol("brk.b") == "BRKB"
    short_db, reference_db = tmp_path / "short.duckdb", tmp_path / "reference.duckdb"
    con = duckdb.connect(str(short_db))
    current = _finra_current().replace(b"TEST", b"BRKB")
    rows = free_short_data.parse_finra_short_interest(current)
    free_short_data.load_rows(con, "finra_short_interest", current, rows, ingested_at=INGESTED)
    old = _finra_current().replace(b"TEST", b"OLDA").replace(b"20260915", b"20190915").replace(
        b"2026-09-15", b"2019-09-15"
    )
    free_short_data.load_rows(
        con, "finra_short_interest", old, free_short_data.parse_finra_short_interest(old),
        ingested_at=INGESTED,
    )
    company_early = _finra_current().replace(b"TEST", b"NEWC")
    company_current = company_early.replace(b"20260915", b"20261001").replace(
        b"2026-09-15", b"2026-10-01"
    )
    for body in (company_early, company_current):
        free_short_data.load_rows(
            con, "finra_short_interest", body,
            free_short_data.parse_finra_short_interest(body), ingested_at=INGESTED,
        )
    con.close()
    ref = duckdb.connect(str(reference_db))
    ref.execute("""CREATE TABLE free_security_master (
        source VARCHAR,source_sha256 VARCHAR,fetched_at TIMESTAMP,source_row BIGINT,
        ticker VARCHAR,exchange VARCHAR,asset_type VARCHAR,price_currency VARCHAR,
        start_date DATE,end_date DATE)""")
    ref.execute("""INSERT INTO free_security_master VALUES
        ('tiingo','hash',TIMESTAMP '2026-10-01',1,'BRK-B','NYSE','Stock','USD',
         DATE '2000-01-01',DATE '2026-10-01'),
        ('tiingo','hash',TIMESTAMP '2026-10-01',2,'OLD-A','NYSE','Stock','USD',
         DATE '2020-01-01',DATE '2026-10-01')""")
    ref.execute("""CREATE VIEW free_cik_ticker_history AS
        SELECT * FROM (VALUES (1::BIGINT,'BRK.B',DATE '2000-01-01',DATE '2026-10-01',
          'insider_submissions')) t(cik,ticker,first_seen,last_seen,source)""")
    ref.execute("""CREATE TABLE free_company_tickers (
        cik BIGINT,ticker VARCHAR,company VARCHAR,snapshot_date DATE,
        source_sha256 VARCHAR,source_row BIGINT)""")
    ref.execute("""INSERT INTO free_company_tickers VALUES
        (2,'NEW.C','Synthetic Current',DATE '2026-10-01','company-hash',1)""")
    ref.close()
    result = free_short_data.map_tickers(short_db, reference_db)
    assert result["matched"] == 2
    con = duckdb.connect(str(short_db), read_only=True)
    try:
        assert con.execute("""SELECT s.symbol,m.mapped_ticker,m.match_basis
            FROM short_ticker_map m JOIN finra_short_interest s
              USING(source_sha256,source_row) ORDER BY s.settlement_date,s.symbol""").fetchall() == [
                ("OLDA", None, "unmatched"),
                ("BRKB", "BRK-B", "tiingo+cik_normalized"),
                ("NEWC", None, "unmatched"),
                ("NEWC", "NEWC", "company_tickers_asof"),
            ]
    finally:
        con.close()


class _FakeResponse:
    status_code = 200

    def __init__(self, content: bytes):
        self.content = content


class _FakeSession:
    def __init__(self, content: bytes):
        self.content, self.calls = content, 0

    def request(self, *args, **kwargs):
        self.calls += 1
        return _FakeResponse(self.content)


def test_cached_client_resumes_from_sha_verified_raw(tmp_path):
    con = duckdb.connect(":memory:")
    free_short_data.init_schema(con)
    session = _FakeSession(b"synthetic response")
    pacer = tool.Pacer(now=lambda: datetime(2026, 10, 3, 3, tzinfo=timezone.utc))
    client = tool.CachedClient(con, tmp_path, session=session, pacer=pacer)
    first = client.get("test", "https://example.test/data", suffix=".txt")
    tool._receipt(con, first, "test", request_key="GET:https://example.test/data:null", rows=[])
    second = client.get("test", "https://example.test/data", suffix=".txt")
    assert session.calls == 1
    assert second.resumed is True
    assert second.body == b"synthetic response"
    assert tool._resumed_rows(con, "GET:https://example.test/data:null") == 0
    con.close()


def test_pacer_waits_between_requests():
    state, waits = {"clock": 10.0}, []

    def clock():
        return state["clock"]

    def sleep(seconds):
        waits.append(seconds)
        state["clock"] += seconds

    pacer = tool.Pacer(interval=1.0, clock=clock, sleep=sleep,
                       now=lambda: datetime(2026, 10, 3, 3, tzinfo=timezone.utc))
    pacer.reserve()
    state["clock"] += 0.25
    pacer.reserve()
    assert waits == [pytest.approx(0.75)]


def test_missing_regsho_html_is_not_parsed(tmp_path):
    con = duckdb.connect(":memory:")
    free_short_data.init_schema(con)
    session = _FakeSession(b"<!DOCTYPE html><title>Page Not Available</title>")
    client = tool.CachedClient(
        con, tmp_path, session=session,
        pacer=tool.Pacer(now=lambda: datetime(2026, 10, 3, 3, tzinfo=timezone.utc)),
    )
    result = tool.capture_regsho(
        client, "nasdaq", start=date(2005, 1, 7), end=date(2005, 1, 7)
    )
    assert result == {"files": 0, "rows": 0, "inserted": 0, "resumed": 0}
    assert con.execute("SELECT http_status FROM short_source_misses").fetchone() == (200,)
    con.close()


def test_nyse_uses_source_specific_two_second_pacing(tmp_path):
    con = duckdb.connect(":memory:")
    free_short_data.init_schema(con)
    body = (b"Symbol|Security Name|Market Category|Reg SHO Threshold Flag|Filler|Filler\n"
            b"TEST|Synthetic Corporation|NYSE|Y||\n20050103210500\n")
    pacer = tool.Pacer(
        interval=1.0, clock=lambda: 1.0, sleep=lambda _: None,
        now=lambda: datetime(2026, 10, 3, 3, tzinfo=timezone.utc),
    )
    client = tool.CachedClient(con, tmp_path, session=_FakeSession(body), pacer=pacer)
    tool.capture_regsho(client, "nyse", start=date(2005, 1, 3), end=date(2005, 1, 3))
    assert pacer.interval == 2.0
    con.close()


def test_cboe_latest_date_parser(tmp_path):
    con = duckdb.connect(":memory:")
    free_short_data.init_schema(con)
    client = tool.CachedClient(
        con, tmp_path, session=_FakeSession(b'{"date":"2026-10-01"}'),
        pacer=tool.Pacer(now=lambda: datetime(2026, 10, 3, 8, tzinfo=timezone.utc)),
    )
    assert tool._cboe_latest_date(client) == date(2026, 10, 1)
    con.close()

