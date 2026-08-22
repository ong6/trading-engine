# Sweep — `gross_voltarget`

_9 candidate(s) · **9 trials** · 10-fold protocol · bootstrap seed 20260820 · generated 2026-08-22 10:50 UTC._

## Read this before the table

**9 of 9 ranked candidate(s) are `INDISTINGUISHABLE` from `ew_benchmark`** — their 90% confidence interval on median excess contains 0, so this evidence does not establish even the SIGN of their edge, let alone its size. That is the headline of this table; the ordering below it is a tie-break among rows most of which are not separated from the benchmark at all.

**Every row here is one of 9 parameter sets tried on the same data.** The best of N trials looks good at N=1 and looks good at N=60 for entirely different reasons, so the top row is NOT a finding — it is the starting point for one, and it has to survive a pre-registered forward test like anything else. Quote this table only with its trial count attached.

Ranked by **median** excess vs `ew_benchmark` on shared folds, not mean: at 6 folds the mean excess of every momentum book was carried entirely by the 2018-2021 window. Excess vs EW (same universe, same screen) is used rather than absolute return because it cancels most of the ~+7pp/yr survivorship inflation in this store.

Benchmark on these folds: median validate **+14.26%**, worst-fold drawdown **-37.54%**.

| Candidate | Distinguishable from EW? | Folds | Median excess | 90% CI on median excess | Mean excess | Beats EW | Worst DD |
|---|---|---|---|---|---|---|---|
| `vol_lookback-40__vol_target-0.2` | **INDISTINGUISHABLE** | 10 | -0.88% | [-6.67%, +4.26%] | -7.12% | 40% | -37.54% |
| `vol_lookback-40__vol_target-0.15` | **INDISTINGUISHABLE** | 10 | -2.49% | [-14.97%, +3.99%] | -10.61% | 40% | -32.82% |
| `vol_lookback-60__vol_target-0.2` | **INDISTINGUISHABLE** | 10 | -2.52% | [-7.22%, +3.31%] | -8.23% | 40% | -37.54% |
| `vol_lookback-120__vol_target-0.2` | **INDISTINGUISHABLE** | 10 | -3.16% | [-8.10%, +3.27%] | -8.51% | 40% | -37.54% |
| `vol_lookback-40__vol_target-0.1` | **INDISTINGUISHABLE** | 10 | -4.19% | [-23.28%, +2.92%] | -14.52% | 40% | -23.28% |
| `vol_lookback-60__vol_target-0.15` | **INDISTINGUISHABLE** | 10 | -4.22% | [-15.18%, +4.13%] | -11.74% | 40% | -36.20% |
| `vol_lookback-120__vol_target-0.15` | **INDISTINGUISHABLE** | 10 | -4.57% | [-16.05%, +2.53%] | -12.13% | 30% | -34.65% |
| `vol_lookback-60__vol_target-0.1` | **INDISTINGUISHABLE** | 10 | -5.58% | [-23.41%, +2.96%] | -15.48% | 40% | -26.48% |
| `vol_lookback-120__vol_target-0.1` | **INDISTINGUISHABLE** | 10 | -5.92% | [-23.61%, +1.99%] | -15.47% | 30% | -23.92% |

## The interval, and what it is not

**Method.** Percentile bootstrap on the fold excesses, 10,000 resamples, seed `20260820` (fixed, so this table re-renders identically from unchanged inputs). The resampling unit is the **fold** — n=10 here — because a fold is one independent replay from the reference notional (D-WF2) over a validate window no other fold's validate window touches (D-WF1). Folds with status other than `ok` — including the `inert` status for a book that placed zero fills — are excluded before resampling; an inert fold is not evidence.

**Verdict rule (pre-registered, mechanical).** If the 90% CI on median excess contains 0, the candidate is `INDISTINGUISHABLE` from `ew_benchmark` — **regardless of where it sits in the ranking**. No discretion, no exceptions for a good-looking point estimate.

**Caveat, stated because it cuts against us.** Adjacent folds share twelve months of TRAIN window (train 24mo, step 12mo), and all folds come from one market history rather than ten independent ones. An i.i.d. bootstrap over overlapping folds therefore UNDERSTATES the true uncertainty: these intervals are a floor on the error bar. That makes an `INDISTINGUISHABLE` verdict stronger than it looks and any distinguishable verdict weaker.

**At n=10 folds this is a crude instrument, and it is the right one.** A percentile bootstrap of a median at n=10 resolves roughly to the gaps between order statistics — it will not separate +0.5% from 0. Methods that would (block bootstrap over fold blocks, a stationary bootstrap, White's Reality Check across the grid) need a fold count in the high tens to mean anything, so they are named here and NOT used. The honest summary of a 10-fold sweep is that it can reject a large effect and cannot confirm a small one.

## Deflated Sharpe — the multiple-testing haircut

Top genuine candidate `vol_lookback-40__vol_target-0.2`, on its **excess-vs-EW** series (10 folds; each fold is a 12-month validate window, so this is already an annual-frequency Sharpe and is NOT rescaled).

| | |
|---|---|
| Raw Sharpe (excess vs EW, per fold) | **-0.365** |
| Trials searched (N) | 9 |
| SR0 — Sharpe the luckiest of 9 zero-skill trials would be expected to show | +0.093 |
| **Deflated Sharpe (DSR) = P(true excess Sharpe > SR0)** | **0.027** |

V in the SR0 formula is the observed variance of the 9 trial excess Sharpes in this grid.

**How to read it.** DSR is a probability, not a Sharpe. Above ~0.95 the top cell's Sharpe is hard to explain as the best of N lucky draws; below that it is not distinguishable from the maximum a zero-skill search of this size produces by construction. Bailey & Lopez de Prado (2014).

**Small-sample warning.** The PSR machinery underneath DSR is a normal approximation whose accuracy comes from the observation count, and there are 10 observations here — not the hundreds the formula was written for. Skew and kurtosis estimated from 10 points are themselves very noisy. Treat this number as a direction-of-travel check on the haircut, not as a test.

**N counts this grid only.** 9 cells were tried here; the store has run more parameter sets than that across all grids, and a reader picking the best cell across grids is searching a larger N than this row is deflated against. The haircut below is therefore a LOWER bound.

## What a good row would look like

Positive median excess AND beats-EW comfortably above 50% AND a worst-fold drawdown no worse than the benchmark's — **and a 90% CI on median excess that stays above 0**. Before 2026-08-20 only the first three were checked, which is how a -3.05% row came to sit at the top of a table as though the position meant something. A row that is positive on median excess but beats EW in under half its folds is a skew bet, not an edge, and the distinction matters more than the headline number.

