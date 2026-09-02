"""The three 2026-09-02 books on a constructed universe (in-memory DuckDB).

Each test builds a small synthetic cross-section with a known right answer and
checks (a) the ranking the strategy produces, (b) that nothing dated after
`as_of` leaks into the decision, and (c) that a non-signal session yields no
orders — both at the cadence gate (`league.generate_all` mid-month) and at the
sizing level (already at target ⇒ no dust orders).
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from sim import league
from sim.schema import INITIAL_CASH
from sim.strategies import get_strategy
from sim.strategies.base import PortfolioView
from sim.strategies.configs import config_by_id
from sim.strategies.multi_asset_trend import MultiAssetTrend
from sim.strategies.xs_momentum_12_1 import XsMomentum121
from sim.strategies.xs_reversal_1m import XsReversal1m
from tests.conftest import insert_bars

# --------------------------------------------------------------------------- #
# a long synthetic calendar: 320 weekday sessions from 2023-01-02
# --------------------------------------------------------------------------- #
def _sessions(n=320, start=date(2023, 1, 2)) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


S = _sessions()
AS_OF = S[299]            # 300 bars available at as_of; S[300:] is the FUTURE
N_BARS = 300


def _path(total_12_1: float, last_month: float, n=N_BARS, base=100.0) -> list[float]:
    """Closes that are flat except a jump of `total_12_1` applied gradually over
    the 12-1 window and `last_month` over the final 21 sessions. Offsets are
    counted back from the LAST bar: bar[-1] is as_of, bar[-22] is 21 sessions
    ago, bar[-253] is 252 sessions ago."""
    closes = [base] * n
    i_start, i_end = n - 253, n - 22
    for i in range(i_start + 1, n):
        frac = min(1.0, (i - i_start) / (i_end - i_start))
        closes[i] = base * (1 + total_12_1 * frac)
    end_level = closes[i_end]
    for i in range(i_end + 1, n):
        frac = (i - i_end) / (n - 1 - i_end)
        closes[i] = end_level * (1 + last_month * frac)
    return closes


def _universe(con, rows):
    """rows: (ticker, active, liquid, etf)."""
    con.execute("CREATE TABLE IF NOT EXISTS universe (ticker VARCHAR PRIMARY KEY, "
                "name VARCHAR, active BOOLEAN, liquid BOOLEAN, etf BOOLEAN)")
    for t, a, l, e in rows:
        con.execute("INSERT INTO universe VALUES (?, ?, ?, ?, ?)", [t, t, a, l, e])


def _add(con, ticker, closes, *, dates=None, active=True, liquid=True, etf=False):
    dates = dates if dates is not None else S[:len(closes)]
    insert_bars(con, ticker, dates, open_=closes, close=closes)
    _universe(con, [(ticker, active, liquid, etf)])


# Designed but withdrawn before registration (see configs.py tail): the class is
# still tested with the params its charter specified.
WITHDRAWN_PARAMS = {
    "xs_reversal_1m": {"max_n": 50, "frac": 0.10, "lookback": 21, "min_bars": 252,
                       "min_price": 5.0},
}


def _view(cid, positions=None, equity=INITIAL_CASH):
    params = (dict(WITHDRAWN_PARAMS[cid]) if cid in WITHDRAWN_PARAMS
              else dict(config_by_id(cid)["params"]))
    return PortfolioView(id=cid, params=params,
                         cash=equity, positions=positions or {}, equity=equity)


def _targets(orders, con, as_of, equity=INITIAL_CASH):
    from sim.strategies.base import close_on
    return {o.ticker: round(o.qty * close_on(con, o.ticker, as_of) / equity, 3)
            for o in orders if o.side == "buy"}


# --------------------------------------------------------------------------- #
# xs_momentum_12_1
# --------------------------------------------------------------------------- #
def _momentum_universe(con):
    _add(con, "WIN", _path(+1.00, 0.00))         # +100% in the 12-1 window
    _add(con, "MID", _path(+0.20, 0.00))         # +20%
    _add(con, "LOSE", _path(-0.30, 0.00))        # -30%
    _add(con, "RECENT", _path(0.00, +0.50))      # flat 12-1, +50% LAST month: skip
    _add(con, "SHORT", _path(+3.00, 0.00)[-100:], dates=S[200:300])   # 100 bars only
    _add(con, "CHEAP", [c * 0.01 for c in _path(+2.00, 0.00)])         # $1→$3 close
    _add(con, "ETFX", _path(+2.00, 0.00), etf=True)
    _add(con, "THIN", _path(+2.00, 0.00), liquid=False)
    _add(con, "DEAD", _path(+2.00, 0.00), active=False)


def test_xs_momentum_ranks_12_1_and_skips_last_month(con):
    _momentum_universe(con)
    pf = _view("xs_momentum_12_1")
    pf.params["n"] = 2
    orders = XsMomentum121().generate_orders(con, pf, AS_OF)
    assert _targets(orders, con, AS_OF) == {"WIN": 0.5, "MID": 0.5}
    assert all(o.signal_date == AS_OF for o in orders)


def test_xs_momentum_excludes_short_cheap_etf_illiquid_inactive(con):
    _momentum_universe(con)
    pf = _view("xs_momentum_12_1")
    pf.params["n"] = 10                              # room for everyone eligible
    chosen = {o.ticker for o in XsMomentum121().generate_orders(con, pf, AS_OF)}
    assert chosen == {"WIN", "MID", "LOSE", "RECENT"}
    for bad in ("SHORT", "CHEAP", "ETFX", "THIN", "DEAD"):
        assert bad not in chosen


def test_xs_momentum_respects_as_of(con):
    _momentum_universe(con)
    # A FUTURE bar on LOSE that would make it the top name if it leaked.
    insert_bars(con, "LOSE", S[300:305], open_=10_000.0, close=10_000.0)
    pf = _view("xs_momentum_12_1")
    pf.params["n"] = 2
    orders = XsMomentum121().generate_orders(con, pf, AS_OF)
    assert _targets(orders, con, AS_OF) == {"WIN": 0.5, "MID": 0.5}


def test_xs_momentum_no_orders_when_at_target(con):
    _momentum_universe(con)
    pf = _view("xs_momentum_12_1")
    pf.params["n"] = 2
    first = XsMomentum121().generate_orders(con, pf, AS_OF)
    held = {o.ticker: o.qty for o in first}
    pf2 = _view("xs_momentum_12_1", positions=held)
    pf2.params["n"] = 2
    assert XsMomentum121().generate_orders(con, pf2, AS_OF) == []


def test_xs_momentum_infeasible_config_raises(con):
    _momentum_universe(con)
    pf = _view("xs_momentum_12_1")
    pf.params.update({"lookback": 21, "skip": 21})
    with pytest.raises(ValueError):
        XsMomentum121().generate_orders(con, pf, AS_OF)


def test_xs_momentum_empty_universe_holds(con):
    _universe(con, [])
    assert XsMomentum121().generate_orders(con, _view("xs_momentum_12_1"), AS_OF) == []


# --------------------------------------------------------------------------- #
# xs_reversal_1m
# --------------------------------------------------------------------------- #
def _reversal_universe(con):
    # All four have 300 bars and are ≥ $5. Uptrend = close > SMA200.
    # +300% over the 12-1 window keeps the SMA200 well under the close even
    # after a 20% monthly drop (a name that fell 20% off a flat base would be
    # BELOW its SMA200 and correctly ineligible — that is the filter working).
    _add(con, "UPLOSER", _path(+3.00, -0.20))    # up 300% then -20% last month: BUY
    _add(con, "UPDIP", _path(+3.00, -0.05))      # mild dip in an uptrend: 2nd worst
    _add(con, "UPWIN", _path(+3.00, +0.10))      # uptrend, rose last month: not a loser
    _add(con, "DOWNLOSER", _path(-0.50, -0.30))  # worst 1m return but BELOW SMA200: skip


def test_xs_reversal_buys_worst_uptrending_names_only(con):
    _reversal_universe(con)
    pf = _view("xs_reversal_1m")
    pf.params.update({"max_n": 2, "frac": 0.75})   # decile → 3 of 4, capped at 2
    orders = XsReversal1m().generate_orders(con, pf, AS_OF)
    assert _targets(orders, con, AS_OF) == {"UPLOSER": 0.5, "UPDIP": 0.5}


def test_xs_reversal_unfilled_slots_stay_in_cash(con):
    _reversal_universe(con)
    pf = _view("xs_reversal_1m")
    pf.params.update({"max_n": 4, "frac": 0.34})   # 3 eligible × .34 → 1 name, 4 slots
    orders = XsReversal1m().generate_orders(con, pf, AS_OF)
    assert _targets(orders, con, AS_OF) == {"UPLOSER": 0.25}


def test_xs_reversal_goes_to_cash_when_nothing_uptrends(con):
    _add(con, "D1", _path(-0.50, -0.30))
    _add(con, "D2", _path(-0.40, -0.10))
    pf = _view("xs_reversal_1m", positions={"D1": 10.0})
    orders = XsReversal1m().generate_orders(con, pf, AS_OF)
    assert [(o.ticker, o.side) for o in orders] == [("D1", "sell")]


def test_xs_reversal_respects_as_of(con):
    _reversal_universe(con)
    # Future crash on UPWIN: if read, it becomes the worst loser.
    insert_bars(con, "UPWIN", S[300:305], open_=1.0, close=1.0)
    pf = _view("xs_reversal_1m")
    pf.params.update({"max_n": 1, "frac": 0.34})
    orders = XsReversal1m().generate_orders(con, pf, AS_OF)
    assert _targets(orders, con, AS_OF) == {"UPLOSER": 1.0}


def test_xs_reversal_infeasible_config_raises(con):
    _reversal_universe(con)
    pf = _view("xs_reversal_1m")
    pf.params["min_bars"] = 100
    with pytest.raises(ValueError):
        XsReversal1m().generate_orders(con, pf, AS_OF)


# --------------------------------------------------------------------------- #
# multi_asset_trend
# --------------------------------------------------------------------------- #
def _flat_then(rate: float, n=N_BARS, base=100.0):
    return [base * (1 + rate * i / (n - 1)) for i in range(n)]


def _etf_universe(con):
    insert_bars(con, "AAA", S[:N_BARS], close=_flat_then(+0.20))    # +20% > BIL
    insert_bars(con, "BBB", S[:N_BARS], close=_flat_then(-0.05))    # below hurdle
    insert_bars(con, "CCC", S[:N_BARS], close=_flat_then(+0.02))    # +2% < BIL's 4%
    insert_bars(con, "NEW", S[250:N_BARS], close=_flat_then(+0.90, n=50))  # 50 bars
    insert_bars(con, "BIL", S[:N_BARS], close=[100.0] * N_BARS)     # flat price…
    con.execute("CREATE TABLE corporate_actions (ticker VARCHAR, ex_date DATE, "
                "kind VARCHAR, value DOUBLE)")
    # …all of BIL's return is coupon: 4 quarterly dividends of $1 inside the window.
    for d in (S[60], S[120], S[180], S[240]):
        con.execute("INSERT INTO corporate_actions VALUES ('BIL', ?, 'dividend', 1.0)", [d])


def test_multi_asset_trend_slots_and_bil_remainder(con):
    _etf_universe(con)
    pf = _view("multi_asset_trend")
    pf.params["assets"] = ["AAA", "BBB", "CCC", "NEW"]
    orders = MultiAssetTrend().generate_orders(con, pf, AS_OF)
    # AAA held (20% > 4%); BBB (-5%), CCC (+2% price-only < 4% total) and NEW (no
    # history) all park in BIL: 3 slots × 25%.
    assert _targets(orders, con, AS_OF) == {"AAA": 0.25, "BIL": 0.75}


def test_multi_asset_trend_hurdle_is_total_return(con):
    _etf_universe(con)
    pf = _view("multi_asset_trend")
    pf.params["assets"] = ["CCC"]
    # CCC's +2% loses to BIL's +4% total return. Drop the dividends and BIL's
    # hurdle collapses to a 0% price return, so CCC would be held instead.
    assert _targets(MultiAssetTrend().generate_orders(con, pf, AS_OF), con, AS_OF) == {"BIL": 1.0}
    con.execute("DELETE FROM corporate_actions")
    assert _targets(MultiAssetTrend().generate_orders(con, pf, AS_OF), con, AS_OF) == {"CCC": 1.0}


def test_multi_asset_trend_respects_as_of(con):
    _etf_universe(con)
    insert_bars(con, "BBB", S[300:305], close=10_000.0)     # future moonshot
    pf = _view("multi_asset_trend")
    pf.params["assets"] = ["AAA", "BBB"]
    assert _targets(MultiAssetTrend().generate_orders(con, pf, AS_OF), con, AS_OF) == \
        {"AAA": 0.5, "BIL": 0.5}


def test_multi_asset_trend_no_orders_when_at_target(con):
    _etf_universe(con)
    pf = _view("multi_asset_trend")
    pf.params["assets"] = ["AAA", "BBB"]
    held = {o.ticker: o.qty for o in MultiAssetTrend().generate_orders(con, pf, AS_OF)}
    pf2 = _view("multi_asset_trend", positions=held)
    pf2.params["assets"] = ["AAA", "BBB"]
    assert MultiAssetTrend().generate_orders(con, pf2, AS_OF) == []


def test_multi_asset_trend_live_config_tickers_all_have_history():
    """The registered asset list is the store's; the strategy never invents one."""
    cfg = config_by_id("multi_asset_trend")
    assert cfg["params"]["assets"] == ["SPY", "EFA", "EEM", "TLT", "IEF", "GLD",
                                       "DBC", "VNQ"]
    assert cfg["params"]["cash_proxy"] == "BIL"


# --------------------------------------------------------------------------- #
# cadence: a non-signal session produces NO orders through the league gate
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("cid", ["xs_momentum_12_1", "multi_asset_trend"])
def test_monthly_books_are_silent_off_the_month_end(con, cid):
    _momentum_universe(con)
    _reversal_universe(con)
    insert_bars(con, "BIL", S[:N_BARS], close=[100.0] * N_BARS)
    for tk in config_by_id("multi_asset_trend")["params"]["assets"]:
        insert_bars(con, tk, S[:N_BARS], close=_flat_then(+0.20))
    cfg = config_by_id(cid)
    assert cfg["cadence"] == "monthly" == get_strategy(cfg["strategy"]).cadence
    con.execute(
        "INSERT INTO portfolios (id, name, strategy, config, created, active, cash) "
        "VALUES (?, ?, ?, ?, ?, TRUE, ?)",
        [cid, cfg["name"], cfg["strategy"], json.dumps(cfg), S[0], INITIAL_CASH])

    # AS_OF = S[299] is a mid-month Wednesday with a later session in the store.
    assert AS_OF.day not in (28, 29, 30, 31)
    assert league.generate_all(con, AS_OF) == 0
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone()[0] == 0

    # The last session of AS_OF's month IS a signal day and the book acts.
    month_end = max(d for d in S if (d.year, d.month) == (AS_OF.year, AS_OF.month))
    assert league.generate_all(con, month_end) > 0
