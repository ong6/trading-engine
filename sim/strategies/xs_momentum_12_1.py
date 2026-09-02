"""xs_momentum_12_1 — plain cross-sectional 12-1 momentum, no Minervini screen.

THE CONTROL (pre-registered 2026-09-02, charter docs/charters/xs_momentum_12_1.md).
Every "beats EW" number in this store is a comparison against `ew_benchmark`,
which IS the trend-template screen. Nothing has ever tested the screen against
the thing it is a dressed-up version of: ranking the liquid universe by trailing
twelve-month return and holding the top of the list. This book is that thing,
and nothing more, so the spread `ew_benchmark − xs_momentum_12_1` is the
screen's marginal value and the spread `template_top10_banded −
xs_momentum_12_1` is the template family's.

Universe: every `active AND liquid AND NOT etf` name in `universe` with at
least `min_bars` stored sessions and a close ≥ `min_price` (see xs_common.py).
Signal: total return from the close `lookback` sessions ago to the close `skip`
sessions ago — the Jegadeesh–Titman 12-1, skipping the most recent month so the
one-month reversal effect does not contaminate the rank. Selection: the top `n`
by that return, equal weight 1/n, refreshed monthly with NO banding — a held
name that falls out of the top `n` is sold. Banding is a rule, and this book
tests no rules.
"""
from __future__ import annotations

from .base import PortfolioView, Strategy, rebalance_orders
from .xs_common import window_returns


class XsMomentum121(Strategy):
    cadence = "monthly"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        p = pf.params
        n = int(p.get("n", 50))
        lookback = int(p.get("lookback", 252))
        skip = int(p.get("skip", 21))
        min_bars = int(p.get("min_bars", lookback + 1))
        min_price = float(p.get("min_price", 5.0))
        if skip < 0 or lookback <= skip:
            raise ValueError(f"xs_momentum_12_1: lookback={lookback} must exceed "
                             f"skip={skip} >= 0")

        rows = window_returns(con, as_of, start_offset=lookback + 1,
                              end_offset=skip + 1, min_bars=min_bars,
                              min_price=min_price)
        if not rows:
            return []            # too little history anywhere — hold, never guess
        chosen = [tk for tk, _ret, _px, _sma in rows[:n]]
        w = 1.0 / n
        return rebalance_orders(con, pf, as_of, {tk: w for tk in chosen})
