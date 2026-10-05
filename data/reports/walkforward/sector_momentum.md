# Sector ETF Rotation — walk-forward re-validation

_`sector_momentum` · sector_momentum · monthly cadence · verdict **WATCH** · generated 2026-10-05T16:42:35+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 9 fold(s), anchored 2026-10-02. Each fold is an independent replay starting at $39,000. Span 2016-10-07 → 2026-10-02 (2510 sessions); data floor 2016-10-07; screen source `not-used`.

**Provenance.** Source `e533fb3b2cbb71a883fdb88ff4af0b6257676575c4e7bc0bfb80df4cf0373c4e`; config `c72300f5e438958572985c2257f7bcdf800dfe2cfe89c73f55c471850cc6e67a`.

**Evidence and execution.** Data quality `fixed_etf_history`; execution profile `baseline_v1`; data snapshot `0affd34308e8ca5132398cb1f228225beb8f46edd2d68291a7428c94d2e3fca8`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Market-like return with lower drawdown — it wins by losing less in downturns, not by out-running the index.

**Pre-registered kill criterion.** Trails spy_benchmark by >10% over 12 months without delivering a lower max drawdown.

**Measured against `spy_benchmark` on the same folds:** beats it in 33% of 9 window(s), mean excess −1.51%, latest +9.25% → **WATCH**.

**90% CI on mean excess vs `spy_benchmark`:** [−6.47%, +4.08%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 2 ⚑ | 2016-10-07→2017-10-02 | +12.18% | +12.37% | 2017-10-02→2018-10-02 | **+18.80%** | +18.81% | +13.96% | +1.30 | −9.78% | · | +1.87% | 35 | 2,931 |
| 3 ⚑ | 2016-10-07→2018-10-02 | +33.27% | +15.57% | 2018-10-02→2019-10-02 | **−1.58%** | −1.58% | +14.74% | −0.03 | −14.52% | · | −2.23% | 45 | 3,048 |
| 4 | 2017-10-02→2019-10-02 | +13.25% | +6.43% | 2019-10-02→2020-10-02 | **+9.93%** | +9.91% | +32.42% | +0.45 | −31.86% | · | −7.30% | 44 | 3,178 |
| 5 | 2018-10-02→2020-10-02 | +17.29% | +8.30% | 2020-10-02→2021-10-01 | **+20.56%** | +20.64% | +16.60% | +1.21 | −10.96% | · | −10.18% | 41 | 3,441 |
| 6 | 2019-10-02→2021-10-01 | +30.53% | +14.26% | 2021-10-01→2022-09-30 | **+3.48%** | +3.49% | +19.59% | +0.27 | −15.04% | · | +19.39% | 45 | 3,583 |
| 7 | 2020-10-02→2022-09-30 | +26.24% | +12.40% | 2022-09-30→2023-10-02 | **+10.44%** | +10.38% | +14.45% | +0.76 | −8.93% | · | −10.33% | 38 | 3,706 |
| 8 | 2021-10-04→2023-10-02 | +6.84% | +3.38% | 2023-10-02→2024-10-02 | **+23.60%** | +23.54% | +13.29% | +1.66 | −8.88% | · | −10.17% | 40 | 3,874 |
| 9 | 2022-10-03→2024-10-02 | +24.03% | +11.38% | 2024-10-02→2025-10-02 | **+14.64%** | +14.65% | +17.17% | +0.89 | −17.18% | · | −3.84% | 41 | 4,089 |
| 10 ◈ | 2023-10-02→2025-10-02 | +44.60% | +20.23% | 2025-10-02→2026-10-02 | **+25.01%** | +25.03% | +13.48% | +1.73 | −7.91% | · | +9.25% | 40 | 12,643 |
| 1 | 2014-10-02→2016-10-02 | — | — | 2016-10-02→2017-10-02 | **dropped**: validate window opens 2016-10-02, at or before this book's data floor 2016-10-07 | | | | | | | |

## Summary

* validate windows: **9**, win rate **89%**
* mean validate return **+13.87%** (median +14.64%, worst −1.58%, best +25.01%)
* mean validate CAGR **+13.87%** vs mean train CAGR +11.59% → decay **+2.29%**
* mean validate Sharpe +0.92, worst validate max drawdown −31.86%
* 369 fill(s) inside validate windows
* runtime 629.2s (scratch 8.0s, screen 0.0s)

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

