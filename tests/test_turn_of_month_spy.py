"""Research-only turn-of-month strategy semantics."""
from datetime import date

import pytest

from sim.strategies import REGISTRY
from sim.strategies.base import PortfolioView
from sim.strategies.configs import CONFIGS
from sim.strategies.turn_of_month_spy import (
    STATIC_SPY_WEIGHT,
    TurnOfMonthSpy,
    TurnOfMonthStaticExposure,
    is_turn_session,
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
    research = {"turn_of_month_spy", "turn_of_month_static_1911"}
    assert research.isdisjoint(ids)
    assert research.isdisjoint(REGISTRY)


def test_turn_window_uses_exchange_sessions_including_holiday_week():
    assert is_turn_session(date(2024, 6, 28))
    assert is_turn_session(date(2024, 7, 1))
    assert is_turn_session(date(2024, 7, 2))
    assert is_turn_session(date(2024, 7, 3))
    assert not is_turn_session(date(2024, 7, 5))
    with pytest.raises(ValueError, match="non-session"):
        is_turn_session(date(2024, 7, 4))


def test_candidate_signals_entry_before_month_end_and_exit_after_third_session(con):
    dates = [date(2024, 6, 27), date(2024, 6, 28), date(2024, 7, 1),
             date(2024, 7, 2), date(2024, 7, 3), date(2024, 7, 5)]
    _prices(con, dates)
    _register(con, dates[0])
    entry = TurnOfMonthSpy().generate_orders(con, _view({"BIL": 390.0}), dates[0])
    assert {(o.ticker, o.side, o.signal_date) for o in entry} == {
        ("BIL", "sell", dates[0]), ("SPY", "buy", dates[0]),
    }
    assert TurnOfMonthSpy().generate_orders(
        con, _view({"SPY": 390.0}), dates[1]
    ) == []
    exit_orders = TurnOfMonthSpy().generate_orders(
        con, _view({"SPY": 390.0}), dates[4]
    )
    assert {(o.ticker, o.side, o.signal_date) for o in exit_orders} == {
        ("BIL", "buy", dates[4]), ("SPY", "sell", dates[4]),
    }


def test_missing_signal_price_emits_no_partial_allocation(con):
    d = date(2024, 6, 27)
    _register(con, d)
    insert_bars(con, "SPY", [d])
    assert TurnOfMonthSpy().generate_orders(con, _view(), d) == []


def test_static_control_uses_frozen_weight_on_transition_dates(con):
    d = date(2024, 6, 27)
    _register(con, d)
    _prices(con, [d])
    orders = TurnOfMonthStaticExposure().generate_orders(con, _view(), d)
    assert _weight(orders, "SPY") == pytest.approx(STATIC_SPY_WEIGHT)
    assert _weight(orders, "BIL") == pytest.approx(1.0 - STATIC_SPY_WEIGHT)
