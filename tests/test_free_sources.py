"""Recorded-fixture tests for the isolated P3 free-source capture."""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pytest

from engine import free_sources
from sim import nyse
from tools import free_source_audit
from tools import free_sources as capture

# Fixed entry time: writestr(name, ...) stamps the current time, so two fixtures
# built across a 2-second tick hash differently.
FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)

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
        archive.writestr(zipfile.ZipInfo("supported_tickers.csv", FIXED_ZIP_TIME), csv_body)
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
    def __init__(self, clock: _Clock, *, fail: bool = False, empty: bool = False):
        self.clock = clock
        self.fail = fail
        self.empty = empty
        self.started: list[float] = []
        self.headers: list[dict] = []
        self.requested: list[date] = []

    def get(self, url: str, **kwargs):
        if self.fail:
            raise AssertionError("resume attempted a network request")
        self.started.append(self.clock.monotonic())
        self.headers.append(kwargs["headers"])
        requested = date.fromisoformat(url.rsplit("/", 1)[-1])
        self.requested.append(requested)
        if self.empty:
            return _Response(_massive_body([]))
        return _Response(_massive_fixture(requested))


def _allowed_now() -> datetime:
    return datetime(2026, 10, 2, 11, 0, tzinfo=timezone.utc)


def _after_close_now() -> datetime:
    return datetime(2026, 10, 2, 20, 30, tzinfo=timezone.utc)


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


def test_massive_refuses_dates_before_rolling_window(tmp_path: Path):
    with pytest.raises(free_sources.FreeSourceError, match="2024-10-03"):
        capture.capture_massive_dates(
            [date(2024, 10, 2)], api_key="fixture-secret",
            database=tmp_path / "free.duckdb", data_dir=tmp_path / "raw",
            session=_Session(_Clock()), now=_allowed_now,
        )


def test_massive_rolling_window_uses_utc_date_and_completed_new_york_session():
    before_close = datetime(2026, 10, 2, 19, 59, tzinfo=timezone.utc)
    at_close = datetime(2026, 10, 2, 20, 0, tzinfo=timezone.utc)

    assert capture.massive_window(before_close) == (date(2024, 10, 3), date(2026, 10, 1))
    assert capture.massive_window(at_close) == (date(2024, 10, 3), date(2026, 10, 2))
    assert capture.massive_window(
        datetime(2028, 2, 29, 22, 0, tzinfo=timezone.utc)
    )[0] == date(2026, 3, 1)


def test_massive_sessions_skip_weekends_and_nyse_holidays():
    assert capture._sessions(date(2026, 7, 2), date(2026, 7, 6)) == [
        date(2026, 7, 2),
        date(2026, 7, 6),
    ]
    assert capture.massive_window(
        datetime(2026, 7, 6, 15, 0, tzinfo=timezone.utc)
    )[1] == date(2026, 7, 2)


def test_massive_daily_fetches_newest_ten_missing_sessions(tmp_path: Path):
    clock = _Clock()
    session = _Session(clock)

    result = capture.capture_massive_daily(
        database=tmp_path / "free.duckdb", data_dir=tmp_path / "raw",
        api_key="fixture-secret", session=session, now=_after_close_now,
        monotonic=clock.monotonic, sleep=clock.sleep,
    )

    assert result["status"] == "complete"
    assert result["fetched_sessions"] == 10
    assert session.requested == [
        date(2026, 10, 2), date(2026, 10, 1), date(2026, 9, 30),
        date(2026, 9, 29), date(2026, 9, 28), date(2026, 9, 25),
        date(2026, 9, 24), date(2026, 9, 23), date(2026, 9, 22),
        date(2026, 9, 21),
    ]


def test_massive_daily_loads_cache_then_reports_up_to_date(
    tmp_path: Path, monkeypatch,
):
    database, data_dir = tmp_path / "free.duckdb", tmp_path / "raw"
    window = (date(2026, 9, 28), date(2026, 9, 30))
    monkeypatch.setattr(capture, "massive_window", lambda _now: window)
    for session_date in capture._sessions(*window):
        capture._cache_massive(data_dir, session_date, _massive_fixture(session_date), FETCHED_AT)

    first = capture.capture_massive_daily(
        database=database, data_dir=data_dir, api_key="unused",
        session=_Session(_Clock(), fail=True), now=_allowed_now,
    )
    second = capture.capture_massive_daily(
        database=database, data_dir=data_dir,
        session=_Session(_Clock(), fail=True), now=_allowed_now,
    )

    assert first["status"] == "complete"
    assert first["fetched_sessions"] == 0
    assert [item["resumed"] for item in first["result"]] == [True, True, True]
    assert second == {"status": "up_to_date"}


@pytest.mark.parametrize("session_date", [date(2026, 10, 1), date(2026, 10, 2)])
def test_massive_recent_empty_session_is_not_cached_and_retries(
    tmp_path: Path, session_date: date,
):
    clock = _Clock()
    database, data_dir = tmp_path / "free.duckdb", tmp_path / "raw"

    first = capture.capture_massive_dates(
        [session_date], api_key="fixture-secret", database=database, data_dir=data_dir,
        session=_Session(clock, empty=True), now=_after_close_now,
        monotonic=clock.monotonic, sleep=clock.sleep,
    )
    retry_session = _Session(clock)
    second = capture.capture_massive_dates(
        [session_date], api_key="fixture-secret", database=database, data_dir=data_dir,
        session=retry_session, now=_after_close_now,
        monotonic=clock.monotonic, sleep=clock.sleep,
    )

    assert first == [{
        "source": free_sources.MASSIVE_SOURCE,
        "date": session_date.isoformat(),
        "status": "not_yet_published",
        "row_count": 0,
        "resumed": False,
    }]
    assert retry_session.requested == [session_date]
    assert second[0]["row_count"] == 2
    assert (data_dir / "massive" / session_date.isoformat() / "receipt.json").exists()


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


def _massive_body(bars: list[dict]) -> bytes:
    return json.dumps({
        "adjusted": True, "queryCount": len(bars), "request_id": "recorded-fixture",
        "resultsCount": len(bars), "status": "OK", "results": bars,
    }).encode()


def _bar(ticker: str, **overrides) -> dict:
    bar = {"T": ticker, "o": 10.0, "h": 11.0, "l": 9.5, "c": 10.5,
           "t": 1790640000000, "v": 1000, "vw": 10.2}
    bar.update(overrides)
    return bar


def test_massive_accepts_fractional_volume_and_quarantines_bad_bars():
    bars = [_bar(f"OK{i}") for i in range(30)]
    bars += [_bar("FRAC", v=1234.5), _bar("BADHL", h=9.0)]
    body = _massive_body(bars)
    con = duckdb.connect()
    try:
        result = free_sources.load_daily_bars(
            con, body, session_date=MASSIVE_DATE, fetched_at=FETCHED_AT
        )
        frac = con.execute(
            "SELECT volume FROM free_daily_bars WHERE ticker='FRAC'"
        ).fetchone()[0]
        rejected = con.execute(
            "SELECT ticker, reason FROM free_daily_bars_rejected"
        ).fetchall()
    finally:
        con.close()
    assert (result["row_count"], result["rejected"]) == (31, 1)
    assert frac == 1234.5
    assert rejected == [("BADHL", "ohlc_relationship")]


def test_massive_fails_date_when_too_many_bars_are_rejected():
    bars = [_bar(f"OK{i}") for i in range(10)] + [_bar("BAD", l=12.0)]
    with pytest.raises(free_sources.FreeSourceError, match="above the 5% limit"):
        free_sources.parse_massive_grouped_daily(_massive_body(bars), MASSIVE_DATE)


def test_massive_accepts_an_empty_holiday_response():
    body = json.dumps({"adjusted": True, "queryCount": 0, "resultsCount": 0,
                       "status": "OK", "request_id": "holiday"}).encode()
    assert free_sources.parse_massive_grouped_daily(body, MASSIVE_DATE) == []


def test_massive_schema_widens_integer_volume_tables():
    con = duckdb.connect()
    try:
        con.execute(
            """CREATE TABLE free_daily_bars (
            date DATE NOT NULL, ticker VARCHAR NOT NULL,
            o DOUBLE NOT NULL, h DOUBLE NOT NULL, l DOUBLE NOT NULL, c DOUBLE NOT NULL,
            volume BIGINT NOT NULL, vwap DOUBLE, source VARCHAR NOT NULL,
            fetched_at TIMESTAMP NOT NULL, source_sha256 VARCHAR NOT NULL,
            PRIMARY KEY(source_sha256, date, ticker))"""
        )
        free_sources.init_schema(con)
        kind = con.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name='free_daily_bars' AND column_name='volume'"
        ).fetchone()[0]
    finally:
        con.close()
    assert kind == "DOUBLE"


def test_daily_panel_returns_canonical_bars_in_date_ticker_order():
    con = duckdb.connect()
    try:
        free_sources.load_daily_bars(
            con, _massive_fixture(date(2026, 9, 30)),
            session_date=date(2026, 9, 30), fetched_at=FETCHED_AT,
        )
        free_sources.load_daily_bars(
            con, _massive_fixture(date(2026, 9, 29)),
            session_date=date(2026, 9, 29), fetched_at=FETCHED_AT,
        )
        panel = free_sources.daily_panel(con, date(2026, 9, 30), date(2026, 9, 30))
    finally:
        con.close()

    assert list(panel.columns) == ["date", "ticker", "o", "h", "l", "c", "volume", "vwap"]
    panel["date"] = panel["date"].dt.date
    assert panel[["date", "ticker"]].to_dict("records") == [
        {"date": date(2026, 9, 30), "ticker": "AAPL"},
        {"date": date(2026, 9, 30), "ticker": "OLD.X"},
    ]


def test_mdv60_uses_vwap_fallback_and_excludes_same_day_and_older_sessions():
    as_of = date(2026, 10, 2)
    sessions, candidate = [], as_of - timedelta(days=1)
    while len(sessions) < 61:
        if nyse.is_session(candidate):
            sessions.append(candidate)
        candidate -= timedelta(days=1)
    rows = [
        # Close fallback is used when VWAP is absent.
        (sessions[0], "ABC", 2.0, None, 10.0),
        # VWAP, not the deliberately different close, is used when present.
        (sessions[59], "ABC", 100.0, 1.0, 10.0),
        # The 61st prior session and same-day data are outside the point-in-time window.
        (sessions[60], "ABC", 1000.0, 1000.0, 10.0),
        (as_of, "ABC", 2000.0, 2000.0, 10.0),
    ]
    con = duckdb.connect()
    try:
        free_sources.init_schema(con)
        con.executemany(
            """INSERT INTO free_daily_bars VALUES
            (?, ?, 1.0, 1.0, 1.0, ?, ?, ?, ?, ?, ?)""",
            [[session_date, ticker, close, volume, vwap,
              free_sources.MASSIVE_SOURCE, FETCHED_AT.replace(tzinfo=None), f"{index:064x}"]
             for index, (session_date, ticker, close, vwap, volume) in enumerate(rows, 1)],
        )
        result = free_sources.mdv60(con, as_of)
    finally:
        con.close()

    assert result.to_dict("records") == [{"ticker": "ABC", "mdv60": 15.0}]
