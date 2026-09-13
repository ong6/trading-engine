"""Research-only sell-in-May strategy semantics."""
from datetime import date

import pytest

from sim.strategies import REGISTRY
from sim.strategies.base import PortfolioView
from sim.strategies.configs import CONFIGS
from sim.strategies.sell_in_may_spy import (
    STATIC_SPY_WEIGHT,
    SellInMaySpy,
    SellInMayStaticExposure,
    is_winter_session,
)
from tests.conftest import insert_bars


def _view(positions=None):
    return PortfolioView("probe", {}, 39_000.0, positions or {}, 39_000.0)


def _register(con, created):
    con.execute(
        "INSERT INTO portfolios (id,name,strategy,config,created,active,cash) "
        "VALUES ('probe','probe','probe','{}',?,TRUE,39000)", [created]
    )


def _prices(con, dates):
    for ticker in ("SPY", "BIL"):
        insert_bars(con, ticker, dates)


def _weight(orders, ticker):
    order = next(order for order in orders if order.ticker == ticker)
    return order.qty * 100.0 / 39_000.0


def test_pair_is_absent_from_production_registry_and_configs():
    ids = {cfg["id"] for cfg in CONFIGS}
    research = {"sell_in_may_spy", "sell_in_may_static_4902"}
    assert research.isdisjoint(ids)
    assert research.isdisjoint(REGISTRY)


def test_winter_window_is_november_through_april():
    assert is_winter_session(date(2024, 4, 30))
    assert not is_winter_session(date(2024, 5, 1))
    assert not is_winter_session(date(2024, 10, 31))
    assert is_winter_session(date(2024, 11, 1))
    with pytest.raises(ValueError, match="non-session"):
        is_winter_session(date(2024, 11, 2))


def test_candidate_signals_at_april_and_october_closes(con):
    dates = [
        date(2024, 4, 29), date(2024, 4, 30), date(2024, 5, 1),
        date(2024, 10, 30), date(2024, 10, 31), date(2024, 11, 1),
    ]
    _prices(con, dates)
    _register(con, dates[0])
    summer = SellInMaySpy().generate_orders(
        con, _view({"SPY": 390.0}), date(2024, 4, 30)
    )
    assert {(o.ticker, o.side, o.signal_date) for o in summer} == {
        ("BIL", "buy", date(2024, 4, 30)),
        ("SPY", "sell", date(2024, 4, 30)),
    }
    assert SellInMaySpy().generate_orders(
        con, _view({"BIL": 390.0}), date(2024, 5, 1)
    ) == []
    winter = SellInMaySpy().generate_orders(
        con, _view({"BIL": 390.0}), date(2024, 10, 31)
    )
    assert {(o.ticker, o.side, o.signal_date) for o in winter} == {
        ("BIL", "sell", date(2024, 10, 31)),
        ("SPY", "buy", date(2024, 10, 31)),
    }


def test_inception_targets_next_session_state(con):
    d = date(2024, 9, 4)
    _prices(con, [d])
    _register(con, d)
    orders = SellInMaySpy().generate_orders(con, _view(), d)
    assert {(o.ticker, o.side) for o in orders} == {("BIL", "buy")}


def test_missing_signal_price_emits_no_partial_allocation(con):
    d = date(2024, 10, 31)
    _register(con, d)
    insert_bars(con, "SPY", [d])
    assert SellInMaySpy().generate_orders(con, _view(), d) == []


def test_static_control_uses_frozen_weight_on_transition_dates(con):
    d = date(2024, 10, 31)
    _register(con, d)
    _prices(con, [d])
    orders = SellInMayStaticExposure().generate_orders(con, _view(), d)
    assert _weight(orders, "SPY") == pytest.approx(STATIC_SPY_WEIGHT)
    assert _weight(orders, "BIL") == pytest.approx(1.0 - STATIC_SPY_WEIGHT)
