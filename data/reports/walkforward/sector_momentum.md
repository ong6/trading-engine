# Sector ETF Rotation — walk-forward re-validation

_`sector_momentum` · sector_momentum · monthly cadence · verdict **WATCH** · generated 2026-10-11T06:11:13+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-10-09. Each fold is an independent replay starting at $39,000. Span 2016-10-07 → 2026-10-09 (2515 sessions); data floor 2016-10-07; screen source `not-used`.

**Provenance.** Source `63f0126debbdf7f1f4d1b5a53d3bc3937d356acaa12e131d1d18c8292a7d939f`; config `c72300f5e438958572985c2257f7bcdf800dfe2cfe89c73f55c471850cc6e67a`.

**Evidence and execution.** Data quality `fixed_etf_history`; execution profile `baseline_v1`; data snapshot `700dbccad7fb0abbbd708b6a689d1ec632d4df83d43d756735652a0d065a6be5`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Market-like return with lower drawdown — it wins by losing less in downturns, not by out-running the index.

**Pre-registered kill criterion.** Trails spy_benchmark by >10% over 12 months without delivering a lower max drawdown.

**Measured against `spy_benchmark` on the same folds:** beats it in 30% of 10 window(s), mean excess −1.90%, latest +11.35% → **WATCH**.

**90% CI on mean excess vs `spy_benchmark`:** [−6.86%, +3.71%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 ⚑ | 2016-10-07→2016-10-07 | · | · | 2016-10-07→2017-10-09 | **+13.13%** | +13.06% | +9.63% | +1.33 | −4.66% | · | −6.41% | 42 | 2,791 |
| 2 ⚑ | 2016-10-07→2017-10-09 | +13.13% | +13.06% | 2017-10-09→2018-10-09 | **+14.93%** | +14.94% | +14.05% | +1.06 | −9.78% | · | +0.31% | 35 | 2,945 |
| 3 | 2016-10-10→2018-10-09 | +30.02% | +14.06% | 2018-10-09→2019-10-09 | **+2.00%** | +2.00% | +14.74% | +0.21 | −12.38% | · | −1.14% | 45 | 3,059 |
| 4 | 2017-10-09→2019-10-09 | +14.51% | +7.01% | 2019-10-09→2020-10-09 | **+13.46%** | +13.43% | +32.56% | +0.55 | −31.86% | · | −6.84% | 44 | 3,194 |
| 5 | 2018-10-09→2020-10-09 | +22.40% | +10.63% | 2020-10-09→2021-10-08 | **+18.11%** | +18.18% | +16.27% | +1.11 | −10.96% | · | −8.87% | 41 | 3,456 |
| 6 | 2019-10-09→2021-10-08 | +33.44% | +15.53% | 2021-10-08→2022-10-07 | **+5.08%** | +5.10% | +19.94% | +0.35 | −15.04% | · | +20.42% | 48 | 3,598 |
| 7 | 2020-10-09→2022-10-07 | +31.06% | +14.53% | 2022-10-07→2023-10-09 | **+7.96%** | +7.92% | +14.13% | +0.61 | −8.93% | · | −12.33% | 35 | 3,723 |
| 8 | 2021-10-11→2023-10-09 | +8.44% | +4.15% | 2023-10-09→2024-10-09 | **+20.20%** | +20.15% | +13.18% | +1.46 | −8.88% | · | −13.93% | 40 | 3,896 |
| 9 | 2022-10-10→2024-10-09 | +22.42% | +10.65% | 2024-10-09→2025-10-09 | **+15.52%** | +15.53% | +17.16% | +0.93 | −17.18% | · | −1.58% | 41 | 4,113 |
| 10 ◈ | 2023-10-09→2025-10-09 | +43.82% | +19.91% | 2025-10-09→2026-10-09 | **+28.13%** | +28.15% | +13.43% | +1.92 | −7.91% | · | +11.35% | 40 | 12,674 |

## Summary

* validate windows: **10**, win rate **100%**
* mean validate return **+13.85%** (median +14.19%, worst +2.00%, best +28.13%)
* mean validate CAGR **+13.85%** vs mean train CAGR +12.17% → decay **+1.76%**
* mean validate Sharpe +0.95, worst validate max drawdown −31.86%
* 411 fill(s) inside validate windows
* runtime 662.1s (scratch 9.1s, screen 0.0s)

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

