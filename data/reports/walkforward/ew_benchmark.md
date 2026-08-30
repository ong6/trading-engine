# Equal-Weight Benchmark — walk-forward re-validation

_`ew_benchmark` · ew_benchmark · monthly cadence · verdict **reference** · generated 2026-08-30T06:47:11+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-08-28. Each fold is an independent replay starting at $39,000. Span 2014-08-28 → 2026-08-28 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,106,099 passing rows).

**Pre-registered expectation.** Captures the screen's breadth; the bar every active strategy must clear.

**Pre-registered kill criterion.** Reference benchmark — not killed.

**Measured against `ew_benchmark` on the same folds:** beats it in 0% of 10 window(s), mean excess +0.00%, latest +0.00% → **reference**.

**90% CI on mean excess vs `ew_benchmark`:** [+0.00%, +0.00%] → —. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-08-28→2016-08-26 | −1.37% | −0.69% | 2016-08-26→2017-08-28 | **+8.33%** | +8.29% | +21.01% | +0.49 | −11.00% | +0.00% | −5.80% | 771 | 2,684 |
| 2 | 2015-08-28→2017-08-28 | +6.61% | +3.25% | 2017-08-28→2018-08-28 | **+42.77%** | +42.81% | +22.73% | +1.68 | −15.47% | +0.00% | +23.02% | 701 | 2,827 |
| 3 | 2016-08-29→2018-08-28 | +62.14% | +27.40% | 2018-08-28→2019-08-28 | **+0.51%** | +0.51% | +24.70% | +0.14 | −30.74% | +0.00% | −0.96% | 821 | 2,933 |
| 4 | 2017-08-28→2019-08-28 | +37.91% | +17.45% | 2019-08-28→2020-08-28 | **+24.86%** | +24.80% | +36.60% | +0.79 | −37.54% | +0.00% | +2.42% | 853 | 3,049 |
| 5 | 2018-08-28→2020-08-28 | +22.89% | +10.85% | 2020-08-28→2021-08-27 | **+128.32%** | +128.96% | +44.00% | +2.11 | −22.59% | +0.00% | +99.22% | 851 | 3,294 |
| 6 | 2019-08-28→2021-08-27 | +187.40% | +69.59% | 2021-08-27→2022-08-26 | **−8.14%** | −8.17% | +36.79% | −0.05 | −34.16% | +0.00% | +0.29% | 887 | 3,438 |
| 7 | 2020-08-28→2022-08-26 | +105.57% | +43.56% | 2022-08-26→2023-08-28 | **−8.44%** | −8.40% | +25.70% | −0.22 | −17.10% | +0.00% | −18.99% | 860 | 3,552 |
| 8 | 2021-08-30→2023-08-28 | −15.71% | −8.22% | 2023-08-28→2024-08-28 | **+14.70%** | +14.67% | +30.97% | +0.60 | −20.55% | +0.00% | −12.18% | 829 | 3,713 |
| 9 | 2022-08-29→2024-08-28 | +10.47% | +5.11% | 2024-08-28→2025-08-28 | **+21.27%** | +21.29% | +36.99% | +0.71 | −33.30% | +0.00% | +4.17% | 849 | 3,905 |
| 10 ◈ | 2023-08-28→2025-08-28 | +29.63% | +13.85% | 2025-08-28→2026-08-28 | **+27.60%** | +27.62% | +56.20% | +0.72 | −36.48% | +0.00% | +8.30% | 910 | 12,105 |

## Summary

* validate windows: **10**, win rate **80%**
* mean validate return **+25.18%** (median +17.98%, worst −8.44%, best +128.32%)
* mean validate CAGR **+25.24%** vs mean train CAGR +18.21% → decay **+7.02%**
* mean validate Sharpe +0.70, worst validate max drawdown −37.54%
* 8332 fill(s) inside validate windows
* runtime 1794.1s (scratch 20.5s, screen 23.8s)

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

