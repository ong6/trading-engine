"""ew_dd_throttle — the ew_benchmark basket, equal-weighted, with a
PORTFOLIO-level drawdown stop: cut gross exposure to `derisk_frac` once the
book is `dd_trigger` below its own equity peak, restore when it recovers to
within `dd_restore` of that peak. The de-risked remainder sits in `cash_proxy`
(BIL), never in un-modelled cash.

WHY THIS BOOK EXISTS (pre-registered 2026-08-20). Same target as its two
siblings: `ew_benchmark` is the bar nothing clears (30 genuine sweep trials, 10
folds, best median excess anywhere +0.02%) and its one weakness is a -36.5% to
-37.5% worst-fold drawdown. `ew_gross_voltarget` attacks that with a
volatility-driven exposure rule and `ew_sector_capped` with diversification.
This one attacks it with the crudest available instrument — the book's own
equity curve — and is deliberately the least clever of the three.

WHAT IS ACTUALLY NEW HERE. A PORTFOLIO-level stop, not a per-name one. Per-name
stops were already tested as `momo_stopped`, and the 2026-08-20 `momo_stop`
sweep put **all nine** of its parameter cells at negative median excess vs
`ew_benchmark` (best -3.19%, beating EW in 30% of folds). That result says
nothing about a book-level stop, because a screen's -36% drawdown is a market
drawdown: the names fall together, so stopping out of each one individually
just re-buys the same exposure at the next rebalance. This rule can only be
tested at the book level, and it has never been tested at the book level here.

THE HONEST PRIOR, AND IT IS NEGATIVE. **Path-dependent de-risking rules usually
whipsaw and lose more to re-entry than they save.** A book that sells 15% below
its peak and buys back 5% below it has, by construction, sold low and bought
higher on every round trip that does not turn into a real bear market; the
V-shaped 2020 and 2025 drawdowns are exactly the shape that punishes it hardest.
`ew_trend_gated`, the other path-dependent rule in this store, gave up 23pp of
return for 0.1pp of drawdown relief on its first fold. This book is a TEST of
that prior, not a bet against it, and the useful outcome is as likely to be
"confirmed again, stop proposing this" as anything else.

THE RULE.
  1. Replay the book's own `sim_equity` history up to and including `as_of`,
     carrying a running peak and a throttled flag:
       - not throttled and (peak - equity) / peak >  dd_trigger  -> THROTTLE
       - throttled     and (peak - equity) / peak <= dd_restore  -> RESTORE
     Between the two thresholds the flag is UNCHANGED. That gap is hysteresis
     and it is the entire reason the rule is stated with two numbers.
  2. exposure = derisk_frac if throttled else 1.0.
  3. Each `ew_benchmark` name gets exposure / len(names); `cash_proxy` takes
     1 - exposure.

WHY THE STATE IS RE-DERIVED FROM THE EQUITY CURVE EVERY TIME, rather than
cached on the portfolio or inferred from "does the book currently hold BIL".
The equity curve is the only record of this that is written by the engine
itself, is queryable with a strict `date <= as_of` bound, and is wiped and
rebuilt with the book on every walk-forward fold. Inferring the flag from
current holdings would need a magic BIL-weight threshold and would break on
`derisk_frac = 0.0` versus `0.5`; caching it would put strategy state somewhere
the replay does not reset. Re-deriving is O(sessions) on a monthly cadence and
is exactly reproducible.

GUARDS — which are correctness and which are optimisation:

  * `dd_restore < dd_trigger` (CORRECTNESS, raises). Equal or inverted
    thresholds make the state machine throttle and restore on the same reading;
    the book would flap with no hysteresis and the "rule" being tested would not
    be the rule described here.
  * `0 <= derisk_frac <= 1` (CORRECTNESS, raises). Above 1 is leverage on
    survivorship-biased data, which this store does not do; below 0 is a short.
  * The peak is the book's OWN equity peak since its inception in this window,
    never a market peak and never carried across folds. CORRECTNESS: a fold
    inherits no state.
  * `dd_trigger` (default 0.15) and `derisk_frac` (default 0.5) are the
    OPTIMISATION axes and the two the grid varies. `dd_restore` (default 0.05)
    is fixed in the grid on purpose — sweeping all three would triple the trial
    count that every result then has to be deflated against.

NO EQUITY HISTORY IS NOT A DRAWDOWN. On the first sessions of a fold the book
has no peak worth the name; the state machine simply starts un-throttled at the
first equity row. Nothing is imputed and no exposure decision is taken off an
absent series.
"""
from __future__ import annotations

from .base import (
    PortfolioView, Strategy, latest_screen_date, passing_ranked, rebalance_orders,
)


class EwDdThrottle(Strategy):
    cadence = "monthly"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        p = pf.params
        cap = int(p.get("cap", 50))
        dd_trigger = float(p.get("dd_trigger", 0.15))
        derisk_frac = float(p.get("derisk_frac", 0.5))
        dd_restore = float(p.get("dd_restore", 0.05))
        cash_proxy = str(p.get("cash_proxy", "BIL"))

        # Fail loudly rather than run a rule that is not the rule in the
        # docstring. See BUILDLOG 2026-08-20: the dangerous outcome in this
        # codebase is never a crash, it is a book that quietly does something
        # else and reports a number for it.
        if not dd_restore < dd_trigger:
            raise ValueError(
                f"ew_dd_throttle config is infeasible: dd_restore={dd_restore} "
                f"is not below dd_trigger={dd_trigger}, so the throttle has no "
                f"hysteresis band and can trigger and restore on one reading")
        if not 0.0 <= derisk_frac <= 1.0:
            raise ValueError(
                f"ew_dd_throttle config is infeasible: derisk_frac="
                f"{derisk_frac} must lie in [0, 1] — above 1 is leverage on "
                f"survivorship-biased history, below 0 is a short")
        if dd_trigger <= 0.0:
            raise ValueError(
                f"ew_dd_throttle config is infeasible: dd_trigger={dd_trigger} "
                f"throttles the book permanently from its first session")

        sd = latest_screen_date(con, as_of)
        if sd is None:
            return []
        names = [t for t, _ in passing_ranked(con, sd)[:cap]
                 if t != cash_proxy]
        if not names:
            return []

        throttled = self._throttled(con, pf.id, as_of, dd_trigger, dd_restore)
        exposure = derisk_frac if throttled else 1.0

        targets = {t: exposure / len(names) for t in names}
        cash_w = 1.0 - exposure
        if cash_w > 0:
            targets[cash_proxy] = cash_w
        return rebalance_orders(con, pf, as_of, targets)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _throttled(con, pf_id: str, as_of, dd_trigger: float,
                   dd_restore: float) -> bool:
        """Replay the book's own equity curve to as_of and return the flag.

        Strictly `date <= as_of`, so no future equity can inform the decision.
        `sim_equity` for as_of is already written when a strategy is called
        (league.step phase b runs before phase c), so today's mark counts.
        """
        rows = con.execute(
            "SELECT equity FROM sim_equity WHERE portfolio_id = ? AND date <= ? "
            "ORDER BY date", [pf_id, as_of]).fetchall()
        peak = None
        throttled = False
        for (eq,) in rows:
            if eq is None:
                continue          # a missing mark is not a drawdown — skip it
            eq = float(eq)
            if peak is None or eq > peak:
                peak = eq
            if peak is None or peak <= 0:
                continue
            dd = (peak - eq) / peak
            if not throttled and dd > dd_trigger:
                throttled = True
            elif throttled and dd <= dd_restore:
                throttled = False
        return throttled
