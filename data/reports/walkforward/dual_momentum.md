# Dual Momentum (GEM) — walk-forward re-validation

_`dual_momentum` · dual_momentum · monthly cadence · verdict **REVIEW** · generated 2026-08-30T06:08:04+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-08-28. Each fold is an independent replay starting at $39,000. Span 2014-08-28 → 2026-08-28 (3018 sessions); data floor 2008-05-29; screen source `not-used`.

**Pre-registered expectation.** Lower drawdown than buy-and-hold via the cash switch; lags in strong bull runs.

**Pre-registered kill criterion.** Underperforms spy_benchmark by >20% over 2 years while not delivering a lower max drawdown.

**Measured against `ew_benchmark` on the same folds:** beats it in 40% of 10 window(s), mean excess −15.57%, latest −4.51% → **REVIEW**.

**90% CI on mean excess vs `ew_benchmark`:** [−32.50%, −1.92%] → **distinguishable −**. The verdict above is unchanged by this interval — see the note below the fold table.

## Disclosures — read before any number below

1. **Survivor universe, and it is NOT a constant.** `prices` holds only tickers
   listed TODAY, so every name delisted, acquired or bankrupted inside a fold is
   absent entirely. The house lesson has priced this at roughly **+7pp/yr of fake
   return** for a screen-driven book — but that flat figure is wrong in SHAPE, and
   the `Universe` column on every fold table below exists to show it. Measured
   2026-08-20 against World Bank listed-company counts, the store covers
   **~11% of the companies that existed in 1996, ~24% in 2003 and ~42% in 2014**
   (ex-ETF). The bias therefore grows monotonically as a window moves back, and an
   early fold rests on a thinner, more winner-selected cross-section than a late
   one. Not one 2008 casualty is present: LEH, BSC, ENE, WCOM, CFC, MER, SIVB and
   FRC are all absent, so **a fold spanning 2008 is one in which those names cannot
   lose money.** That is WHY the headline comparison here is **vs EW (same
   universe, same screen), fold by fold** — the bias is largely common to both
   sides of that difference. Absolute return is context, not evidence, and a fold
   with a small `Universe` count deserves proportionally less weight.
2. **Out-of-sample in the DATA, not in the RULE.** Each validate window is data
   the preceding train window never saw, and nothing is fitted anywhere in this
   workload (see D-WF5). But these books were written by a human who has lived
   through this market, so a validate window from 2021 is not evidence the rule
   would have been *chosen* in 2020. **The league's live forward record remains
   the only true out-of-sample evidence.** This report answers a narrower and
   still useful question: *is the rule behaving now the way it behaved on the
   sessions immediately before, and against the same benchmark?*
3. **`low_vol` uses TODAY's fundamentals snapshot.** No historical market caps
   exist (first snapshot 2026-07-18), so its "$5B+" filter is the current cap
   list restamped to the window start — a static-cap look-ahead, disclosed.
4. **The newest validate window overlaps the live league.** The anchor is the
   latest session in the store (D-WF3), and the league went live
   2026-07-17. Sessions after that date are a *shadow* of the
   live book — the same rule re-run on the same bars — not independent evidence.
   The overlap is a few weeks against a 12-month window today, and it is
   labelled per fold below.
5. **Every fold restarts at the reference notional** (D-WF2), so folds are
   comparable to each other and a book cannot be flattered or crippled by what
   an account did years earlier. Fold returns therefore do NOT compound into
   the multi-year number a single continuous replay would give — that number is
   the historical-backtest farm's job (`data/reports/backtests/`).
6. **Books that cannot be replayed are absent, not zero.** See the exclusions
   list at the bottom. Nothing is faked to fill a row.


## Folds

| Fold | Train window | Train ret | Train CAGR | Validate window | Validate ret | CAGR | Vol | Sharpe | Max DD | vs EW | vs SPY | Fills | Universe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2014-08-28→2016-08-26 | −3.10% | −1.57% | 2016-08-26→2017-08-28 | **+16.65%** | +16.57% | +8.24% | +1.91 | −4.31% | +8.32% | +2.52% | 6 | 2,684 |
| 2 | 2015-08-28→2017-08-28 | +15.34% | +7.39% | 2017-08-28→2018-08-28 | **+12.95%** | +12.96% | +10.75% | +1.19 | −9.71% | −29.82% | −6.80% | 4 | 2,827 |
| 3 | 2016-08-29→2018-08-28 | +31.58% | +14.74% | 2018-08-28→2019-08-28 | **−11.06%** | −11.07% | +15.54% | −0.68 | −19.33% | −11.57% | −12.53% | 5 | 2,933 |
| 4 | 2017-08-28→2019-08-28 | −0.24% | −0.12% | 2019-08-28→2020-08-28 | **+0.86%** | +0.86% | +29.47% | +0.18 | −33.69% | −23.99% | −21.57% | 5 | 3,049 |
| 5 | 2018-08-28→2020-08-28 | −10.36% | −5.32% | 2020-08-28→2021-08-27 | **+30.31%** | +30.43% | +14.86% | +1.86 | −9.43% | −98.00% | +1.22% | 4 | 3,294 |
| 6 | 2019-08-28→2021-08-27 | +30.53% | +14.26% | 2021-08-27→2022-08-26 | **−6.98%** | −7.01% | +17.52% | −0.33 | −18.23% | +1.16% | +1.45% | 4 | 3,438 |
| 7 | 2020-08-28→2022-08-26 | +21.22% | +10.14% | 2022-08-26→2023-08-28 | **−4.85%** | −4.83% | +5.69% | −0.85 | −6.64% | +3.59% | −15.40% | 5 | 3,552 |
| 8 | 2021-08-30→2023-08-28 | −12.04% | −6.23% | 2023-08-28→2024-08-28 | **+25.96%** | +25.90% | +12.50% | +1.91 | −8.41% | +11.26% | −0.92% | 6 | 3,713 |
| 9 | 2022-08-29→2024-08-28 | +19.84% | +9.48% | 2024-08-28→2025-08-28 | **+9.17%** | +9.18% | +19.76% | +0.55 | −18.75% | −12.10% | −7.93% | 9 | 3,905 |
| 10 ◈ | 2023-08-28→2025-08-28 | +35.14% | +16.24% | 2025-08-28→2026-08-28 | **+23.09%** | +23.11% | +14.84% | +1.48 | −11.42% | −4.51% | +3.79% | 11 | 12,105 |

## Summary

* validate windows: **10**, win rate **70%**
* mean validate return **+9.61%** (median +11.06%, worst −11.06%, best +30.31%)
* mean validate CAGR **+9.61%** vs mean train CAGR +5.90% → decay **+3.71%**
* mean validate Sharpe +0.72, worst validate max drawdown −33.69%
* 59 fill(s) inside validate windows
* runtime 481.0s (scratch 19.1s, screen 0.0s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.


**The interval is new information, not a new rule (added 2026-08-20).** The
PASS / WATCH / REVIEW rule above is unchanged: it still reads the beat rate and
the *mean* excess exactly as it was pre-registered, and no verdict in this
report has been recomputed, softened or overridden by an interval. What is new
is the **90% bootstrap CI on mean excess vs EW** in the column beside it, and a
mechanical `INDISTINGUISHABLE` label for any book whose interval contains 0.

Read the two together: a **PASS whose interval straddles zero is a PASS on a
number this evidence cannot separate from the benchmark**, and a REVIEW whose
interval straddles zero is not proof the book is broken either. The verdict says
what gets read on Sunday. The interval says how much the number underneath it
is worth.

**Method.** Percentile bootstrap over FOLDS, 10,000 resamples, fixed seed
`20260820` so the report re-renders identically from unchanged inputs. Folds are
the resampling unit because each is an independent replay from the reference
notional (D-WF2) over a validate window no other fold's validate window touches
(D-WF1). Folds with status other than `ok` — including `inert`, a book that
placed zero fills — are excluded before resampling; an inert fold is not
evidence. Fewer than 3 comparable folds gets **no interval**, printed as
`·`, never a zero.

**Caveat that cuts against us.** Adjacent folds share twelve months of TRAIN
window (train 24mo, step 12mo) and all folds come from one market history, so an
i.i.d. bootstrap UNDERSTATES the true uncertainty. These intervals are a floor
on the error bar. At 10 folds the bootstrap can reject a large effect and cannot
confirm a small one; methods that could (block or stationary bootstrap) need a
fold count in the high tens and are deliberately not used here.

