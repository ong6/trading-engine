# Charter — `ew_dd_throttle`

_Pre-registration, 2026-08-20. The text below preserves the original candidate
hypothesis and gates; the dated outcome addendum records the completed decision._

Status: **completed — rejected and closed 2026-09-07** · Class: `sim/strategies/ew_dd_throttle.py` ·
Sweep grid: `dd_throttle` · Cadence: **monthly** (matching `ew_benchmark`).

## Outcome addendum — 2026-09-07

The six-cell, 10-fold sweep rejects this candidate under its pre-registered first
gate. The best-returning cell had **-6.71% median excess**, beat EW in **30%** of
folds, and reached a **-36.47%** worst drawdown versus EW's **-37.54%**. That is
only 1.07 percentage points of relief, far short of the required 8 points. Some
full-exit cells reduced drawdown more, but paid median excess losses of roughly
13% and therefore failed the return-cost gate. No book was registered; do not
resweep nearby thresholds on this evidence set.

## Hypothesis

`ew_benchmark`'s -36.5% to -37.5% worst-fold drawdown is the only weakness the
10-fold evidence has found in it. This book attacks it with the crudest
available instrument — the book's own equity curve.

Track the equity peak. When equity is more than `dd_trigger` below the peak, cut
gross exposure to `derisk_frac`, with the remainder in BIL. Restore to full when
equity recovers to within `dd_restore` of the peak. The gap between the two
thresholds is hysteresis and is the whole reason the rule takes two numbers.

## What changes vs `ew_benchmark`, and only that

Exactly one thing: **gross exposure, as a function of the book's own drawdown**.
Same screen, same basket, same equal weights, same monthly cadence.

## Why this is not `momo_stopped`

`momo_stopped` is a **per-name** stop and it has already been answered: the
2026-08-20 `momo_stop` sweep put **all nine** of its parameter cells at negative
median excess vs `ew_benchmark`, best `n-20__stop_frac-0.9` at **-3.19%**,
beating EW in 30% of folds. The BUILDLOG's conclusion was that the rule does not
clear the screen, not that it is badly parameterised.

That result says nothing about a **portfolio-level** stop, and the reason is
mechanical. A screen drawdown is a market drawdown: the names fall together, so
stopping out of each one individually just re-buys the same aggregate exposure
at the next rebalance. Only a book-level rule can reduce aggregate exposure, and
no book-level rule has been tested here.

## Expectation — and the prior is NEGATIVE, in writing

**Path-dependent de-risking rules usually whipsaw and lose more to re-entry than
they save.** A book that sells 15% below its peak and buys back 5% below it has,
by construction, sold low and bought higher on every round trip that does not
become a real bear market. The V-shaped drawdowns in this sample (2020-03,
2025-04) are precisely the shape that punishes it most: the trigger fires near
the low and the restore fires after the rebound has already happened.

The store already has one data point in this direction. `ew_trend_gated`, the
other path-dependent rule here, gave up **23pp of return for 0.1pp of drawdown
relief** on its first fold.

**This book is a TEST of that prior, not a bet against it.** The most likely
outcome — and a completely acceptable one — is that it confirms the prior and
the store stops proposing equity-curve stops. That is a result worth the compute.

**The positive case, if it exists.** A drawdown throttle only earns its keep in
a long grinding decline where a slow signal has time to be right (2015-16,
2018Q4, 2022). If the walk-forward shows drawdown relief concentrated in exactly
those folds and whipsaw losses concentrated in the V-shaped ones, that is an
informative shape even if the median excess is negative — but a negative median
excess is still a kill under the criterion below, because "informative" is not
"promotable".

**Expected mechanical asymmetry.** `derisk_frac = 0.0` (full exit) should show
larger drawdown relief and larger whipsaw cost than `derisk_frac = 0.5`. If it
does not, something is wrong with the implementation rather than with the rule,
and the run should be treated as suspect.

## Comparison

Always against **`ew_benchmark`** on identical folds and the identical universe.
Never against SPY. Primary statistic: **median excess validate return** over the
10-fold protocol, with beat-rate and worst-fold drawdown alongside. Trial count
quoted with every number.

## Kill criterion

Kill (do not promote; if promoted, retire) if **any** of:

1. Over the 10-fold walk-forward no cell improves worst-fold drawdown vs
   `ew_benchmark` by at least **8 percentage points**. The bar is set higher
   than the sibling candidates' 5pp on purpose: this is the bluntest of the
   three rules and the one with the worst prior, so it has to earn more to be
   worth the path dependence it introduces.
2. It buys that relief at more than **10pp of median excess return** vs
   `ew_benchmark` — the `ew_trend_gated` failure shape.
3. Median excess is negative in the best cell AND the beat rate is under 40%.
4. Any fold returns `status: "inert"`.

## Implementation notes that belong in the pre-registration

- **The throttle state is re-derived from `sim_equity` on every call**, strictly
  `date <= as_of`, never cached on the portfolio and never inferred from "does
  the book currently hold BIL". Inferring from holdings would need a magic
  BIL-weight threshold and would behave differently at `derisk_frac = 0.0` and
  `0.5`; caching would put strategy state somewhere the walk-forward does not
  reset between folds.
- **The peak is the book's own peak within the current window**, not a market
  peak, and it does not carry across folds — each fold re-creates the book with
  fresh cash and a fresh peak. A fold inherits no state.
- **No equity history is not a drawdown.** The state machine starts un-throttled
  at the first equity row. Nothing is imputed.
- Infeasible configs raise rather than run a different rule quietly:
  `dd_restore >= dd_trigger` (no hysteresis band), `derisk_frac` outside [0, 1],
  `dd_trigger <= 0`.
- `dd_restore` is fixed at 0.05 in the grid rather than swept. A third axis
  would triple the trial count that every result is then deflated against.
