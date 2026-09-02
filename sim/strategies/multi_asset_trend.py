"""multi_asset_trend — time-series momentum across eight asset-class ETFs, BIL hurdle.

Pre-registered 2026-09-02, charter docs/charters/multi_asset_trend.md. Extends
`dual_momentum` (SPY vs EFA vs BIL, one winner, 100% in it) to a diversified
sleeve: SPY, EFA, EEM, TLT, IEF, GLD, DBC, VNQ — US and ex-US equity, EM,
long and intermediate Treasuries, gold, broad commodities, REITs. Every ticker
is in the store with history back to 2006 or earlier (checked 2026-09-02).

Rule, monthly at the close: each asset owns a fixed 1/N slot (N = number of
configured assets). The slot is HELD in the asset when its `lookback`-session
TOTAL return exceeds BIL's over the same window (the Antonacci absolute-
momentum hurdle, per asset rather than per winner), and sits in BIL otherwise.
Fixed slots, not "equal weight among holders": when seven of eight assets are
below the hurdle the book is 7/8 BIL, not 100% in the one survivor — that is
the diversification `dual_momentum` lacks, and concentrating into the last
asset standing would throw it away exactly when it matters.

Returns are TOTAL returns (price + dividends going ex in the window). This
matters twice here: the hurdle is BIL, whose price is flat and whose whole
return is coupon, and TLT/IEF/VNQ pay 2-4% that a price return would rank
short. An asset with insufficient history is skipped and its slot sits in BIL
— never scored on a shorter window. If BIL itself has no history its hurdle
is taken as 0 and the idle fraction stays in un-modelled cash (rebalance_orders
skips an unpriced ticker); never fabricated.
"""
from __future__ import annotations

from .base import PortfolioView, Strategy, rebalance_orders, total_return

ASSETS = ["SPY", "EFA", "EEM", "TLT", "IEF", "GLD", "DBC", "VNQ"]


class MultiAssetTrend(Strategy):
    cadence = "monthly"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        p = pf.params
        assets = list(p.get("assets", ASSETS))
        cash_proxy = p.get("cash_proxy", "BIL")
        lookback = int(p.get("lookback", 252))
        if not assets or lookback < 1:
            raise ValueError("multi_asset_trend: need >= 1 asset and lookback >= 1")

        hurdle = total_return(con, cash_proxy, as_of, lookback)
        hurdle = 0.0 if hurdle is None else hurdle

        slot = 1.0 / len(assets)
        targets: dict[str, float] = {}
        idle = 0.0
        for tk in assets:
            r = total_return(con, tk, as_of, lookback)
            if r is not None and r > hurdle:
                targets[tk] = targets.get(tk, 0.0) + slot
            else:
                idle += slot            # below hurdle OR not enough history
        if idle > 0:
            targets[cash_proxy] = targets.get(cash_proxy, 0.0) + idle
        return rebalance_orders(con, pf, as_of, targets)
