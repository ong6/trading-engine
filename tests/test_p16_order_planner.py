"""Whole-share P16 funding and post-rounding feasibility checks."""
from __future__ import annotations

import pytest

from engine.p16_order_planner import plan_whole_share_orders


def test_sales_and_spy_financing_precede_stock_buys_and_cash_has_beta_zero():
    result = plan_whole_share_orders(
        tickers=["AAA", "BBB"], target_weights=[0.1, 0.1, 0.8],
        current_quantities={"AAA": 20, "SPY": 12},
        operational_prices={"AAA": 50, "BBB": 100, "SPY": 500},
        cash=3_000, equity=10_000, beta=[1, 1], sectors=["a", "b"],
        alpha=[0.02, 0.01], entry_atr={"AAA": 2, "BBB": 3},
    )
    assert result["status"] == "planned"
    sides = [row["side"] for row in result["orders"]]
    assert sides == sorted(sides, reverse=True)
    assert 0.8 <= result["portfolio_beta"] <= 1.1
    assert result["cash_weight"] >= 0
    assert all(row.get("entry_atr") in {2.0, 3.0} for row in result["orders"]
               if row["side"] == "buy" and row["ticker"] != "SPY")


def test_unknown_sector_fallback_and_expensive_spy_fail_closed():
    result = plan_whole_share_orders(
        tickers=["AAA"], target_weights=[0.1, 0.9], current_quantities={},
        operational_prices={"AAA": 50, "SPY": 20_000}, cash=10_000, equity=10_000,
        beta=[1], sectors=[None], alpha=[1],
        entry_atr={"AAA": 2},
    )
    assert result["status"] == "rounded_plan_infeasible"
    assert result["sector_status"] == "sector_unavailable"
    assert result["orders"] == []


def test_mandatory_exits_survive_infeasible_discretionary_plan():
    result = plan_whole_share_orders(
        tickers=["AAA"], target_weights=[0.1, 0.9],
        current_quantities={"AAA": 10},
        operational_prices={"AAA": 100, "SPY": 20_000},
        cash=9_000, equity=10_000, beta=[1], sectors=[None], alpha=[1],
        mandatory_exits={"AAA"},
        entry_atr={"AAA": 2},
    )
    assert result["status"] == "rounded_plan_infeasible"
    assert result["orders"] == [{
        "ticker": "AAA", "side": "sell", "qty": 10.0,
        "order_role": "mandatory_exit", "target_weight": 0.0,
    }]


def test_planner_requires_sorted_unique_universe_and_complete_prices():
    with pytest.raises(ValueError, match="universe"):
        plan_whole_share_orders(
            tickers=["BBB", "AAA"], target_weights=[0.1, 0.1, 0.8],
            current_quantities={}, operational_prices={"AAA": 1, "BBB": 1, "SPY": 1},
            cash=10_000, equity=10_000, beta=[1, 1], sectors=["a", "b"], alpha=[1, 1],
            entry_atr={"AAA": 1, "BBB": 1},
        )
