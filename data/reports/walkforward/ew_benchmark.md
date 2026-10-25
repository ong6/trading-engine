# Equal-Weight Benchmark — walk-forward re-validation

_`ew_benchmark` · ew_benchmark · monthly cadence · verdict **reference** · generated 2026-10-25T07:30:50+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-10-23. Each fold is an independent replay starting at $39,000. Span 2014-10-23 → 2026-10-23 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,129,255 passing rows).

**Provenance.** Source `e0310995858cc1919c2ae994131d9902a165fad2e577691c01c3d7aca86da5dd`; config `692d49494298d2e840c98ab78cb8e4a4829516b6049d7d24253eb3e28fe1318e`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `0683f98b1ab3d4b1ece8862855d7f15e7eb87a121ead5d24f38139bde9f8f1a7`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Captures the screen's breadth; the bar every active strategy must clear.

**Pre-registered kill criterion.** Reference benchmark — not killed.

**Reference benchmark.** This book is a control and receives no relative verdict.

**Relative confidence interval:** not applicable to a reference benchmark.

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
| 1 | 2014-10-23→2016-10-21 | −0.00% | −0.00% | 2016-10-21→2017-10-23 | **+20.49%** | +20.38% | +19.85% | +1.04 | −8.28% | +0.00% | · | 726 | 2,818 |
| 2 | 2015-10-23→2017-10-23 | +11.31% | +5.50% | 2017-10-23→2018-10-23 | **+14.55%** | +14.56% | +25.56% | +0.66 | −16.87% | +0.00% | · | 719 | 2,972 |
| 3 | 2016-10-24→2018-10-23 | +44.22% | +20.14% | 2018-10-23→2019-10-23 | **−1.38%** | −1.38% | +23.37% | +0.06 | −20.09% | +0.00% | · | 846 | 3,092 |
| 4 | 2017-10-23→2019-10-23 | +9.25% | +4.52% | 2019-10-23→2020-10-23 | **+54.73%** | +54.59% | +39.79% | +1.29 | −38.78% | +0.00% | · | 816 | 3,234 |
| 5 | 2018-10-23→2020-10-23 | +54.70% | +24.36% | 2020-10-23→2021-10-22 | **+123.59%** | +124.21% | +42.53% | +2.11 | −23.33% | +0.00% | · | 879 | 3,495 |
| 6 | 2019-10-23→2021-10-22 | +241.23% | +84.80% | 2021-10-22→2022-10-21 | **−16.77%** | −16.83% | +37.37% | −0.31 | −34.29% | +0.00% | · | 909 | 3,636 |
| 7 | 2020-10-23→2022-10-21 | +98.37% | +41.01% | 2022-10-21→2023-10-23 | **−10.18%** | −10.13% | +25.19% | −0.30 | −20.95% | +0.00% | · | 857 | 3,767 |
| 8 | 2021-10-25→2023-10-23 | −26.95% | −14.58% | 2023-10-23→2024-10-23 | **+31.80%** | +31.72% | +31.27% | +1.04 | −20.12% | +0.00% | · | 795 | 3,944 |
| 9 | 2022-10-24→2024-10-23 | +16.29% | +7.85% | 2024-10-23→2025-10-23 | **+33.31%** | +33.33% | +39.47% | +0.93 | −35.13% | +0.00% | · | 867 | 4,157 |
| 10 ◈ | 2023-10-23→2025-10-23 | +76.92% | +32.99% | 2025-10-23→2026-10-23 | **−7.36%** | −7.36% | +55.08% | +0.14 | −37.30% | +0.00% | · | 898 | 12,717 |

## Summary

* validate windows: **10**, win rate **60%**
* mean validate return **+24.28%** (median +17.52%, worst −16.77%, best +123.59%)
* mean validate CAGR **+24.31%** vs mean train CAGR +20.66% → decay **+3.65%**
* mean validate Sharpe +0.67, worst validate max drawdown −38.78%
* 8312 fill(s) inside validate windows
* runtime 5418.4s (scratch 0.1s, screen 26.2s)

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

