"""engine/actions.py — the split reconciler's adjudicator and restatement.

Synthetic series on the conftest session calendar, in-memory DuckDB. The three
regressions here are the 2026-09-02 findings: a ratio-sized ordinary move was
accepted as "the break" anywhere in the scan window (BH / ORCL / NEM), and
`_restate` scaled every open position instead of only lots opened before the
ex-date (the declared truth in sim/portfolio.rebuild_state).
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

import pytest

from conftest import SESSIONS, insert_bars
from engine import actions
from engine.lib import db
from sim import portfolio
from sim.schema import INITIAL_CASH

TK = "AAA"
RATIO = 1.5
EX_IDX = 20
EX = SESSIONS[EX_IDX]
PRE = 100.0                 # pre-split scale
POST = PRE / RATIO          # post-split scale (66.67)

FETCHED_BEFORE_EX = datetime.combine(SESSIONS[0], time(23, 0))          # stored pre-ex
FETCHED_AFTER_EX = datetime.combine(SESSIONS[-1] + timedelta(days=1), time(23, 0))


def _setup(con, closes: list[float], fetched: datetime | list[datetime]) -> None:
    db.init_actions_schema(con)
    insert_bars(con, TK, SESSIONS, open_=closes, close=closes)
    fl = fetched if isinstance(fetched, list) else [fetched] * len(SESSIONS)
    con.executemany("UPDATE prices SET fetched_at = ? WHERE ticker = ? AND date = ?",
                    [[f, TK, d] for f, d in zip(fl, SESSIONS)])
    con.execute("INSERT INTO corporate_actions VALUES (?, ?, 'split', ?, 'yfinance', now())",
                [TK, EX, RATIO])


def _closes(con) -> dict:
    return dict(con.execute(
        "SELECT date, close FROM prices WHERE ticker = ? ORDER BY date", [TK]).fetchall())


def _verdict(con) -> tuple:
    return con.execute(
        "SELECT outcome, break_date, rows_restated FROM split_adjustments WHERE ticker = ?",
        [TK]).fetchone()


def _step(i: int, lo: float, hi: float) -> list[float]:
    """`lo` before session i, `hi` from session i on."""
    return [lo if k < i else hi for k in range(len(SESSIONS))]


# --------------------------------------------------------------------------- #
# rule 1+2: tolerance and location
# --------------------------------------------------------------------------- #
def test_rejects_earnings_drop_8_sessions_after_adjusted_ex(con):
    """Yahoo already adjusted the 3:2 split (series continuous at EX). Eight
    sessions later the stock drops 22% on earnings: 100/78 = 1.28, inside the
    old ±20% band around 1.5. Must NOT be restated (this was BH / ORCL / NEM)."""
    closes = _step(EX_IDX + 8, 100.0, 78.0)
    _setup(con, closes, FETCHED_AFTER_EX)
    before = _closes(con)
    actions.reconcile(con)
    outcome, brk, n = _verdict(con)
    assert outcome != "applied"
    assert outcome == "noop_restated"          # calm at the ex-date, no ratio match
    assert n == 0 and _closes(con) == before


def test_ratio_sized_jump_far_from_ex_is_skipped_not_applied(con):
    """An exact 1/1.5 drop 8 sessions after the ex-date matches the ratio but
    cannot be the scale break — recorded as skipped_no_break_near_ex."""
    closes = _step(EX_IDX + 8, PRE, POST)
    _setup(con, closes, FETCHED_AFTER_EX)
    before = _closes(con)
    actions.reconcile(con)
    outcome, brk, n = _verdict(con)
    assert outcome == "skipped_no_break_near_ex"
    assert brk == SESSIONS[EX_IDX + 8] and n == 0
    assert _closes(con) == before


def test_bh_shape_drop_two_sessions_before_ex_not_applied(con):
    """BH 2018: −20% two sessions before an already-adjusted ex-date. Near the
    ex-date but outside ±8% of 1.5 -> not a break."""
    closes = _step(EX_IDX - 2, 100.0, 79.9)
    _setup(con, closes, FETCHED_AFTER_EX)
    before = _closes(con)
    actions.reconcile(con)
    assert _verdict(con)[0] != "applied"
    assert _closes(con) == before


# --------------------------------------------------------------------------- #
# rule 3 + the genuine case
# --------------------------------------------------------------------------- #
def test_accepts_genuine_break_at_ex_date(con):
    closes = _step(EX_IDX, PRE, POST)
    fetched = [FETCHED_BEFORE_EX if d < EX else datetime.combine(d, time(23, 0))
               for d in SESSIONS]
    _setup(con, closes, fetched)
    actions.reconcile(con)
    outcome, brk, n = _verdict(con)
    assert outcome == "applied" and brk == EX and n == EX_IDX
    after = _closes(con)
    assert all(abs(after[d] - POST) < 1e-9 for d in SESSIONS)   # one scale now
    # idempotent: the watermark keeps it from being touched again
    actions.reconcile(con)
    assert _closes(con) == after


def test_accepts_refetch_edge_break_before_ex(con):
    """Split spotted late: the nightly 5d re-fetch put sessions EX-3.. on the new
    scale, so the break sits 3 sessions BEFORE the ex-date (BUILDLOG D3b)."""
    brk_idx = EX_IDX - 3
    closes = _step(brk_idx, PRE, POST)
    fetched = [FETCHED_BEFORE_EX if k < brk_idx else datetime.combine(EX, time(23, 0))
               for k in range(len(SESSIONS))]
    _setup(con, closes, fetched)
    actions.reconcile(con)
    outcome, brk, n = _verdict(con)
    assert outcome == "applied" and brk == SESSIONS[brk_idx] and n == brk_idx


def test_break_at_ex_but_history_fetched_after_ex_is_skipped(con):
    """Same shape as the genuine case, but every bar was stored after the ex-date:
    Yahoo had already restated them, so a 1.5 jump there is not OUR scale break."""
    closes = _step(EX_IDX, PRE, POST)
    _setup(con, closes, FETCHED_AFTER_EX)
    before = _closes(con)
    actions.reconcile(con)
    outcome, brk, n = _verdict(con)
    assert outcome == "skipped_already_adjusted" and brk == EX and n == 0
    assert _closes(con) == before


def test_adjudicate_never_widens_ambiguity_band():
    # 5:4 and 4:3 stay undecidable; 3:2 is decidable — unchanged from the original.
    import math
    assert math.log(1.25) < actions.MIN_SEPARATION_LOG
    assert math.log(1.44) <= actions.MIN_SEPARATION_LOG + 1e-12
    assert math.log(1.5) > actions.MIN_SEPARATION_LOG
    assert abs(actions.TOL_LOG - math.log(1.08)) < 1e-12


# --------------------------------------------------------------------------- #
# _restate + rebuild: positions follow the fill boundary (ex_date)
# --------------------------------------------------------------------------- #
def _fill(con, pf, side, qty, px, d, oid):
    con.execute(
        "INSERT INTO sim_orders (id, portfolio_id, ticker, side, qty, signal_date, status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'filled')", [oid, pf, TK, side, qty, d - timedelta(days=1)])
    con.execute(
        "INSERT INTO sim_fills VALUES (?, ?, ?, ?, ?, ?, ?, ?, 10, 10)",
        [oid, pf, TK, side, qty, d, px, px])
    portfolio.apply_fill(con, {"portfolio_id": pf, "ticker": TK, "side": side,
                               "qty": qty, "fill_px": px})


def test_restate_leaves_post_ex_position_unscaled(con, book):
    closes = _step(EX_IDX, PRE, POST)
    fetched = [FETCHED_BEFORE_EX if d < EX else datetime.combine(d, time(23, 0))
               for d in SESSIONS]
    _setup(con, closes, fetched)
    con.execute(
        "INSERT INTO portfolios (id, name, strategy, config, created, active, cash) "
        "VALUES ('pre', 'pre', 'none', '{}', ?, TRUE, ?)", [SESSIONS[0], INITIAL_CASH])
    # 'pre' bought 60 sh at the PRE-split price before the ex-date;
    # 'test' bought 100 sh at the POST-split price two sessions after it.
    _fill(con, "pre", "buy", 60.0, PRE, SESSIONS[EX_IDX - 5], 1)
    _fill(con, book, "buy", 100.0, POST, SESSIONS[EX_IDX + 2], 2)
    # pending orders: one signalled before the ex-date, one after
    con.execute("INSERT INTO sim_orders (id, portfolio_id, ticker, side, qty, signal_date, status) "
                "VALUES (3, 'pre', ?, 'buy', 10, ?, 'pending')", [TK, SESSIONS[EX_IDX - 1]])
    con.execute("INSERT INTO sim_orders (id, portfolio_id, ticker, side, qty, signal_date, status) "
                "VALUES (4, ?, 'buy', 10, ?, 'pending')".replace("?, 'buy'", "?, ?, 'buy'"),
                [book, TK, SESSIONS[EX_IDX + 3]])

    actions.reconcile(con)
    assert _verdict(con)[0] == "applied"

    pos = {pf: (q, c) for pf, q, c in con.execute(
        "SELECT portfolio_id, qty, avg_cost FROM sim_positions WHERE ticker = ?", [TK]).fetchall()}
    assert pos[book][0] == pytest.approx(100.0)          # post-ex lot: untouched
    assert pos[book][1] == pytest.approx(POST)
    assert pos["pre"][0] == pytest.approx(90.0)          # pre-ex lot: ×1.5
    assert pos["pre"][1] == pytest.approx(POST)          # avg_cost ÷1.5, notional invariant
    cash = dict(con.execute("SELECT id, cash FROM portfolios").fetchall())
    assert cash[book] == pytest.approx(INITIAL_CASH - 100.0 * POST)
    assert cash["pre"] == pytest.approx(INITIAL_CASH - 60.0 * PRE)
    orders = dict(con.execute("SELECT id, qty FROM sim_orders WHERE status = 'pending'").fetchall())
    assert orders[3] == pytest.approx(15.0) and orders[4] == pytest.approx(10.0)

    # --rerun semantics: a rebuild reproduces exactly the same state (no silent revert)
    portfolio.rebuild_state(con)
    pos2 = {pf: (q, c) for pf, q, c in con.execute(
        "SELECT portfolio_id, qty, avg_cost FROM sim_positions WHERE ticker = ?", [TK]).fetchall()}
    for pf in pos:
        assert pos2[pf][0] == pytest.approx(pos[pf][0]) and pos2[pf][1] == pytest.approx(pos[pf][1])
    assert dict(con.execute("SELECT id, cash FROM portfolios").fetchall())[book] == pytest.approx(cash[book])
