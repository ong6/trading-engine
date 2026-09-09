# Turtle Breakout (ATR-stopped) — walk-forward re-validation

_`turtle_breakout` · turtle_breakout · daily cadence · verdict **REVIEW** · generated 2026-09-09T00:33:37+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-09-04. Each fold is an independent replay starting at $39,000. Span 2014-09-04 → 2026-09-04 (3019 sessions); data floor 1994-01-27; screen source `hist` (1,107,456 passing rows).

**Provenance.** Source `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`; config `6fa914b37ef88e139303b049f7f29c2de7b967bef750c18461d1c76dc28d563c`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `a3823b32b5f04344fb909d1fd72c6db6e27812752f8ec99ce8408ed28ff4d668`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Positive-skew trend capture: roughly a 40% win rate with the winners carrying the book, and drawdown well below Template Top 5 thanks to ATR sizing and the trail.

**Pre-registered kill criterion.** Max drawdown exceeds 25%, or trails ew_benchmark by >15% over any rolling 6 months.

**Measured against `ew_benchmark` on the same folds:** beats it in 20% of 10 window(s), mean excess −22.16%, latest −38.77% → **REVIEW**.

**90% CI on mean excess vs `ew_benchmark`:** [−36.27%, −10.35%] → **distinguishable −**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-09-04→2016-09-02 | −2.00% | −1.01% | 2016-09-02→2017-09-01 | **+8.01%** | +8.03% | +21.12% | +0.47 | −13.54% | −8.00% | · | 124 | 2,685 |
| 2 | 2015-09-04→2017-09-01 | +10.36% | +5.07% | 2017-09-01→2018-09-04 | **+18.33%** | +18.18% | +23.52% | +0.83 | −17.66% | −22.98% | · | 142 | 2,827 |
| 3 | 2016-09-06→2018-09-04 | +36.82% | +17.03% | 2018-09-04→2019-09-04 | **−16.56%** | −16.57% | +19.81% | −0.82 | −25.47% | −14.30% | · | 119 | 2,933 |
| 4 | 2017-09-05→2019-09-04 | +2.75% | +1.37% | 2019-09-04→2020-09-04 | **−3.17%** | −3.16% | +21.83% | −0.04 | −19.12% | −20.18% | · | 119 | 3,051 |
| 5 | 2018-09-04→2020-09-04 | −21.65% | −11.47% | 2020-09-04→2021-09-03 | **+62.59%** | +62.86% | +35.93% | +1.53 | −17.02% | −88.60% | · | 164 | 3,295 |
| 6 | 2019-09-04→2021-09-03 | +58.95% | +26.10% | 2021-09-03→2022-09-02 | **−12.69%** | −12.73% | +23.23% | −0.47 | −26.38% | +2.32% | · | 108 | 3,441 |
| 7 | 2020-09-04→2022-09-02 | +44.58% | +20.32% | 2022-09-02→2023-09-01 | **−7.11%** | −7.13% | +17.02% | −0.35 | −13.60% | −9.83% | · | 106 | 3,552 |
| 8 | 2021-09-07→2023-09-01 | −19.58% | −10.41% | 2023-09-01→2024-09-04 | **+6.99%** | +6.92% | +26.52% | +0.39 | −22.95% | +3.85% | · | 162 | 3,716 |
| 9 | 2022-09-06→2024-09-04 | −0.61% | −0.31% | 2024-09-04→2025-09-04 | **−5.09%** | −5.09% | +24.15% | −0.10 | −31.00% | −25.06% | · | 160 | 3,908 |
| 10 ◈ | 2023-09-05→2025-09-04 | −4.07% | −2.06% | 2025-09-04→2026-09-04 | **−8.35%** | −8.36% | +29.89% | −0.14 | −30.16% | −38.77% | · | 164 | 12,105 |

## Summary

* validate windows: **10**, win rate **40%**
* mean validate return **+4.29%** (median −4.13%, worst −16.56%, best +62.59%)
* mean validate CAGR **+4.29%** vs mean train CAGR +4.46% → decay **−0.17%**
* mean validate Sharpe +0.13, worst validate max drawdown −31.00%
* 1368 fill(s) inside validate windows
* runtime 1771.2s (scratch 23.2s, screen 24.5s)

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

