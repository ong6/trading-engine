# EW Screen — Inverse-Vol Weighted — walk-forward re-validation

_`ew_voltarget` · ew_voltarget · monthly cadence · verdict **WATCH** · generated 2026-08-30T06:48:44+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-08-28. Each fold is an independent replay starting at $39,000. Span 2014-08-28 → 2026-08-28 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,106,099 passing rows).

**Pre-registered expectation.** Lower drawdown and lower volatility than ew_benchmark at a small CAGR toll, because the screen's worst drawdowns are driven by its highest-vol names. The honest prior is that inverse-vol weighting mostly re-expresses a low-vol tilt, and low_vol already trails EW by -19.95% mean excess.

**Pre-registered kill criterion.** Fails to reduce max drawdown vs ew_benchmark across a full risk-off fold, or trails ew_benchmark by >10% cumulative over 12 months without a lower max drawdown.

**Measured against `ew_benchmark` on the same folds:** beats it in 50% of 10 window(s), mean excess −2.29%, latest −1.34% → **WATCH**.

**90% CI on mean excess vs `ew_benchmark`:** [−7.40%, +1.97%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-08-28→2016-08-26 | −2.03% | −1.02% | 2016-08-26→2017-08-28 | **+8.47%** | +8.43% | +19.78% | +0.51 | −9.90% | +0.14% | −5.67% | 824 | 2,684 |
| 2 | 2015-08-28→2017-08-28 | +6.34% | +3.12% | 2017-08-28→2018-08-28 | **+38.35%** | +38.38% | +22.04% | +1.58 | −15.71% | −4.42% | +18.60% | 774 | 2,827 |
| 3 | 2016-08-29→2018-08-28 | +55.21% | +24.64% | 2018-08-28→2019-08-28 | **−2.79%** | −2.79% | +23.02% | −0.01 | −28.83% | −3.30% | −4.26% | 869 | 2,933 |
| 4 | 2017-08-28→2019-08-28 | +29.71% | +13.90% | 2019-08-28→2020-08-28 | **+19.44%** | +19.39% | +34.72% | +0.69 | −35.39% | −5.42% | −3.00% | 879 | 3,049 |
| 5 | 2018-08-28→2020-08-28 | +14.07% | +6.80% | 2020-08-28→2021-08-27 | **+101.40%** | +101.88% | +39.09% | +2.00 | −22.02% | −26.92% | +72.30% | 857 | 3,294 |
| 6 | 2019-08-28→2021-08-27 | +141.95% | +55.59% | 2021-08-27→2022-08-26 | **−7.64%** | −7.67% | +35.35% | −0.05 | −31.60% | +0.50% | +0.79% | 916 | 3,438 |
| 7 | 2020-08-28→2022-08-26 | +81.35% | +34.80% | 2022-08-26→2023-08-28 | **−4.69%** | −4.67% | +24.06% | −0.08 | −13.88% | +3.75% | −15.24% | 893 | 3,552 |
| 8 | 2021-08-30→2023-08-28 | −11.97% | −6.20% | 2023-08-28→2024-08-28 | **+23.34%** | +23.29% | +28.79% | +0.87 | −18.02% | +8.64% | −3.54% | 872 | 3,713 |
| 9 | 2022-08-29→2024-08-28 | +22.59% | +10.73% | 2024-08-28→2025-08-28 | **+26.76%** | +26.78% | +33.26% | +0.89 | −30.17% | +5.49% | +9.66% | 880 | 3,905 |
| 10 ◈ | 2023-08-28→2025-08-28 | +46.22% | +20.90% | 2025-08-28→2026-08-28 | **+26.26%** | +26.28% | +51.66% | +0.71 | −31.74% | −1.34% | +6.96% | 905 | 12,105 |

## Summary

* validate windows: **10**, win rate **70%**
* mean validate return **+22.89%** (median +21.39%, worst −7.64%, best +101.40%)
* mean validate CAGR **+22.93%** vs mean train CAGR +16.33% → decay **+6.60%**
* mean validate Sharpe +0.71, worst validate max drawdown −35.39%
* 8669 fill(s) inside validate windows
* runtime 1879.5s (scratch 22.8s, screen 23.9s)

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

