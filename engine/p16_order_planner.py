"""Deterministic whole-share planning for P16 continuous construction targets."""
from __future__ import annotations

import math

import numpy as np

from farm.p16_projection import Constraints


def _finite_mapping(values: dict[str, float], names: list[str], field: str) -> np.ndarray:
    try:
        result = np.asarray([values[name] for name in names], dtype=float)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{field} is incomplete") from exc
    if not np.all(np.isfinite(result)):
        raise ValueError(f"{field} is incomplete")
    return result


def plan_whole_share_orders(
    *, tickers: list[str], target_weights, current_quantities: dict[str, float],
    operational_prices: dict[str, float], cash: float, equity: float,
    beta, sectors, alpha, mandatory_exits: set[str] | None = None,
) -> dict:
    """Round down targets, fund sells first, and fail closed on post-rounding drift."""
    if (tickers != sorted(set(tickers)) or "SPY" in tickers or equity <= 0 or cash < 0
            or not np.isfinite(equity) or not np.isfinite(cash)):
        raise ValueError("invalid whole-share planning universe")
    names = [*tickers, "SPY"]
    target = np.asarray(target_weights, dtype=float)
    stock_beta = np.asarray(beta, dtype=float)
    alpha_values = np.asarray(alpha, dtype=float)
    if (target.shape != (len(names),) or stock_beta.shape != (len(tickers),)
            or alpha_values.shape != (len(tickers),)
            or not all(np.all(np.isfinite(value))
                       for value in (target, stock_beta, alpha_values))
            or np.any(target < 0) or abs(target.sum() - 1) > 1e-8):
        raise ValueError("invalid continuous target")
    prices = _finite_mapping(operational_prices, names, "operational prices")
    current = np.asarray([current_quantities.get(name, 0.0) for name in names], dtype=float)
    if np.any(prices <= 0) or np.any(current < 0) or not np.all(np.isfinite(current)):
        raise ValueError("invalid prices or current quantities")
    exits = mandatory_exits or set()
    if not exits <= set(tickers):
        raise ValueError("mandatory exit is outside the risk universe")
    desired = np.floor(target * equity / prices)
    for ticker in exits:
        desired[tickers.index(ticker)] = 0
    delta = desired - current
    projected_cash = float(cash + np.sum((-np.minimum(delta, 0)) * prices))
    purchases = np.maximum(delta, 0)
    # SPY financing happens before stock purchases; discretionary stock buys retain alpha order.
    if purchases[-1] * prices[-1] > projected_cash:
        purchases[-1] = math.floor(projected_cash / prices[-1])
    projected_cash -= purchases[-1] * prices[-1]
    for index in sorted(range(len(tickers)), key=lambda item: (-alpha_values[item], tickers[item])):
        affordable = math.floor(projected_cash / prices[index])
        purchases[index] = min(purchases[index], affordable)
        projected_cash -= purchases[index] * prices[index]
    projected = current + np.minimum(delta, 0) + purchases
    # Reinvest remaining cash in SPY so uninvested cash (beta zero) is explicit and minimized.
    extra_spy = math.floor(projected_cash / prices[-1])
    projected[-1] += extra_spy
    purchases[-1] += extra_spy
    projected_cash -= extra_spy * prices[-1]
    weights = projected * prices / equity
    cash_weight = projected_cash / equity
    constraints = Constraints(stock_beta, sectors)
    stock_sector_violation = constraints.violation(np.r_[weights[:-1], 1 - weights[:-1].sum()])
    actual_beta = float(stock_beta @ weights[:-1] + weights[-1])
    invalid = (
        weights[:-1].max(initial=0) > 0.1 + 1e-10
        or weights[:-1].sum() > (0.3 + 1e-10 if constraints.sector_status == "sector_unavailable"
                                else 1 + 1e-10)
        or stock_sector_violation > 1e-10 or actual_beta < 0.8 - 1e-10
        or actual_beta > 1.1 + 1e-10 or cash_weight < -1e-12
    )
    if invalid:
        mandatory_orders = [
            {"ticker": tickers[index], "side": "sell", "qty": float(current[index]),
             "order_role": "mandatory_exit", "target_weight": 0.0}
            for index in range(len(tickers)) if tickers[index] in exits and current[index] > 0
        ]
        return {
            "status": "rounded_plan_infeasible", "orders": mandatory_orders,
            "projected_quantities": None, "projected_cash": None,
            "cash_weight": None, "portfolio_beta": None,
            "sector_status": constraints.sector_status,
            "sector_coverage": constraints.sector_coverage,
        }
    orders = []
    for index, name in enumerate(names):
        change = projected[index] - current[index]
        if abs(change) < 1e-12:
            continue
        role = ("mandatory_exit" if name in exits else "spy_financing"
                if name == "SPY" else "rebalance")
        orders.append({
            "ticker": name, "side": "buy" if change > 0 else "sell",
            "qty": float(abs(change)), "order_role": role,
            "target_weight": float(target[index]),
        })
    orders.sort(key=lambda row: (row["side"] != "sell", row["ticker"]))
    return {
        "status": "planned", "orders": orders,
        "projected_quantities": dict(zip(names, projected.tolist(), strict=True)),
        "projected_cash": float(projected_cash), "cash_weight": float(cash_weight),
        "portfolio_beta": actual_beta, "sector_status": constraints.sector_status,
        "sector_coverage": constraints.sector_coverage,
    }
