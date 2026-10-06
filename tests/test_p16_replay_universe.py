"""Point-in-time replay universe, liquidity and screen from as-of private prices."""
from __future__ import annotations

from datetime import date, datetime, timezone

import duckdb
import pandas as pd

from engine.daily_opportunities import p15_universe
from engine.lib import db
from farm.replay.asof import reconstruct_unadjusted_bars
from farm.replay.runner import ReplaySessionStore, run_session, session_phases
from farm.replay.universe import build_session_universe
from sim import nyse


def _sessions(count: int, start: date = date(2023, 1, 3)) -> list[date]:
    out, current = [], start
    while len(out) < count:
        if nyse.is_session(current):
            out.append(current)
        current = date.fromordinal(current.toordinal() + 1)
    return out


SESSIONS = _sessions(300)
D = SESSIONS[280]


def _prices(con, ticker: str, days: list[date], base: float = 20.0) -> None:
    frame = pd.DataFrame({
        "ticker": ticker, "date": days,
        "open": [base + index * 0.1 for index in range(len(days))],
        "high": [base + index * 0.1 + 1 for index in range(len(days))],
        "low": [base + index * 0.1 - 1 for index in range(len(days))],
        "close": [base + index * 0.1 for index in range(len(days))],
        "volume": 2_000_000, "source": "historical_backfill",
        "fetched_at": datetime(2024, 1, 1),
    })
    with db.registered_frame(con, "_bars", frame):
        con.execute(
            """INSERT INTO prices
            (ticker,date,open,high,low,close,volume,source,fetched_at)
            SELECT ticker,date,open,high,low,close,volume,source,fetched_at FROM _bars"""
        )


def _con():
    con = duckdb.connect(":memory:")
    db.init_schema(con)
    _prices(con, "AAA", SESSIONS)
    _prices(con, "BBB", SESSIONS, base=30.0)
    _prices(con, "NEWCO", SESSIONS[281:])          # first bar after D
    _prices(con, "GONE", SESSIONS[:270], base=10.0)  # delisted before D
    return con


def test_security_listed_after_d_and_later_bars_are_invisible():
    con = _con()
    result = build_session_universe(con, D)
    assert result["screened"] == 2
    assert con.execute(
        "SELECT ticker,active,liquid FROM universe ORDER BY ticker"
    ).fetchall() == [("AAA", True, True), ("BBB", True, True), ("GONE", False, False)]
    assert con.execute(
        "SELECT COUNT(*) FROM screen_results WHERE ticker='NEWCO'"
    ).fetchone() == (0,)
    # D's screen equals one built from a store holding no bar after D.
    clean = duckdb.connect(":memory:")
    db.init_schema(clean)
    for ticker, days, base in (("AAA", SESSIONS[:281], 20.0), ("BBB", SESSIONS[:281], 30.0),
                               ("GONE", SESSIONS[:270], 10.0)):
        _prices(clean, ticker, days, base)
    build_session_universe(clean, D)
    query = "SELECT * FROM screen_results ORDER BY ticker"
    assert con.execute(query).fetchall() == clean.execute(query).fetchall()


def test_screen_computed_after_d_is_invisible_to_d_scoring():
    con = _con()
    _prices(con, "SPY", SESSIONS, base=50.0)
    build_session_universe(con, D)
    later = SESSIONS[285]
    build_session_universe(con, later)
    assert con.execute(
        "SELECT run_date,COUNT(*) FROM screen_results GROUP BY run_date ORDER BY run_date"
    ).fetchall() == [(D, 3), (later, 3)]
    universe = p15_universe(con, D)
    assert "NEWCO" not in {row["ticker"] for row in universe["candidates"]}
    assert con.execute(
        "SELECT MAX(run_date) FROM screen_results WHERE run_date<=?", [D]
    ).fetchone() == (D,)
    # Re-running D (resume) never rewrites the append-only screen.
    assert build_session_universe(con, D)["screened"] == 0


def test_delisted_security_is_a_member_before_its_delisting_and_kept_after():
    con = _con()
    before = SESSIONS[265]
    build_session_universe(con, before)
    build_session_universe(con, D)
    assert con.execute(
        "SELECT snapshot_date,active FROM universe_snapshot WHERE ticker='GONE' "
        "ORDER BY snapshot_date"
    ).fetchall() == [(before, True), (D, False)]
    assert con.execute(
        "SELECT COUNT(*) FROM screen_results WHERE ticker='GONE' AND run_date=?", [before]
    ).fetchone() == (1,)
    assert con.execute(
        "SELECT COUNT(*) FROM universe_snapshot WHERE ticker='NEWCO'"
    ).fetchone() == (0,)


def test_run_session_builds_the_screen_before_scoring(tmp_path):
    root = (tmp_path / "research").resolve()
    root.mkdir()
    live = (tmp_path / "live.duckdb").resolve()
    live.touch()
    checkpoint, session = SESSIONS[279], SESSIONS[280]
    bars = reconstruct_unadjusted_bars(
        [
            {
                "security_id": ticker.lower(), "ticker": ticker, "session": day,
                "series": "source_back_adjusted_v1",
                "available_at": session_phases(day)["close_visible"].isoformat(),
                "open": 20 + index * 0.1, "high": 21 + index * 0.1,
                "low": 19 + index * 0.1, "close": 20 + index * 0.1, "volume": 2_000_000,
            }
            for ticker in ("SPY", "AAA", "NEWCO")
            for index, day in enumerate(SESSIONS)
            if ticker != "NEWCO" or day > session
        ],
        [],
    )
    seen = {}

    def execute(phase, market_date, _logical_at, _context):
        if phase == "SCORE":
            with duckdb.connect(str(root / "replay.duckdb"), read_only=True) as con:
                seen["screen"] = con.execute(
                    "SELECT run_date,ticker FROM screen_results ORDER BY ticker"
                ).fetchall()
                seen["universe"] = con.execute(
                    "SELECT ticker,etf,active FROM universe ORDER BY ticker"
                ).fetchall()
        return [{"status": "completed"}]

    store = ReplaySessionStore(
        path=root / "replay.duckdb", research_root=root, live_db_path=live,
        cohort_id="fixture", policy_id="control", checkpoint=checkpoint,
        initialized_at=datetime(2026, 9, 27, tzinfo=timezone.utc),
        reconstructed_bars=bars, securities={"SPY": {"etf": True}},
        _test_execute_phase=execute,
    )
    run_session(store, session)
    assert seen["screen"] == [(session, "AAA"), (session, "SPY")]
    assert seen["universe"] == [("AAA", None, True), ("SPY", True, True)]
