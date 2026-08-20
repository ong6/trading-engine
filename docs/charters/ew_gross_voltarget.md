# Charter — `ew_gross_voltarget`

_Pre-registration, 2026-08-20. **Candidate, not a book.** Nothing here creates a
row in `portfolios`. It becomes a league book only if a human promotes it._

Status: **candidate** · Class: `sim/strategies/ew_gross_voltarget.py` ·
Sweep grid: `gross_voltarget` · Cadence: **monthly** (matching `ew_benchmark`,
so any spread is attributable to the rule and not to trading frequency).

## Hypothesis

`ew_benchmark`'s worst-fold drawdown of **-36.5% to -37.5%** is a market
drawdown, not a selection failure. The screen's names are momentum names and
they fall together, so no reweighting *among* them can avoid it. If the
drawdown is to be reduced at all, it has to be reduced by holding **less of the
basket** when the basket itself is volatile.

Concretely: scale gross exposure so the portfolio's realized volatility targets
`vol_target` annualised, estimated from the equal-weighted basket's own daily
returns over `vol_lookback` sessions. `exposure = clamp(vol_target /
realized_vol, 0, max_leverage)`, with `max_leverage = 1.0` — **de-risk only,
never lever**. The remainder is held in BIL, a modelled instrument with a real
price and a real coupon, not in un-modelled cash.

## What changes vs `ew_benchmark`, and only that

Exactly one thing: **gross exposure**. Same screen, same top-`cap` basket, same
equal relative weights, same monthly cadence.

## Why this is not `ew_voltarget`

`ew_voltarget` varies *relative* weights (1/sigma per name) at a constant 100%
gross. Its 10-fold sweep verdict over 6 genuine cells was **+0.02% median
excess** — inverse-vol weighting buys approximately nothing here, which is the
result you would expect if the drawdown is market-wide. This book holds relative
weights flat and varies gross instead. Different mechanism, different
hypothesis, and only one of the two can address a market drawdown. Reading a
result from one as evidence about the other is a category error.

Nothing in this repo — banding, concentration, momo stops, inverse-vol — has
ever varied gross exposure. That is the gap.

## Expectation, including the negative case

**Positive case.** Lower worst-fold drawdown than `ew_benchmark` (target:
materially better than its -37.5%) at a cost in return, because the exposure cut
is a real cut and cannot be free. A book that de-risks into high-vol regimes and
never levers gives up upside by construction. A reasonable success shape is
**5-10pp of drawdown relief for under 5pp of median return give-up**.

**Negative case, and it is genuinely likely.** Realized volatility is a lagging
estimator. In a V-shaped drawdown (2020-03, 2025-04) the vol spike arrives with
the bottom, so the book de-risks near the low and re-risks after the recovery —
it eats the drawdown *and* misses the rebound, which is worse than not acting.
`ew_trend_gated`, the other lagging-signal rule in this store, gave up **23pp of
return for 0.1pp of drawdown relief** on its first fold. There is a real chance
this book lands in the same place, and the honest prior is that the effect is
modest at best.

**Second negative possibility, specific to this data.** Survivorship inflates
every absolute return here by roughly +7pp/yr. A rule that spends time out of
the market gives up disproportionately much of an inflated return, so this book
is measured against `ew_benchmark` on the same folds and universe, never in
absolute terms.

## Comparison

Always against **`ew_benchmark`** on identical folds and the identical universe.
Never against SPY: the vs-SPY column is a universe comparison, not a rule
comparison, and it flatters everything in this store.

Primary statistic: **median excess validate return vs `ew_benchmark`** over the
10-fold protocol, with beat-rate and worst-fold drawdown alongside. Median, not
mean — the mean was hijacked by the 2018-2021 window for every momentum book at
6 folds. The trial count is quoted with every number.

## Kill criterion

Kill (do not promote; if promoted, retire) if **any** of:

1. Over the 10-fold walk-forward it fails to improve worst-fold drawdown vs
   `ew_benchmark` by at least **5 percentage points**. The book's only claim is
   drawdown; a book that does not deliver drawdown relief has no claim left.
2. It buys that drawdown relief at more than **10pp of median excess return**
   vs `ew_benchmark`. That is the `ew_trend_gated` failure shape and it is not
   worth promoting a second instance of.
3. It beats `ew_benchmark` in fewer than **30%** of folds while also showing
   negative median excess — a skew bet with no drawdown payoff is neither.
4. Any fold returns `status: "inert"`. An inert fold is a config defect, not a
   flat return, and it invalidates the run rather than scoring 0%.

## Honesty notes attached to every result from this book

- `max_leverage` is fixed at 1.0 and is **not** a sweep axis. Levering a
  survivorship-biased backtest manufactures return out of a known data defect.
- An unmeasurable volatility (too few usable basket-return days, or a zero /
  non-finite sigma) does **not** produce an exposure. The book holds the plain
  benchmark basket and logs that no exposure decision was taken. `vol_target / 0`
  is a missing measurement, not infinite risk capacity.
- Infeasible configs raise: `min_obs > vol_lookback`, `vol_target <= 0`,
  `max_leverage <= 0`. None of them may reach a report as a number.
