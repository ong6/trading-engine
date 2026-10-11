# 52-Week-High Momentum — walk-forward re-validation

_`high_52wk` · high_52wk · monthly cadence · verdict **WATCH** · generated 2026-10-11T06:30:11+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-10-09. Each fold is an independent replay starting at $39,000. Span 2014-10-09 → 2026-10-09 (3018 sessions); data floor 1994-01-27; screen source `not-used`.

**Provenance.** Source `63f0126debbdf7f1f4d1b5a53d3bc3937d356acaa12e131d1d18c8292a7d939f`; config `6ebb24fa08f9b55336dc09c420472115e02f35f86e15d1fed1c19e957f073410`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `700dbccad7fb0abbbd708b6a689d1ec632d4df83d43d756735652a0d065a6be5`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Momentum-like returns without the long-run reversal that dogs raw RS ranking, and lower churn than the RS books.

**Pre-registered kill criterion.** Trails ew_benchmark by >15% over any rolling 6 months, or max drawdown exceeds 35%.

**Measured against `ew_benchmark` on the same folds:** beats it in 30% of 10 window(s), mean excess −15.22%, latest +8.23% → **WATCH**.

**90% CI on mean excess vs `ew_benchmark`:** [−29.94%, −2.31%] → **distinguishable −**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-10-09→2016-10-07 | −12.13% | −6.27% | 2016-10-07→2017-10-09 | **+13.19%** | +13.12% | +8.59% | +1.49 | −6.65% | −5.97% | · | 515 | 2,791 |
| 2 | 2015-10-09→2017-10-09 | −4.13% | −2.08% | 2017-10-09→2018-10-09 | **+1.73%** | +1.73% | +11.41% | +0.21 | −9.56% | −20.96% | · | 502 | 2,945 |
| 3 | 2016-10-10→2018-10-09 | +18.28% | +8.78% | 2018-10-09→2019-10-09 | **+2.07%** | +2.07% | +12.54% | +0.23 | −12.07% | +11.31% | · | 496 | 3,059 |
| 4 | 2017-10-09→2019-10-09 | −5.81% | −2.95% | 2019-10-09→2020-10-09 | **+23.39%** | +23.34% | +26.59% | +0.92 | −32.40% | −48.14% | · | 478 | 3,194 |
| 5 | 2018-10-09→2020-10-09 | +29.74% | +13.89% | 2020-10-09→2021-10-08 | **+25.67%** | +25.77% | +17.13% | +1.42 | −9.99% | −77.53% | · | 541 | 3,456 |
| 6 | 2019-10-09→2021-10-08 | +46.27% | +20.96% | 2021-10-08→2022-10-07 | **−7.50%** | −7.52% | +17.00% | −0.38 | −18.29% | +9.35% | · | 486 | 3,598 |
| 7 | 2020-10-09→2022-10-07 | +23.47% | +11.16% | 2022-10-07→2023-10-09 | **−11.42%** | −11.37% | +19.09% | −0.54 | −23.93% | −8.47% | · | 526 | 3,723 |
| 8 | 2021-10-11→2023-10-09 | −20.27% | −10.74% | 2023-10-09→2024-10-09 | **+19.36%** | +19.32% | +13.27% | +1.40 | −8.22% | −5.06% | · | 538 | 3,896 |
| 9 | 2022-10-10→2024-10-09 | +2.26% | +1.12% | 2024-10-09→2025-10-09 | **+28.30%** | +28.32% | +13.76% | +1.90 | −8.47% | −14.92% | · | 528 | 4,113 |
| 10 ◈ | 2023-10-09→2025-10-09 | +58.03% | +25.69% | 2025-10-09→2026-10-09 | **+10.09%** | +10.10% | +15.62% | +0.70 | −11.50% | +8.23% | · | 544 | 12,674 |

## Summary

* validate windows: **10**, win rate **80%**
* mean validate return **+10.49%** (median +11.64%, worst −11.42%, best +28.30%)
* mean validate CAGR **+10.49%** vs mean train CAGR +5.96% → decay **+4.53%**
* mean validate Sharpe +0.73, worst validate max drawdown −32.40%
* 5154 fill(s) inside validate windows
* runtime 1792.1s (scratch 1.1s, screen 0.0s)

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

