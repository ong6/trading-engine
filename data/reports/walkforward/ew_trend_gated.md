# EW Screen — 200d Trend Gated — walk-forward re-validation

_`ew_trend_gated` · ew_trend_gated · monthly cadence · verdict **REVIEW** · generated 2026-10-18T06:51:30+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-10-16. Each fold is an independent replay starting at $39,000. Span 2014-10-16 → 2026-10-16 (3018 sessions); data floor 2008-05-29; screen source `hist` (1,127,086 passing rows).

**Provenance.** Source `63f0126debbdf7f1f4d1b5a53d3bc3937d356acaa12e131d1d18c8292a7d939f`; config `bca58f64dc0aaad72a668c87f82e633a979a2fa77bb9732738145ec500296e3e`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `45749c2ac18cd407148b1d1006f1fa98ab98065d83802841a009a23e44751dce`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Materially lower max drawdown than ew_benchmark across a full risk-off episode, paid for in whipsaw during choppy sideways tapes. The honest prior is negative: the existing entry-block gates bought only ~4pp of drawdown relief (top10_banded -47.81% ungated vs -43.69% gated), and a 200-day filter on a monthly basket is slow.

**Pre-registered kill criterion.** No max-drawdown improvement vs ew_benchmark across a full risk-off fold, or trails ew_benchmark by >15% cumulative over 12 months without a lower max drawdown.

**Measured against `ew_benchmark` on the same folds:** beats it in 40% of 10 window(s), mean excess −3.67%, latest −13.96% → **REVIEW**.

**90% CI on mean excess vs `ew_benchmark`:** [−6.40%, −1.11%] → **distinguishable −**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-10-16→2016-10-14 | +0.71% | +0.35% | 2016-10-14→2017-10-16 | **+23.58%** | +23.46% | +19.88% | +1.17 | −8.43% | +0.07% | · | 730 | 2,803 |
| 2 | 2015-10-16→2017-10-16 | +19.00% | +9.08% | 2017-10-16→2018-10-16 | **+20.72%** | +20.74% | +25.24% | +0.87 | −16.86% | +0.01% | · | 727 | 2,955 |
| 3 | 2016-10-17→2018-10-16 | +52.44% | +23.52% | 2018-10-16→2019-10-16 | **−13.31%** | −13.32% | +18.85% | −0.67 | −15.97% | −5.67% | · | 533 | 3,077 |
| 4 | 2017-10-16→2019-10-16 | +1.50% | +0.75% | 2019-10-16→2020-10-16 | **+63.32%** | +63.15% | +27.21% | +1.93 | −17.40% | −1.56% | · | 629 | 3,215 |
| 5 | 2018-10-16→2020-10-16 | +51.55% | +23.09% | 2020-10-16→2021-10-15 | **+108.05%** | +108.58% | +42.78% | +1.93 | −23.33% | +0.04% | · | 876 | 3,473 |
| 6 | 2019-10-16→2021-10-15 | +231.85% | +82.24% | 2021-10-15→2022-10-14 | **−15.00%** | −15.05% | +25.43% | −0.51 | −34.29% | +3.54% | · | 473 | 3,619 |
| 7 | 2020-10-16→2022-10-14 | +98.85% | +41.18% | 2022-10-14→2023-10-16 | **−12.04%** | −11.98% | +22.93% | −0.45 | −20.56% | −10.06% | · | 722 | 3,746 |
| 8 | 2021-10-18→2023-10-16 | −28.38% | −15.42% | 2023-10-16→2024-10-16 | **+25.28%** | +25.22% | +31.30% | +0.88 | −20.09% | −3.63% | · | 732 | 3,922 |
| 9 | 2022-10-17→2024-10-16 | +10.01% | +4.89% | 2024-10-16→2025-10-16 | **+36.69%** | +36.72% | +35.02% | +1.07 | −28.79% | −5.47% | · | 749 | 4,135 |
| 10 ◈ | 2023-10-16→2025-10-16 | +81.09% | +34.54% | 2025-10-16→2026-10-16 | **−30.49%** | −30.50% | +54.71% | −0.39 | −37.08% | −13.96% | · | 842 | 12,715 |

## Summary

* validate windows: **10**, win rate **60%**
* mean validate return **+20.68%** (median +22.15%, worst −30.49%, best +108.05%)
* mean validate CAGR **+20.70%** vs mean train CAGR +20.42% → decay **+0.28%**
* mean validate Sharpe +0.58, worst validate max drawdown −37.08%
* 7013 fill(s) inside validate windows
* runtime 2352.7s (scratch 0.1s, screen 26.5s)

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

