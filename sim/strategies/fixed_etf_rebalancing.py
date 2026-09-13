"""Research-only fixed-ETF rebalancing candidate and buy-and-hold control.

These classes implement charter ``FIXED-ETF-REBAL-2026-09-07-v1``. The isolated
experiment runner installs them in the strategy registry only for the duration
of its process. They are absent from both the default registry and
``sim.strategies.configs.CONFIGS``, so normal paper operation cannot select or
create either book.
"""
from __future__ import annotations

from .base import PortfolioView, Strategy, rebalance_orders

ASSETS = ("SPY", "IEF", "GLD")
QUARTER_END_MONTHS = frozenset({3, 6, 9, 12})


def _assets(params: dict) -> tuple[str, ...]:
    assets = tuple(params.get("assets", ASSETS))
    if assets != ASSETS:
        raise ValueError(f"fixed ETF charter requires exactly {ASSETS}, got {assets}")
    return assets


def _targets_if_all_priced(con, assets: tuple[str, ...], as_of) -> dict[str, float]:
    """Equal weights only when every asset has an exact signal-date close."""
    placeholders = ",".join("?" for _ in assets)
    rows = con.execute(
        f"SELECT ticker FROM prices WHERE date = ? AND close > 0 "
        f"AND ticker IN ({placeholders})",
        [as_of, *assets],
    ).fetchall()
    if {row[0] for row in rows} != set(assets):
        return {}
    weight = 1.0 / len(assets)
    return {ticker: weight for ticker in assets}


def _is_inception(con, portfolio_id: str, as_of) -> bool:
    row = con.execute(
        "SELECT created FROM portfolios WHERE id = ?", [portfolio_id]
    ).fetchone()
    return row is not None and row[0] == as_of


class FixedEtfBuyHold(Strategy):
    """Enter the three-ETF basket once, then emit no further orders."""

    cadence = "daily"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        if pf.positions:
            return []
        if not _is_inception(con, pf.id, as_of):
            return []
        assets = _assets(pf.params)
        targets = _targets_if_all_priced(con, assets, as_of)
        return rebalance_orders(con, pf, as_of, targets) if targets else []


class FixedEtfRebalanced(Strategy):
    """Enter once, then restore equal weights at calendar-quarter ends."""

    cadence = "daily"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        assets = _assets(pf.params)
        targets = _targets_if_all_priced(con, assets, as_of)
        if not targets:
            return []
        if not pf.positions and _is_inception(con, pf.id, as_of):
            return rebalance_orders(con, pf, as_of, targets)
        if not pf.positions:
            return []
        if as_of.month not in QUARTER_END_MONTHS:
            return []
        from sim import calendar

        if not calendar.is_month_signal(con, as_of):
            return []
        return rebalance_orders(con, pf, as_of, targets)
