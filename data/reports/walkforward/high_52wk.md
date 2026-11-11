# 52-Week-High Momentum — walk-forward re-validation

_`high_52wk` · high_52wk · monthly cadence · verdict **WATCH** · generated 2026-11-08T07:12:25+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-11-06. Each fold is an independent replay starting at $39,000. Span 2014-11-06 → 2026-11-06 (3018 sessions); data floor 1994-01-27; screen source `not-used`.

**Provenance.** Source `75fea67fdebd95883443c0460a9f95d28a006d58d3a56c88f605331b7341dd7c`; config `6ebb24fa08f9b55336dc09c420472115e02f35f86e15d1fed1c19e957f073410`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `c7bbed27906c224c92972a34ced3c497680e5cf2c30c01cc0c0c3fc25d714289`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Momentum-like returns without the long-run reversal that dogs raw RS ranking, and lower churn than the RS books.

**Pre-registered kill criterion.** Trails ew_benchmark by >15% over any rolling 6 months, or max drawdown exceeds 35%.

**Measured against `ew_benchmark` on the same folds:** beats it in 40% of 10 window(s), mean excess −14.58%, latest +14.86% → **WATCH**.

**90% CI on mean excess vs `ew_benchmark`:** [−33.75%, +0.74%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
   lose money.** That is WHY the headline comparison for single-name books is
   **vs EW (same universe, same screen), fold by fold** — the bias is largely
   common to both sides of that difference. Newly generated ETF/asset-allocation
   artifacts declare SPY as their comparison. Absolute return is context, not evidence, and a fold
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
7. **An undefined statistic is `null` in the result file and `·` here.** A
   window with fewer than two returns or zero return volatility (a book that sat
   in cash) has no Sharpe, and one with fewer than two month-ends has no worst
   month. Result files are strict JSON: never NaN, infinity or a stand-in zero.


## Folds

| Fold | Train window | Train ret | Train CAGR | Validate window | Validate ret | CAGR | Vol | Sharpe | Max DD | vs EW | vs SPY | Fills | Universe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2014-11-06→2016-11-04 | −19.82% | −10.47% | 2016-11-04→2017-11-06 | **+24.46%** | +24.33% | +8.32% | +2.67 | −3.02% | −8.22% | · | 490 | 2,838 |
| 2 | 2015-11-06→2017-11-06 | +1.43% | +0.71% | 2017-11-06→2018-11-06 | **−7.08%** | −7.09% | +13.00% | −0.50 | −13.44% | −18.81% | · | 498 | 2,989 |
| 3 | 2016-11-07→2018-11-06 | +5.51% | +2.72% | 2018-11-06→2019-11-06 | **+4.35%** | +4.35% | +10.55% | +0.46 | −10.98% | +5.25% | · | 457 | 3,112 |
| 4 | 2017-11-06→2019-11-06 | −3.81% | −1.93% | 2019-11-06→2020-11-06 | **+22.54%** | +22.48% | +26.26% | +0.90 | −31.15% | −39.66% | · | 479 | 3,258 |
| 5 | 2018-11-06→2020-11-06 | +25.17% | +11.87% | 2020-11-06→2021-11-05 | **+27.32%** | +27.42% | +16.58% | +1.55 | −10.27% | −104.23% | · | 535 | 3,519 |
| 6 | 2019-11-06→2021-11-05 | +54.18% | +24.19% | 2021-11-05→2022-11-04 | **−7.53%** | −7.55% | +17.50% | −0.36 | −20.47% | +13.72% | · | 493 | 3,659 |
| 7 | 2020-11-06→2022-11-04 | +15.17% | +7.34% | 2022-11-04→2023-11-06 | **−14.71%** | −14.65% | +18.98% | −0.75 | −24.90% | −1.94% | · | 524 | 3,792 |
| 8 | 2021-11-08→2023-11-06 | −17.64% | −9.28% | 2023-11-06→2024-11-06 | **+28.93%** | +28.86% | +12.07% | +2.17 | −6.55% | −12.40% | · | 532 | 3,970 |
| 9 | 2022-11-07→2024-11-06 | +7.53% | +3.70% | 2024-11-06→2025-11-06 | **+20.29%** | +20.31% | +13.75% | +1.42 | −8.47% | +5.66% | · | 530 | 4,195 |
| 10 ◈ | 2023-11-06→2025-11-06 | +53.20% | +23.75% | 2025-11-06→2026-11-06 | **+9.47%** | +9.48% | +15.49% | +0.66 | −11.45% | +14.86% | · | 533 | 12,755 |

## Summary

* validate windows: **10**, win rate **70%**
* mean validate return **+10.80%** (median +14.88%, worst −14.71%, best +28.93%)
* mean validate CAGR **+10.80%** vs mean train CAGR +5.26% → decay **+5.53%**
* mean validate Sharpe +0.82, worst validate max drawdown −31.15%
* 5071 fill(s) inside validate windows
* runtime 4329.4s (scratch 9.5s, screen 0.0s)

**Verdict rule (mechanical exploratory triage, NOT an automatic kill).** For
each book, against the versioned comparison declared in its result artifact:

* **PASS** — beats its control in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails its control.

REVIEW means the book goes on the Sunday review agenda against its own frozen
kill criterion (printed on its page). The prose criterion decides; this flag
only decides what gets read. Historical comparator choices are exploratory,
not proof of pre-registration or positive edge. Benchmarks are not judged.


**The interval is new information, not a new rule (added 2026-08-20).** The
PASS / WATCH / REVIEW rule reads the beat rate and the *mean* excess; the
interval does not soften or override that triage label. It is the **90%
bootstrap CI on mean excess vs the declared control** in the column beside it, and a
mechanical `INDISTINGUISHABLE` label for any book whose interval contains 0.

Read the two together: a **PASS whose interval straddles zero is a PASS on a
number this evidence cannot separate from the control**, and a REVIEW whose
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

