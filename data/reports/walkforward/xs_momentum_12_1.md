# XS Momentum 12-1 (unscreened control) — walk-forward re-validation

_`xs_momentum_12_1` · xs_momentum_12_1 · monthly cadence · verdict **PASS** · generated 2026-09-13T07:07:03+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-09-11. Each fold is an independent replay starting at $39,000. Span 2014-09-11 → 2026-09-11 (3018 sessions); data floor 1994-01-27; screen source `not-used`.

**Provenance.** Source `2a45f846b7a4628661c4539adf71074377c529a450c90cb07cd4125aafed7d75`; config `fb5a0f0e3472f14ed9b0a5d5bac05a081ec0284f200db91663b11d5d47ab9214`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `039bd02c7cdb5678f28e5cf93098393c7e695625c4fc37fc5281d2e8e19fa80e`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Market-beating in trending years with deep momentum crashes (2009-style, 2020-11, 2022). If the screen adds value beyond momentum, ew_benchmark beats this book on median excess AND drawdown across the 10 folds; the honest prior is that most of ew_benchmark's edge is plain momentum and the two are INDISTINGUISHABLE.

**Pre-registered kill criterion.** Control: retired only once its question is answered. Kill if ew_benchmark beats it in >= 70% of walk-forward folds with a 90% CI on median excess that excludes 0 AND a lower worst-fold drawdown (screen shown to add value), or if any fold is inert, or if live max drawdown exceeds 55%.

**Measured against `ew_benchmark` on the same folds:** beats it in 90% of 10 window(s), mean excess +5.51%, latest +15.42% → **PASS**.

**90% CI on mean excess vs `ew_benchmark`:** [−6.62%, +13.54%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-09-11→2016-09-09 | +21.80% | +10.38% | 2016-09-09→2017-09-11 | **+20.29%** | +20.18% | +21.92% | +0.95 | −10.91% | +1.80% | · | 657 | 2,743 |
| 2 | 2015-09-11→2017-09-11 | +36.50% | +16.82% | 2017-09-11→2018-09-11 | **+52.52%** | +52.57% | +21.89% | +2.04 | −12.46% | +9.27% | · | 644 | 2,891 |
| 3 | 2016-09-12→2018-09-11 | +79.97% | +34.23% | 2018-09-11→2019-09-11 | **+0.00%** | +0.00% | +30.10% | +0.15 | −34.32% | +13.41% | · | 664 | 3,000 |
| 4 | 2017-09-11→2019-09-11 | +49.61% | +22.33% | 2019-09-11→2020-09-11 | **+48.62%** | +48.50% | +41.29% | +1.17 | −42.92% | +16.23% | · | 697 | 3,125 |
| 5 | 2018-09-11→2020-09-11 | +44.69% | +20.27% | 2020-09-11→2021-09-10 | **+93.18%** | +93.62% | +45.02% | +1.69 | −33.15% | −52.68% | · | 712 | 3,380 |
| 6 | 2019-09-11→2021-09-10 | +206.36% | +75.10% | 2021-09-10→2022-09-09 | **−5.01%** | −5.03% | +40.01% | +0.07 | −35.22% | +6.65% | · | 693 | 3,538 |
| 7 | 2020-09-11→2022-09-09 | +66.94% | +29.32% | 2022-09-09→2023-09-11 | **+13.23%** | +13.16% | +27.67% | +0.59 | −19.37% | +14.02% | · | 701 | 3,645 |
| 8 | 2021-09-13→2023-09-11 | +12.51% | +6.09% | 2023-09-11→2024-09-11 | **+21.14%** | +21.10% | +32.20% | +0.76 | −18.41% | +14.60% | · | 690 | 3,820 |
| 9 | 2022-09-12→2024-09-11 | +52.88% | +23.66% | 2024-09-11→2025-09-11 | **+40.77%** | +40.80% | +47.39% | +0.96 | −38.58% | +16.32% | · | 734 | 4,023 |
| 10 ◈ | 2023-09-11→2025-09-11 | +79.15% | +33.82% | 2025-09-11→2026-09-11 | **+35.60%** | +35.63% | +52.03% | +0.85 | −31.64% | +15.42% | · | 738 | 12,517 |

## Summary

* validate windows: **10**, win rate **90%**
* mean validate return **+32.03%** (median +28.37%, worst −5.01%, best +93.18%)
* mean validate CAGR **+32.05%** vs mean train CAGR +27.20% → decay **+4.85%**
* mean validate Sharpe +0.92, worst validate max drawdown −42.92%
* 6930 fill(s) inside validate windows
* runtime 1976.9s (scratch 28.7s, screen 0.0s)

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

