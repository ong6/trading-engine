# Turtle Breakout (ATR-stopped) — walk-forward re-validation

_`turtle_breakout` · turtle_breakout · daily cadence · verdict **REVIEW** · generated 2026-10-18T07:07:50+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-10-16. Each fold is an independent replay starting at $39,000. Span 2014-10-16 → 2026-10-16 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,127,086 passing rows).

**Provenance.** Source `63f0126debbdf7f1f4d1b5a53d3bc3937d356acaa12e131d1d18c8292a7d939f`; config `6fa914b37ef88e139303b049f7f29c2de7b967bef750c18461d1c76dc28d563c`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `45749c2ac18cd407148b1d1006f1fa98ab98065d83802841a009a23e44751dce`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Positive-skew trend capture: roughly a 40% win rate with the winners carrying the book, and drawdown well below Template Top 5 thanks to ATR sizing and the trail.

**Pre-registered kill criterion.** Max drawdown exceeds 25%, or trails ew_benchmark by >15% over any rolling 6 months.

**Measured against `ew_benchmark` on the same folds:** beats it in 20% of 10 window(s), mean excess −19.15%, latest −4.64% → **REVIEW**.

**90% CI on mean excess vs `ew_benchmark`:** [−31.71%, −7.07%] → **distinguishable −**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-10-16→2016-10-14 | +8.00% | +3.93% | 2016-10-14→2017-10-16 | **+1.14%** | +1.14% | +20.62% | +0.16 | −12.27% | −22.37% | · | 154 | 2,803 |
| 2 | 2015-10-16→2017-10-16 | +7.84% | +3.84% | 2017-10-16→2018-10-16 | **+14.22%** | +14.23% | +25.21% | +0.65 | −19.26% | −6.49% | · | 152 | 2,955 |
| 3 | 2016-10-17→2018-10-16 | +16.72% | +8.05% | 2018-10-16→2019-10-16 | **−16.64%** | −16.65% | +18.79% | −0.88 | −18.63% | −8.99% | · | 130 | 3,077 |
| 4 | 2017-10-16→2019-10-16 | +2.82% | +1.40% | 2019-10-16→2020-10-16 | **+9.26%** | +9.24% | +22.00% | +0.51 | −24.60% | −55.61% | · | 106 | 3,215 |
| 5 | 2018-10-16→2020-10-16 | −6.25% | −3.17% | 2020-10-16→2021-10-15 | **+60.40%** | +60.66% | +35.51% | +1.51 | −17.57% | −47.61% | · | 152 | 3,473 |
| 6 | 2019-10-16→2021-10-15 | +83.58% | +35.52% | 2021-10-15→2022-10-14 | **−2.17%** | −2.18% | +22.90% | +0.02 | −24.78% | +16.37% | · | 82 | 3,619 |
| 7 | 2020-10-16→2022-10-14 | +50.83% | +22.90% | 2022-10-14→2023-10-16 | **−25.00%** | −24.89% | +17.78% | −1.53 | −26.29% | −23.02% | · | 142 | 3,746 |
| 8 | 2021-10-18→2023-10-16 | −25.50% | −13.73% | 2023-10-16→2024-10-16 | **+37.36%** | +37.27% | +26.45% | +1.33 | −10.53% | +8.45% | · | 148 | 3,922 |
| 9 | 2022-10-17→2024-10-16 | +3.02% | +1.50% | 2024-10-16→2025-10-16 | **−5.42%** | −5.43% | +26.20% | −0.08 | −31.34% | −47.58% | · | 160 | 4,135 |
| 10 ◈ | 2023-10-16→2025-10-16 | +31.15% | +14.51% | 2025-10-16→2026-10-16 | **−21.16%** | −21.18% | +29.54% | −0.66 | −33.39% | −4.64% | · | 168 | 12,715 |

## Summary

* validate windows: **10**, win rate **50%**
* mean validate return **+5.20%** (median −0.51%, worst −25.00%, best +60.40%)
* mean validate CAGR **+5.22%** vs mean train CAGR +7.48% → decay **−2.25%**
* mean validate Sharpe +0.10, worst validate max drawdown −33.39%
* 1394 fill(s) inside validate windows
* runtime 2433.3s (scratch 0.1s, screen 25.9s)

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

