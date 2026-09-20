# Turtle Breakout (ATR-stopped) — walk-forward re-validation

_`turtle_breakout` · turtle_breakout · daily cadence · verdict **REVIEW** · generated 2026-09-20T07:08:05+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-09-18. Each fold is an independent replay starting at $39,000. Span 2014-09-18 → 2026-09-18 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,116,920 passing rows).

**Provenance.** Source `158dd063aa57e6e37448fdf630ca3e2f244043f4d1bd2520a7b30edcc76b2371`; config `6fa914b37ef88e139303b049f7f29c2de7b967bef750c18461d1c76dc28d563c`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `c868f4fcc1655450840ca9fb0f244fb9c3c708ec50ec181d46905f33faba08b8`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Positive-skew trend capture: roughly a 40% win rate with the winners carrying the book, and drawdown well below Template Top 5 thanks to ATR sizing and the trail.

**Pre-registered kill criterion.** Max drawdown exceeds 25%, or trails ew_benchmark by >15% over any rolling 6 months.

**Measured against `ew_benchmark` on the same folds:** beats it in 20% of 10 window(s), mean excess −20.08%, latest −31.97% → **REVIEW**.

**90% CI on mean excess vs `ew_benchmark`:** [−31.59%, −9.51%] → **distinguishable −**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-09-18→2016-09-16 | −10.18% | −5.24% | 2016-09-16→2017-09-18 | **+12.14%** | +12.08% | +20.77% | +0.66 | −14.59% | −6.63% | · | 124 | 2,752 |
| 2 | 2015-09-18→2017-09-18 | +13.13% | +6.36% | 2017-09-18→2018-09-18 | **+26.71%** | +26.73% | +24.26% | +1.10 | −20.89% | −15.34% | · | 137 | 2,902 |
| 3 | 2016-09-19→2018-09-18 | +47.69% | +21.58% | 2018-09-18→2019-09-18 | **−20.37%** | −20.38% | +20.29% | −1.03 | −24.33% | −5.24% | · | 137 | 3,014 |
| 4 | 2017-09-18→2019-09-18 | +5.72% | +2.82% | 2019-09-18→2020-09-18 | **+1.67%** | +1.66% | +22.07% | +0.19 | −24.60% | −39.39% | · | 113 | 3,143 |
| 5 | 2018-09-18→2020-09-18 | −14.47% | −7.51% | 2020-09-18→2021-09-17 | **+66.44%** | +66.73% | +35.00% | +1.63 | −16.69% | −68.53% | · | 145 | 3,398 |
| 6 | 2019-09-18→2021-09-17 | +97.21% | +40.46% | 2021-09-17→2022-09-16 | **−7.41%** | −7.44% | +23.03% | −0.22 | −25.93% | +6.91% | · | 102 | 3,555 |
| 7 | 2020-09-18→2022-09-16 | +54.74% | +24.49% | 2022-09-16→2023-09-18 | **−16.16%** | −16.09% | +16.64% | −0.98 | −16.62% | −14.45% | · | 118 | 3,663 |
| 8 | 2021-09-20→2023-09-18 | −25.03% | −13.46% | 2023-09-18→2024-09-18 | **+18.34%** | +18.30% | +27.50% | +0.75 | −18.18% | +0.13% | · | 162 | 3,837 |
| 9 | 2022-09-19→2024-09-18 | −0.78% | −0.39% | 2024-09-18→2025-09-18 | **−1.56%** | −1.56% | +23.41% | +0.05 | −30.86% | −26.31% | · | 158 | 4,045 |
| 10 ◈ | 2023-09-18→2025-09-18 | +13.48% | +6.52% | 2025-09-18→2026-09-18 | **−16.75%** | −16.76% | +30.29% | −0.45 | −33.22% | −31.97% | · | 164 | 12,565 |

## Summary

* validate windows: **10**, win rate **50%**
* mean validate return **+6.30%** (median +0.05%, worst −20.37%, best +66.44%)
* mean validate CAGR **+6.33%** vs mean train CAGR +7.56% → decay **−1.24%**
* mean validate Sharpe +0.17, worst validate max drawdown −33.22%
* 1360 fill(s) inside validate windows
* runtime 1886.1s (scratch 25.2s, screen 24.7s)

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

