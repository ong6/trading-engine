# Sector ETF Rotation — walk-forward re-validation

_`sector_momentum` · sector_momentum · monthly cadence · verdict **REVIEW** · generated 2026-08-23T06:08:13+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 9 fold(s), anchored 2026-08-21. Each fold is an independent replay starting at $39,000. Span 2016-10-07 → 2026-08-21 (2481 sessions); data floor 2016-10-07; screen source `not-used`.

**Pre-registered expectation.** Market-like return with lower drawdown — it wins by losing less in downturns, not by out-running the index.

**Pre-registered kill criterion.** Trails spy_benchmark by >10% over 12 months without delivering a lower max drawdown.

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 9 window(s), mean excess −12.54%, latest −10.12% → **REVIEW**.

**90% CI on mean excess vs `ew_benchmark`:** [−31.23%, +1.62%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 2 ⚑ | 2016-10-07→2017-08-21 | +7.13% | +8.23% | 2017-08-21→2018-08-21 | **+20.37%** | +20.38% | +13.97% | +1.40 | −9.78% | −20.93% | +1.91% | 36 | 2,827 |
| 3 ⚑ | 2016-10-07→2018-08-21 | +28.94% | +14.56% | 2018-08-21→2019-08-21 | **+1.26%** | +1.26% | +14.50% | +0.16 | −14.93% | −2.29% | −2.64% | 46 | 2,933 |
| 4 | 2017-08-21→2019-08-21 | +19.40% | +9.28% | 2019-08-21→2020-08-21 | **+11.63%** | +11.61% | +31.54% | +0.51 | −31.84% | −14.12% | −5.79% | 42 | 3,047 |
| 5 | 2018-08-21→2020-08-21 | +10.43% | +5.08% | 2020-08-21→2021-08-20 | **+20.03%** | +20.10% | +17.99% | +1.11 | −10.93% | −91.60% | −11.17% | 39 | 3,293 |
| 6 | 2019-08-21→2021-08-20 | +34.14% | +15.83% | 2021-08-20→2022-08-19 | **+17.41%** | +17.48% | +18.69% | +0.96 | −14.87% | +20.48% | +20.76% | 49 | 3,435 |
| 7 | 2020-08-21→2022-08-19 | +35.01% | +16.25% | 2022-08-19→2023-08-21 | **−1.65%** | −1.65% | +15.28% | −0.03 | −13.22% | +6.03% | −7.12% | 38 | 3,549 |
| 8 | 2021-08-23→2023-08-21 | +12.45% | +6.07% | 2023-08-21→2024-08-21 | **+18.00%** | +17.96% | +14.07% | +1.25 | −9.37% | +0.66% | −10.35% | 36 | 3,710 |
| 9 | 2022-08-22→2024-08-21 | +20.57% | +9.81% | 2024-08-21→2025-08-21 | **+10.22%** | +10.23% | +17.15% | +0.66 | −17.19% | −0.96% | −4.08% | 41 | 3,905 |
| 10 ◈ | 2023-08-21→2025-08-21 | +24.47% | +11.56% | 2025-08-21→2026-08-21 | **+32.33%** | +32.35% | +13.59% | +2.14 | −7.91% | −10.12% | +11.13% | 41 | 12,105 |
| 1 | 2014-08-21→2016-08-21 | — | — | 2016-08-21→2017-08-21 | **dropped**: validate window opens 2016-08-21, at or before this book's data floor 2016-10-07 | | | | | | | |

## Summary

* validate windows: **9**, win rate **89%**
* mean validate return **+14.40%** (median +17.41%, worst −1.65%, best +32.33%)
* mean validate CAGR **+14.41%** vs mean train CAGR +10.74% → decay **+3.67%**
* mean validate Sharpe +0.90, worst validate max drawdown −31.84%
* 368 fill(s) inside validate windows
* runtime 482.0s (scratch 19.8s, screen 0.0s)

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

