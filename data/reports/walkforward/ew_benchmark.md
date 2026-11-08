# Equal-Weight Benchmark — walk-forward re-validation

_`ew_benchmark` · ew_benchmark · monthly cadence · verdict **reference** · generated 2026-11-08T07:34:33+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-11-06. Each fold is an independent replay starting at $39,000. Span 2014-11-06 → 2026-11-06 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,133,551 passing rows).

**Provenance.** Source `75fea67fdebd95883443c0460a9f95d28a006d58d3a56c88f605331b7341dd7c`; config `692d49494298d2e840c98ab78cb8e4a4829516b6049d7d24253eb3e28fe1318e`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `c7bbed27906c224c92972a34ced3c497680e5cf2c30c01cc0c0c3fc25d714289`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Captures the screen's breadth; the bar every active strategy must clear.

**Pre-registered kill criterion.** Reference benchmark — not killed.

**Reference benchmark.** This book is a control and receives no relative verdict.

**Relative confidence interval:** not applicable to a reference benchmark.

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
| 1 | 2014-11-06→2016-11-04 | −11.36% | −5.86% | 2016-11-04→2017-11-06 | **+32.67%** | +32.50% | +19.78% | +1.53 | −8.11% | +0.00% | · | 686 | 2,838 |
| 2 | 2015-11-06→2017-11-06 | +12.78% | +6.19% | 2017-11-06→2018-11-06 | **+11.73%** | +11.74% | +26.54% | +0.55 | −22.42% | +0.00% | · | 767 | 2,989 |
| 3 | 2016-11-07→2018-11-06 | +33.50% | +15.58% | 2018-11-06→2019-11-06 | **−0.90%** | −0.90% | +22.11% | +0.07 | −20.09% | +0.00% | · | 814 | 3,112 |
| 4 | 2017-11-06→2019-11-06 | +8.60% | +4.21% | 2019-11-06→2020-11-06 | **+62.20%** | +62.04% | +40.57% | +1.39 | −38.78% | +0.00% | · | 824 | 3,258 |
| 5 | 2018-11-06→2020-11-06 | +57.62% | +25.53% | 2020-11-06→2021-11-05 | **+131.55%** | +132.22% | +42.06% | +2.22 | −23.32% | +0.00% | · | 865 | 3,519 |
| 6 | 2019-11-06→2021-11-05 | +249.76% | +87.10% | 2021-11-05→2022-11-04 | **−21.25%** | −21.31% | +37.02% | −0.46 | −34.29% | +0.00% | · | 920 | 3,659 |
| 7 | 2020-11-06→2022-11-04 | +66.19% | +29.03% | 2022-11-04→2023-11-06 | **−12.78%** | −12.72% | +25.33% | −0.42 | −22.75% | +0.00% | · | 844 | 3,792 |
| 8 | 2021-11-08→2023-11-06 | −24.33% | −13.05% | 2023-11-06→2024-11-06 | **+41.34%** | +41.24% | +31.66% | +1.25 | −20.31% | +0.00% | · | 790 | 3,970 |
| 9 | 2022-11-07→2024-11-06 | +22.05% | +10.48% | 2024-11-06→2025-11-06 | **+14.63%** | +14.64% | +40.19% | +0.54 | −35.13% | +0.00% | · | 874 | 4,195 |
| 10 ◈ | 2023-11-06→2025-11-06 | +58.48% | +25.87% | 2025-11-06→2026-11-06 | **−5.39%** | −5.39% | +55.17% | +0.18 | −40.14% | +0.00% | · | 911 | 12,755 |

## Summary

* validate windows: **10**, win rate **60%**
* mean validate return **+25.38%** (median +13.18%, worst −21.25%, best +131.55%)
* mean validate CAGR **+25.40%** vs mean train CAGR +18.51% → decay **+6.90%**
* mean validate Sharpe +0.69, worst validate max drawdown −40.14%
* 8295 fill(s) inside validate windows
* runtime 5649.2s (scratch 1.5s, screen 26.2s)

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

