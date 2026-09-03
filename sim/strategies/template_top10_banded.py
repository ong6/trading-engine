"""template_top10_banded — weekly top-N with banding.

Target set = top-N by RS PLUS any currently-held name still passing within RS
rank `band_rank`. A holding is only sold once it falls below that band (or drops
out of the passing set entirely), which cuts week-to-week churn. Equal weight
across the target set.
"""
from __future__ import annotations

from .base import (
    PortfolioView,
    Strategy,
    latest_screen_date,
    passing_ranked,
    rank_position,
    rebalance_orders,
    regime_risk_off,
)


class TemplateTop10Banded(Strategy):
    cadence = "weekly"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        sd = latest_screen_date(con, as_of)
        if sd is None:
            return []
        n = pf.params.get("n", 10)
        band = pf.params.get("band_rank", 20)
        ranks = rank_position(con, sd)
        top = [t for t, _ in passing_ranked(con, sd)[:n]]
        keepers = [t for t in pf.positions if ranks.get(t, 10**9) <= band]
        target_names = list(dict.fromkeys(top + keepers))
        if not target_names:
            targets = {}
        else:
            w = 1.0 / len(target_names)
            targets = {t: w for t in target_names}
        gated_off = pf.params.get("gated") and regime_risk_off(con, as_of)
        return rebalance_orders(con, pf, as_of, targets, allow_buys=not gated_off)
