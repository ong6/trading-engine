"""Backtest and walk-forward fold books pay the live book's dollar fees from its break.

Before the fix a scratch book had no `portfolio_accounts` row, so it resolved to
`baseline_v1` and paid $0 on every session, while the live book pays
`ibkr_pro_tiered_v1` from its D0 break (reproduced on a 2026-10-22 store copy: a
spy_benchmark replay bought 50.78 SPY on 2026-10-19 with no fee row).
"""
from __future__ import annotations

import duckdb
import pytest

from farm.backtest import replay
from farm.walkforward import runner
from sim import league
from sim.schema import init_sim_schema, set_portfolio_account
from tests.conftest import PRICES_DDL, SESSIONS, insert_bars

D0 = SESSIONS[31]


def _connection():
    con = duckdb.connect()
    con.execute(PRICES_DDL)
    init_sim_schema(con)
    return con


@pytest.fixture
def live():
    con = _connection()
    con.execute(
        "INSERT INTO portfolios (id,name,strategy,config,created,active,cash,initial_cash,"
        "execution_profile) VALUES ('bk','bk','spy_benchmark','{}',?,TRUE,1,1,'baseline_v1')",
        [SESSIONS[0]])
    set_portfolio_account(con, "bk", cost_profile="ibkr_pro_tiered_v1")
    con.execute("INSERT INTO sim_book_breaks VALUES ('bk',?,'cost_profile','baseline_v1',"
                "'ibkr_pro_tiered_v1',13,'d0',now())", [D0])
    yield con
    con.close()


def _scratch(book: dict):
    con = _connection()
    insert_bars(con, "XYZ", SESSIONS[:33], open_=100.0, close=100.0, high=101.0, low=99.0)
    runner._insert_book(con, book, SESSIONS[0], 10_000.0, "baseline_v1")
    return con


def _buy(con, order_id: int, signal_index: int) -> None:
    con.execute("INSERT INTO sim_orders VALUES (?,'bk','XYZ','buy',10,?,'pending',NULL)",
                [order_id, SESSIONS[signal_index]])
    assert league.fill_pending(con, SESSIONS[signal_index + 1])["filled"] == 1


def test_live_book_cost_profile_and_break_are_read(live):
    assert replay.cost_assumptions(live, "bk") == {
        "cost_profile": "ibkr_pro_tiered_v1",
        "breaks": [{"break_date": D0.isoformat(), "from_value": "baseline_v1",
                    "to_value": "ibkr_pro_tiered_v1"}]}
    assert replay.cost_assumptions(live, "unknown") == {
        "cost_profile": "baseline_v1", "breaks": []}


def test_fold_book_pays_nothing_before_the_break_and_dollar_fees_after(live):
    (book,) = runner.active_books(live)
    con = _scratch(book)
    # $100M median dollar volume: 5 bp half-spread + 5 bp adverse, so a buy fills
    # at 100.10 and 10 shares cost $1,001.00 before fees.
    _buy(con, 1, 29)                                  # fills SESSIONS[30], before D0
    assert con.execute("SELECT COUNT(*) FROM sim_fill_fees").fetchone() == (0,)
    assert con.execute("SELECT cash FROM portfolios").fetchone()[0] == pytest.approx(
        10_000.0 - 1_001.0)

    _buy(con, 2, 30)                                  # fills D0
    # IBKR Pro Tiered, 10 shares at the opening auction: commission $0.35 (minimum),
    # exchange 10 x 0.0015 = 0.015, clearing 10 x 0.0002 = 0.002, pass-through
    # 0.35 x (0.000175 + 0.000565) = 0.000259, CAT 10 x 0.000003 = 0.00003; no SEC
    # fee or TAF on a buy. 0.367289 rounds half-up to $0.37, charged once, in cash.
    fee = con.execute("SELECT cost_profile, commission, exchange_fee, clearing_fee, "
                      "total_usd FROM sim_fill_fees WHERE order_id = 2").fetchone()
    assert fee[0] == "ibkr_pro_tiered_v1"
    assert fee[1:4] == pytest.approx((0.35, 0.015, 0.002))
    assert fee[4] == 0.37
    assert con.execute("SELECT fill_px FROM sim_fills WHERE order_id = 2").fetchone()[0] \
        == pytest.approx(100.10)                      # the fee is not in the price too
    assert con.execute("SELECT cash FROM portfolios").fetchone()[0] == pytest.approx(
        10_000.0 - 2 * 1_001.0 - 0.37)
    assert replay.dollar_fees(con, "bk") == pytest.approx(0.37)


def test_fold_reset_reinstalls_the_break_once(live):
    (book,) = runner.active_books(live)
    con = _scratch(book)
    runner._reset_sim(con)
    runner._insert_book(con, book, SESSIONS[0], 10_000.0, "baseline_v1")
    assert con.execute("SELECT COUNT(*) FROM sim_book_breaks").fetchone() == (1,)
    _buy(con, 1, 30)
    assert replay.dollar_fees(con, "bk") == pytest.approx(0.37)


def test_candidate_book_without_live_costs_keeps_the_compatibility_profile(live):
    (book,) = runner.active_books(live)
    con = _scratch({**book, "cost": None})
    _buy(con, 1, 30)
    assert replay.dollar_fees(con, "bk") == 0.0
    assert con.execute("SELECT cash FROM portfolios").fetchone()[0] == pytest.approx(
        10_000.0 - 1_001.0)
