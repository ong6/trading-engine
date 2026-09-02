"""xs_reversal_1m — long-only one-month cross-sectional reversal, trend-filtered.

Pre-registered 2026-09-02, charter docs/charters/xs_reversal_1m.md. The store's
only mean-reversion book (`mr_overlay`, RSI(2) on template passers) is dead in
9 of 9 sweep cells; this book is a DIFFERENT effect — the Jegadeesh (1990)
one-month reversal, cross-sectional, on the whole liquid universe — and the
first live book whose return source is not momentum.

Universe: every `active AND liquid AND NOT etf` name with at least `min_bars`
stored sessions and a close ≥ `min_price`. Eligibility: close > its 200-session
SMA — long-only means the book buys pullbacks in uptrends, not falling knives;
the filter is a pre-registered part of the hypothesis, not a tuning knob.
Signal: trailing `lookback`-session TOTAL return (dividends included, so a
special dividend does not masquerade as a loss). Selection: the WORST
`frac` of eligible names, capped at `max_n`, each in a fixed 1/`max_n` slot;
unfilled slots stay in cash. With ~1.5k eligible names the decile (~150) is
always capped, so in practice the book is "the 50 worst-performing uptrending
liquid names of the past month" — and in a broad bear tape, when few names sit
above their 200d, it shrinks toward cash by construction. Monthly, no banding:
a reversal position is a one-month bet and is re-underwritten every month.
"""
from __future__ import annotations

from .base import PortfolioView, Strategy, rebalance_orders
from .xs_common import window_returns


class XsReversal1m(Strategy):
    cadence = "monthly"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        p = pf.params
        max_n = int(p.get("max_n", 50))
        frac = float(p.get("frac", 0.10))
        lookback = int(p.get("lookback", 21))
        min_bars = int(p.get("min_bars", 252))
        min_price = float(p.get("min_price", 5.0))
        if not (0 < frac <= 1) or max_n < 1 or lookback < 1:
            raise ValueError(f"xs_reversal_1m: bad params frac={frac} "
                             f"max_n={max_n} lookback={lookback}")
        if min_bars < 200:
            raise ValueError("xs_reversal_1m: min_bars must be >= 200 so the "
                             "200-session SMA filter can be evaluated")

        rows = window_returns(con, as_of, start_offset=lookback + 1,
                              end_offset=1, min_bars=min_bars,
                              min_price=min_price)
        eligible = [(ret, tk) for tk, ret, last, sma in rows
                    if sma is not None and last > sma]
        if not eligible:
            return rebalance_orders(con, pf, as_of, {})   # nothing uptrending
        eligible.sort(key=lambda s: (s[0], s[1]))          # worst first
        k = min(max_n, max(1, int(len(eligible) * frac)))
        chosen = [tk for _ret, tk in eligible[:k]]
        w = 1.0 / max_n
        return rebalance_orders(con, pf, as_of, {tk: w for tk in chosen})
