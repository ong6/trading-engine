# Mean-Reversion Overlay — walk-forward re-validation

_`mr_overlay` · mr_overlay · daily cadence · verdict **REVIEW** · generated 2026-08-30T07:54:38+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-08-28. Each fold is an independent replay starting at $39,000. Span 2014-08-28 → 2026-08-28 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,106,099 passing rows).

**Pre-registered expectation.** Many small quick wins; positive expectancy in trending names bought on pullbacks.

**Pre-registered kill criterion.** Expectancy per trade turns negative over 50+ trades, or max drawdown exceeds 25%.

**Measured against `ew_benchmark` on the same folds:** beats it in 10% of 10 window(s), mean excess −22.65%, latest −19.68% → **REVIEW**.

**90% CI on mean excess vs `ew_benchmark`:** [−37.96%, −10.53%] → **distinguishable −**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-08-28→2016-08-26 | −9.60% | −4.93% | 2016-08-26→2017-08-28 | **−6.96%** | −6.93% | +9.53% | −0.71 | −8.60% | −15.30% | −21.10% | 416 | 2,684 |
| 2 | 2015-08-28→2017-08-28 | −9.16% | −4.69% | 2017-08-28→2018-08-28 | **+2.98%** | +2.98% | +10.29% | +0.34 | −7.23% | −39.79% | −16.78% | 442 | 2,827 |
| 3 | 2016-08-29→2018-08-28 | −3.70% | −1.87% | 2018-08-28→2019-08-28 | **−6.76%** | −6.76% | +13.80% | −0.44 | −16.02% | −7.26% | −8.23% | 375 | 2,933 |
| 4 | 2017-08-28→2019-08-28 | −2.59% | −1.30% | 2019-08-28→2020-08-28 | **+4.08%** | +4.07% | +13.51% | +0.36 | −17.95% | −20.78% | −18.36% | 433 | 3,049 |
| 5 | 2018-08-28→2020-08-28 | −1.49% | −0.75% | 2020-08-28→2021-08-27 | **+31.32%** | +31.44% | +16.08% | +1.78 | −12.55% | −97.00% | +2.22% | 447 | 3,294 |
| 6 | 2019-08-28→2021-08-27 | +35.92% | +16.60% | 2021-08-27→2022-08-26 | **−6.94%** | −6.97% | +12.20% | −0.53 | −14.94% | +1.20% | +1.49% | 379 | 3,438 |
| 7 | 2020-08-28→2022-08-26 | +18.02% | +8.67% | 2022-08-26→2023-08-28 | **−10.56%** | −10.51% | +13.57% | −0.76 | −15.85% | −2.12% | −21.11% | 430 | 3,552 |
| 8 | 2021-08-30→2023-08-28 | −17.94% | −9.44% | 2023-08-28→2024-08-28 | **−0.54%** | −0.54% | +11.20% | +0.01 | −10.20% | −15.24% | −27.42% | 453 | 3,713 |
| 9 | 2022-08-29→2024-08-28 | −9.77% | −5.01% | 2024-08-28→2025-08-28 | **+10.78%** | +10.79% | +14.56% | +0.78 | −17.30% | −10.49% | −6.33% | 461 | 3,905 |
| 10 ◈ | 2023-08-28→2025-08-28 | +10.71% | +5.21% | 2025-08-28→2026-08-28 | **+7.91%** | +7.92% | +16.55% | +0.54 | −8.96% | −19.68% | −11.39% | 459 | 12,105 |

## Summary

* validate windows: **10**, win rate **50%**
* mean validate return **+2.53%** (median +1.22%, worst −10.56%, best +31.32%)
* mean validate CAGR **+2.55%** vs mean train CAGR +0.25% → decay **+2.30%**
* mean validate Sharpe +0.14, worst validate max drawdown −17.95%
* 4295 fill(s) inside validate windows
* runtime 5821.4s (scratch 23.6s, screen 24.6s)

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

