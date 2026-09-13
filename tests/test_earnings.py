"""Earnings pulls preserve honest, restart-safe per-ticker outcomes."""

from __future__ import annotations

from datetime import date, timedelta

import duckdb
import pytest

from engine import earnings
from engine.lib import db


@pytest.fixture
def earnings_con():
    con = duckdb.connect()
    db.init_schema(con)
    db.init_mining_schema(con)
    yield con
    con.close()


def _run(monkeypatch, con, tmp_path, pairs, responses):
    remaining = iter(responses)
    monkeypatch.setattr(earnings, "_select_universe", lambda _con, _params: (pairs, "test"))
    monkeypatch.setattr(earnings, "_fetch_calendar", lambda _ticker: next(remaining))
    monkeypatch.setattr(earnings, "PER_NAME_SLEEP", 0)
    monkeypatch.setattr(earnings.rsc, "dir_size_gb", lambda _path: 0.0)
    return earnings.run({}, con, meta_path=tmp_path / "meta.json")


def test_default_universe_is_active_equities_from_fundamentals_and_latest_screen(
    earnings_con,
):
    today = date.today()
    earnings_con.executemany(
        """
        INSERT INTO universe (ticker, yf_ticker, active, liquid, etf)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            ("FUND", "FUND.YF", True, True, False),
            ("SCREEN", "SCREEN.YF", True, True, False),
            ("FUND_ETF", "FUND_ETF.YF", True, True, True),
            ("SCREEN_ETF", "SCREEN_ETF.YF", True, True, True),
            ("INACTIVE", "INACTIVE.YF", False, True, False),
            ("OLD_SCREEN", "OLD_SCREEN.YF", True, True, False),
            ("LATEST_FAIL", "LATEST_FAIL.YF", True, True, False),
            ("TOO_OLD", "TOO_OLD.YF", True, True, False),
        ],
    )
    earnings_con.executemany(
        "INSERT INTO fundamentals (ticker, as_of, market_cap) VALUES (?, ?, ?)",
        [
            ("FUND", today, 1_000_000),
            ("FUND_ETF", today, 1_000_000),
            ("INACTIVE", today, 1_000_000),
            ("MISSING_UNIVERSE", today, 1_000_000),
            ("TOO_OLD", today - timedelta(days=15), 1_000_000),
        ],
    )
    earnings_con.executemany(
        """
        INSERT INTO screen_results (run_date, ticker, passes_template)
        VALUES (?, ?, ?)
        """,
        [
            (today - timedelta(days=1), "OLD_SCREEN", True),
            (today, "SCREEN", True),
            (today, "SCREEN_ETF", True),
            (today, "INACTIVE", True),
            (today, "LATEST_FAIL", False),
        ],
    )

    pairs, source = earnings._select_universe(earnings_con, {})

    assert source == "fundamentals-coverage ∪ screen-passers"
    assert pairs == [("FUND", "FUND.YF"), ("SCREEN", "SCREEN.YF")]


def test_default_universe_fallback_is_active_liquid_non_etf(earnings_con):
    earnings_con.executemany(
        """
        INSERT INTO universe (ticker, yf_ticker, active, liquid, etf)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            ("ELIGIBLE", "ELIGIBLE.YF", True, True, False),
            ("INACTIVE", "INACTIVE.YF", False, True, False),
            ("ILLIQUID", "ILLIQUID.YF", True, False, False),
            ("ETF", "ETF.YF", True, True, True),
        ],
    )

    pairs, source = earnings._select_universe(earnings_con, {})

    assert source == "liquid-non-etf (fundamentals empty)"
    assert pairs == [("ELIGIBLE", "ELIGIBLE.YF")]


def test_explicit_universe_preserves_order_mapping_and_unrestricted_override(
    earnings_con,
):
    earnings_con.executemany(
        """
        INSERT INTO universe (ticker, yf_ticker, active, liquid, etf)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            ("ETF", "ETF.YF", True, True, True),
            ("INACTIVE", None, False, False, False),
        ],
    )

    pairs, source = earnings._select_universe(earnings_con, {"tickers": " etf, inactive, missing "})

    assert source == "explicit-tickers"
    assert pairs == [
        ("ETF", "ETF.YF"),
        ("INACTIVE", "INACTIVE"),
        ("MISSING", "MISSING"),
    ]


def test_fetch_log_validates_and_preserves_attempts(earnings_con):
    today = date.today()
    rows = [{"ticker": "AAA", "status": "failed", "n_dates": 0}]
    assert db.insert_earnings_fetch_log(earnings_con, rows, as_of=today) == 1
    assert db.insert_earnings_fetch_log(earnings_con, rows, as_of=today) == 1
    assert earnings_con.execute(
        "SELECT COUNT(*) FROM earnings_fetch_log WHERE ticker = 'AAA'"
    ).fetchone() == (2,)

    with pytest.raises(ValueError, match="invalid earnings fetch status"):
        db.insert_earnings_fetch_log(
            earnings_con,
            [{"ticker": "AAA", "status": "unknown", "n_dates": 0}],
            as_of=today,
        )
    with pytest.raises(ValueError, match="inconsistent earnings fetch outcome"):
        db.insert_earnings_fetch_log(
            earnings_con,
            [{"ticker": "AAA", "status": "ok", "n_dates": 0}],
            as_of=today,
        )


def test_resume_skips_ok_and_empty_but_retries_failed(monkeypatch, earnings_con, tmp_path):
    pairs = [("AAA", "AAA"), ("BBB", "BBB"), ("CCC", "CCC")]
    first = _run(
        monkeypatch,
        earnings_con,
        tmp_path,
        pairs,
        [{"Earnings Date": [date(2026, 10, 1)]}, {}, None],
    )
    assert first["pulled_this_run"] == 3
    assert (first["with_upcoming_date"], first["no_upcoming_date"], first["failed_tickers"]) == (
        1,
        1,
        1,
    )

    second = _run(
        monkeypatch,
        earnings_con,
        tmp_path,
        pairs,
        [{"Earnings Date": [date(2026, 11, 1), date(2026, 11, 2)]}],
    )
    assert second["pulled_this_run"] == 1
    assert second["with_upcoming_date"] == 1
    assert earnings_con.execute(
        "SELECT ticker, status, n_dates FROM earnings_fetch_log ORDER BY attempted_at, ticker"
    ).fetchall() == [
        ("AAA", "ok", 1),
        ("BBB", "empty", 0),
        ("CCC", "failed", 0),
        ("CCC", "ok", 2),
    ]
    assert earnings._already_done(earnings_con, date.today()) == {"AAA", "BBB", "CCC"}


def test_legacy_calendar_row_remains_resume_evidence(earnings_con):
    today = date.today()
    earnings_con.execute(
        "INSERT INTO earnings_calendar "
        "(ticker, earnings_date, as_of, is_estimate) VALUES ('OLD', ?, ?, FALSE)",
        [date(2026, 12, 1), today],
    )
    db.insert_earnings_fetch_log(
        earnings_con,
        [{"ticker": "RETRY", "status": "failed", "n_dates": 0}],
        as_of=today,
    )
    assert earnings._already_done(earnings_con, today) == {"OLD"}


def test_calendar_and_fetch_log_checkpoint_roll_back_together(monkeypatch, earnings_con, tmp_path):
    def fail_log(*_args, **_kwargs):
        raise RuntimeError("injected fetch-log failure")

    monkeypatch.setattr(db, "insert_earnings_fetch_log", fail_log)
    with pytest.raises(RuntimeError, match="injected fetch-log failure"):
        _run(
            monkeypatch,
            earnings_con,
            tmp_path,
            [("AAA", "AAA")],
            [{"Earnings Date": [date(2026, 10, 1)]}],
        )
    assert earnings_con.execute("SELECT COUNT(*) FROM earnings_calendar").fetchone() == (0,)
    assert earnings_con.execute("SELECT COUNT(*) FROM earnings_fetch_log").fetchone() == (0,)


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
        return {}

    monkeypatch.setattr(earnings, "_fetch_calendar", fetch_while_reading)
    monkeypatch.setattr(earnings, "PER_NAME_SLEEP", 0)
    monkeypatch.setattr(earnings.rsc, "dir_size_gb", lambda _path: 0.0)
    result = earnings.run_connection_narrowed(
        {"tickers": ["AAA"]}, db_path=db_path, meta_path=tmp_path / "meta.json"
    )
    assert observed == [1]
    assert result["no_upcoming_date"] == 1
    check = db.connect(db_path, read_only=True)
    try:
        assert check.execute("SELECT ticker, status FROM earnings_fetch_log").fetchall() == [
            ("AAA", "empty")
        ]
    finally:
        check.close()
