"""Shared mechanics for isolated SPY/BIL research strategies.

This module contains no strategy registration and no signal rule. It only
enforces complete signal-date prices, inception/transition gating, and the
common target construction used by the frozen research experiments.
"""
from __future__ import annotations

from datetime import date

from .base import PortfolioView, rebalance_orders

ASSETS = ("SPY", "BIL")


def transition_orders(
    con,
    pf: PortfolioView,
    as_of: date,
    *,
    risk_on: bool,
    changed: bool,
    static_spy_weight: float | None = None,
):
    """Build a complete SPY/BIL rebalance only at inception or a state change."""
    rows = con.execute(
        "SELECT ticker FROM prices WHERE date = ? AND close > 0 "
        "AND ticker IN ('SPY', 'BIL')", [as_of]
    ).fetchall()
    if {row[0] for row in rows} != set(ASSETS):
        return []

    created = con.execute(
        "SELECT created FROM portfolios WHERE id = ?", [pf.id]
    ).fetchone()
    is_inception = created is not None and created[0] == as_of
    if not is_inception and not changed:
        return []

    if static_spy_weight is None:
        targets = {"SPY": 1.0} if risk_on else {"BIL": 1.0}
    else:
        if not 0 <= static_spy_weight <= 1:
            raise ValueError("static SPY weight must be between zero and one")
        targets = {"SPY": static_spy_weight, "BIL": 1.0 - static_spy_weight}
    return rebalance_orders(con, pf, as_of, targets)
