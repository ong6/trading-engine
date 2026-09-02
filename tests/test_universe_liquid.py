"""`universe.liquid` recompute (collect.py --refresh-liquid).

The flag had one writer — the 2026-07-16 bootstrap — so the forward record
could never admit a newly liquid name. The refresh recomputes it from the
trailing 63-session median dollar volume under the SAME floor bootstrap used
(close >= $3, median $vol >= $5M), admits, and demotes flag-only.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import collect  # noqa: E402  (engine/collect.py)
from engine.lib import db  # noqa: E402
from tests.conftest import insert_bars, sessions  # noqa: E402

DAYS = sessions(date(2024, 1, 2), date(2024, 7, 31))      # ~150 sessions
WINDOW = DAYS[-collect.LIQ_BARS:]
OLD = DAYS[:-collect.LIQ_BARS - 5]                          # ends before the window


def _row(con, ticker, *, active=True, liquid=False):
    # A name that is already liquid was backfilled by the bootstrap.
    con.execute("INSERT INTO universe (ticker, yf_ticker, active, liquid, backfill_done) "
                "VALUES (?, ?, ?, ?, ?)", [ticker, ticker, active, liquid, liquid])


def _setup(con):
    db.init_schema(con)
    # NEW: listed after bootstrap, clearly liquid ($10 x 1M = $10M/day) -> admit
    _row(con, "NEW", liquid=False)
    insert_bars(con, "NEW", WINDOW, open_=10.0, close=10.0, volume=1_000_000)
    # THIN: was liquid, now $10 x 100k = $1M/day -> demote
    _row(con, "THIN", liquid=True)
    insert_bars(con, "THIN", WINDOW, open_=10.0, close=10.0, volume=100_000)
    # PENNY: was liquid, $2 x 10M = $20M/day but close < $3 -> demote
    _row(con, "PENNY", liquid=True)
    insert_bars(con, "PENNY", WINDOW, open_=2.0, close=2.0, volume=10_000_000)
    # GONE: was liquid, no bars inside the window at all -> demote
    _row(con, "GONE", liquid=True)
    insert_bars(con, "GONE", OLD, open_=50.0, close=50.0, volume=5_000_000)
    # HELD: delisted (active=FALSE), no fresh bars, but a book holds it -> kept
    _row(con, "HELD", active=False, liquid=True)
    insert_bars(con, "HELD", OLD, open_=200.0, close=200.0, volume=5_000_000)
    con.execute("INSERT INTO portfolios (id, name, strategy, created, active, cash) "
                "VALUES ('b', 'b', 'x', ?, TRUE, 1000)", [DAYS[0]])
    con.execute("INSERT INTO sim_positions (portfolio_id, ticker, qty, avg_cost) "
                "VALUES ('b', 'HELD', 10, 200.0)")
    # DEAD_NEW: qualifies on the numbers but is not active -> never admitted
    _row(con, "DEAD_NEW", active=False, liquid=False)
    insert_bars(con, "DEAD_NEW", WINDOW, open_=10.0, close=10.0, volume=1_000_000)
    # STAY: liquid and still liquid -> untouched
    _row(con, "STAY", liquid=True)
    insert_bars(con, "STAY", WINDOW, open_=100.0, close=100.0, volume=1_000_000)


def test_liquid_flags_apply_bootstrap_rule_over_trailing_window(con):
    _setup(con)
    flags = collect.liquid_flags(con).set_index("ticker")
    assert flags.loc["NEW", "qualifies"] and flags.loc["STAY", "qualifies"]
    assert not flags.loc["THIN", "qualifies"]
    assert not flags.loc["PENNY", "qualifies"]        # $20M/day but < $3
    assert "GONE" not in flags.index                  # no bars in the window
    assert flags.loc["NEW", "nbars"] == collect.LIQ_BARS
    assert flags.loc["NEW", "med_dollar_vol"] == 10_000_000


def test_refresh_admits_demotes_and_keeps_held(con):
    _setup(con)
    before = con.execute("SELECT COUNT(*) FROM universe").fetchone()[0]
    out = collect.apply_liquid_flags(con, collect.liquid_flags(con), dry_run=False)
    assert out["admitted"] == ["NEW"]
    assert out["demoted"] == ["GONE", "PENNY", "THIN"]
    assert out["kept_held"] == ["HELD"]
    liquid = {r[0]: r[1] for r in con.execute("SELECT ticker, liquid FROM universe").fetchall()}
    assert liquid == {"NEW": True, "THIN": False, "PENNY": False, "GONE": False,
                      "HELD": True, "DEAD_NEW": False, "STAY": True}
    # flag-only: no row deleted, and the admitted name is queued for backfill
    assert con.execute("SELECT COUNT(*) FROM universe").fetchone()[0] == before
    assert con.execute("SELECT COUNT(*) FROM prices WHERE ticker = 'GONE'").fetchone()[0] == len(OLD)
    assert con.execute("SELECT ticker FROM universe WHERE liquid AND NOT backfill_done").fetchall() == [("NEW",)]
    assert out["liquid_after"] == 3


def test_dry_run_changes_nothing(con):
    _setup(con)
    snap = con.execute("SELECT ticker, liquid FROM universe ORDER BY ticker").fetchall()
    out = collect.apply_liquid_flags(con, collect.liquid_flags(con), dry_run=True)
    assert out["admitted"] == ["NEW"] and out["demoted"] == ["GONE", "PENNY", "THIN"]
    assert out["dry_run"] is True
    assert con.execute("SELECT ticker, liquid FROM universe ORDER BY ticker").fetchall() == snap


def test_refresh_is_idempotent(con):
    _setup(con)
    flags = collect.liquid_flags(con)
    collect.apply_liquid_flags(con, flags, dry_run=False)
    again = collect.apply_liquid_flags(con, flags, dry_run=False)
    assert again["admitted"] == [] and again["demoted"] == []
    assert again["kept_held"] == ["HELD"]


def test_no_sim_schema_means_nothing_is_held():
    import duckdb
    c = duckdb.connect()
    db.init_schema(c)
    assert collect._held_tickers(c) == set()
    assert collect.liquid_flags(c).empty
