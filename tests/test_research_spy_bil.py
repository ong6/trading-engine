"""Shared mechanics for isolated SPY/BIL research rules."""
from datetime import date

import pytest

from sim.strategies.base import PortfolioView
from sim.strategies.research_spy_bil import transition_orders
from tests.conftest import insert_bars


def _view(positions=None):
    return PortfolioView("probe", {}, 39_000.0, positions or {}, 39_000.0)


def _register(con, created):
    con.execute(
        "INSERT INTO portfolios (id,name,strategy,config,created,active,cash) "
        "VALUES ('probe','probe','probe','{}',?,TRUE,39000)", [created]
    )


def _prices(con, d):
    for ticker in ("SPY", "BIL"):
        insert_bars(con, ticker, [d])


def test_requires_complete_positive_signal_date_prices(con):
    d = date(2024, 6, 3)
    _register(con, d)
    insert_bars(con, "SPY", [d])

    assert transition_orders(
        con, _view(), d, risk_on=True, changed=True
    ) == []


def test_nontransition_after_inception_emits_nothing(con):
    created, d = date(2024, 6, 3), date(2024, 6, 4)
    _register(con, created)
    _prices(con, d)

    assert transition_orders(
        con, _view({"SPY": 390.0}), d, risk_on=True, changed=False
    ) == []


def test_inception_uses_requested_binary_state(con):
    d = date(2024, 6, 3)
    _register(con, d)
    _prices(con, d)

    orders = transition_orders(con, _view(), d, risk_on=False, changed=False)

    assert {(order.ticker, order.side) for order in orders} == {("BIL", "buy")}


def test_static_weight_is_bounded(con):
    d = date(2024, 6, 3)
    _register(con, d)
    _prices(con, d)

    with pytest.raises(ValueError, match="between zero and one"):
        transition_orders(
            con, _view(), d, risk_on=True, changed=True, static_spy_weight=1.01
        )
