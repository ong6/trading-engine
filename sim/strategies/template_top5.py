"""template_top5 — weekly top-N passes_template names, equal weight."""
from __future__ import annotations

from .base import (
    PortfolioView,
    Strategy,
    latest_screen_date,
    passing_ranked,
    rebalance_orders,
    regime_risk_off,
)


class TemplateTop5(Strategy):
    cadence = "weekly"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        sd = latest_screen_date(con, as_of)
        if sd is None:
            return []
        n = pf.params.get("n", 5)
        w = pf.params.get("weight", 0.20)
        top = [t for t, _ in passing_ranked(con, sd)[:n]]
        targets = {t: w for t in top}
        gated_off = pf.params.get("gated") and regime_risk_off(con, as_of)
        return rebalance_orders(con, pf, as_of, targets, allow_buys=not gated_off)
