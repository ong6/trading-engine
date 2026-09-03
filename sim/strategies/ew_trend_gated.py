"""ew_trend_gated — the ew_benchmark basket, held only while SPY is above its
200-session SMA; otherwise the book sits in `cash_proxy` (BIL).

WHY THIS BOOK EXISTS (pre-registered 2026-08-18). Same motivation as
`ew_voltarget`: the 2026-08-17 walk-forward showed `ew_benchmark` is the bar
nothing clears (mean validate +30.55%, no book beating it in >50% of folds),
and its one weakness is a −36.48% worst-fold drawdown. This book attacks that
drawdown with a trend filter instead of a sizing rule, so the two are
independent tests of the same weakness and can be read side by side.

HOW THIS DIFFERS FROM THE EXISTING `*_gated` BOOKS — this matters, and it is
deliberate. `template_top5_gated`, `mr_overlay_gated` et al. use the house
regime gate as "block NEW entries while risk-off" (`allow_buys=False`), which
leaves existing positions fully exposed all the way down. Their walk-forward
records show the expected consequence: `template_top10_banded_gated` still ate
−43.69% in its worst validate window versus −47.81% ungated, i.e. the entry
block bought ~4pp of drawdown relief. Nearly nothing.

This book therefore tests the STRONGER form of the same idea: on risk-off it
ROTATES OUT — sells the basket and holds BIL — rather than merely declining to
add. If the screen's drawdown is avoidable by a public, lagging, widely-known
filter, this is the version that would show it. If it is not avoidable, this
book will underperform ew_benchmark through whipsaws and the answer is equally
informative. The honest prior is that a 200-day filter on a monthly-rebalanced
basket whipsaws more than it saves.

The gate reuses `regime_risk_off` unchanged — the same SPY/200d SMA definition
the rest of the league already trades — so no new signal is introduced and the
comparison stays clean. Unknown regime (SPY absent or <200 bars) is treated as
NOT risk-off by that helper, i.e. the book stays invested rather than acting on
missing data.
"""
from __future__ import annotations

from .base import (
    PortfolioView,
    Strategy,
    latest_screen_date,
    passing_ranked,
    rebalance_orders,
    regime_risk_off,
)


class EwTrendGated(Strategy):
    cadence = "monthly"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        cash_proxy = pf.params.get("cash_proxy", "BIL")

        # Risk-off: the whole book rotates to the cash proxy. rebalance_orders
        # sells every held name absent from the target map, so this is a full
        # exit plus a single BIL buy — not an entry block.
        if regime_risk_off(con, as_of):
            return rebalance_orders(con, pf, as_of, {cash_proxy: 1.0})

        sd = latest_screen_date(con, as_of)
        if sd is None:
            return []
        cap = pf.params.get("cap", 50)
        names = [t for t, _ in passing_ranked(con, sd)[:cap]]
        if not names:
            return []
        w = 1.0 / len(names)
        # BIL is not in the target map on risk-on, so any BIL held from a
        # previous risk-off stretch is sold back into the basket.
        return rebalance_orders(con, pf, as_of, {t: w for t in names})
