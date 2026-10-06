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
    status_code = 200

    def __init__(self, body):
        self.content = body


class Session:
    def __init__(self, *, fail=False):
        self.urls = []
        self.fail = fail

    def get(self, url, **_kwargs):
        if self.fail:
            raise AssertionError("verified cache should prevent network access")
        self.urls.append(url)
        return Response(CONTRACTS if "/v3/reference/" in url else DAILY)


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
