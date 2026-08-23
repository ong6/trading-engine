# Template Top 10 (banded) — walk-forward re-validation

_`template_top10_banded` · template_top10_banded · weekly cadence · verdict **WATCH** · generated 2026-08-23T06:15:22+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-08-21. Each fold is an independent replay starting at $39,000. Span 2014-08-21 → 2026-08-21 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,104,935 passing rows).

**Pre-registered expectation.** Similar return to top5 with lower turnover and drawdown; banding cuts whipsaw churn.

**Pre-registered kill criterion.** Turnover fails to fall below template_top5, or trails ew_benchmark by >15% over 6 months.

**Measured against `ew_benchmark` on the same folds:** beats it in 30% of 10 window(s), mean excess +3.98%, latest −9.55% → **WATCH**.

**90% CI on mean excess vs `ew_benchmark`:** [−12.37%, +27.14%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-08-21→2016-08-19 | −0.88% | −0.44% | 2016-08-19→2017-08-21 | **−18.51%** | −18.43% | +31.99% | −0.48 | −23.99% | −16.80% | −31.28% | 711 | 2,683 |
| 2 | 2015-08-21→2017-08-21 | −4.73% | −2.39% | 2017-08-21→2018-08-21 | **+35.53%** | +35.56% | +29.41% | +1.18 | −17.37% | −5.77% | +17.07% | 701 | 2,827 |
| 3 | 2016-08-22→2018-08-21 | +30.86% | +14.42% | 2018-08-21→2019-08-21 | **−2.11%** | −2.11% | +31.34% | +0.09 | −48.61% | −5.65% | −6.00% | 750 | 2,933 |
| 4 | 2017-08-21→2019-08-21 | +32.50% | +15.12% | 2019-08-21→2020-08-21 | **+38.71%** | +38.62% | +43.44% | +0.97 | −43.52% | +12.96% | +21.29% | 768 | 3,047 |
| 5 | 2018-08-21→2020-08-21 | +29.00% | +13.57% | 2020-08-21→2021-08-20 | **+226.98%** | +228.31% | +58.43% | +2.33 | −30.38% | +115.35% | +195.78% | 772 | 3,293 |
| 6 | 2019-08-21→2021-08-20 | +340.94% | +110.09% | 2021-08-20→2022-08-19 | **+1.49%** | +1.50% | +43.81% | +0.25 | −35.77% | +4.56% | +4.84% | 792 | 3,435 |
| 7 | 2020-08-21→2022-08-19 | +221.14% | +79.56% | 2022-08-19→2023-08-21 | **−15.68%** | −15.61% | +35.58% | −0.30 | −22.83% | −8.00% | −21.15% | 761 | 3,549 |
| 8 | 2021-08-23→2023-08-21 | −20.81% | −11.05% | 2023-08-21→2024-08-21 | **+4.15%** | +4.15% | +42.35% | +0.31 | −30.09% | −13.19% | −24.20% | 749 | 3,710 |
| 9 | 2022-08-22→2024-08-21 | −15.06% | −7.84% | 2024-08-21→2025-08-21 | **−22.98%** | −22.99% | +54.84% | −0.20 | −47.83% | −34.16% | −37.28% | 755 | 3,905 |
| 10 ◈ | 2023-08-21→2025-08-21 | −20.47% | −10.81% | 2025-08-21→2026-08-21 | **+32.90%** | +32.92% | +70.66% | +0.77 | −43.70% | −9.55% | +11.70% | 744 | 12,105 |

## Summary

* validate windows: **10**, win rate **60%**
* mean validate return **+28.05%** (median +2.82%, worst −22.98%, best +226.98%)
* mean validate CAGR **+28.19%** vs mean train CAGR +20.02% → decay **+8.17%**
* mean validate Sharpe +0.49, worst validate max drawdown −48.61%
* 7503 fill(s) inside validate windows
* runtime 895.2s (scratch 24.0s, screen 23.8s)

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

