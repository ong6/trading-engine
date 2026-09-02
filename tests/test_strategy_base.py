from datetime import date

import numpy as np
import pytest

from sim.strategies import base
from tests.conftest import SESSIONS, insert_bars


def _view(cash, positions, equity):
    return base.PortfolioView(id="t", params={}, cash=cash, positions=positions, equity=equity)


def test_rebalance_orders_buys_sells_and_skips_dust(con):
    d = SESSIONS[10]
    insert_bars(con, "AAA", [d], close=100.0)
    insert_bars(con, "BBB", [d], close=50.0)
    insert_bars(con, "CCC", [d], close=10.0)
    # BBB already at target (100 sh = $5k = 50%); AAA short by 0.3 sh ($30, dust);
    # CCC not in targets -> sold in full.
    pf = _view(cash=0, positions={"BBB": 100.0, "CCC": 500.0, "AAA": 49.7}, equity=10_000.0)
    orders = base.rebalance_orders(con, pf, d, {"AAA": 0.5, "BBB": 0.5})
    assert [(o.ticker, o.side, o.qty) for o in orders] == [("CCC", "sell", 500.0)]


def test_rebalance_orders_dust_threshold(con):
    d = SESSIONS[10]
    insert_bars(con, "AAA", [d], close=100.0)
    pf = _view(cash=0, positions={"AAA": 49.7}, equity=10_000.0)
    assert base.rebalance_orders(con, pf, d, {"AAA": 0.5}) == []       # $30 delta < $50
    pf2 = _view(cash=0, positions={"AAA": 49.0}, equity=10_000.0)
    o = base.rebalance_orders(con, pf2, d, {"AAA": 0.5})
    assert len(o) == 1 and o[0].side == "buy" and o[0].qty == pytest.approx(1.0)
    assert o[0].signal_date == d


def test_rebalance_orders_sells_names_absent_from_targets(con):
    d = SESSIONS[10]
    insert_bars(con, "OLD", [d], close=20.0)
    pf = _view(cash=0, positions={"OLD": 10.0}, equity=1_000.0)
    o = base.rebalance_orders(con, pf, d, {})
    assert (o[0].side, o[0].qty) == ("sell", 10.0)


def test_rebalance_orders_risk_off_blocks_buys_only(con):
    d = SESSIONS[10]
    insert_bars(con, "AAA", [d], close=100.0)
    insert_bars(con, "OLD", [d], close=20.0)
    pf = _view(cash=1_000, positions={"OLD": 10.0}, equity=1_200.0)
    o = base.rebalance_orders(con, pf, d, {"AAA": 1.0}, allow_buys=False)
    assert [(x.ticker, x.side) for x in o] == [("OLD", "sell")]


def test_rebalance_orders_skips_unpriced_names(con):
    pf = _view(cash=1_000, positions={}, equity=1_000.0)
    assert base.rebalance_orders(con, pf, SESSIONS[10], {"NOPX": 1.0}) == []


def test_n_down_closes():
    assert base.n_down_closes(np.array([5, 4, 3, 2])) == 3
    assert base.n_down_closes(np.array([1, 2, 3])) == 0
    assert base.n_down_closes(np.array([3, 4, 3, 2])) == 2


def test_rsi_wilder_bounds():
    assert base.rsi_wilder(np.array([1.0, 2.0]), period=2) is None
    assert base.rsi_wilder(np.array([1, 2, 3, 4.0]), period=2) == 100.0
    assert base.rsi_wilder(np.array([4, 3, 2, 1.0]), period=2) == 0.0
    mid = base.rsi_wilder(np.array([10, 11, 10, 11, 10.0]), period=2)
    assert 0 < mid < 100


def test_price_return_and_total_return(con):
    ds = SESSIONS[:4]
    insert_bars(con, "AAA", ds, close=[100.0, 110.0, 120.0, 130.0])
    assert base.price_return(con, "AAA", ds[3], 3) == pytest.approx(0.30)
    assert base.price_return(con, "AAA", ds[3], 10) is None
    con.execute("CREATE TABLE corporate_actions (ticker VARCHAR, ex_date DATE, kind VARCHAR, value DOUBLE)")
    con.execute("INSERT INTO corporate_actions VALUES ('AAA', ?, 'dividend', 5.0)", [ds[2]])
    con.execute("INSERT INTO corporate_actions VALUES ('AAA', ?, 'dividend', 5.0)", [ds[0]])  # at start: excluded
    assert base.total_return(con, "AAA", ds[3], 3) == pytest.approx(0.35)


def test_apply_agent_gate_twin_safety_and_fail_open(tmp_path, monkeypatch):
    monkeypatch.setattr(base, "AGENTS_DIR", tmp_path)
    d = date(2024, 7, 1)
    orders = [base.Order("bk", "AAA", "buy", 10, d), base.Order("bk", "BBB", "sell", 5, d)]
    plain = base.PortfolioView("bk", {}, 0, {}, 0)
    assert base.apply_agent_gate(plain, d, orders) is orders
    gated = base.PortfolioView("bk", {"agent_gate": True}, 0, {}, 0)
    assert base.apply_agent_gate(gated, d, orders) is orders          # no file


def test_apply_agent_gate_veto_downscale_floor(tmp_path, monkeypatch):
    monkeypatch.setattr(base, "AGENTS_DIR", tmp_path)
    d = date(2024, 7, 1)
    (tmp_path / "bk").mkdir()
    (tmp_path / "bk" / f"gate-{d}.json").write_text(
        '{"date": "2024-07-01", "decisions": ['
        '{"ticker": "aaa", "action": "veto"},'
        '{"ticker": "BBB", "action": "downscale", "scale": 0.05},'
        '{"ticker": "CCC", "action": "downscale", "scale": 1.7},'
        '{"ticker": "DDD", "action": "veto"}]}')
    orders = [base.Order("bk", t, "buy", 10, d) for t in ("AAA", "BBB", "CCC")]
    orders.append(base.Order("bk", "DDD", "sell", 10, d))
    out = base.apply_agent_gate(base.PortfolioView("bk", {"agent_gate": True}, 0, {}, 0), d, orders)
    got = {(o.ticker, o.side): o.qty for o in out}
    assert ("AAA", "buy") not in got
    assert got[("BBB", "buy")] == pytest.approx(10 * base.MIN_GATE_SCALE)   # floored at 0.25
    assert got[("CCC", "buy")] == 10                                          # never scaled up
    assert got[("DDD", "sell")] == 10                                         # sells untouched
