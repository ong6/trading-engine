"""sector_momentum — monthly rotation across the eleven SPDR sector ETFs.

Score per ETF = the mean of its total return over each lookback in `lookbacks`;
an ETF with insufficient history for any lookback is skipped rather than scored
on a shorter window. Hold the top `n` by score, but a slot whose ETF has a
non-positive long-lookback return goes to cash instead — the absolute-momentum
filter that keeps the book out of falling sectors. Equal weight `1/n` per slot.
"""
from __future__ import annotations

from .base import PortfolioView, Strategy, rebalance_orders, total_return

SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB",
           "XLRE", "XLC"]


class SectorMomentum(Strategy):
    cadence = "monthly"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        p = pf.params
        lookbacks = p.get("lookbacks", [63, 126, 252])
        n = p.get("n", 3)
        longest = max(lookbacks)

        scored = []
        for tk in p.get("sectors", SECTORS):
            rets = {lb: total_return(con, tk, as_of, lb) for lb in lookbacks}
            if any(r is None for r in rets.values()):
                continue
            scored.append((sum(rets.values()) / len(rets), rets[longest], tk))
        scored.sort(key=lambda s: (-s[0], s[2]))

        w = 1.0 / n
        targets = {tk: w for _score, long_ret, tk in scored[:n] if long_ret > 0}
        return rebalance_orders(con, pf, as_of, targets)
