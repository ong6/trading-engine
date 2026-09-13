# Charter — `ew_gross_voltarget`

_Pre-registration, 2026-08-20. The text below preserves the original candidate
hypothesis and gates; the dated outcome addendum records the completed decision._

Status: **completed — `INCONCLUSIVE-LEGACY`, closed 2026-09-07** · Class: `sim/strategies/ew_gross_voltarget.py` ·
Sweep grid: `gross_voltarget` · Cadence: **monthly** (matching `ew_benchmark`,
so any spread is attributable to the rule and not to trading frequency).

## Outcome addendum — 2026-09-07

The superseding matched-control review is
[`../../data/reports/experiments/gross-voltarget-matched-static/README.md`](../../data/reports/experiments/gross-voltarget-matched-static/README.md).
It compares all nine dynamic cells fold-by-fold with the nearest-volatility cell
from the five-cell static-exposure grid. Three 10%-target cells survive the
original permissive kill gates, but **every mean timing-excess 90% interval
contains zero**, no predeclared volatility-slope interval is wholly positive,
and no cell establishes a positive timing edge. The source artifacts use legacy
fill model v2 and lack complete source/data/profile provenance.

The decision is therefore **`INCONCLUSIVE-LEGACY`**, not a positive result and
not a promotion candidate. No book, parameter selection, automatic action, or
new rerun follows from it. Reopening the mechanism requires a new charter and a
prospectively generated, fully provenance-stamped matched cohort.

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

---

## Amendment, 2026-08-20 — the control, and a pre-registered sub-hypothesis

**Why this amendment exists.** The book's first evidence (2 folds) was reported as "worst
validate drawdown −18.22% vs the benchmark's −36.48%", i.e. drawdown halved. An adversarial
audit the same day showed that reading is not supportable: the book ran at `vol_ann`
**17.31% / 17.70%** against the benchmark's **37.02% / 56.24%**, so it held roughly a third
to a half of the benchmark's risk. **Most of the drawdown relief is the arithmetic
consequence of holding less equity and says nothing about whether varying exposure over time
helped.** `ew_static_exposure` was built as the control and run over the same two folds.

| fold (benchmark vol) | book | ret | vol_ann | max DD | ret/vol |
|---|---|---|---|---|---|
| **1** (37.02%) | ew_benchmark | +10.18% | 37.02% | −33.25% | 0.27 |
| | ew_gross_voltarget | +6.15% | 17.31% | −18.22% | 0.36 |
| | **static @ 0.5** | **+8.50%** | 18.41% | −17.42% | **0.46** |
| | static @ 0.3 | +7.08% | 11.06% | −10.62% | 0.64 |
| **2** (56.24%) | ew_benchmark | +43.13% | 56.24% | −36.48% | 0.77 |
| | **ew_gross_voltarget** | **+27.52%** | 17.70% | −11.48% | **1.55** |
| | static @ 0.5 | +26.23% | 27.55% | −18.32% | 0.95 |
| | static @ 0.3 | +17.83% | 16.52% | −10.81% | 1.08 |

**Fold 1 is a loss for this book.** At matched risk (17.31% vs 18.41% vol; −18.22% vs
−17.42% drawdown) the control returned **+8.50% against this book's +6.15%**. The timing
subtracted 2.35pp. **Fold 2 is a clear win**: the same return as `static @ 0.5` (+27.52% vs
+26.23%) at **64% of its volatility** and two thirds of its drawdown.

### Pre-registered sub-hypothesis (written BEFORE the 10-fold grid runs)

**H:** the timing benefit — `ew_gross_voltarget` minus the vol-matched `ew_static_exposure`
cell — is **positively correlated with the fold's benchmark realized volatility**. Vol
targeting should earn its keep when realized vol is high and varying, and cost something
when it is low and stable. The two folds so far are consistent with this (benchmark vol
37.02% → timing −2.35pp; 56.24% → timing strongly positive) and **two points are not
evidence for a correlation** — they are the reason to state the hypothesis before there are
ten.

**Test:** over the 10-fold grid, regress (voltarget − matched static) validate excess on the
fold's `ew_benchmark` `vol_ann`. Report the slope with a bootstrap CI on the same protocol
as everything else.

**Honest negative case, stated because it is likely:** at n=10 the power analysis on this
protocol gives 50% power near +7pp/yr, so a slope of the size implied here will very probably
come back INDISTINGUISHABLE. **That outcome is not a failure of the hypothesis — it is the
evidence ceiling**, and it must be reported as such rather than dressed up either way.

**Comparison rule, superseding the original charter:** this book is judged against
`ew_static_exposure` at the cell whose realized vol is closest to its own, **not** against
`ew_benchmark`. A comparison to `ew_benchmark` measures de-risking plus timing and credits
all of it to the rule under test. Any grid that omits the static control is invalid for
this book.

**Kill criterion, unchanged in spirit and sharpened:** the AGENT-free rule is killed if,
over the 10-fold grid, it fails to beat the vol-matched static control on risk-adjusted
return in at least 50% of folds. Beating `ew_benchmark` is not sufficient and never was.
