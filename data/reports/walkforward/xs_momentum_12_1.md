# XS Momentum 12-1 (unscreened control) — walk-forward re-validation

_`xs_momentum_12_1` · xs_momentum_12_1 · monthly cadence · verdict **PASS** · generated 2026-10-05T17:37:21+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-10-02. Each fold is an independent replay starting at $39,000. Span 2014-10-02 → 2026-10-02 (3018 sessions); data floor 1994-01-27; screen source `not-used`.

**Provenance.** Source `e533fb3b2cbb71a883fdb88ff4af0b6257676575c4e7bc0bfb80df4cf0373c4e`; config `fb5a0f0e3472f14ed9b0a5d5bac05a081ec0284f200db91663b11d5d47ab9214`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `0affd34308e8ca5132398cb1f228225beb8f46edd2d68291a7428c94d2e3fca8`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Market-beating in trending years with deep momentum crashes (2009-style, 2020-11, 2022). If the screen adds value beyond momentum, ew_benchmark beats this book on median excess AND drawdown across the 10 folds; the honest prior is that most of ew_benchmark's edge is plain momentum and the two are INDISTINGUISHABLE.

**Pre-registered kill criterion.** Control: retired only once its question is answered. Kill if ew_benchmark beats it in >= 70% of walk-forward folds with a 90% CI on median excess that excludes 0 AND a lower worst-fold drawdown (screen shown to add value), or if any fold is inert, or if live max drawdown exceeds 55%.

**Measured against `ew_benchmark` on the same folds:** beats it in 90% of 10 window(s), mean excess +7.29%, latest +7.77% → **PASS**.

**90% CI on mean excess vs `ew_benchmark`:** [−2.57%, +14.90%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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


## Folds

| Fold | Train window | Train ret | Train CAGR | Validate window | Validate ret | CAGR | Vol | Sharpe | Max DD | vs EW | vs SPY | Fills | Universe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2014-10-02→2016-09-30 | +27.68% | +13.02% | 2016-09-30→2017-10-02 | **+21.18%** | +21.07% | +21.09% | +1.02 | −9.33% | +4.14% | · | 718 | 2,779 |
| 2 | 2015-10-02→2017-10-02 | +35.78% | +16.51% | 2017-10-02→2018-10-02 | **+40.31%** | +40.35% | +21.86% | +1.66 | −10.96% | +6.99% | · | 656 | 2,931 |
| 3 | 2016-10-03→2018-10-02 | +78.86% | +33.82% | 2018-10-02→2019-10-02 | **−3.06%** | −3.06% | +29.71% | +0.04 | −30.27% | +13.17% | · | 665 | 3,048 |
| 4 | 2017-10-02→2019-10-02 | +38.08% | +17.52% | 2019-10-02→2020-10-02 | **+81.09%** | +80.87% | +42.16% | +1.62 | −42.66% | +18.34% | · | 684 | 3,178 |
| 5 | 2018-10-02→2020-10-02 | +99.06% | +41.05% | 2020-10-02→2021-10-01 | **+76.74%** | +77.08% | +44.96% | +1.50 | −32.68% | −41.18% | · | 713 | 3,441 |
| 6 | 2019-10-02→2021-10-01 | +202.49% | +73.99% | 2021-10-01→2022-09-30 | **−12.89%** | −12.93% | +40.39% | −0.14 | −34.78% | +5.11% | · | 639 | 3,583 |
| 7 | 2020-10-02→2022-09-30 | +56.31% | +25.12% | 2022-09-30→2023-10-02 | **+21.26%** | +21.15% | +25.47% | +0.89 | −15.72% | +22.84% | · | 770 | 3,706 |
| 8 | 2021-10-04→2023-10-02 | −3.47% | −1.76% | 2023-10-02→2024-10-02 | **+39.58%** | +39.49% | +32.26% | +1.20 | −17.90% | +14.96% | · | 685 | 3,874 |
| 9 | 2022-10-03→2024-10-02 | +45.05% | +20.45% | 2024-10-02→2025-10-02 | **+55.35%** | +55.40% | +46.89% | +1.18 | −38.38% | +20.80% | · | 738 | 4,089 |
| 10 ◈ | 2023-10-02→2025-10-02 | +137.56% | +54.08% | 2025-10-02→2026-10-02 | **+17.61%** | +17.62% | +52.57% | +0.57 | −31.42% | +7.77% | · | 743 | 12,643 |

## Summary

* validate windows: **10**, win rate **80%**
* mean validate return **+33.72%** (median +30.42%, worst −12.89%, best +81.09%)
* mean validate CAGR **+33.70%** vs mean train CAGR +29.38% → decay **+4.32%**
* mean validate Sharpe +0.95, worst validate max drawdown −42.66%
* 7011 fill(s) inside validate windows
* runtime 2362.3s (scratch 0.1s, screen 0.0s)

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

