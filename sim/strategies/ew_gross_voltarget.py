"""ew_gross_voltarget — the ew_benchmark basket, equal-weighted, with GROSS
exposure scaled so the PORTFOLIO's realized volatility targets `vol_target`.
The unused fraction sits in `cash_proxy` (BIL), never in un-modelled cash.

WHY THIS BOOK EXISTS (pre-registered 2026-08-20). Four sweep grids, 30 genuine
trials, 10 folds each: the best median excess vs `ew_benchmark` anywhere is
**+0.02%**. `ew_benchmark` posts +24.03% mean validate with a -36.5% to -37.5%
worst-fold drawdown and no active book beats it in more than half its folds.
The standing conclusion is that the SCREEN is the edge and nearly every rule
layered on it subtracts value.

Every rule tried so far — banding, concentration, per-name stops, inverse-vol
weighting — varies WHICH names are held or HOW they are weighted RELATIVE TO
ONE ANOTHER, always at 100% gross. **Nothing has ever varied gross exposure.**
A -36% drawdown is a market drawdown: the screen's names fall together, so no
per-name reweighting can fix it, which is exactly what the `voltarget` sweep
measured when it bought approximately nothing.

HOW THIS DIFFERS FROM `ew_voltarget` — this is the whole point, and the two are
easy to confuse. `ew_voltarget` changes RELATIVE weights (1/sigma per name) at a
constant 100% gross. This book holds relative weights FLAT (equal weight, the
benchmark's own sizing) and changes GROSS. They are different hypotheses about
different mechanisms and only one of them can address a market-wide drawdown.
Running both is how the store tells them apart.

THE RULE.
  1. Take the `ew_benchmark` basket: the top `cap` passing names by RS.
  2. Estimate the basket's own realized volatility — build the daily return
     series of the EQUAL-WEIGHTED basket over the last `vol_lookback` sessions
     (the cross-sectional mean of the constituents' daily log returns), take its
     sample standard deviation and annualise by sqrt(252).
  3. exposure = clamp(vol_target / realized_vol, 0, max_leverage).
  4. Each name gets exposure / len(names); `cash_proxy` gets 1 - exposure.

`max_leverage` defaults to **1.0 — de-risk only, never lever.** That is a
deliberate honesty constraint, not a tuned parameter: this store's price history
is survivorship-biased (~+7pp/yr, disclosed in every report), and levering a
survivorship-biased backtest manufactures return out of a known data defect.

GUARDS — which are correctness and which are optimisation:

  * `min_obs` (default 20, CORRECTNESS) — the minimum number of basket-return
    days needed before a volatility is quoted at all. Fewer than that and the
    estimate is not measured, it is asserted.
  * `min_name_frac` (default 0.8, CORRECTNESS) — a session is used in the vol
    estimate only if at least this fraction of the basket has a bar that day.
    A day on which 6 of 50 names traded is not the basket's return, and
    back-filling the other 44 would be a fabricated input.
  * `max_leverage` (default 1.0, CORRECTNESS as set — see above). Raising it
    above 1.0 turns this into an optimisation and a dishonest one on this data.
  * `vol_target` (default 0.15, OPTIMISATION) — the one number this book is
    actually asking a question about, and the axis the sweep grid varies.
  * `vol_lookback` (default 60, OPTIMISATION) — how fast the exposure reacts.

UNKNOWN VOLATILITY IS NOT ZERO RISK. If the window cannot supply `min_obs`
usable basket-return days, or the measured sigma is zero or non-finite, this
book does NOT compute an exposure from it — `vol_target / 0` is not "infinite
capacity for risk", it is a missing measurement. It holds the plain benchmark
basket at exposure min(1.0, max_leverage) and says so on stdout, the same
convention `regime_risk_off` uses for an unknown regime: never act on data you
do not have. It never sizes off a guessed sigma.

AN INFEASIBLE CONFIG RAISES. `min_obs > vol_lookback` can never be satisfied by
any basket, and a non-positive `vol_target` or `max_leverage` pins exposure at
zero forever. Both would produce a book that quietly does nothing (or quietly
holds only BIL) and reports a number for it — the failure mode this codebase
has now hit four separate times. They fail loudly here instead.
"""
from __future__ import annotations

import numpy as np

from engine.lib.log import get_logger

from .base import (
    PortfolioView,
    Strategy,
    latest_screen_date,
    passing_ranked,
    rebalance_orders,
)

log = get_logger("ew_gross_voltarget")

TRADING_DAYS = 252

# Daily EW-basket returns over the window. One set-based scan: rank each name's
# closes back from as_of, take the newest `lookback + 1`, difference them in log
# space, then average ACROSS names per session. Names are equal-weighted in the
# average, which is the basket this book actually holds.
BASKET_RET_SQL = """
WITH px AS (
    SELECT ticker, date, close,
           ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
    FROM prices
    WHERE ticker IN ({placeholders}) AND date <= ? AND close > 0
), w AS (
    SELECT ticker, date, close FROM px WHERE rn <= ?
), rets AS (
    SELECT date,
           LN(close / LAG(close) OVER (PARTITION BY ticker ORDER BY date)) AS r
    FROM w
)
SELECT date, AVG(r) AS basket_ret, COUNT(*) AS n_names
FROM rets WHERE r IS NOT NULL
GROUP BY date ORDER BY date
"""


class EwGrossVolTarget(Strategy):
    cadence = "monthly"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        p = pf.params
        cap = int(p.get("cap", 50))
        vol_target = float(p.get("vol_target", 0.15))
        lookback = int(p.get("vol_lookback", 60))
        max_lev = float(p.get("max_leverage", 1.0))
        min_obs = int(p.get("min_obs", 20))
        min_name_frac = float(p.get("min_name_frac", 0.8))
        cash_proxy = str(p.get("cash_proxy", "BIL"))

        # Fail loudly on a config no basket can ever satisfy, rather than
        # posting no orders (or only BIL) forever and being reported as a flat
        # return downstream. Same class of defect as ew_voltarget's
        # min_obs > vol_lookback + 1 (BUILDLOG 2026-08-20).
        if min_obs > lookback:
            raise ValueError(
                f"ew_gross_voltarget config is infeasible: min_obs={min_obs} "
                f"exceeds the {lookback} basket-return days a "
                f"vol_lookback={lookback} window can supply, so a volatility "
                f"can never be measured")
        if vol_target <= 0:
            raise ValueError(
                f"ew_gross_voltarget config is infeasible: vol_target="
                f"{vol_target} pins gross exposure at 0 forever — the book "
                f"would hold nothing but {cash_proxy} and never test the rule")
        if max_lev <= 0:
            raise ValueError(
                f"ew_gross_voltarget config is infeasible: max_leverage="
                f"{max_lev} pins gross exposure at 0 forever")
        if not 0 < min_name_frac <= 1:
            raise ValueError(
                f"ew_gross_voltarget config is infeasible: min_name_frac="
                f"{min_name_frac} must be in (0, 1]")

        sd = latest_screen_date(con, as_of)
        if sd is None:
            return []
        names = [t for t, _ in passing_ranked(con, sd)[:cap]
                 if t != cash_proxy]
        if not names:
            return []

        sigma = self._basket_vol(con, names, as_of, lookback, min_obs,
                                 min_name_frac)
        if sigma is None:
            # Unknown risk is not low risk and is not high risk. Hold the plain
            # benchmark basket and say so; never size off a guessed sigma.
            log.info(f"[ew_gross_voltarget] {pf.id} {as_of}: basket volatility "
                  f"unmeasurable over {lookback} sessions "
                  f"(need {min_obs} usable days at >={min_name_frac:.0%} of "
                  f"{len(names)} names) — holding full basket, no exposure "
                  f"decision taken")
            exposure = min(1.0, max_lev)
        else:
            exposure = min(max_lev, vol_target / sigma)
        exposure = max(0.0, exposure)

        targets = {t: exposure / len(names) for t in names}
        cash_w = 1.0 - exposure
        if cash_w > 0:
            # The de-risked remainder is HELD, in a modelled instrument with a
            # real price and a real coupon, not parked in un-modelled cash.
            targets[cash_proxy] = cash_w
        return rebalance_orders(con, pf, as_of, targets)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _basket_vol(con, names, as_of, lookback, min_obs, min_name_frac):
        """Annualised realized vol of the equal-weighted basket, or None.

        None means UNMEASURABLE — too few usable sessions, or a degenerate
        (zero / non-finite) sigma. It is never coerced into a number.
        """
        sql = BASKET_RET_SQL.format(placeholders=",".join(["?"] * len(names)))
        rows = con.execute(sql, [*names, as_of, lookback + 1]).fetchall()
        need = max(1, int(np.ceil(min_name_frac * len(names))))
        # A session with too few constituents reporting is DROPPED, not
        # patched: the mean of 6 of 50 names is not the basket's return.
        series = [float(r[1]) for r in rows
                  if r[1] is not None and r[2] >= need]
        if len(series) < min_obs:
            return None
        sigma_d = float(np.std(np.array(series), ddof=1))
        if not np.isfinite(sigma_d) or sigma_d <= 0.0:
            return None
        return sigma_d * np.sqrt(TRADING_DAYS)
