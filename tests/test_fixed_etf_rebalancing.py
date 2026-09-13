"""Prospective fixed-ETF rebalancing charter behavior."""
from datetime import date

import pytest

from sim.strategies import REGISTRY
from sim.strategies.base import PortfolioView
from sim.strategies.configs import CONFIGS
from sim.strategies.fixed_etf_rebalancing import FixedEtfBuyHold, FixedEtfRebalanced
from tests.conftest import insert_bars

ASSETS = ("SPY", "IEF", "GLD")


def _prices(con, dates):
    for ticker in ASSETS:
        insert_bars(con, ticker, dates, close=100.0)


def _view(positions=None):
    return PortfolioView(
        id="probe",
        params={"assets": list(ASSETS)},
        cash=39_000.0 if not positions else 0.0,
        positions=positions or {},
        equity=39_000.0,
    )


def _register(con, created):
    con.execute(
        "INSERT INTO portfolios (id,name,strategy,config,created,active,cash) "
        "VALUES ('probe','probe','fixed_etf_rebalanced','{}',?,TRUE,39000)",
        [created],
    )


def test_pair_is_research_only_and_absent_from_production_registry():
    ids = {cfg["id"] for cfg in CONFIGS}
    assert "fixed_etf_rebalanced" not in ids
    assert "fixed_etf_buy_hold" not in ids
    assert {"fixed_etf_rebalanced", "fixed_etf_buy_hold"}.isdisjoint(REGISTRY)


def test_pair_requires_all_three_exact_signal_date_prices(con):
    d = date(2024, 3, 28)
    _register(con, d)
    insert_bars(con, "SPY", [d])
    insert_bars(con, "IEF", [d])
    assert FixedEtfBuyHold().generate_orders(con, _view(), d) == []
    insert_bars(con, "GLD", [d])
    orders = FixedEtfBuyHold().generate_orders(con, _view(), d)
    assert {o.ticker for o in orders} == set(ASSETS)
    assert all(o.signal_date == d for o in orders)


def test_buy_hold_never_rebalances_after_entry(con):
    d = date(2024, 3, 28)
    _register(con, d)
    _prices(con, [d])
    assert FixedEtfBuyHold().generate_orders(
        con, _view({"SPY": 100.0, "IEF": 100.0, "GLD": 100.0}), d
    ) == []


def test_candidate_rebalances_only_at_calendar_quarter_end(con):
    dates = [date(2024, 3, 27), date(2024, 3, 28), date(2024, 4, 1)]
    _prices(con, dates)
    _register(con, dates[0])
    positions = {"SPY": 200.0, "IEF": 100.0, "GLD": 90.0}
    strategy = FixedEtfRebalanced()

    assert strategy.generate_orders(con, _view(positions), dates[0]) == []
    orders = strategy.generate_orders(con, _view(positions), dates[1])
    assert orders
    assert {o.ticker for o in orders} == set(ASSETS)
    assert strategy.generate_orders(con, _view(positions), dates[2]) == []


def test_candidate_enters_on_first_non_quarter_session(con):
    d = date(2024, 4, 1)
    _register(con, d)
    _prices(con, [d])
    orders = FixedEtfRebalanced().generate_orders(con, _view(), d)
    assert {o.ticker for o in orders} == set(ASSETS)


def test_asset_substitution_fails_closed(con):
    d = date(2024, 4, 1)
    _register(con, d)
    _prices(con, [d])
    pf = _view()
    pf.params = {"assets": ["SPY", "IEF", "SLV"]}
    with pytest.raises(ValueError, match="requires exactly"):
        FixedEtfRebalanced().generate_orders(con, pf, d)


def test_missing_inception_price_is_not_retried_later(con):
    first, later = date(2024, 4, 1), date(2024, 4, 2)
    _register(con, first)
    insert_bars(con, "SPY", [first, later])
    insert_bars(con, "IEF", [first, later])
    insert_bars(con, "GLD", [later])
    strategy = FixedEtfBuyHold()
    assert strategy.generate_orders(con, _view(), first) == []
    assert strategy.generate_orders(con, _view(), later) == []
