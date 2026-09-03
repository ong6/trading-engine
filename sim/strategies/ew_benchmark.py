"""ew_benchmark — equal-weight the passes_template set (top `cap` by RS),
rebalanced monthly. The strategy-agnostic yardstick every active book must beat.
"""
from __future__ import annotations

from .base import (
    PortfolioView,
    Strategy,
    latest_screen_date,
    passing_ranked,
    rebalance_orders,
)


class EwBenchmark(Strategy):
    cadence = "monthly"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        sd = latest_screen_date(con, as_of)
        if sd is None:
            return []
        cap = pf.params.get("cap", 50)
        names = [t for t, _ in passing_ranked(con, sd)[:cap]]
        if not names:
            return []
        w = 1.0 / len(names)
        targets = {t: w for t in names}
        return rebalance_orders(con, pf, as_of, targets)
