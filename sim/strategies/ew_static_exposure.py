"""ew_static_exposure — the ew_benchmark basket at a FIXED gross exposure.

WHY THIS BOOK EXISTS. It is a control, and it exists because the first evidence
for `ew_gross_voltarget` could not be read without it.

That book cut the worst validate drawdown from -36.48% to -18.22% over two
folds, which reads as a win for volatility targeting. But it ran at `vol_ann`
17.31% / 17.70% against the benchmark's 37.02% / 56.24% — roughly 47% and 31%
of the benchmark's risk. **Most of that drawdown relief is the mechanical
consequence of holding less equity, and says nothing about whether varying the
exposure over time helped at all.** An adversarial audit on 2026-08-20 tested
the alternative directly and found a static blend matched to the same drawdown
BEAT vol-targeting in fold 1 (+7.3% vs +6.15%) and lost it in fold 2 (+14.4% vs
+27.52%): one-for-two, unresolved.

So this book holds the same basket at a CONSTANT `exposure`, rest in the cash
proxy, rebalanced on the same monthly cadence. It has no signal, no estimate and
no timing. It exists so that:

    ew_gross_voltarget  -  ew_static_exposure   =   the value of the TIMING
    ew_static_exposure  -  ew_benchmark         =   the value of DE-RISKING

Without it, a grid comparing `ew_gross_voltarget` to `ew_benchmark` measures the
sum of those two and attributes all of it to the rule under test. That is the
same error as reading a sweep's ranking without its trial count: the number is
real, the attribution is wrong.

THE RULE. Take the top `cap` screen passers by RS, equal-weight them, and scale
every weight by `exposure`. Put `1 - exposure` in `cash_proxy` (BIL) so the book
is always fully accounted for and never holds un-modelled cash.

**Deliberately dumb.** No vol estimate, no regime input, no drawdown state. A
control that acquires a signal stops being a control.

EXPECTATION (pre-registered). This should track `ew_benchmark` scaled down: less
return in up markets, proportionally less drawdown, and a broadly SIMILAR
risk-adjusted return, because scaling a portfolio by a constant leaves its
Sharpe unchanged up to the cash yield. If `ew_gross_voltarget` cannot beat THIS
on risk-adjusted return over ten folds, then the vol targeting adds nothing and
the honest conclusion is "hold less equity", which needs no new strategy code at
all.

KILL CRITERION. None — a control is not killed for underperforming. It is
retired only if `ew_gross_voltarget` is retired, since its only purpose is to
give that book a denominator.
"""
from __future__ import annotations

from .base import (
    PortfolioView,
    Strategy,
    latest_screen_date,
    passing_ranked,
    rebalance_orders,
)


class EwStaticExposure(Strategy):
    cadence = "monthly"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        p = pf.params
        cap = int(p.get("cap", 50))
        exposure = float(p.get("exposure", 0.5))
        cash_proxy = str(p.get("cash_proxy", "BIL"))

        # An exposure outside (0, 1] is a config that can never test the rule:
        # 0 holds nothing but the cash proxy forever and would be reported as a
        # flat return, and > 1 is leverage this engine does not model. Fail
        # loudly rather than posting a plausible-looking nothing — the defect
        # class recorded in BUILDLOG 2026-08-20.
        if not 0 < exposure <= 1:
            raise ValueError(
                f"ew_static_exposure config is infeasible: exposure={exposure} "
                f"must be in (0, 1] — 0 holds only {cash_proxy} forever and "
                f">1 is leverage this engine does not model")

        sd = latest_screen_date(con, as_of)
        if sd is None:
            return []
        names = [t for t, _ in passing_ranked(con, sd)[:cap]]
        if not names:
            return []

        w = exposure / len(names)
        targets = {t: w for t in names}
        cash_w = 1.0 - exposure
        if cash_w > 0:
            targets[cash_proxy] = cash_w
        return rebalance_orders(con, pf, as_of, targets)
