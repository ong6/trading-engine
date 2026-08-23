# Template Top 5 — walk-forward re-validation

_`template_top5` · template_top5 · weekly cadence · verdict **WATCH** · generated 2026-08-23T06:33:38+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-08-21. Each fold is an independent replay starting at $39,000. Span 2014-08-21 → 2026-08-21 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,104,935 passing rows).

**Pre-registered expectation.** Concentrated momentum: higher return and higher drawdown than the broad benchmark in risk-on regimes.

**Pre-registered kill criterion.** Trails ew_benchmark by >15% over any rolling 6 months, or max drawdown exceeds 40%.

**Measured against `ew_benchmark` on the same folds:** beats it in 40% of 10 window(s), mean excess +24.39%, latest +47.12% → **WATCH**.

**90% CI on mean excess vs `ew_benchmark`:** [−12.07%, +68.57%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-08-21→2016-08-19 | −32.02% | −17.58% | 2016-08-19→2017-08-21 | **−3.23%** | −3.21% | +37.79% | +0.10 | −28.16% | −1.51% | −16.00% | 321 | 2,683 |
| 2 | 2015-08-21→2017-08-21 | −15.86% | −8.27% | 2017-08-21→2018-08-21 | **+52.83%** | +52.87% | +40.57% | +1.25 | −23.33% | +11.53% | +34.37% | 324 | 2,827 |
| 3 | 2016-08-22→2018-08-21 | +74.23% | +32.07% | 2018-08-21→2019-08-21 | **−0.40%** | −0.40% | +39.07% | +0.19 | −55.87% | −3.95% | −4.30% | 350 | 2,933 |
| 4 | 2017-08-21→2019-08-21 | +50.35% | +22.64% | 2019-08-21→2020-08-21 | **+95.40%** | +95.13% | +58.75% | +1.43 | −41.57% | +69.64% | +77.97% | 346 | 3,047 |
| 5 | 2018-08-21→2020-08-21 | +78.90% | +33.73% | 2020-08-21→2021-08-20 | **+345.23%** | +347.52% | +86.39% | +2.15 | −32.49% | +233.60% | +314.03% | 327 | 3,293 |
| 6 | 2019-08-21→2021-08-20 | +743.45% | +190.63% | 2021-08-20→2022-08-19 | **−3.74%** | −3.75% | +54.49% | +0.20 | −44.72% | −0.67% | −0.39% | 344 | 3,435 |
| 7 | 2020-08-21→2022-08-19 | +331.46% | +108.24% | 2022-08-19→2023-08-21 | **−9.89%** | −9.84% | +44.07% | −0.02 | −30.80% | −2.21% | −15.36% | 351 | 3,549 |
| 8 | 2021-08-23→2023-08-21 | −17.77% | −9.35% | 2023-08-21→2024-08-21 | **−14.01%** | −13.98% | +56.59% | +0.01 | −47.46% | −31.35% | −42.36% | 344 | 3,710 |
| 9 | 2022-08-22→2024-08-21 | −23.98% | −12.82% | 2024-08-21→2025-08-21 | **−67.09%** | −67.11% | +65.07% | −1.39 | −68.54% | −78.27% | −81.39% | 348 | 3,905 |
| 10 ◈ | 2023-08-21→2025-08-21 | −70.05% | −45.25% | 2025-08-21→2026-08-21 | **+89.57%** | +89.65% | +72.49% | +1.25 | −45.99% | +47.12% | +68.37% | 332 | 12,105 |

## Summary

* validate windows: **10**, win rate **40%**
* mean validate return **+48.47%** (median −1.81%, worst −67.09%, best +345.23%)
* mean validate CAGR **+48.69%** vs mean train CAGR +29.40% → decay **+19.28%**
* mean validate Sharpe +0.52, worst validate max drawdown −68.54%
* 3387 fill(s) inside validate windows
* runtime 768.0s (scratch 18.6s, screen 25.4s)

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

