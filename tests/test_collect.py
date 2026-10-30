"""EOD collection releases DuckDB around network work and checkpoints batches."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest
from yfinance.exceptions import YFPricesMissingError

from engine import collect
from engine.lib import db
from server import agent_evaluation, p15_incremental_collect, p15_price_fetch_attempts
from tests.conftest import SESSIONS, insert_bars


def _raw_frame(day: str = "2026-09-08", *, volume: int = 1_000_000) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [100.0],
            "High": [101.0],
            "Low": [99.0],
            "Close": [100.5],
            "Volume": [volume],
        },
        index=pd.DatetimeIndex([day], name="Date"),
    )


def _setup_store(path, *, liquid: bool, backfill_done: bool = False) -> None:
    con = db.connect(path)
    try:
        db.init_schema(con)
        con.execute(
            "INSERT INTO universe (ticker, yf_ticker, active, liquid, backfill_done) "
            "VALUES ('AAA', 'AAA', TRUE, ?, ?)",
            [liquid, backfill_done],
        )
    finally:
        con.close()


def _read(path, sql: str):
    con = db.connect(path, read_only=True, wait_s=0)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def _probe_raises(error: Exception, calls: list[str] | None = None):
    """A per-name source probe that records the name and raises `error`."""

    def probe(yf_ticker):
        if calls is not None:
            calls.append(yf_ticker)
        raise error

    return probe


def _no_price_data(ticker: str) -> Exception:
    # yfinance's "possibly delisted; no price data found  (period=5d)": no Yahoo reason.
    return YFPricesMissingError(ticker, " (period=5d)")


def _add_universe(path, *rows: tuple[str, bool, bool]) -> None:
    con = db.connect(path)
    try:
        con.executemany(
            "INSERT INTO universe (ticker,yf_ticker,active,liquid,backfill_done) "
            "VALUES (?,?,?,?,TRUE)",
            [[ticker, ticker, active, liquid] for ticker, active, liquid in rows],
        )
    finally:
        con.close()


def _stored_frame(day: str = "2026-09-08") -> pd.DataFrame:
    frame, got = collect._extract_long(_raw_frame(day), {"AAA": "AAA"})
    assert got == {"AAA"}
    return frame


def test_incremental_releases_db_during_download_and_sleep(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=True)
    observed: list[tuple[str, int]] = []

    def download_while_reading(tickers, *, period, start):
        assert tickers == ["AAA"] and period == "5d" and start is None
        count = _read(db_path, "SELECT COUNT(*) FROM prices")[0][0]
        observed.append(("download", count))
        return _raw_frame()

    def sleep_while_reading(seconds):
        assert seconds == 2
        count = _read(db_path, "SELECT COUNT(*) FROM prices")[0][0]
        observed.append(("sleep", count))

    monkeypatch.setattr(collect, "_download", download_while_reading)
    monkeypatch.setattr(collect.time, "sleep", sleep_while_reading)

    assert collect.mode_incremental(db_path, force=True) == (1, 0)
    assert observed == [("download", 0), ("sleep", 1)]
    assert _read(db_path, "SELECT ticker, date, close FROM prices") == [
        ("AAA", date(2026, 9, 8), 100.5)
    ]


def test_incremental_records_append_only_price_fetch_attempts(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=True)
    con = db.connect(db_path)
    con.execute(
        "INSERT INTO universe (ticker,yf_ticker,active,liquid,backfill_done) "
        "VALUES ('BBB','BBB',TRUE,TRUE,FALSE)"
    )
    con.close()
    market_date = date(2026, 9, 25)
    raw = pd.concat({"AAA": _raw_frame(market_date.isoformat())}, axis=1)
    monkeypatch.setattr(collect, "_download", lambda *_args, **_kwargs: raw)
    monkeypatch.setattr(collect.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(collect, "_probe_history", _probe_raises(TimeoutError("read timed out")))

    assert collect.mode_incremental(db_path, force=True) == (2, 1)
    first_attempt = collect.datetime(2026, 9, 26, 1, tzinfo=collect.timezone.utc)
    con = db.connect(db_path)
    with db.transaction(con):
        p15_price_fetch_attempts.record(
            con, market_date=market_date, attempted_at=first_attempt,
            requested_count=2, failed_count=0,
        )
    con.close()
    assert collect.mode_incremental(db_path, force=True) == (2, 1)
    con = db.connect(db_path)
    with db.transaction(con):
        p15_price_fetch_attempts.record(
            con, market_date=market_date,
            attempted_at=first_attempt + timedelta(minutes=1),
            requested_count=2, failed_count=0,
        )
    con.close()

    assert _read(
        db_path,
        "SELECT ticker,market_date,status FROM price_fetch_attempts "
        "ORDER BY id",
    ) == [
        ("BBB", market_date, "missing"),
        ("BBB", market_date, "missing"),
    ]
    assert _read(db_path, "SELECT COUNT(*) FROM prices WHERE ticker='BBB'") == [(0,)]
    con = db.connect(db_path)
    p15_price_fetch_attempts.validate(con, ValueError)
    insert_bars(con, "BBB", [market_date], open_=100, close=101, high=102, low=99)
    con.execute(
        "UPDATE prices SET fetched_at=? WHERE ticker='BBB' AND date=?",
        [(first_attempt + timedelta(hours=1)).replace(tzinfo=None), market_date],
    )
    p15_price_fetch_attempts.validate(con, ValueError)
    con.execute(
        "INSERT INTO price_fetch_attempts VALUES "
        "(99,'BBB',?,?, 'yfinance','missing',?,?)",
        [market_date, first_attempt.replace(tzinfo=None), "f" * 64, "e" * 64],
    )
    with pytest.raises(ValueError, match="fetch attempt evidence differs"):
        p15_price_fetch_attempts.validate(con, ValueError)
    con.execute("DELETE FROM price_fetch_attempts WHERE id=99")
    con.execute("UPDATE price_fetch_attempts SET status='present' WHERE ticker='BBB'")
    with pytest.raises(ValueError, match="fetch attempt evidence differs"):
        p15_price_fetch_attempts.validate(con, ValueError)
    con.close()


def test_p15_incremental_wrapper_withholds_failed_or_misdated_attempts(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=True)
    market_date = date(2026, 9, 28)
    con = db.connect(db_path)
    con.execute(
        "INSERT INTO prices (ticker,date,open,high,low,close,volume) "
        "VALUES ('AAA',?,100,101,99,100,1000)", [market_date],
    )
    con.close()
    delayed = collect.datetime(2026, 9, 29, 1, tzinfo=collect.timezone.utc)
    metadata = []
    monkeypatch.setattr(
        p15_incremental_collect.collect, "write_meta",
        lambda database, mode, requested, failed: metadata.append(
            (database, mode, requested, failed)
        ),
    )

    monkeypatch.setattr(
        p15_incremental_collect.collect, "mode_incremental",
        lambda *_args, **_kwargs: (1, 1),
    )
    withheld = p15_incremental_collect.run(db_path, now=delayed)
    assert withheld["status"] == "withheld" and withheld["attempt_count"] == 0
    assert _read(db_path, "SELECT COUNT(*) FROM price_fetch_attempts") == [(0,)]

    monkeypatch.setattr(
        p15_incremental_collect.collect, "mode_incremental",
        lambda *_args, **_kwargs: (1, 0),
    )
    recorded = p15_incremental_collect.run(db_path, now=delayed)
    assert recorded["status"] == "complete"
    assert recorded["market_date"] == market_date.isoformat()
    assert _read(db_path, "SELECT COUNT(*) FROM price_fetch_attempts") == [(0,)]
    assert _read(
        db_path,
        "SELECT market_date,present_count,missing_count FROM p15_price_fetch_batches",
    ) == [(market_date, 1, 0)]
    assert metadata == [
        (db_path, "incremental", 1, 1),
        (db_path, "incremental", 1, 0),
    ]


def test_incremental_requests_only_active_liquid_names(monkeypatch, tmp_path):
    """Rev-14 (e): the 10-14 nightly requested 27 inactive names still flagged liquid."""
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=True)
    _add_universe(db_path, ("GONE", False, True), ("THIN", True, False))
    requested: list[str] = []

    def download(tickers, *, period, start):
        requested.extend(tickers)
        return _raw_frame()

    monkeypatch.setattr(collect, "_download", download)
    monkeypatch.setattr(collect.time, "sleep", lambda _seconds: None)

    assert collect.mode_incremental(db_path, force=True) == (1, 0)
    assert requested == ["AAA"]


def test_incremental_counts_source_no_data_as_completed(monkeypatch, tmp_path):
    """A name the source answers with "no data" is a completed request, not a failure."""
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=True)
    _add_universe(
        db_path, ("BBB", True, True), ("CCC", True, True), ("DDD", True, True),
        ("EEE", True, True), ("FFF", True, True),
    )
    raw = pd.concat({"AAA": _raw_frame()}, axis=1)
    monkeypatch.setattr(collect, "_download", lambda *_args, **_kwargs: raw)
    monkeypatch.setattr(collect.time, "sleep", lambda _seconds: None)
    probed: list[str] = []
    outcomes = {
        "BBB": _no_price_data("BBB"),
        "CCC": YFPricesMissingError(
            "CCC", " (period=5d)", "No data found, symbol may be delisted",
        ),
        "DDD": None,
        "EEE": YFPricesMissingError("EEE", " (period=5d)(Yahoo status_code = 500)"),
    }

    def probe(yf_ticker):
        probed.append(yf_ticker)
        if outcomes[yf_ticker] is None:
            return _raw_frame()
        raise outcomes[yf_ticker]

    monkeypatch.setattr(collect, "_probe_history", probe)

    # BBB and CCC: no data (completed). DDD: the batch missed it but the source
    # has it, so its bar is stored. EEE: an HTTP status (failed), after which
    # FFF is not re-asked and counts as failed too.
    assert collect.mode_incremental(db_path, force=True) == (6, 2)
    assert probed == ["BBB", "CCC", "DDD", "EEE"]
    assert _read(db_path, "SELECT ticker FROM prices ORDER BY ticker") == [("AAA",), ("DDD",)]


def test_incremental_does_not_probe_names_of_an_empty_batch(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=True)
    _add_universe(db_path, ("BBB", True, True))
    monkeypatch.setattr(collect, "_download", lambda *_args, **_kwargs: pd.DataFrame())
    monkeypatch.setattr(collect.time, "sleep", lambda _seconds: None)
    probed: list[str] = []
    monkeypatch.setattr(collect, "_probe_history", _probe_raises(_no_price_data("X"), probed))

    assert collect.mode_incremental(db_path, force=True) == (2, 2)
    assert probed == []


def test_price_fetch_record_covers_active_liquid_names(con):
    db.init_schema(con)
    con.executemany(
        "INSERT INTO universe (ticker,yf_ticker,active,liquid,backfill_done) "
        "VALUES (?,?,?,TRUE,TRUE)",
        [["AAA", "AAA", True], ["BBB", "BBB", True], ["GONE", "GONE", False]],
    )
    market_date = date(2026, 9, 28)
    insert_bars(con, "AAA", [market_date], open_=100, close=101, high=102, low=99)
    attempted_at = datetime(2026, 9, 28, 22, 33, tzinfo=timezone.utc)

    result = p15_price_fetch_attempts.record(
        con, market_date=market_date, attempted_at=attempted_at,
        requested_count=2, failed_count=0,
    )

    assert result == {
        "status": "complete", "market_date": "2026-09-28", "attempt_count": 2,
        "present_count": 1, "missing_count": 1,
    }
    assert con.execute("SELECT ticker,status FROM price_fetch_attempts").fetchall() == [
        ("BBB", "missing")
    ]
    p15_price_fetch_attempts.validate(con, ValueError)


def test_nightly_records_fetch_attempts_despite_inactive_and_delisted_names(
    monkeypatch, tmp_path,
):
    """The 10-14 nightly shape: inactive liquid names and a delisted active name
    withheld the whole batch (`attempt_count: 0 ... collection_incomplete`)."""
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=True)
    _add_universe(db_path, ("GONE", False, True), ("DLST", True, True))
    market_date = date(2026, 9, 28)
    raw = pd.concat({"AAA": _raw_frame(market_date.isoformat())}, axis=1)
    monkeypatch.setattr(collect, "_download", lambda *_args, **_kwargs: raw)
    monkeypatch.setattr(collect.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(collect, "_probe_history", _probe_raises(_no_price_data("DLST")))
    monkeypatch.setattr(collect, "write_meta", lambda *_args: None)
    monkeypatch.setattr(collect, "_is_trading_day", lambda _day: True)
    # A two-name store cannot meet the 90%-breadth market-date rule with one name
    # delisted; the production store resolves 10-14 with 4,072 of 4,099 names.
    monkeypatch.setattr(
        p15_incremental_collect.db, "latest_operational_market_date", lambda _con: market_date,
    )

    result = p15_incremental_collect.run(
        db_path, now=datetime(2026, 9, 28, 22, 33, tzinfo=timezone.utc),
    )

    assert result["status"] == "complete"
    assert (result["requested"], result["failed"], result["attempt_count"]) == (2, 0, 2)
    assert (result["present_count"], result["missing_count"]) == (1, 1)
    assert _read(db_path, "SELECT ticker,status FROM price_fetch_attempts") == [
        ("DLST", "missing")
    ]


def test_bar_with_a_non_positive_open_high_or_low_is_not_a_real_bar(con):
    """Rev-14 (g): WBD 2026-10-05 (open 0, volume 40) counted as WBD's last
    traded bar; WSLS 10-09 carried high = low = 0."""
    insert_bars(con, "WBD", [SESSIONS[0]], open_=30.95, close=30.94, high=30.96,
                low=30.93, volume=59_649_600)
    con.executemany(
        "INSERT INTO prices (ticker,date,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?)",
        [
            ("WBD", SESSIONS[1], 0.0, 30.99, 30.94, 30.95, 40),
            ("HIGH0", SESSIONS[1], 24.94, 0.0, 24.70, 24.80, 10),
            ("LOWNEG", SESSIONS[1], 24.94, 25.00, -1.0, 24.80, 10),
        ],
    )

    real = con.execute(
        f"SELECT ticker, MAX(date) FROM prices WHERE {db.REAL_BAR_SQL} GROUP BY 1 ORDER BY 1"
    ).fetchall()

    assert real == [("WBD", SESSIONS[0])]
    assert db.latest_real_prices_date(con) == SESSIONS[0]


def test_demoted_p15_ticker_keeps_exact_date_fetch_obligations_until_labeled(con):
    db.init_schema(con)
    p15_price_fetch_attempts.init_schema(con)
    con.execute(
        "CREATE TABLE agent_evaluation_traces "
        "(id BIGINT,policy_id VARCHAR,market_date DATE)"
    )
    con.execute(
        "CREATE TABLE agent_evaluation_decisions "
        "(id BIGINT,trace_id BIGINT,ticker VARCHAR,decision VARCHAR,decision_payload VARCHAR)"
    )
    con.execute(
        "CREATE TABLE agent_evaluation_labels_v2 "
        "(decision_id BIGINT,horizon_sessions INTEGER,label_basis VARCHAR)"
    )
    con.execute(
        "INSERT INTO universe (ticker,yf_ticker,active,liquid,backfill_done) "
        "VALUES ('AAA','AAA',FALSE,FALSE,FALSE)"
    )
    con.execute(
        "INSERT INTO agent_evaluation_traces VALUES (1,'p15-scoring-v1',?)",
        [SESSIONS[0]],
    )
    con.execute(
        "INSERT INTO agent_evaluation_decisions VALUES "
        "(1,1,'AAA','buy_candidate',?)",
        [json.dumps({"scoring_status": "available"})],
    )
    labeled_at = datetime(2024, 8, 5, tzinfo=timezone.utc)
    horizon_sessions = SESSIONS[1:21]
    insert_bars(con, "SPY", SESSIONS[1:24], open_=100, close=100, high=101, low=99)
    insert_bars(con, "AAA", horizon_sessions[:4], open_=100, close=101, high=102, low=99)
    con.execute("UPDATE prices SET fetched_at=?", [labeled_at.replace(tzinfo=None)])

    obligations = p15_price_fetch_attempts.open_label_obligations(
        con, through_date=SESSIONS[23], known_at=labeled_at,
    )

    assert {(row["ticker"], row["market_date"]) for row in obligations} == {
        ("AAA", market_date) for market_date in horizon_sessions[4:]
    }
    for obligation in obligations:
        p15_price_fetch_attempts.record_open_label_receipt(
            con, **obligation, requested_at=labeled_at - timedelta(minutes=1),
            completed_at=labeled_at, status="missing",
            outcome_reason=p15_price_fetch_attempts.OPEN_LABEL_MISSING_REASON,
            request_sha256=p15_price_fetch_attempts.open_label_request_sha256(
                obligation["ticker"], obligation["provider_ticker"],
                obligation["market_date"],
            ),
            response_sha256=(
                p15_price_fetch_attempts.open_label_missing_response_sha256()
            ),
        )
    p15_price_fetch_attempts.validate(con, ValueError)
    assert p15_price_fetch_attempts.open_label_obligations(
        con, through_date=SESSIONS[23], known_at=labeled_at,
    ) == []
    for horizon in (5, 10, 20):
        outcome = agent_evaluation._label_outcome_when_ready(
            con, "AAA", horizon_sessions[:horizon], labeled_at,
            grace_through=SESSIONS[23],
        )
        assert outcome["missing_bar_status"] == "last_available_close"
    insert_bars(con, "AAA", [horizon_sessions[4]], open_=100, close=101, high=102, low=99)
    con.execute(
        "UPDATE prices SET fetched_at=? WHERE ticker='AAA' AND date=?",
        [(labeled_at + timedelta(hours=1)).replace(tzinfo=None), horizon_sessions[4]],
    )
    p15_price_fetch_attempts.validate(con, ValueError)
    con.execute(
        "UPDATE p15_open_label_fetch_receipts SET request_sha256=? WHERE id=1",
        ["0" * 64],
    )
    with pytest.raises(ValueError, match="open-label fetch receipt differs"):
        p15_price_fetch_attempts.validate(con, ValueError)


def test_exact_label_fetch_distinguishes_missing_from_ambiguous_empty(con):
    obligation = {
        "ticker": "AAA", "provider_ticker": "AAA", "market_date": date(2026, 9, 25),
    }
    requested_at = datetime(2026, 9, 26, 1, tzinfo=timezone.utc)

    def missing(*_args):
        raise p15_incremental_collect.YFPricesMissingError(
            "AAA", "exact date", "Not Found, No data found, symbol may be delisted",
        )

    receipt, frame = p15_incremental_collect._fetch_exact(
        obligation, requested_at=requested_at, history=missing,
        sleep=lambda _seconds: None,
    )
    assert receipt["status"] == "missing" and frame is None
    assert receipt["outcome_reason"] == (
        p15_price_fetch_attempts.OPEN_LABEL_MISSING_REASON
    )

    # Rev-14 (e): yfinance's "possibly delisted; no price data found" carries no
    # Yahoo reason; the 10-14 nightly failed 14 of 15 exact fetches on it.
    def no_price_data(*_args):
        raise _no_price_data("AAA")

    receipt, frame = p15_incremental_collect._fetch_exact(
        obligation, requested_at=requested_at, history=no_price_data,
        sleep=lambda _seconds: None,
    )
    assert receipt["status"] == "missing" and frame is None
    assert receipt["outcome_reason"] == (
        p15_price_fetch_attempts.OPEN_LABEL_NO_PRICE_DATA_REASON
    )
    p15_price_fetch_attempts.record_open_label_receipt(
        con, completed_at=requested_at + timedelta(seconds=1), **receipt,
    )
    p15_price_fetch_attempts.validate(con, ValueError)
    con.execute("UPDATE p15_open_label_fetch_receipts SET outcome_reason=?",
                [p15_price_fetch_attempts.OPEN_LABEL_MISSING_REASON])
    with pytest.raises(ValueError, match="open-label fetch receipt differs"):
        p15_price_fetch_attempts.validate(con, ValueError)

    def http_status(*_args):
        raise YFPricesMissingError("AAA", " (1d 2026-09-25)(Yahoo status_code = 404)")

    assert p15_incremental_collect._fetch_exact(
        obligation, requested_at=requested_at, history=http_status,
        sleep=lambda _seconds: None,
    ) == (None, None)

    calls = 0

    def server_error(*_args):
        nonlocal calls
        calls += 1
        raise p15_incremental_collect.YFPricesMissingError(
            "AAA", "exact date", "Internal Server Error",
        )

    assert p15_incremental_collect._fetch_exact(
        obligation, requested_at=requested_at, history=server_error,
        sleep=lambda _seconds: None,
    ) == (None, None)
    assert calls == 2
    assert p15_incremental_collect._fetch_exact(
        obligation, requested_at=requested_at,
        history=lambda *_args: pd.DataFrame(), sleep=lambda _seconds: None,
    ) == (None, None)


def test_open_label_exact_fetch_is_bounded_and_reports_deferred(monkeypatch, tmp_path):
    database = tmp_path / "market.duckdb"
    _setup_store(database, liquid=True)
    market_date = date(2026, 9, 28)
    con = db.connect(database)
    con.execute(
        "INSERT INTO prices (ticker,date,open,high,low,close,volume) "
        "VALUES ('AAA',?,100,101,99,100,1000)",
        [market_date],
    )
    con.close()
    obligations = [
        {"ticker": f"OLD{index:02d}", "provider_ticker": f"OLD{index:02d}",
         "market_date": market_date}
        for index in range(p15_incremental_collect.MAX_OPEN_LABEL_FETCHES + 5)
    ]
    monkeypatch.setattr(
        p15_incremental_collect.collect, "mode_incremental",
        lambda *_args, **_kwargs: (1, 0),
    )
    monkeypatch.setattr(
        p15_incremental_collect.collect, "write_meta", lambda *_args: None,
    )
    monkeypatch.setattr(
        p15_incremental_collect.p15_price_fetch_attempts,
        "open_label_obligations",
        lambda *_args, **_kwargs: obligations,
    )
    calls = []

    def missing(provider, start, end):
        calls.append((provider, start, end))
        raise p15_incremental_collect.YFPricesMissingError(
            provider, "exact date", "No data found, symbol may be delisted",
        )

    result = p15_incremental_collect.run(
        database, now=datetime(2026, 9, 29, 1, tzinfo=timezone.utc),
        history=missing, sleep=lambda _seconds: None,
    )

    assert len(calls) == p15_incremental_collect.MAX_OPEN_LABEL_FETCHES
    assert result["open_label_requested"] == len(obligations)
    assert result["open_label_completed"] == len(calls)
    assert result["open_label_missing"] == len(calls)
    assert result["open_label_failed"] == 0
    assert result["open_label_deferred"] == 5
    assert result["open_label_outstanding"] == len(obligations)


def test_backfill_checkpoints_state_and_releases_db(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=True)
    observed: list[tuple[str, list[tuple]]] = []

    def download_while_reading(tickers, *, period, start):
        assert tickers == ["AAA"] and period == "max" and start is None
        observed.append(("download", _read(db_path, "SELECT state, progress FROM jobs")))
        return _raw_frame()

    def sleep_while_reading(seconds):
        assert seconds == 2
        observed.append(
            (
                "sleep",
                _read(
                    db_path,
                    "SELECT backfill_done, state, progress FROM universe, jobs",
                ),
            )
        )

    monkeypatch.setattr(collect, "_download", download_while_reading)
    monkeypatch.setattr(collect.time, "sleep", sleep_while_reading)

    assert collect.mode_backfill(db_path, None) == (1, 0)
    assert observed == [
        ("download", [("running", "0/1")]),
        ("sleep", [(True, "done", "1/1")]),
    ]


def test_bootstrap_releases_db_during_download_and_sleep(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=False)
    observed: list[tuple[str, int]] = []

    def download_while_reading(tickers, *, period, start):
        assert tickers == ["AAA"] and period is None and start is not None
        observed.append(("download", _read(db_path, "SELECT COUNT(*) FROM prices")[0][0]))
        return _raw_frame()

    def sleep_while_reading(seconds):
        assert seconds == 2
        observed.append(("sleep", _read(db_path, "SELECT COUNT(*) FROM prices")[0][0]))

    monkeypatch.setattr(collect, "_download", download_while_reading)
    monkeypatch.setattr(collect.time, "sleep", sleep_while_reading)

    assert collect.mode_bootstrap_floor(db_path, None) == (1, 0)
    assert observed == [("download", 0), ("sleep", 1)]
    assert _read(db_path, "SELECT liquid FROM universe WHERE ticker='AAA'") == [(True,)]


def test_refresh_releases_db_during_download_and_sleep(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=False)
    observed: list[tuple[str, int]] = []

    def download_while_reading(tickers, *, period, start):
        assert tickers == ["AAA"] and period is None and start is not None
        observed.append(("download", _read(db_path, "SELECT COUNT(*) FROM prices")[0][0]))
        return _raw_frame(volume=1_000)

    def sleep_while_reading(seconds):
        assert seconds == 2
        observed.append(("sleep", _read(db_path, "SELECT COUNT(*) FROM prices")[0][0]))

    monkeypatch.setattr(collect, "_download", download_while_reading)
    monkeypatch.setattr(collect.time, "sleep", sleep_while_reading)

    requested, failed, summary = collect.mode_refresh_liquid(db_path, None, False)
    assert (requested, failed) == (1, 0)
    assert summary["admitted"] == []
    assert summary["backfill"] == {"processed": 0, "failed": 0}
    assert observed == [("download", 0), ("sleep", 1)]


def test_refresh_retries_pending_backfill_without_new_admission(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=True)
    con = db.connect(db_path)
    try:
        db.upsert_prices(con, _stored_frame())
    finally:
        con.close()
    calls: list[tuple[list[str], str | None, str | None]] = []

    def download(tickers, *, period, start):
        calls.append((tickers, period, start))
        return _raw_frame(day="2026-09-09")

    monkeypatch.setattr(collect, "_download", download)
    monkeypatch.setattr(collect.time, "sleep", lambda _seconds: None)

    requested, failed, summary = collect.mode_refresh_liquid(db_path, None, False)

    assert (requested, failed) == (0, 0)
    assert summary["admitted"] == []
    assert summary["backfill"] == {"processed": 1, "failed": 0}
    assert calls == [(["AAA"], "max", None)]
    assert _read(db_path, "SELECT backfill_done FROM universe") == [(True,)]


def test_refresh_keeps_failed_pending_backfill_resumable(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=True)
    con = db.connect(db_path)
    try:
        db.upsert_prices(con, _stored_frame())
    finally:
        con.close()
    monkeypatch.setattr(collect, "_download", lambda *_args, **_kwargs: pd.DataFrame())
    monkeypatch.setattr(collect.liquid_history, "probe", lambda _ticker: ("fetch_error", None))
    monkeypatch.setattr(collect.time, "sleep", lambda _seconds: None)

    requested, failed, summary = collect.mode_refresh_liquid(db_path, None, False)

    assert (requested, failed) == (0, 0)
    assert summary["admitted"] == []
    assert summary["backfill"] == {"processed": 1, "failed": 1}
    assert _read(db_path, "SELECT backfill_done FROM universe") == [(False,)]


def test_refresh_with_no_pending_backfill_reports_zero_without_network(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=True, backfill_done=True)
    con = db.connect(db_path)
    try:
        db.upsert_prices(con, _stored_frame())
    finally:
        con.close()

    def unexpected_download(*_args, **_kwargs):
        raise AssertionError("no candidates or pending backfills must not make a network request")

    monkeypatch.setattr(collect, "_download", unexpected_download)

    requested, failed, summary = collect.mode_refresh_liquid(db_path, None, False)

    assert (requested, failed) == (0, 0)
    assert summary["admitted"] == []
    assert summary["backfill"] == {"processed": 0, "failed": 0}


def test_backfill_batch_state_rolls_back_with_price_rows(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=True)
    monkeypatch.setattr(collect, "_download", lambda *_args, **_kwargs: _raw_frame())

    def fail_progress(*_args, **_kwargs):
        raise RuntimeError("checkpoint failure")

    monkeypatch.setattr(collect, "_update_job", fail_progress)

    try:
        collect.mode_backfill(db_path, None)
    except RuntimeError as exc:
        assert str(exc) == "checkpoint failure"
    else:  # pragma: no cover - assertion branch
        raise AssertionError("failed checkpoint was accepted")
    assert _read(db_path, "SELECT COUNT(*) FROM prices") == [(0,)]
    assert _read(db_path, "SELECT backfill_done FROM universe") == [(False,)]
    assert _read(db_path, "SELECT state, progress FROM jobs") == [("running", "0/1")]


def test_limit_zero_is_an_explicit_no_network_path(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=True)

    def unexpected_download(*_args, **_kwargs):
        raise AssertionError("limit=0 must not make an HTTP request")

    monkeypatch.setattr(collect, "_download", unexpected_download)

    assert collect.mode_incremental(db_path, force=True, limit=0) == (0, 0)
    assert collect.mode_backfill(db_path, limit=0) == (0, 0)


def test_negative_limit_is_rejected_before_network(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=True)

    def unexpected_download(*_args, **_kwargs):
        raise AssertionError("invalid limits must not make an HTTP request")

    monkeypatch.setattr(collect, "_download", unexpected_download)

    try:
        collect.mode_incremental(db_path, force=True, limit=-1)
    except ValueError as exc:
        assert str(exc) == "limit must be non-negative"
    else:  # pragma: no cover - assertion branch
        raise AssertionError("negative limit was accepted")


def test_collection_metadata_preserves_other_producers(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    meta_path = tmp_path / "_meta.json"
    _setup_store(db_path, liquid=True)
    meta_path.write_text(
        json.dumps(
            {
                "regime": "risk-on",
                "last_screen": "2026-09-04T22:35:00+00:00",
                "fundamentals": {"last_run": "2026-09-05T00:33:22+00:00"},
                "price_verify": {"last_run": "2026-09-05T05:00:00+00:00"},
            }
        )
    )
    monkeypatch.setattr(collect, "_stale_cutoff", lambda _n=3: date(2026, 9, 1))

    collect.write_meta(db_path, "incremental", requested=1, failed=0, meta_path=meta_path)

    result = json.loads(meta_path.read_text())
    assert result["regime"] == "risk-on"
    assert result["last_screen"] == "2026-09-04T22:35:00+00:00"
    assert result["fundamentals"] == {"last_run": "2026-09-05T00:33:22+00:00"}
    assert result["price_verify"] == {"last_run": "2026-09-05T05:00:00+00:00"}
    assert result["mode"] == "incremental"
    assert result["universe_size"] == 1
    assert result["liquid_count"] == 1
    assert result["failed_this_run"] == 0


def test_stale_provisional_bar_is_asked_again_and_retired_when_never_settled(
    monkeypatch, tmp_path,
):
    """DDS and SUNC 2026-10-12 and CIB 2026-10-16 kept their same-night bars (open
    outside the range) after the newest session moved on: the source answered NaN
    for DDS/SUNC on every later night, and CIB left the fetch set (deactivated)."""
    db_path = tmp_path / "market.duckdb"
    _setup_store(db_path, liquid=True)
    day, latest = date(2026, 10, 12), date(2026, 10, 13)
    same_night = datetime(2026, 10, 12, 22, 30)
    con = db.connect(db_path)
    try:
        bars = [("DDS", day, 648.70, 648.54, 618.64, 642.29, same_night),   # open > high
                ("CIB", day, 95.97, 98.13, 96.87, 97.91, same_night),       # open < low
                ("ET", day, 18.0, 18.5, 17.5, 18.2, same_night),            # valid, unsettled
                ("AAA", latest, 10.5, 10.0, 9.0, 9.5, datetime(2026, 10, 13, 22, 30))]
        con.executemany("INSERT INTO prices (ticker,date,open,high,low,close,volume,"
                        "fetched_at) VALUES (?,?,?,?,?,?,1000,?)", bars)
    finally:
        con.close()
    asked = []

    def download(tickers, *, period, start):
        asked.append((tuple(tickers), period, start))
        frames = {
            "CIB": pd.DataFrame({"Open": [95.97, 96.0], "High": [98.13, 97.0],
                                 "Low": [95.97, 95.0], "Close": [97.91, 96.5],
                                 "Volume": [183_400, 100_000]},
                                index=pd.DatetimeIndex(["2026-10-12", "2026-10-13"])),
            **{t: pd.DataFrame({"Open": [float("nan")], "High": [float("nan")],
                                "Low": [float("nan")], "Close": [float("nan")],
                                "Volume": [float("nan")]},
                               index=pd.DatetimeIndex(["2026-10-12"])) for t in ("DDS", "ET")},
        }
        return pd.concat({t: frames[t] for t in tickers}, axis=1)

    monkeypatch.setattr(collect, "_download", download)
    report = collect.settle_stale_provisional(db_path, today=date(2026, 10, 14))

    assert asked == [(("CIB", "DDS", "ET"), None, "2026-10-12")]
    assert report["stale"] == 3 and report["refetched"] == 1
    assert report["retired_keys"] == ["DDS 2026-10-12"]
    rows = _read(db_path, "SELECT ticker, date, open, low FROM prices ORDER BY ticker, date")
    # CIB settled from the source (only the stale key, never the 10-13 bar of an
    # inactive name); DDS left the cache with its original retained; ET is valid
    # and stays to be asked again; the newest session is untouched.
    assert [(t, d.isoformat()) for t, d, *_ in rows] == [
        ("AAA", "2026-10-13"), ("CIB", "2026-10-12"), ("ET", "2026-10-12")]
    assert rows[1][2:] == pytest.approx((95.97, 95.97))
    assert _read(db_path, "SELECT reason FROM price_observation_rejects WHERE ticker='DDS' "
                          "AND open = 648.7") == [("stale_provisional,high_geometry",)]
    # The next night asks again for the valid unsettled ET bar and for DDS's hole;
    # the source still has no bar for either, so nothing is stored or rejected.
    rejects = _read(db_path, "SELECT COUNT(*) FROM price_observation_rejects")
    again = collect.settle_stale_provisional(db_path, today=date(2026, 10, 14))
    assert again["keys"] == ["DDS 2026-10-12", "ET 2026-10-12"]
    assert again["refetched"] == 0 and again["retired"] == 0
    assert _read(db_path, "SELECT COUNT(*) FROM price_observation_rejects") == rejects
