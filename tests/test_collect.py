"""EOD collection releases DuckDB around network work and checkpoints batches."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

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
    con.execute(
        "UPDATE p15_open_label_fetch_receipts SET request_sha256=? WHERE id=1",
        ["0" * 64],
    )
    with pytest.raises(ValueError, match="open-label fetch receipt differs"):
        p15_price_fetch_attempts.validate(con, ValueError)


def test_exact_label_fetch_distinguishes_missing_from_ambiguous_empty():
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
