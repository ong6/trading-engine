# SPY Buy & Hold — walk-forward re-validation

_`spy_benchmark` · spy_benchmark · once cadence · verdict **reference** · generated 2026-09-08T10:30:09+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-09-04. Each fold is an independent replay starting at $39,000. Span 2014-09-04 → 2026-09-04 (3019 sessions); data floor 1994-01-27; screen source `not-used`.

**Provenance.** Source `44641be995d3b1dda59732f52076138b40d983d94eda22211dbae17a17a5d82f`; config `277c8f3c71e7fe220af0b0cd80ff41400ccacebd6be90495ad3433fc5b040e1e`.

**Evidence and execution.** Data quality `fixed_etf_history`; execution profile `baseline_v1`; data snapshot `d16f6337aff010dd78090410db5786ac468e0be0f85aa8ff87932d069f572cbd`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Baseline market return; the absolute-return yardstick.

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


## Folds

| Fold | Train window | Train ret | Train CAGR | Validate window | Validate ret | CAGR | Vol | Sharpe | Max DD | vs EW | vs SPY | Fills | Universe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2014-09-04→2016-09-02 | +13.18% | +6.40% | 2016-09-02→2017-09-01 | **+15.04%** | +15.09% | +7.98% | +1.80 | −4.13% | · | +0.00% | 0 | 2,685 |
| 2 | 2015-09-04→2017-09-01 | +30.95% | +14.49% | 2017-09-01→2018-09-04 | **+18.26%** | +18.11% | +11.91% | +1.47 | −9.71% | · | +0.00% | 0 | 2,827 |
| 3 | 2016-09-06→2018-09-04 | +36.66% | +16.96% | 2018-09-04→2019-09-04 | **+3.22%** | +3.23% | +15.93% | +0.28 | −18.63% | · | +0.00% | 0 | 2,933 |
| 4 | 2017-09-05→2019-09-04 | +23.19% | +11.02% | 2019-09-04→2020-09-04 | **+17.82%** | +17.78% | +30.65% | +0.69 | −32.41% | · | +0.00% | 0 | 3,051 |
| 5 | 2018-09-04→2020-09-04 | +22.09% | +10.49% | 2020-09-04→2021-09-03 | **+32.81%** | +32.94% | +13.80% | +2.13 | −7.09% | · | +0.00% | 0 | 3,295 |
| 6 | 2019-09-04→2021-09-03 | +56.31% | +25.04% | 2021-09-03→2022-09-02 | **−11.81%** | −11.85% | +20.39% | −0.52 | −22.29% | · | +0.00% | 0 | 3,441 |
| 7 | 2020-09-04→2022-09-02 | +19.49% | +9.35% | 2022-09-02→2023-09-01 | **+15.99%** | +16.05% | +17.30% | +0.95 | −12.34% | · | +0.00% | 0 | 3,552 |
| 8 | 2021-09-07→2023-09-01 | +2.74% | +1.37% | 2023-09-01→2024-09-04 | **+22.98%** | +22.72% | +12.10% | +1.77 | −8.39% | · | +0.00% | 0 | 3,716 |
| 9 | 2022-09-06→2024-09-04 | +44.39% | +20.21% | 2024-09-04→2025-09-04 | **+18.67%** | +18.68% | +19.02% | +1.00 | −18.21% | · | +0.00% | 0 | 3,908 |
| 10 ◈ | 2023-09-05→2025-09-04 | +47.70% | +21.55% | 2025-09-04→2026-09-04 | **+19.38%** | +19.40% | +12.45% | +1.49 | −8.65% | · | +0.00% | 0 | 12,105 |

## Summary

* validate windows: **10**, win rate **90%**
* mean validate return **+15.24%** (median +18.04%, worst −11.81%, best +32.81%)
* mean validate CAGR **+15.22%** vs mean train CAGR +13.69% → decay **+1.53%**
* mean validate Sharpe +1.11, worst validate max drawdown −32.41%
* 0 fill(s) inside validate windows
* runtime 372.7s (scratch 20.9s, screen 0.0s)

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

