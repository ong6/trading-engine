# EW Screen — 200d Trend Gated — walk-forward re-validation

_`ew_trend_gated` · ew_trend_gated · monthly cadence · verdict **REVIEW** · generated 2026-10-05T17:19:01+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-10-02. Each fold is an independent replay starting at $39,000. Span 2014-10-02 → 2026-10-02 (3018 sessions); data floor 2008-05-29; screen source `hist` (1,120,910 passing rows).

**Provenance.** Source `e533fb3b2cbb71a883fdb88ff4af0b6257676575c4e7bc0bfb80df4cf0373c4e`; config `bca58f64dc0aaad72a668c87f82e633a979a2fa77bb9732738145ec500296e3e`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `0affd34308e8ca5132398cb1f228225beb8f46edd2d68291a7428c94d2e3fca8`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Materially lower max drawdown than ew_benchmark across a full risk-off episode, paid for in whipsaw during choppy sideways tapes. The honest prior is negative: the existing entry-block gates bought only ~4pp of drawdown relief (top10_banded -47.81% ungated vs -43.69% gated), and a 200-day filter on a monthly basket is slow.

**Pre-registered kill criterion.** No max-drawdown improvement vs ew_benchmark across a full risk-off fold, or trails ew_benchmark by >15% cumulative over 12 months without a lower max drawdown.

**Measured against `ew_benchmark` on the same folds:** beats it in 30% of 10 window(s), mean excess −4.11%, latest −18.39% → **REVIEW**.

**90% CI on mean excess vs `ew_benchmark`:** [−7.58%, −0.98%] → **distinguishable −**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-10-02→2016-09-30 | +5.00% | +2.47% | 2016-09-30→2017-10-02 | **+17.07%** | +16.98% | +20.20% | +0.88 | −10.69% | +0.03% | · | 780 | 2,779 |
| 2 | 2015-10-02→2017-10-02 | +17.12% | +8.22% | 2017-10-02→2018-10-02 | **+33.31%** | +33.33% | +23.59% | +1.34 | −16.08% | −0.02% | · | 729 | 2,931 |
| 3 | 2016-10-03→2018-10-02 | +66.17% | +28.97% | 2018-10-02→2019-10-02 | **−21.37%** | −21.38% | +20.72% | −1.06 | −21.78% | −5.14% | · | 534 | 3,048 |
| 4 | 2017-10-02→2019-10-02 | −0.99% | −0.49% | 2019-10-02→2020-10-02 | **+60.01%** | +59.86% | +26.64% | +1.89 | −17.19% | −2.73% | · | 625 | 3,178 |
| 5 | 2018-10-02→2020-10-02 | +44.08% | +20.02% | 2020-10-02→2021-10-01 | **+117.94%** | +118.53% | +43.08% | +2.03 | −22.92% | +0.03% | · | 872 | 3,441 |
| 6 | 2019-10-02→2021-10-01 | +228.26% | +81.25% | 2021-10-01→2022-09-30 | **−12.96%** | −13.00% | +25.65% | −0.41 | −34.16% | +5.03% | · | 474 | 3,583 |
| 7 | 2020-10-02→2022-09-30 | +100.47% | +41.76% | 2022-09-30→2023-10-02 | **−12.89%** | −12.83% | +22.50% | −0.50 | −20.54% | −11.31% | · | 724 | 3,706 |
| 8 | 2021-10-04→2023-10-02 | −29.02% | −15.80% | 2023-10-02→2024-10-02 | **+21.10%** | +21.06% | +31.23% | +0.77 | −20.55% | −3.52% | · | 737 | 3,874 |
| 9 | 2022-10-03→2024-10-02 | +5.24% | +2.59% | 2024-10-02→2025-10-02 | **+29.49%** | +29.52% | +33.39% | +0.95 | −28.31% | −5.06% | · | 749 | 4,089 |
| 10 ◈ | 2023-10-02→2025-10-02 | +63.75% | +27.94% | 2025-10-02→2026-10-02 | **−8.54%** | −8.55% | +54.98% | +0.11 | −37.13% | −18.39% | · | 846 | 12,643 |

## Summary

* validate windows: **10**, win rate **60%**
* mean validate return **+22.32%** (median +19.09%, worst −21.37%, best +117.94%)
* mean validate CAGR **+22.35%** vs mean train CAGR +19.69% → decay **+2.66%**
* mean validate Sharpe +0.60, worst validate max drawdown −37.13%
* 7070 fill(s) inside validate windows
* runtime 2185.0s (scratch 0.1s, screen 26.9s)

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

