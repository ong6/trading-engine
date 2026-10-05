# Turtle Breakout (ATR-stopped) — walk-forward re-validation

_`turtle_breakout` · turtle_breakout · daily cadence · verdict **REVIEW** · generated 2026-10-05T17:34:03+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-10-02. Each fold is an independent replay starting at $39,000. Span 2014-10-02 → 2026-10-02 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,120,910 passing rows).

**Provenance.** Source `e533fb3b2cbb71a883fdb88ff4af0b6257676575c4e7bc0bfb80df4cf0373c4e`; config `6fa914b37ef88e139303b049f7f29c2de7b967bef750c18461d1c76dc28d563c`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `0affd34308e8ca5132398cb1f228225beb8f46edd2d68291a7428c94d2e3fca8`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Positive-skew trend capture: roughly a 40% win rate with the winners carrying the book, and drawdown well below Template Top 5 thanks to ATR sizing and the trail.

**Pre-registered kill criterion.** Max drawdown exceeds 25%, or trails ew_benchmark by >15% over any rolling 6 months.

**Measured against `ew_benchmark` on the same folds:** beats it in 20% of 10 window(s), mean excess −20.07%, latest −24.54% → **REVIEW**.

**90% CI on mean excess vs `ew_benchmark`:** [−32.44%, −8.15%] → **distinguishable −**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-10-02→2016-09-30 | +2.00% | +0.99% | 2016-09-30→2017-10-02 | **+10.33%** | +10.28% | +21.17% | +0.57 | −13.08% | −6.71% | · | 143 | 2,779 |
| 2 | 2015-10-02→2017-10-02 | +19.45% | +9.29% | 2017-10-02→2018-10-02 | **+25.16%** | +25.18% | +24.50% | +1.04 | −19.26% | −8.16% | · | 137 | 2,931 |
| 3 | 2016-10-03→2018-10-02 | +29.12% | +13.66% | 2018-10-02→2019-10-02 | **−22.29%** | −22.31% | +20.03% | −1.16 | −23.55% | −6.06% | · | 133 | 3,048 |
| 4 | 2017-10-02→2019-10-02 | −0.32% | −0.16% | 2019-10-02→2020-10-02 | **+6.47%** | +6.46% | +21.81% | +0.40 | −24.60% | −56.28% | · | 115 | 3,178 |
| 5 | 2018-10-02→2020-10-02 | −15.04% | −7.82% | 2020-10-02→2021-10-01 | **+63.07%** | +63.35% | +35.53% | +1.55 | −17.57% | −54.84% | · | 150 | 3,441 |
| 6 | 2019-10-02→2021-10-01 | +70.36% | +30.55% | 2021-10-01→2022-09-30 | **−4.80%** | −4.82% | +22.53% | −0.11 | −26.57% | +13.19% | · | 88 | 3,583 |
| 7 | 2020-10-02→2022-09-30 | +49.17% | +22.22% | 2022-09-30→2023-10-02 | **−23.28%** | −23.18% | +17.41% | −1.44 | −23.28% | −21.70% | · | 130 | 3,706 |
| 8 | 2021-10-04→2023-10-02 | −32.89% | −18.13% | 2023-10-02→2024-10-02 | **+30.87%** | +30.80% | +27.08% | +1.13 | −10.96% | +6.25% | · | 154 | 3,874 |
| 9 | 2022-10-03→2024-10-02 | +0.41% | +0.20% | 2024-10-02→2025-10-02 | **−7.33%** | −7.33% | +23.63% | −0.21 | −30.86% | −41.88% | · | 163 | 4,089 |
| 10 ◈ | 2023-10-02→2025-10-02 | +23.78% | +11.25% | 2025-10-02→2026-10-02 | **−14.70%** | −14.70% | +30.18% | −0.38 | −32.64% | −24.54% | · | 165 | 12,643 |

## Summary

* validate windows: **10**, win rate **50%**
* mean validate return **+6.35%** (median +0.84%, worst −23.28%, best +63.07%)
* mean validate CAGR **+6.37%** vs mean train CAGR +6.20% → decay **+0.17%**
* mean validate Sharpe +0.14, worst validate max drawdown −32.64%
* 1378 fill(s) inside validate windows
* runtime 2177.7s (scratch 0.1s, screen 26.9s)

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

