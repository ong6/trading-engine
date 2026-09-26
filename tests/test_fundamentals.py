"""Fundamentals pulls preserve honest, restart-safe per-ticker outcomes."""
from __future__ import annotations

from datetime import date

import duckdb
import pytest

from engine import fundamentals
from engine.lib import db


@pytest.fixture
def fundamentals_con():
    con = duckdb.connect()
    db.init_mining_schema(con)
    yield con
    con.close()


def _run(monkeypatch, con, tmp_path, pairs, responses):
    remaining = iter(responses)
    monkeypatch.setattr(fundamentals, "_select_universe", lambda _con, _params: pairs)
    monkeypatch.setattr(fundamentals, "_fetch_info", lambda _ticker: next(remaining))
    monkeypatch.setattr(fundamentals, "PER_NAME_SLEEP", 0)
    monkeypatch.setattr(fundamentals.rsc, "dir_size_gb", lambda _path: 0.0)
    return fundamentals.run({}, con, meta_path=tmp_path / "meta.json")


def test_fetch_log_validates_and_preserves_failed_attempts(fundamentals_con):
    today = date.today()
    rows = [{"ticker": "AAA", "status": "failed", "n_fields": 0}]
    assert db.insert_fundamentals_fetch_log(fundamentals_con, rows, as_of=today) == 1
    assert db.insert_fundamentals_fetch_log(fundamentals_con, rows, as_of=today) == 1
    assert fundamentals_con.execute(
        "SELECT COUNT(*) FROM fundamentals_fetch_log WHERE ticker = 'AAA'"
    ).fetchone() == (2,)

    with pytest.raises(ValueError, match="invalid fundamentals fetch status"):
        db.insert_fundamentals_fetch_log(
            fundamentals_con,
            [{"ticker": "AAA", "status": "empty", "n_fields": 0}],
            as_of=today,
        )
    with pytest.raises(ValueError, match="inconsistent fundamentals fetch outcome"):
        db.insert_fundamentals_fetch_log(
            fundamentals_con,
            [{"ticker": "AAA", "status": "ok", "n_fields": 0}],
            as_of=today,
        )


def test_resume_skips_committed_snapshot_but_retries_failed(
    monkeypatch, fundamentals_con, tmp_path
):
    pairs = [("AAA", "AAA"), ("BBB", "BBB")]
    first = _run(
        monkeypatch,
        fundamentals_con,
        tmp_path,
        pairs,
        [{"quoteType": "EQUITY", "marketCap": 10_000}, {}],
    )
    assert first["pulled_this_run"] == 2
    assert (first["with_data"], first["with_market_cap"], first["failed_tickers"]) == (
        1,
        1,
        1,
    )

    second = _run(
        monkeypatch,
        fundamentals_con,
        tmp_path,
        pairs,
        [{"quoteType": "EQUITY", "sector": "Technology"}],
    )
    assert second["pulled_this_run"] == 1
    assert second["with_data"] == 1
    assert fundamentals_con.execute(
        "SELECT ticker, status, n_fields FROM fundamentals_fetch_log "
        "ORDER BY attempted_at, ticker"
    ).fetchall() == [
        ("AAA", "ok", 2),
        ("BBB", "failed", 0),
        ("BBB", "ok", 2),
    ]
    assert fundamentals._already_done(fundamentals_con, date.today()) == {"AAA", "BBB"}


def test_orphaned_ok_log_does_not_hide_missing_snapshot(fundamentals_con):
    today = date.today()
    db.insert_fundamentals_fetch_log(
        fundamentals_con,
        [{"ticker": "ORPHAN", "status": "ok", "n_fields": 1}],
        as_of=today,
    )
    assert fundamentals._already_done(fundamentals_con, today) == set()


def test_default_universe_excludes_inactive_liquid_names_but_override_does_not(
    fundamentals_con,
):
    db.init_schema(fundamentals_con)
    fundamentals_con.executemany(
        "INSERT INTO universe (ticker,yf_ticker,active,liquid,etf) VALUES (?,?,?,?,FALSE)",
        [("ACTIVE", "ACTIVE", True, True), ("INACTIVE", "INACTIVE", False, True)],
    )

    assert fundamentals._select_universe(fundamentals_con, {}) == [("ACTIVE", "ACTIVE")]
    assert fundamentals._select_universe(
        fundamentals_con, {"tickers": ["INACTIVE"]}
    ) == [("INACTIVE", "INACTIVE")]


def test_snapshot_and_fetch_log_checkpoint_roll_back_together(
    monkeypatch, fundamentals_con, tmp_path
):
    def fail_log(*_args, **_kwargs):
        raise RuntimeError("injected fetch-log failure")

    monkeypatch.setattr(db, "insert_fundamentals_fetch_log", fail_log)
    with pytest.raises(RuntimeError, match="injected fetch-log failure"):
        _run(
            monkeypatch,
            fundamentals_con,
            tmp_path,
            [("AAA", "AAA")],
            [{"quoteType": "EQUITY", "marketCap": 10_000}],
        )
    assert fundamentals_con.execute("SELECT COUNT(*) FROM fundamentals").fetchone() == (0,)
    assert fundamentals_con.execute(
        "SELECT COUNT(*) FROM fundamentals_fetch_log"
    ).fetchone() == (0,)


def test_connection_narrowed_run_releases_db_during_fetch(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    con = db.connect(db_path)
    db.init_schema(con)
    con.execute(
        "INSERT INTO universe (ticker, yf_ticker, active, liquid, etf) "
        "VALUES ('AAA', 'AAA', TRUE, TRUE, FALSE)"
    )
    con.close()

    observed = []

    def fetch_while_reading(_ticker):
        reader = db.connect(db_path, read_only=True, wait_s=0)
        try:
            observed.append(reader.execute("SELECT COUNT(*) FROM universe").fetchone()[0])
        finally:
            reader.close()
        return {"quoteType": "EQUITY", "marketCap": 10_000}

    monkeypatch.setattr(fundamentals, "_fetch_info", fetch_while_reading)
    monkeypatch.setattr(fundamentals, "PER_NAME_SLEEP", 0)
    monkeypatch.setattr(fundamentals.rsc, "dir_size_gb", lambda _path: 0.0)
    result = fundamentals.run_connection_narrowed(
        {"tickers": ["AAA"]}, db_path=db_path, meta_path=tmp_path / "meta.json"
    )
    assert observed == [1]
    assert result["with_data"] == 1
    check = db.connect(db_path, read_only=True)
    try:
        assert check.execute(
            "SELECT ticker, status FROM fundamentals_fetch_log"
        ).fetchall() == [("AAA", "ok")]
    finally:
        check.close()
