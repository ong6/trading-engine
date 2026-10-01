"""Recorded-fixture tests for the isolated P3 free-source capture."""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pytest

from engine import free_sources
from tools import free_source_audit
from tools import free_sources as capture

FETCHED_AT = datetime(2026, 10, 1, 7, 5, tzinfo=timezone.utc)
MASSIVE_DATE = date(2026, 9, 29)
MASSIVE_FIXTURE = (
    b'{"adjusted":true,"queryCount":2,"request_id":"recorded-fixture",'
    b'"resultsCount":2,"status":"OK","results":['
    b'{"T":"AAPL","c":255.1,"h":256.2,"l":251.4,"o":252.0,'
    b'"t":1790640000000,"v":42100000,"vw":254.3},'
    b'{"T":"OLD.X","c":4.5,"h":4.8,"l":4.1,"o":4.2,'
    b'"t":1790640000000,"v":12000,"vw":4.45}]}'
)


def _tiingo_zip() -> bytes:
    csv_body = """ticker,exchange,assetType,priceCurrency,startDate,endDate
REUSE,NASDAQ,Stock,USD,2012-01-03,2014-05-06
REUSE,NASDAQ,Stock,USD,2020-02-03,
-P-ODD,NYSE,Stock,USD,2018-01-02,2019-03-04
NAT,NYSE NAT,Stock,USD,2021-01-04,
ETF1,NYSE,ETF,USD,2015-01-02,
FOREIGN,LSE,Stock,USD,2010-01-04,
CADSTK,NASDAQ,Stock,CAD,2010-01-04,
"""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("supported_tickers.csv", csv_body)
    return output.getvalue()


def _massive_fixture(session_date: date) -> bytes:
    timestamp = int(datetime(
        session_date.year, session_date.month, session_date.day, tzinfo=timezone.utc
    ).timestamp() * 1000)
    payload = json.loads(MASSIVE_FIXTURE)
    for row in payload["results"]:
        row["t"] = timestamp
    return json.dumps(payload, separators=(",", ":")).encode()


def test_tiingo_parser_keeps_us_stock_intervals_and_odd_tickers():
    rows = free_sources.parse_tiingo_archive(_tiingo_zip())

    assert [(row["ticker"], row["start_date"], row["end_date"]) for row in rows] == [
        ("REUSE", date(2012, 1, 3), date(2014, 5, 6)),
        ("REUSE", date(2020, 2, 3), None),
        ("-P-ODD", date(2018, 1, 2), date(2019, 3, 4)),
        ("NAT", date(2021, 1, 4), None),
    ]
    assert {row["exchange"] for row in rows} == {"NASDAQ", "NYSE", "NYSE NAT"}


def test_tiingo_reload_is_idempotent():
    con = duckdb.connect()
    try:
        first = free_sources.load_security_master(con, _tiingo_zip(), fetched_at=FETCHED_AT)
        second = free_sources.load_security_master(con, _tiingo_zip(), fetched_at=FETCHED_AT)
        count = con.execute("SELECT COUNT(*) FROM free_security_master").fetchone()[0]
    finally:
        con.close()

    assert (first["row_count"], first["inserted"], first["replayed"]) == (4, 4, False)
    assert (second["row_count"], second["inserted"], second["replayed"]) == (4, 0, True)
    assert count == 4


def test_massive_recorded_fixture_parses_and_loads_idempotently():
    rows = free_sources.parse_massive_grouped_daily(MASSIVE_FIXTURE, MASSIVE_DATE)
    assert rows[0] == {
        "date": MASSIVE_DATE, "ticker": "AAPL", "o": 252.0, "h": 256.2,
        "l": 251.4, "c": 255.1, "volume": 42_100_000, "vwap": 254.3,
    }
    con = duckdb.connect()
    try:
        first = free_sources.load_daily_bars(
            con, MASSIVE_FIXTURE, session_date=MASSIVE_DATE, fetched_at=FETCHED_AT
        )
        second = free_sources.load_daily_bars(
            con, MASSIVE_FIXTURE, session_date=MASSIVE_DATE, fetched_at=FETCHED_AT
        )
        count = con.execute("SELECT COUNT(*) FROM free_daily_bars").fetchone()[0]
    finally:
        con.close()
    assert (first["inserted"], first["replayed"]) == (2, False)
    assert (second["inserted"], second["replayed"]) == (0, True)
    assert count == 2


def test_massive_key_refuses_missing_and_open_permissions(tmp_path: Path):
    key_path = tmp_path / "massive.key"
    with pytest.raises(free_sources.FreeSourceError, match="missing.*mode 600"):
        capture._load_massive_key(key_path)

    key_path.write_text("fixture-secret\n")
    key_path.chmod(0o644)
    with pytest.raises(free_sources.FreeSourceError, match="mode 600"):
        capture._load_massive_key(key_path)

    key_path.chmod(0o600)
    assert capture._load_massive_key(key_path) == "fixture-secret"


def test_massive_main_exits_cleanly_without_key(tmp_path: Path, monkeypatch, capsys):
    missing = tmp_path / "missing.key"
    monkeypatch.setattr(capture, "MASSIVE_KEY_PATH", missing)
    result = capture.main([
        "massive", "--start", MASSIVE_DATE.isoformat(), "--end", MASSIVE_DATE.isoformat(),
        "--database", str(tmp_path / "free.duckdb"), "--data-dir", str(tmp_path / "raw"),
    ])
    output = json.loads(capsys.readouterr().out)
    assert result == 2
    assert output["status"] == "failed"
    assert "missing" in output["reason"]
    assert not (tmp_path / "free.duckdb").exists()


class _Clock:
    def __init__(self):
        self.value = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


class _Response:
    status_code = 200

    def __init__(self, body: bytes):
        self.content = body


class _Session:
    def __init__(self, clock: _Clock, *, fail: bool = False):
        self.clock = clock
        self.fail = fail
        self.started: list[float] = []
        self.headers: list[dict] = []

    def get(self, url: str, **kwargs):
        if self.fail:
            raise AssertionError("resume attempted a network request")
        self.started.append(self.clock.monotonic())
        self.headers.append(kwargs["headers"])
        requested = date.fromisoformat(url.rsplit("/", 1)[-1])
        return _Response(_massive_fixture(requested))


def _allowed_now() -> datetime:
    return datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)  # Sunday, outside UTC windows.


def test_massive_paces_requests_at_least_thirteen_seconds(tmp_path: Path):
    clock = _Clock()
    session = _Session(clock)
    days = [date(2026, 9, 28), date(2026, 9, 29)]

    result = capture.capture_massive_dates(
        days, api_key="fixture-secret", database=tmp_path / "free.duckdb",
        data_dir=tmp_path / "raw", session=session, now=_allowed_now,
        monotonic=clock.monotonic, sleep=clock.sleep,
    )

    assert len(result) == 2
    assert session.started == [0.0, 13.0]
    assert clock.sleeps == [13.0]
    assert all(item["Authorization"] == "Bearer fixture-secret" for item in session.headers)


def test_massive_resumes_from_date_cache_without_network(tmp_path: Path):
    clock = _Clock()
    database, data_dir = tmp_path / "free.duckdb", tmp_path / "raw"
    first = capture.capture_massive_dates(
        [MASSIVE_DATE], api_key="fixture-secret", database=database, data_dir=data_dir,
        session=_Session(clock), now=_allowed_now,
        monotonic=clock.monotonic, sleep=clock.sleep,
    )
    second = capture.capture_massive_dates(
        [MASSIVE_DATE], api_key="fixture-secret", database=database, data_dir=data_dir,
        session=_Session(clock, fail=True), now=_allowed_now,
        monotonic=clock.monotonic, sleep=clock.sleep,
    )
    con = duckdb.connect(str(database), read_only=True)
    try:
        count = con.execute("SELECT COUNT(*) FROM free_daily_bars").fetchone()[0]
    finally:
        con.close()

    assert first[0]["resumed"] is False
    assert second[0]["resumed"] is True
    assert second[0]["replayed"] is True
    assert count == 2
    receipts = list((data_dir / "massive" / MASSIVE_DATE.isoformat()).glob("receipt.json"))
    assert len(receipts) == 1


def test_massive_refuses_dates_before_registered_window(tmp_path: Path):
    with pytest.raises(free_sources.FreeSourceError, match="2024-10-01"):
        capture.capture_massive_dates(
            [date(2024, 9, 30)], api_key="fixture-secret",
            database=tmp_path / "free.duckdb", data_dir=tmp_path / "raw",
            session=_Session(_Clock()), now=_allowed_now,
        )


def test_audit_reports_exact_ticker_survivor_gap(tmp_path: Path):
    free_database, store_copy = tmp_path / "free.duckdb", tmp_path / "market.duckdb"
    con = duckdb.connect(str(free_database))
    try:
        free_sources.load_security_master(con, _tiingo_zip(), fetched_at=FETCHED_AT)
    finally:
        con.close()
    con = duckdb.connect(str(store_copy))
    try:
        con.execute("CREATE TABLE prices(ticker VARCHAR, date DATE)")
        con.execute("CREATE TABLE universe(ticker VARCHAR, exchange VARCHAR, etf BOOLEAN)")
        con.execute(
            "INSERT INTO prices VALUES ('REUSE','2012-02-01'),('ONLY','2012-02-01')"
        )
        con.execute("INSERT INTO universe VALUES ('REUSE','Q',FALSE),('ONLY','N',FALSE)")
    finally:
        con.close()

    result = free_source_audit.audit(free_database, store_copy)
    year = next(item for item in result["yearly_totals"] if item["year"] == 2012)
    exchange = next(
        item for item in result["yearly_exchange"]
        if item["year"] == 2012 and item["exchange"] == "NASDAQ"
    )
    assert year == {
        "year": 2012, "master": 1, "store": 2, "matched": 1,
        "master_only": 0, "store_only": 1,
    }
    assert exchange["matched"] == 1
    assert result["master"]["reused_tickers"] == 1


@pytest.mark.parametrize(
    "instant",
    [
        datetime(2026, 10, 1, 1, 15, tzinfo=timezone.utc),
        datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc),
        datetime(2026, 10, 1, 22, 0, tzinfo=timezone.utc),
        datetime(2026, 10, 1, 13, 0, tzinfo=timezone.utc),
    ],
)
def test_network_blackouts_are_enforced(instant: datetime):
    assert capture._network_permitted(instant) is False


def test_network_window_boundary_is_permitted():
    assert capture._network_permitted(datetime(2026, 10, 1, 7, 0, tzinfo=timezone.utc)) is True
