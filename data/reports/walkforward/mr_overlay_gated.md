# Mean-Reversion Overlay (regime-gated) — walk-forward re-validation

_`mr_overlay_gated` · mr_overlay · daily cadence · verdict **WATCH** · generated 2026-10-18T08:36:44+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-10-16. Each fold is an independent replay starting at $39,000. Span 2014-10-16 → 2026-10-16 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,127,086 passing rows).

**Provenance.** Source `63f0126debbdf7f1f4d1b5a53d3bc3937d356acaa12e131d1d18c8292a7d939f`; config `733f1b12222d04238953cc8e119f149512e06a0bf2eb647f9a659173a85070fa`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `45749c2ac18cd407148b1d1006f1fa98ab98065d83802841a009a23e44751dce`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Fewer trades and lower drawdown than ungated MR; avoids catching falling knives in bear tapes.

**Pre-registered kill criterion.** No drawdown/expectancy improvement vs ungated MR.

**Measured against `ew_benchmark` on the same folds:** beats it in 30% of 10 window(s), mean excess −20.73%, latest +23.54% → **WATCH**.

**90% CI on mean excess vs `ew_benchmark`:** [−37.53%, −4.89%] → **distinguishable −**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-10-16→2016-10-14 | +1.10% | +0.55% | 2016-10-14→2017-10-16 | **−6.05%** | −6.02% | +9.09% | −0.64 | −8.33% | −29.57% | · | 418 | 2,803 |
| 2 | 2015-10-16→2017-10-16 | −10.00% | −5.13% | 2017-10-16→2018-10-16 | **+0.32%** | +0.32% | +14.16% | +0.09 | −9.31% | −20.39% | · | 431 | 2,955 |
| 3 | 2016-10-17→2018-10-16 | −7.60% | −3.88% | 2018-10-16→2019-10-16 | **−1.67%** | −1.67% | +8.91% | −0.15 | −7.56% | +5.97% | · | 302 | 3,077 |
| 4 | 2017-10-16→2019-10-16 | −1.40% | −0.70% | 2019-10-16→2020-10-16 | **−1.63%** | −1.63% | +12.05% | −0.08 | −13.59% | −66.50% | · | 340 | 3,215 |
| 5 | 2018-10-16→2020-10-16 | −3.24% | −1.63% | 2020-10-16→2021-10-15 | **+28.99%** | +29.10% | +15.84% | +1.69 | −9.12% | −79.03% | · | 453 | 3,473 |
| 6 | 2019-10-16→2021-10-15 | +27.02% | +12.71% | 2021-10-15→2022-10-14 | **−6.32%** | −6.35% | +8.15% | −0.76 | −11.46% | +12.22% | · | 137 | 3,619 |
| 7 | 2020-10-16→2022-10-14 | +24.69% | +11.71% | 2022-10-14→2023-10-16 | **−7.76%** | −7.73% | +9.22% | −0.83 | −8.29% | −5.79% | · | 335 | 3,746 |
| 8 | 2021-10-18→2023-10-16 | −13.20% | −6.86% | 2023-10-16→2024-10-16 | **+13.11%** | +13.08% | +11.26% | +1.15 | −9.26% | −15.80% | · | 459 | 3,922 |
| 9 | 2022-10-17→2024-10-16 | +4.32% | +2.14% | 2024-10-16→2025-10-16 | **+10.23%** | +10.24% | +14.13% | +0.77 | −13.64% | −31.93% | · | 398 | 4,135 |
| 10 ◈ | 2023-10-16→2025-10-16 | +25.72% | +12.12% | 2025-10-16→2026-10-16 | **+7.02%** | +7.02% | +17.12% | +0.48 | −9.98% | +23.54% | · | 435 | 12,715 |

## Summary

* validate windows: **10**, win rate **50%**
* mean validate return **+3.62%** (median −0.65%, worst −7.76%, best +28.99%)
* mean validate CAGR **+3.64%** vs mean train CAGR +2.10% → decay **+1.53%**
* mean validate Sharpe +0.17, worst validate max drawdown −13.64%
* 3708 fill(s) inside validate windows
* runtime 7476.8s (scratch 0.1s, screen 25.8s)

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

