# 52-Week-High Momentum — walk-forward re-validation

_`high_52wk` · high_52wk · monthly cadence · verdict **REVIEW** · generated 2026-09-07T11:50:31+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-09-04. Each fold is an independent replay starting at $39,000. Span 2014-09-04 → 2026-09-04 (3019 sessions); data floor 1994-01-27; screen source `not-used`.

**Provenance.** Source `7727bc6b9af2964075d782037983414929cb53d9ffb78c59fa889b3974d29d9a`; config `6ebb24fa08f9b55336dc09c420472115e02f35f86e15d1fed1c19e957f073410`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `b1b031ac37c5b658034fd5b6234fdbe61facab5cba9cdd4afb1159c542fa3785`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Momentum-like returns without the long-run reversal that dogs raw RS ranking, and lower churn than the RS books.

**Pre-registered kill criterion.** Trails ew_benchmark by >15% over any rolling 6 months, or max drawdown exceeds 35%.

**Measured against `ew_benchmark` on the same folds:** beats it in 30% of 10 window(s), mean excess −16.42%, latest −10.82% → **REVIEW**.

**90% CI on mean excess vs `ew_benchmark`:** [−37.73%, −0.93%] → **distinguishable −**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-09-04→2016-09-02 | −8.04% | −4.11% | 2016-09-02→2017-09-01 | **+8.28%** | +8.31% | +9.32% | +0.90 | −7.70% | −7.73% | · | 511 | 2,685 |
| 2 | 2015-09-04→2017-09-01 | −2.03% | −1.03% | 2017-09-01→2018-09-04 | **+10.50%** | +10.42% | +11.32% | +0.94 | −9.91% | −30.81% | · | 511 | 2,827 |
| 3 | 2016-09-06→2018-09-04 | +19.96% | +9.56% | 2018-09-04→2019-09-04 | **−3.12%** | −3.13% | +12.78% | −0.19 | −17.90% | −0.87% | · | 492 | 2,933 |
| 4 | 2017-09-05→2019-09-04 | +2.93% | +1.46% | 2019-09-04→2020-09-04 | **+14.41%** | +14.38% | +26.06% | +0.65 | −32.10% | −2.61% | · | 481 | 3,051 |
| 5 | 2018-09-04→2020-09-04 | +9.55% | +4.66% | 2020-09-04→2021-09-03 | **+31.24%** | +31.37% | +17.81% | +1.62 | −9.96% | −119.95% | · | 540 | 3,295 |
| 6 | 2019-09-04→2021-09-03 | +46.48% | +21.05% | 2021-09-03→2022-09-02 | **−3.84%** | −3.85% | +17.04% | −0.15 | −14.35% | +11.18% | · | 499 | 3,441 |
| 7 | 2020-09-04→2022-09-02 | +22.41% | +10.68% | 2022-09-02→2023-09-01 | **−10.92%** | −10.96% | +19.10% | −0.52 | −22.37% | −13.64% | · | 502 | 3,552 |
| 8 | 2021-09-07→2023-09-01 | −11.18% | −5.81% | 2023-09-01→2024-09-04 | **+11.62%** | +11.49% | +13.15% | +0.90 | −7.51% | +8.47% | · | 534 | 3,716 |
| 9 | 2022-09-06→2024-09-04 | +1.03% | +0.51% | 2024-09-04→2025-09-04 | **+22.54%** | +22.55% | +13.46% | +1.59 | −8.72% | +2.57% | · | 530 | 3,908 |
| 10 ◈ | 2023-09-05→2025-09-04 | +45.41% | +20.60% | 2025-09-04→2026-09-04 | **+19.60%** | +19.62% | +15.94% | +1.20 | −11.28% | −10.82% | · | 554 | 12,105 |

## Summary

* validate windows: **10**, win rate **70%**
* mean validate return **+10.03%** (median +11.06%, worst −10.92%, best +31.24%)
* mean validate CAGR **+10.02%** vs mean train CAGR +5.76% → decay **+4.26%**
* mean validate Sharpe +0.70, worst validate max drawdown −32.10%
* 5154 fill(s) inside validate windows
* runtime 1272.0s (scratch 14.6s, screen 0.0s)

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

