"""ew_voltarget — the ew_benchmark basket, sized inverse to realized volatility.

WHY THIS BOOK EXISTS (pre-registered 2026-08-18). The 2026-08-17 walk-forward
put `ew_benchmark` at +30.55% mean validate return with NO active book beating
it in more than 50% of folds — i.e. on eight years of six-fold evidence the
SCREEN is the edge and almost every rule layered on top of it subtracts value.
EW's one clear weakness is drawdown: −36.48% in its worst validate window.

So this book changes exactly ONE thing versus `ew_benchmark`: the weighting.
Same screen, same universe, same monthly cadence, same `cap` — only the sizing
differs. That isolation is the whole point; a spread against ew_benchmark is
then attributable to the sizing rule and nothing else.

THE RULE. Weight each name proportional to 1/σ, where σ is the realized
standard deviation of its last `vol_lookback` daily log returns. Normalise to
sum to 1.

Two guards, both pre-registered rather than tuned:

  * `max_weight_mult` (default 3.0) caps any single name at 3× what it would
    have received under equal weight. Without it a name whose price barely
    moved over the lookback — a stale or newly-listed quote — takes an
    unbounded share of the book. This is a correctness guard, not an
    optimisation.
  * `min_obs` (default 40) drops names with too few bars to measure vol at
    all. They are EXCLUDED, never silently equal-weighted: a guessed weight is
    a fabricated input, and the honesty rules forbid it.

A name with σ = 0 over the window (a genuinely unchanged close, e.g. a halted
ticker) is also excluded — 1/0 is not a weight, and treating it as "lowest
risk" would be exactly backwards.
"""
from __future__ import annotations

import numpy as np

from .base import (
    PortfolioView, Strategy, latest_screen_date, passing_ranked, recent_closes,
    rebalance_orders,
)


class EwVolTarget(Strategy):
    cadence = "monthly"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        sd = latest_screen_date(con, as_of)
        if sd is None:
            return []

        cap = pf.params.get("cap", 50)
        lookback = int(pf.params.get("vol_lookback", 60))
        min_obs = int(pf.params.get("min_obs", 40))
        max_mult = float(pf.params.get("max_weight_mult", 3.0))

        # The vol window is fetched as `lookback + 1` closes, so a `min_obs`
        # above that can never be met by ANY name: every candidate is dropped,
        # `inv_vol` is empty, and the book silently posts no orders forever.
        # That is a config error, and it fails loudly here rather than being
        # reported downstream as a flat 0.00% return (2026-08-20: the
        # `vol_lookback=20` cells of the `voltarget` sweep did exactly that).
        if min_obs > lookback + 1:
            raise ValueError(
                f"ew_voltarget config is infeasible: min_obs={min_obs} exceeds "
                f"the {lookback + 1} closes a vol_lookback={lookback} window "
                f"can supply, so no name can ever be weighted")

        names = [t for t, _ in passing_ranked(con, sd)[:cap]]
        if not names:
            return []

        inv_vol: dict[str, float] = {}
        for tk in names:
            closes = recent_closes(con, tk, as_of, lookback + 1)
            if len(closes) < min_obs:
                continue                      # not enough bars to measure — drop
            rets = np.diff(np.log(closes))
            sigma = float(rets.std(ddof=1)) if len(rets) > 1 else 0.0
            if not np.isfinite(sigma) or sigma <= 0.0:
                continue                      # zero/undefined vol is not "safe"
            inv_vol[tk] = 1.0 / sigma

        if not inv_vol:
            return []

        # normalise, then cap at max_mult x equal weight and renormalise so the
        # book stays fully invested rather than leaking the capped excess to cash.
        total = sum(inv_vol.values())
        w = {t: v / total for t, v in inv_vol.items()}
        ceiling = max_mult / len(w)
        if any(v > ceiling for v in w.values()):
            w = {t: min(v, ceiling) for t, v in w.items()}
            s = sum(w.values())
            w = {t: v / s for t, v in w.items()}

        return rebalance_orders(con, pf, as_of, w)
