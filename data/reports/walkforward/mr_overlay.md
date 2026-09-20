# Mean-Reversion Overlay — walk-forward re-validation

_`mr_overlay` · mr_overlay · daily cadence · verdict **REVIEW** · generated 2026-09-20T09:25:06+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-09-18. Each fold is an independent replay starting at $39,000. Span 2014-09-18 → 2026-09-18 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,116,920 passing rows).

**Provenance.** Source `158dd063aa57e6e37448fdf630ca3e2f244043f4d1bd2520a7b30edcc76b2371`; config `cc049dd59ad46b14ff6f16c5878b8ef49789945a7714226a6e6929db25429cb4`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `c868f4fcc1655450840ca9fb0f244fb9c3c708ec50ec181d46905f33faba08b8`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Many small quick wins; positive expectancy in trending names bought on pullbacks.

**Pre-registered kill criterion.** Expectancy per trade turns negative over 50+ trades, or max drawdown exceeds 25%.

**Measured against `ew_benchmark` on the same folds:** beats it in 20% of 10 window(s), mean excess −24.21%, latest −12.30% → **REVIEW**.

**90% CI on mean excess vs `ew_benchmark`:** [−41.18%, −10.44%] → **distinguishable −**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-09-18→2016-09-16 | −9.33% | −4.79% | 2016-09-16→2017-09-18 | **−5.80%** | −5.77% | +9.40% | −0.59 | −8.99% | −24.57% | · | 415 | 2,752 |
| 2 | 2015-09-18→2017-09-18 | −11.82% | −6.09% | 2017-09-18→2018-09-18 | **+6.15%** | +6.16% | +13.60% | +0.51 | −8.30% | −35.89% | · | 442 | 2,902 |
| 3 | 2016-09-19→2018-09-18 | −0.07% | −0.04% | 2018-09-18→2019-09-18 | **−10.49%** | −10.50% | +11.04% | −0.95 | −14.95% | +4.64% | · | 384 | 3,014 |
| 4 | 2017-09-18→2019-09-18 | −5.05% | −2.56% | 2019-09-18→2020-09-18 | **+7.37%** | +7.35% | +13.50% | +0.59 | −16.27% | −33.69% | · | 429 | 3,143 |
| 5 | 2018-09-18→2020-09-18 | −1.68% | −0.84% | 2020-09-18→2021-09-17 | **+28.66%** | +28.78% | +15.86% | +1.68 | −11.76% | −106.30% | · | 446 | 3,398 |
| 6 | 2019-09-18→2021-09-17 | +37.78% | +17.39% | 2021-09-17→2022-09-16 | **−13.04%** | −13.08% | +12.70% | −1.04 | −14.99% | +1.28% | · | 374 | 3,555 |
| 7 | 2020-09-18→2022-09-16 | +10.35% | +5.06% | 2022-09-16→2023-09-18 | **−7.70%** | −7.67% | +13.24% | −0.54 | −12.49% | −6.00% | · | 439 | 3,663 |
| 8 | 2021-09-20→2023-09-18 | −17.70% | −9.31% | 2023-09-18→2024-09-18 | **+1.38%** | +1.38% | +11.41% | +0.18 | −10.20% | −16.83% | · | 455 | 3,837 |
| 9 | 2022-09-19→2024-09-18 | −5.00% | −2.53% | 2024-09-18→2025-09-18 | **+12.29%** | +12.30% | +14.64% | +0.87 | −17.30% | −12.45% | · | 458 | 4,045 |
| 10 ◈ | 2023-09-18→2025-09-18 | +16.05% | +7.72% | 2025-09-18→2026-09-18 | **+2.92%** | +2.92% | +16.80% | +0.26 | −9.14% | −12.30% | · | 450 | 12,565 |

## Summary

* validate windows: **10**, win rate **60%**
* mean validate return **+2.17%** (median +2.15%, worst −13.04%, best +28.66%)
* mean validate CAGR **+2.19%** vs mean train CAGR +0.40% → decay **+1.79%**
* mean validate Sharpe +0.10, worst validate max drawdown −17.30%
* 4292 fill(s) inside validate windows
* runtime 6819.8s (scratch 22.6s, screen 24.0s)

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

