"""Cash/position accounting, MTM, dividends, rebuild."""
import pytest

from sim import portfolio as pf
from sim.schema import INITIAL_CASH
from tests.conftest import SESSIONS, insert_bars


def _buy(con, book, tk, qty, px):
    return pf.apply_fill(con, {"portfolio_id": book, "ticker": tk,
                               "side": "buy", "qty": qty, "fill_px": px})


def _sell(con, book, tk, qty, px):
    return pf.apply_fill(con, {"portfolio_id": book, "ticker": tk,
                               "side": "sell", "qty": qty, "fill_px": px})


def test_buy_debits_cash_and_opens_position(con, book):
    assert _buy(con, book, "AAA", 10, 50.0) == 10.0
    assert pf.get_cash(con, book) == pytest.approx(INITIAL_CASH - 500.0)
    assert pf.get_positions(con, book) == {"AAA": {"qty": 10.0, "avg_cost": 50.0}}


def test_avg_cost_is_notional_weighted(con, book):
    _buy(con, book, "AAA", 10, 50.0)
    _buy(con, book, "AAA", 10, 70.0)
    p = pf.get_positions(con, book)["AAA"]
    assert p["qty"] == 20.0
    assert p["avg_cost"] == pytest.approx(60.0)


def test_buy_clamp_is_fractional_and_cash_never_negative(con, book):
    px = 1_000.0
    applied = _buy(con, book, "AAA", 100, px)       # $100k > $39k cash
    cash = pf.get_cash(con, book)
    assert 0.0 <= cash < 1e-6
    assert applied == pytest.approx(INITIAL_CASH / px, rel=1e-9)
    assert applied != int(applied)                  # fractional, not floor()


def test_buy_dust_below_min_fill_is_rejected_and_nothing_written(con, book):
    con.execute("UPDATE portfolios SET cash = 0.5 WHERE id = ?", [book])
    assert _buy(con, book, "AAA", 10, 100.0) == 0.0
    assert pf.get_cash(con, book) == 0.5
    assert pf.get_positions(con, book) == {}


def test_buy_with_zero_cash_rejected(con, book):
    con.execute("UPDATE portfolios SET cash = 0 WHERE id = ?", [book])
    assert _buy(con, book, "AAA", 1, 10.0) == 0.0


def test_buy_at_exact_cash_is_not_clamped(con, book):
    assert _buy(con, book, "AAA", 390, 100.0) == 390.0
    assert pf.get_cash(con, book) == pytest.approx(0.0)


def test_sell_credits_cash_and_keeps_avg_cost(con, book):
    _buy(con, book, "AAA", 10, 50.0)
    assert _sell(con, book, "AAA", 4, 80.0) == 4.0
    assert pf.get_cash(con, book) == pytest.approx(INITIAL_CASH - 500 + 320)
    assert pf.get_positions(con, book)["AAA"] == {"qty": 6.0, "avg_cost": 50.0}


def test_sell_clamps_to_held_never_short(con, book):
    _buy(con, book, "AAA", 10, 50.0)
    assert _sell(con, book, "AAA", 25, 60.0) == 10.0
    assert pf.get_positions(con, book) == {}       # qty 0 filtered out
    assert pf.get_cash(con, book) == pytest.approx(INITIAL_CASH + 100.0)


def test_sell_with_nothing_held_is_noop(con, book):
    assert _sell(con, book, "ZZZ", 5, 10.0) == 0.0
    assert pf.get_cash(con, book) == INITIAL_CASH
    assert con.execute("SELECT COUNT(*) FROM sim_positions").fetchone()[0] == 0


def test_get_positions_includes_accidental_shorts(con, book):
    con.execute("INSERT INTO sim_positions VALUES (?, 'NEG', -3, 10)", [book])
    assert "NEG" in pf.get_positions(con, book)


# -------------------------------------------------------------- MTM ------- #
def test_mark_to_market_equity_is_cash_plus_positions(con, book):
    d = SESSIONS[5]
    insert_bars(con, "AAA", [d], close=120.0)
    insert_bars(con, "BBB", [d], close=10.0)
    _buy(con, book, "AAA", 10, 100.0)
    _buy(con, book, "BBB", 100, 8.0)
    out = pf.mark_to_market(con, book, d)
    expect_cash = INITIAL_CASH - 1000 - 800
    assert out["cash"] == pytest.approx(expect_cash)
    assert out["equity"] == pytest.approx(expect_cash + 1200 + 1000)
    assert out["n_positions"] == 2 and out["carried"] == []
    row = con.execute("SELECT equity, cash, n_positions FROM sim_equity "
                      "WHERE portfolio_id = ? AND date = ?", [book, d]).fetchone()
    assert row[0] == pytest.approx(out["equity"]) and row[2] == 2


def test_mark_to_market_carries_last_close_and_flags_it(con, book):
    d0, d1 = SESSIONS[5], SESSIONS[6]
    insert_bars(con, "AAA", [d0], close=90.0)   # no bar on d1
    _buy(con, book, "AAA", 10, 100.0)
    out = pf.mark_to_market(con, book, d1)
    assert out["carried"] == ["AAA"]
    assert out["equity"] == pytest.approx(INITIAL_CASH - 1000 + 900)


def test_mark_to_market_no_price_contributes_zero(con, book):
    _buy(con, book, "GHOST", 10, 100.0)
    out = pf.mark_to_market(con, book, SESSIONS[5])
    assert out["carried"] == ["GHOST"]
    assert out["equity"] == pytest.approx(INITIAL_CASH - 1000)


def test_close_on_exact_vs_carried(con):
    d0, d1 = SESSIONS[0], SESSIONS[1]
    insert_bars(con, "AAA", [d0], close=55.0)
    assert pf.close_on(con, "AAA", d0) == (55.0, False)
    assert pf.close_on(con, "AAA", d1) == (55.0, True)
    assert pf.close_on(con, "NOPE", d1) == (None, True)


# -------------------------------------------------------- dividends ------- #
@pytest.fixture
def ca(con):
    con.execute("CREATE TABLE corporate_actions (ticker VARCHAR, ex_date DATE, "
                "kind VARCHAR, value DOUBLE)")
    return con


def test_credit_dividends_pays_held_qty_times_dps(ca, book):
    d = SESSIONS[3]
    _buy(ca, book, "AAA", 10, 100.0)
    ca.execute("INSERT INTO corporate_actions VALUES ('AAA', ?, 'dividend', 0.5)", [d])
    ca.execute("INSERT INTO corporate_actions VALUES ('AAA', ?, 'split', 2.0)", [d])
    out = pf.credit_dividends(ca, d)
    assert out == {"credited": 1, "amount": 5.0}
    assert pf.get_cash(ca, book) == pytest.approx(INITIAL_CASH - 1000 + 5.0)
    assert ca.execute("SELECT qty, dps, amount FROM sim_dividends").fetchone() == (10.0, 0.5, 5.0)


def test_credit_dividends_ignores_unheld_and_other_dates(ca, book):
    _buy(ca, book, "AAA", 10, 100.0)
    ca.execute("INSERT INTO corporate_actions VALUES ('BBB', ?, 'dividend', 1)", [SESSIONS[3]])
    ca.execute("INSERT INTO corporate_actions VALUES ('AAA', ?, 'dividend', 1)", [SESSIONS[4]])
    assert pf.credit_dividends(ca, SESSIONS[3]) == {"credited": 0, "amount": 0.0}


def test_credit_dividends_without_table_is_noop(con, book):
    assert pf.credit_dividends(con, SESSIONS[3]) == {"credited": 0, "amount": 0.0}


# ---------------------------------------------------------- rebuild ------- #
def _record_fill(con, book, oid, tk, side, qty, px, d):
    applied = pf.apply_fill(con, {"portfolio_id": book, "ticker": tk,
                                  "side": side, "qty": qty, "fill_px": px})
    con.execute("INSERT INTO sim_fills VALUES (?, ?, ?, ?, ?, ?, ?, ?, 10, 10)",
                [oid, book, tk, side, applied, d, px, px])


def test_rebuild_state_reproduces_cash_and_positions(ca, book):
    _record_fill(ca, book, 1, "AAA", "buy", 10, 100.0, SESSIONS[1])
    _record_fill(ca, book, 2, "BBB", "buy", 5, 20.0, SESSIONS[1])
    ca.execute("INSERT INTO corporate_actions VALUES ('AAA', ?, 'dividend', 0.5)", [SESSIONS[2]])
    pf.credit_dividends(ca, SESSIONS[2])
    _record_fill(ca, book, 3, "AAA", "sell", 4, 110.0, SESSIONS[3])
    cash0, pos0 = pf.get_cash(ca, book), pf.get_positions(ca, book)
    ca.execute("UPDATE portfolios SET cash = 1 WHERE id = ?", [book])
    ca.execute("DELETE FROM sim_positions")
    pf.rebuild_state(ca)
    assert pf.get_cash(ca, book) == pytest.approx(cash0)
    assert pf.get_positions(ca, book) == pos0


def test_rebuild_state_applies_split_to_pre_ex_fills(con, book):
    con.execute("CREATE TABLE split_adjustments (ticker VARCHAR, ex_date DATE, "
                "ratio DOUBLE, outcome VARCHAR)")
    _record_fill(con, book, 1, "AAA", "buy", 10, 100.0, SESSIONS[1])      # pre-split
    con.execute("INSERT INTO split_adjustments VALUES ('AAA', ?, 2.0, 'applied')",
                [SESSIONS[3]])
    _record_fill(con, book, 2, "AAA", "buy", 10, 50.0, SESSIONS[5])       # post-split
    pf.rebuild_state(con)
    p = pf.get_positions(con, book)["AAA"]
    assert p["qty"] == pytest.approx(30.0)          # 10*2 + 10
    assert p["avg_cost"] == pytest.approx(50.0)     # (20*50 + 10*50)/30
    assert pf.get_cash(con, book) == pytest.approx(INITIAL_CASH - 1000 - 500)


def test_position_open_since_resets_after_sell(con, book):
    for oid, side, d in [(1, "buy", SESSIONS[0]), (2, "sell", SESSIONS[2]),
                         (3, "buy", SESSIONS[4])]:
        con.execute("INSERT INTO sim_fills VALUES (?, ?, 'AAA', ?, 1, ?, 1, 1, 0, 0)",
                    [oid, book, side, d])
    assert pf.position_open_since(con, book, "AAA") == SESSIONS[4]
    assert pf.position_open_since(con, book, "NONE") is None
