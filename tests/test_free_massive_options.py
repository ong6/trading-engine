"""Recorded-response tests for bounded Massive options capture."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone

import duckdb
import pytest

from engine import free_massive_options as options
from engine import free_sources
from tools import free_massive_options as capture

AS_OF = date(2026, 10, 6)
NOW = datetime(2026, 10, 6, 11, 35, tzinfo=timezone.utc)
OCC = "SPY261106C00500000"
CONTRACTS = json.dumps({
    "status": "OK", "request_id": "recorded-contracts", "results": [{
        "ticker": f"O:{OCC}", "underlying_ticker": "SPY",
        "expiration_date": "2026-11-06", "contract_type": "call",
        "strike_price": 500.0, "exercise_style": "american",
        "shares_per_contract": 100, "cfi": "OCASPS", "primary_exchange": "BATO",
    }],
}, separators=(",", ":")).encode()
DAILY = json.dumps({
    "status": "OK", "adjusted": True, "ticker": f"O:{OCC}",
    "request_id": "recorded-daily", "resultsCount": 1, "results": [{
        "o": 4.0, "h": 5.0, "l": 3.5, "c": 4.5, "v": 1200,
        "vw": 4.4, "n": 321,
        "t": int(datetime(2026, 10, 5, tzinfo=timezone.utc).timestamp() * 1000),
    }],
}, separators=(",", ":")).encode()


class Response:
    def __init__(self, body, status_code=200):
        self.content = body
        self.status_code = status_code


class Session:
    def __init__(self, *, fail=False, status_code=200):
        self.urls = []
        self.fail = fail
        self.status_code = status_code

    def get(self, url, **_kwargs):
        if self.fail:
            raise AssertionError("verified cache should prevent network access")
        self.urls.append(url)
        return Response(
            CONTRACTS if "/v3/reference/" in url else DAILY,
            status_code=self.status_code,
        )


def test_recorded_contract_and_daily_pages_load_through_shared_limiter(tmp_path):
    database, data_dir = tmp_path / "options.duckdb", tmp_path / "raw"
    limiter = []
    session = Session()

    result = capture.capture(
        database=database, data_dir=data_dir, daily_database=tmp_path / "unused.duckdb",
        api_key="fixture-key", session=session, now=lambda: NOW, as_of=AS_OF,
        selected_underlyings=("SPY",), rate_limit=lambda: limiter.append("reserved"),
        close_overrides={"SPY": 500.0},
    )
    con = duckdb.connect(str(database), read_only=True)
    try:
        contract = con.execute(
            "SELECT as_of,occ,underlying,expiry,strike,\"right\",shares_per_contract "
            "FROM option_contracts"
        ).fetchone()
        bar = con.execute(
            "SELECT occ,date,o,h,l,c,v,vw,n,source FROM option_daily_bars"
        ).fetchone()
        receipts = con.execute("SELECT COUNT(*) FROM option_capture_receipts").fetchone()[0]
    finally:
        con.close()

    assert result == {
        "contract_pages": 1, "contracts": 1, "daily_requests": 1, "daily_bars": 1,
        "as_of": AS_OF.isoformat(), "truncated": [],
    }
    assert limiter == ["reserved", "reserved"]
    assert contract == (AS_OF, OCC, "SPY", date(2026, 11, 6), 500.0, "C", 100)
    assert bar == (
        OCC, date(2026, 10, 5), 4.0, 5.0, 3.5, 4.5, 1200.0, 4.4, 321,
        options.DAILY_SOURCE,
    )
    assert receipts == 2
    assert len(session.urls) == 2


def test_tampered_cached_response_fails_sha_check(tmp_path):
    database, data_dir = tmp_path / "options.duckdb", tmp_path / "raw"
    capture.capture(
        database=database, data_dir=data_dir, daily_database=tmp_path / "unused.duckdb",
        api_key="fixture-key", session=Session(), now=lambda: NOW, as_of=AS_OF,
        selected_underlyings=("SPY",), limit_pages=1, contracts_only=True,
        rate_limit=lambda: None, close_overrides={"SPY": 500.0},
    )
    digest = hashlib.sha256(CONTRACTS).hexdigest()
    (data_dir / f"{digest}.json").write_bytes(CONTRACTS + b" ")

    with pytest.raises(free_sources.FreeSourceError, match="cached response hash"):
        capture.capture(
            database=database, data_dir=data_dir,
            daily_database=tmp_path / "unused.duckdb", api_key="fixture-key",
            session=Session(fail=True), now=lambda: NOW, as_of=AS_OF,
            selected_underlyings=("SPY",), limit_pages=1, contracts_only=True,
            rate_limit=lambda: None, close_overrides={"SPY": 500.0},
        )


def test_capture_resumes_from_verified_receipts_without_network_or_limiter(tmp_path):
    database, data_dir = tmp_path / "options.duckdb", tmp_path / "raw"
    calls = []
    first = capture.capture(
        database=database, data_dir=data_dir, daily_database=tmp_path / "unused.duckdb",
        api_key="fixture-key", session=Session(), now=lambda: NOW, as_of=AS_OF,
        selected_underlyings=("SPY",), contracts_only=True,
        rate_limit=lambda: calls.append("reserved"), close_overrides={"SPY": 500.0},
    )
    second = capture.capture(
        database=database, data_dir=data_dir, daily_database=tmp_path / "unused.duckdb",
        api_key="fixture-key", session=Session(fail=True), now=lambda: NOW, as_of=AS_OF,
        selected_underlyings=("SPY",), contracts_only=True,
        rate_limit=lambda: (_ for _ in ()).throw(AssertionError("limiter called on resume")),
        close_overrides={"SPY": 500.0},
    )

    assert first == second
    assert calls == ["reserved"]


def test_missing_cached_response_file_is_a_source_error(tmp_path):
    database, data_dir = tmp_path / "options.duckdb", tmp_path / "raw"
    capture.capture(
        database=database, data_dir=data_dir, daily_database=tmp_path / "unused.duckdb",
        api_key="fixture-key", session=Session(), now=lambda: NOW, as_of=AS_OF,
        selected_underlyings=("SPY",), contracts_only=True,
        rate_limit=lambda: None, close_overrides={"SPY": 500.0},
    )
    (data_dir / f"{hashlib.sha256(CONTRACTS).hexdigest()}.json").unlink()

    with pytest.raises(free_sources.FreeSourceError, match="file is missing or unreadable"):
        capture.capture(
            database=database, data_dir=data_dir,
            daily_database=tmp_path / "unused.duckdb", api_key="fixture-key",
            session=Session(fail=True), now=lambda: NOW, as_of=AS_OF,
            selected_underlyings=("SPY",), contracts_only=True,
            rate_limit=lambda: None, close_overrides={"SPY": 500.0},
        )


def test_capture_refuses_missing_key_before_network(tmp_path, monkeypatch):
    monkeypatch.setattr(capture.daily_capture, "MASSIVE_KEY_PATH", tmp_path / "missing.key")

    with pytest.raises(free_sources.FreeSourceError, match="API key is missing"):
        capture.capture(
            database=tmp_path / "options.duckdb", data_dir=tmp_path / "raw",
            daily_database=tmp_path / "unused.duckdb", session=Session(fail=True),
            now=lambda: NOW, as_of=AS_OF, selected_underlyings=("SPY",),
            contracts_only=True, close_overrides={"SPY": 500.0},
        )


def test_http_429_is_refused_after_one_shared_limiter_reservation(tmp_path):
    calls = []
    with pytest.raises(free_sources.FreeSourceError, match="HTTP 429"):
        capture.capture(
            database=tmp_path / "options.duckdb", data_dir=tmp_path / "raw",
            daily_database=tmp_path / "unused.duckdb", api_key="fixture-key",
            session=Session(status_code=429), now=lambda: NOW, as_of=AS_OF,
            selected_underlyings=("SPY",), contracts_only=True,
            rate_limit=lambda: calls.append("reserved"), close_overrides={"SPY": 500.0},
        )
    assert calls == ["reserved"]


def test_loader_checks_expected_source_hash():
    con = duckdb.connect()
    try:
        with pytest.raises(free_sources.FreeSourceError, match="cached response hash"):
            options.load_contracts_page(
                con, CONTRACTS, as_of=AS_OF, underlying="SPY",
                expiry_min=date(2026, 10, 26), expiry_max=date(2026, 12, 5),
                strike_min=475.0, strike_max=525.0, fetched_at=NOW,
                expected_sha256="0" * 64,
            )
    finally:
        con.close()


def test_prior_closes_opens_existing_adjusted_store_read_only(tmp_path, monkeypatch):
    database = tmp_path / "daily.duckdb"
    con = duckdb.connect(str(database))
    try:
        free_sources.init_schema(con)
        con.execute(
            """INSERT INTO free_daily_bars VALUES
            ('2026-10-05','SPY',499,501,498,500,1000,500,
             'fixture','2026-10-05 22:00:00',?)""",
            ["a" * 64],
        )
    finally:
        con.close()
    real_connect = capture.db.connect
    calls = []

    def observed_connect(path, **kwargs):
        calls.append(kwargs)
        return real_connect(path, **kwargs)

    monkeypatch.setattr(capture.db, "connect", observed_connect)

    assert capture.prior_closes(database, ["SPY"], AS_OF) == {"SPY": 500.0}
    assert calls == [{"read_only": True}]


def test_prior_closes_refuses_store_without_adjusted_view(tmp_path):
    database = tmp_path / "daily.duckdb"
    duckdb.connect(str(database)).close()

    with pytest.raises(free_sources.FreeSourceError, match="adjusted daily-bar view"):
        capture.prior_closes(database, ["SPY"], AS_OF)


def test_daily_contract_cap_is_equal_and_prefers_31_to_60_dte_then_atm():
    con = duckdb.connect()
    try:
        options.init_schema(con)
        for underlying, close in (("SPY", 500), ("QQQ", 600), ("IWM", 700)):
            rows = [
                (f"{underlying}-PREFERRED-ATM", date(2026, 11, 6), close),
                (f"{underlying}-PREFERRED-FAR", date(2026, 11, 7), close + 10),
                (f"{underlying}-NEAR-DTE", date(2026, 10, 31), close),
            ]
            con.executemany(
                """INSERT INTO option_contracts
                (as_of,occ,underlying,expiry,strike,"right",shares_per_contract,
                 source_sha256,fetched_at)
                VALUES (?,?,?,?,?,'C',100,?,'2026-10-06 11:35:00')""",
                [[AS_OF, occ, underlying, expiry, strike, "b" * 64]
                 for occ, expiry, strike in rows],
            )
        selected = capture._select_daily_contracts(
            con, as_of=AS_OF, underlyings=["SPY", "QQQ", "IWM"],
            closes={"SPY": 500, "QQQ": 600, "IWM": 700}, cap=6,
        )
    finally:
        con.close()

    assert selected == [
        "SPY-PREFERRED-ATM", "SPY-PREFERRED-FAR",
        "QQQ-PREFERRED-ATM", "QQQ-PREFERRED-FAR",
        "IWM-PREFERRED-ATM", "IWM-PREFERRED-FAR",
    ]
