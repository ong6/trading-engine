"""Recorded-response tests for bounded Massive options capture."""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pytest

from engine import free_massive_options as options
from engine import free_sources, raw_payload
from tools import free_massive_options as capture
from tools import provider_contracts as contracts

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


@pytest.fixture(autouse=True)
def enable_collection_for_capture_tests(monkeypatch):
    monkeypatch.setattr(capture, "COLLECTION_ENABLED", True)


def test_collection_is_paused_by_default_config_without_io(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(capture, "COLLECTION_ENABLED", False)
    database = tmp_path / "options.duckdb"
    result = capture.capture(
        database=database, data_dir=tmp_path / "raw",
        daily_database=tmp_path / "daily.duckdb", session=Session(fail=True),
    )
    assert result == {
        "status": "paused", "reason": "no_registered_reader",
        "collection_enabled": False,
    }
    assert not database.exists()
    assert capture.main([
        "--database", str(database), "--data-dir", str(tmp_path / "raw"),
        "--daily-database", str(tmp_path / "daily.duckdb"),
    ]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "paused"


def test_service_always_refreshes_splits_before_paused_options():
    service = Path(capture.__file__).parents[1] / "server/massive-options-daily.service"
    lines = service.read_text().splitlines()
    commands = [line.removeprefix("ExecStart=") for line in lines if line.startswith("ExecStart=")]
    assert len(commands) == 2
    assert "tools.free_sources massive --splits" in commands[0]
    assert "tools.free_massive_options" in commands[1]
    assert not any(line.startswith("ExecCondition=") for line in lines)


def test_options_service_import_failure_is_not_mapped_to_paused(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    service = root / "server/massive-options-daily.service"
    option_command = next(
        line.removeprefix("ExecStart=") for line in service.read_text().splitlines()
        if line.startswith("ExecStart=") and "tools.free_massive_options" in line
    )
    arguments = shlex.split(option_command)[1:]
    shadow = tmp_path / "tools"
    shadow.mkdir()
    (shadow / "__init__.py").write_text("")
    (shadow / "free_massive_options.py").write_text(
        "raise RuntimeError('injected options import failure')\n"
    )
    result = subprocess.run(
        [sys.executable, *arguments], cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": f"{tmp_path}:{root}"},
        text=True, capture_output=True, check=False,
    )
    assert result.returncode != 0
    assert "injected options import failure" in result.stderr


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
    for body in (CONTRACTS, DAILY):
        logical = data_dir / f"{hashlib.sha256(body).hexdigest()}.json"
        assert not logical.exists()
        assert raw_payload.read(logical, expected_sha256=logical.stem) == body


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
    logical = data_dir / f"{hashlib.sha256(CONTRACTS).hexdigest()}.json"
    logical.write_bytes(raw_payload.read(logical))
    raw_payload.compressed_path(logical).unlink()
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
    logical = data_dir / f"{hashlib.sha256(CONTRACTS).hexdigest()}.json"
    raw_payload.compressed_path(logical).unlink()

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


RECORDED = json.loads((contracts.FIXTURES_DIR / "manifest.json").read_text())["options"]
RECORDED_AS_OF = date.fromisoformat(RECORDED["as_of"])
RECORDED_NOW = datetime.fromisoformat(RECORDED["now"])
RECORDED_OCC = RECORDED["daily"]["occ"]
RECORDED_CLOSES = {page["underlying"]: page["close"] for page in RECORDED["contracts"]}
RECORDED_BODIES = {
    page["underlying"]: (contracts.FIXTURES_DIR / page["file"]).read_bytes()
    for page in RECORDED["contracts"]
}
RECORDED_DAILY = (contracts.FIXTURES_DIR / RECORDED["daily"]["file"]).read_bytes()


class RecordedSession(Session):
    """Serve the 2026-10-18 free-tier responses: contracts by underlying, one daily page."""

    def __init__(self, contracts_by_underlying=None):
        super().__init__()
        self.contracts = contracts_by_underlying or RECORDED_BODIES

    def get(self, url, **_kwargs):
        self.urls.append(url)
        if "/v3/reference/" in url:
            underlying = url.split("underlying_ticker=")[1].split("&")[0]
            return Response(self.contracts[underlying])
        return Response(RECORDED_DAILY if f"O:{RECORDED_OCC}/" in url else b"{}", 200)


def _recorded_capture(tmp_path, session, underlyings, **kwargs):
    return capture.capture(
        database=tmp_path / "options.duckdb", data_dir=tmp_path / "raw",
        daily_database=tmp_path / "unused.duckdb", api_key="fixture-key", session=session,
        now=lambda: RECORDED_NOW, as_of=RECORDED_AS_OF, selected_underlyings=underlyings,
        rate_limit=lambda: None,
        close_overrides={key: RECORDED_CLOSES[key] for key in underlyings}, **kwargs,
    )


def test_recorded_free_tier_contract_pages_load_for_every_underlying(tmp_path):
    result = _recorded_capture(
        tmp_path, RecordedSession(), ("SPY", "QQQ", "IWM"), contracts_only=True
    )
    con = duckdb.connect(str(tmp_path / "options.duckdb"), read_only=True)
    try:
        per_underlying = dict(con.execute(
            "SELECT underlying, COUNT(*) FROM option_contracts GROUP BY 1"
        ).fetchall())
        recorded = con.execute(
            "SELECT expiry, strike, \"right\" FROM option_contracts WHERE occ=?", [RECORDED_OCC]
        ).fetchone()
    finally:
        con.close()

    assert result["contract_pages"] == 3 and result["truncated"] == []
    assert per_underlying == {page["underlying"]: page["rows"] for page in RECORDED["contracts"]}
    assert recorded == (date(2026, 11, 20), 763.0, "C")


def test_recorded_free_tier_delayed_daily_page_loads(tmp_path):
    spy = json.loads(RECORDED_BODIES["SPY"])
    only_recorded = json.dumps({**spy, "results": [
        row for row in spy["results"] if row["ticker"] == f"O:{RECORDED_OCC}"
    ]}).encode()

    result = _recorded_capture(tmp_path, RecordedSession({"SPY": only_recorded}), ("SPY",))

    assert json.loads(RECORDED_DAILY)["status"] == "DELAYED"
    assert (result["daily_requests"], result["daily_bars"]) == (1, RECORDED["daily"]["rows"])


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


def test_prior_closes_uses_requested_asof_not_current_adjusted_view(tmp_path):
    database = tmp_path / "daily.duckdb"
    con = duckdb.connect(str(database))
    try:
        free_sources.init_schema(con)
        con.execute(
            """INSERT INTO free_daily_bars VALUES
            ('2026-01-02','SPY',100,101,99,100,1000,100,
             'fixture','2026-01-02 22:00:00',?)""",
            ["c" * 64],
        )
        split_body = json.dumps({
            "status": "OK", "count": 1, "results": [{
                "ticker": "SPY", "execution_date": "2026-01-07",
                "split_from": 1, "split_to": 2,
            }],
        }).encode()
        free_sources.load_splits(
            con, split_body, fetched_at=datetime(2026, 1, 3, tzinfo=timezone.utc)
        )
        current_adjusted = con.execute(
            "SELECT c FROM free_daily_bars_adjusted WHERE ticker='SPY'"
        ).fetchone()[0]
    finally:
        con.close()

    assert current_adjusted == 50.0
    assert capture.prior_closes(database, ["SPY"], date(2026, 1, 6)) == {"SPY": 100.0}


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


DELAYED_DAILY = json.dumps({
    "ticker": f"O:{OCC}", "queryCount": 1, "resultsCount": 1, "adjusted": True,
    "results": [{
        "v": 928, "vw": 15.9404, "o": 20.23, "c": 15.28, "h": 20.23, "l": 15.0,
        "t": int(datetime(2026, 10, 5, tzinfo=timezone.utc).timestamp() * 1000), "n": 77,
    }],
    "status": "DELAYED", "request_id": "recorded-delayed-daily", "count": 1,
}, separators=(",", ":")).encode()


class DelayedSession(Session):
    def get(self, url, **_kwargs):
        self.urls.append(url)
        return Response(CONTRACTS if "/v3/reference/" in url else DELAYED_DAILY)


def test_free_tier_delayed_daily_page_loads_and_receipt_records_status(tmp_path):
    database, data_dir = tmp_path / "options.duckdb", tmp_path / "raw"

    result = capture.capture(
        database=database, data_dir=data_dir, daily_database=tmp_path / "unused.duckdb",
        api_key="fixture-key", session=DelayedSession(), now=lambda: NOW, as_of=AS_OF,
        selected_underlyings=("SPY",), rate_limit=lambda: None,
        close_overrides={"SPY": 500.0},
    )
    con = duckdb.connect(str(database), read_only=True)
    try:
        bar = con.execute("SELECT occ,date,c,v,n FROM option_daily_bars").fetchone()
        statuses = con.execute(
            "SELECT url LIKE '%/v3/reference/%', provider_status "
            "FROM option_capture_receipts ORDER BY 1"
        ).fetchall()
    finally:
        con.close()

    assert result["daily_requests"] == 1 and result["daily_bars"] == 1
    assert bar == (OCC, date(2026, 10, 5), 15.28, 928.0, 77)
    assert statuses == [(False, "DELAYED"), (True, "OK")]


def test_delayed_status_is_accepted_only_for_option_daily_bars():
    delayed_contracts = CONTRACTS.replace(b'"status":"OK"', b'"status":"DELAYED"')
    with pytest.raises(free_sources.FreeSourceError, match="contracts response status"):
        options.parse_contracts_page(
            delayed_contracts, underlying="SPY", expiry_min=date(2026, 10, 26),
            expiry_max=date(2026, 12, 5), strike_min=475.0, strike_max=525.0,
        )
    for status in ("ERROR", "delayed", None):
        body = json.dumps({**json.loads(DELAYED_DAILY), "status": status}).encode()
        with pytest.raises(free_sources.FreeSourceError, match="daily bars response status"):
            options.parse_daily_bars_page(
                body, occ=OCC, start=date(2026, 10, 1), end=AS_OF,
            )


def test_legacy_receipts_table_gains_provider_status_column():
    con = duckdb.connect()
    try:
        con.execute(
            """CREATE TABLE option_capture_receipts (
            request_key VARCHAR PRIMARY KEY, url VARCHAR, http_status INTEGER,
            source_sha256 VARCHAR, fetched_at TIMESTAMP, row_count BIGINT)"""
        )
        con.execute(
            "INSERT INTO option_capture_receipts VALUES ('old', 'u', 200, 's', ?, 1)",
            [NOW.replace(tzinfo=None)],
        )
        loaded = options.load_daily_bars_page(
            con, DELAYED_DAILY, occ=OCC, start=date(2026, 10, 1), end=AS_OF,
            fetched_at=NOW,
        )
        options.record_receipt(
            con, request_key="new", url="u2", source_sha256="s2", fetched_at=NOW,
            row_count=loaded["row_count"], provider_status=loaded["provider_status"],
        )
        rows = con.execute(
            "SELECT request_key, provider_status FROM option_capture_receipts ORDER BY 1"
        ).fetchall()
    finally:
        con.close()

    assert rows == [("new", "DELAYED"), ("old", None)]
