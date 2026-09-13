"""Research-only VIX term strategy semantics."""
from datetime import date

import pytest

from sim.strategies import REGISTRY
from sim.strategies.base import PortfolioView
from sim.strategies.configs import CONFIGS
from sim.strategies.vix_term_spy_timing import (
    STATIC_SPY_WEIGHT,
    VixTermSpyTiming,
    VixTermStaticExposure,
)
from tests.conftest import insert_bars


def _view(positions=None):
    return PortfolioView("probe", {}, 39_000.0, positions or {}, 39_000.0)


def _register(con, created):
    con.execute(
        "INSERT INTO portfolios (id,name,strategy,config,created,active,cash) "
        "VALUES ('probe','probe','probe','{}',?,TRUE,39000)", [created]
    )


def _macro(con, rows):
    con.execute(
        "CREATE TABLE IF NOT EXISTS macro_signals (series VARCHAR, obs_date DATE, "
        "value DOUBLE, fetch_as_of DATE, PRIMARY KEY(series, obs_date))"
    )
    con.executemany(
        "INSERT INTO macro_signals VALUES (?, ?, ?, ?)",
        [(series, d, value, d) for d, vix, vix3m in rows
         for series, value in (("vix", vix), ("vix3m", vix3m))],
    )


def _weight(orders, ticker):
    order = next(order for order in orders if order.ticker == ticker)
    return order.qty * 100.0 / 39_000.0


def test_pair_is_absent_from_production_registry_and_configs():
    ids = {cfg["id"] for cfg in CONFIGS}
    assert {"vix_term_spy_timing", "vix_term_static_8068"}.isdisjoint(ids)
    assert {"vix_term_spy_timing", "vix_term_static_8068"}.isdisjoint(REGISTRY)


def test_candidate_uses_exact_close_then_next_open_intent(con):
    d = date(2024, 6, 3)
    _register(con, d)
    insert_bars(con, "SPY", [d])
    insert_bars(con, "BIL", [d])
    _macro(con, [(d, 18.0, 20.0)])
    orders = VixTermSpyTiming().generate_orders(con, _view(), d)
    assert [(o.ticker, o.side, o.signal_date) for o in orders] == [("SPY", "buy", d)]


def test_threshold_is_strict_and_missing_pair_emits_nothing(con):
    d = date(2024, 6, 3)
    _register(con, d)
    insert_bars(con, "SPY", [d])
    insert_bars(con, "BIL", [d])
    _macro(con, [(d, 19.0, 20.0)])
    orders = VixTermSpyTiming().generate_orders(con, _view(), d)
    assert [(o.ticker, o.side) for o in orders] == [("BIL", "buy")]

    con.execute("DELETE FROM macro_signals WHERE series='vix3m'")
    assert VixTermSpyTiming().generate_orders(con, _view(), d) == []


def test_candidate_trades_only_when_binary_state_changes(con):
    dates = [date(2024, 6, 3), date(2024, 6, 4), date(2024, 6, 5)]
    _register(con, dates[0])
    for ticker in ("SPY", "BIL"):
        insert_bars(con, ticker, dates)
    _macro(con, [
        (dates[0], 18.0, 20.0),
        (dates[1], 18.5, 20.0),
        (dates[2], 21.0, 20.0),
    ])
    held = {"SPY": 390.0}
    assert VixTermSpyTiming().generate_orders(con, _view(held), dates[1]) == []
    orders = VixTermSpyTiming().generate_orders(con, _view(held), dates[2])
    assert {(o.ticker, o.side) for o in orders} == {("BIL", "buy"), ("SPY", "sell")}


def test_static_control_uses_frozen_exposure_on_same_transitions(con):
    dates = [date(2024, 6, 3), date(2024, 6, 4)]
    _register(con, dates[0])
    for ticker in ("SPY", "BIL"):
        insert_bars(con, ticker, dates)
    _macro(con, [(dates[0], 18.0, 20.0), (dates[1], 21.0, 20.0)])
    orders = VixTermStaticExposure().generate_orders(con, _view(), dates[0])
    assert _weight(orders, "SPY") == pytest.approx(STATIC_SPY_WEIGHT)
    assert _weight(orders, "BIL") == pytest.approx(1.0 - STATIC_SPY_WEIGHT)
    assert VixTermStaticExposure().generate_orders(
        con,
        _view({"SPY": STATIC_SPY_WEIGHT * 390, "BIL": (1 - STATIC_SPY_WEIGHT) * 390}),
        dates[0],
    ) == []
