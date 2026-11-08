# Sector ETF Rotation — walk-forward re-validation

_`sector_momentum` · sector_momentum · monthly cadence · verdict **WATCH** · generated 2026-11-08T06:11:32+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-11-06. Each fold is an independent replay starting at $39,000. Span 2016-10-07 → 2026-11-06 (2535 sessions); data floor 2016-10-07; screen source `not-used`.

**Provenance.** Source `75fea67fdebd95883443c0460a9f95d28a006d58d3a56c88f605331b7341dd7c`; config `c72300f5e438958572985c2257f7bcdf800dfe2cfe89c73f55c471850cc6e67a`.

**Evidence and execution.** Data quality `fixed_etf_history`; execution profile `baseline_v1`; data snapshot `c7bbed27906c224c92972a34ced3c497680e5cf2c30c01cc0c0c3fc25d714289`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Market-like return with lower drawdown — it wins by losing less in downturns, not by out-running the index.

**Pre-registered kill criterion.** Trails spy_benchmark by >10% over 12 months without delivering a lower max drawdown.

**Measured against `spy_benchmark` on the same folds:** beats it in 40% of 10 window(s), mean excess −1.59%, latest +16.10% → **WATCH**.

**90% CI on mean excess vs `spy_benchmark`:** [−7.17%, +4.83%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 ⚑ | 2016-10-07→2016-11-04 | −2.60% | −29.06% | 2016-11-04→2017-11-06 | **+18.60%** | +18.51% | +9.64% | +1.82 | −4.66% | · | −6.77% | 43 | 2,838 |
| 2 ⚑ | 2016-10-07→2017-11-06 | +15.52% | +14.27% | 2017-11-06→2018-11-06 | **+8.50%** | +8.50% | +16.01% | +0.59 | −10.73% | · | +0.57% | 35 | 2,989 |
| 3 | 2016-11-07→2018-11-06 | +24.01% | +11.38% | 2018-11-06→2019-11-06 | **+4.80%** | +4.80% | +12.64% | +0.44 | −11.57% | · | −8.34% | 45 | 3,112 |
| 4 | 2017-11-06→2019-11-06 | +11.88% | +5.78% | 2019-11-06→2020-11-06 | **+15.73%** | +15.69% | +33.12% | +0.61 | −31.86% | · | +0.38% | 44 | 3,258 |
| 5 | 2018-11-06→2020-11-06 | +18.05% | +8.65% | 2020-11-06→2021-11-05 | **+23.23%** | +23.31% | +15.30% | +1.45 | −10.96% | · | −11.10% | 42 | 3,519 |
| 6 | 2019-11-06→2021-11-05 | +40.55% | +18.57% | 2021-11-05→2022-11-04 | **+4.48%** | +4.50% | +20.19% | +0.32 | −15.04% | · | +22.41% | 48 | 3,659 |
| 7 | 2020-11-06→2022-11-04 | +23.56% | +11.20% | 2022-11-04→2023-11-06 | **+2.52%** | +2.51% | +13.92% | +0.25 | −10.63% | · | −14.44% | 34 | 3,792 |
| 8 | 2021-11-08→2023-11-06 | +9.05% | +4.44% | 2023-11-06→2024-11-06 | **+24.86%** | +24.80% | +13.27% | +1.74 | −8.88% | · | −11.35% | 41 | 3,970 |
| 9 | 2022-11-07→2024-11-06 | +22.02% | +10.47% | 2024-11-06→2025-11-06 | **+10.91%** | +10.92% | +17.44% | +0.69 | −17.18% | · | −3.40% | 40 | 4,195 |
| 10 ◈ | 2023-11-06→2025-11-06 | +33.77% | +15.65% | 2025-11-06→2026-11-06 | **+26.70%** | +26.72% | +12.75% | +1.93 | −6.16% | · | +16.10% | 41 | 12,755 |

## Summary

* validate windows: **10**, win rate **100%**
* mean validate return **+14.03%** (median +13.32%, worst +2.52%, best +26.70%)
* mean validate CAGR **+14.03%** vs mean train CAGR +7.13% → decay **+6.89%**
* mean validate Sharpe +0.98, worst validate max drawdown −31.86%
* 413 fill(s) inside validate windows
* runtime 684.5s (scratch 17.4s, screen 0.0s)

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

