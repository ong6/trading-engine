# Template Top 5 — walk-forward re-validation

_`template_top5` · template_top5 · weekly cadence · verdict **PASS** · generated 2026-10-18T06:27:15+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-10-16. Each fold is an independent replay starting at $39,000. Span 2014-10-16 → 2026-10-16 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,127,086 passing rows).

**Provenance.** Source `63f0126debbdf7f1f4d1b5a53d3bc3937d356acaa12e131d1d18c8292a7d939f`; config `98bb6fc4717af8df5153bf49b309de631bb087d5debc3465a0197a4a640b647f`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `45749c2ac18cd407148b1d1006f1fa98ab98065d83802841a009a23e44751dce`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Concentrated momentum: higher return and higher drawdown than the broad benchmark in risk-on regimes.

**Pre-registered kill criterion.** Trails ew_benchmark by >15% over any rolling 6 months, or max drawdown exceeds 40%.

**Measured against `ew_benchmark` on the same folds:** beats it in 50% of 10 window(s), mean excess +31.79%, latest +38.55% → **PASS**.

**90% CI on mean excess vs `ew_benchmark`:** [−10.12%, +81.61%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-10-16→2016-10-14 | −36.34% | −20.25% | 2016-10-14→2017-10-16 | **+60.34%** | +59.98% | +33.95% | +1.56 | −21.74% | +36.83% | · | 326 | 2,803 |
| 2 | 2015-10-16→2017-10-16 | +17.42% | +8.36% | 2017-10-16→2018-10-16 | **+34.28%** | +34.30% | +42.38% | +0.91 | −28.60% | +13.57% | · | 321 | 2,955 |
| 3 | 2016-10-17→2018-10-16 | +99.99% | +41.52% | 2018-10-16→2019-10-16 | **−21.94%** | −21.96% | +39.65% | −0.43 | −44.65% | −14.30% | · | 362 | 3,077 |
| 4 | 2017-10-16→2019-10-16 | +9.54% | +4.67% | 2019-10-16→2020-10-16 | **+183.36%** | +182.76% | +64.48% | +1.93 | −44.01% | +118.49% | · | 360 | 3,215 |
| 5 | 2018-10-16→2020-10-16 | +134.11% | +52.96% | 2020-10-16→2021-10-15 | **+366.25%** | +368.72% | +85.19% | +2.22 | −32.93% | +258.23% | · | 328 | 3,473 |
| 6 | 2019-10-16→2021-10-15 | +1031.29% | +236.63% | 2021-10-15→2022-10-14 | **−34.62%** | −34.71% | +51.11% | −0.58 | −46.69% | −16.08% | · | 335 | 3,619 |
| 7 | 2020-10-16→2022-10-14 | +180.22% | +67.70% | 2022-10-14→2023-10-16 | **−19.58%** | −19.50% | +42.88% | −0.30 | −38.93% | −17.61% | · | 360 | 3,746 |
| 8 | 2021-10-18→2023-10-16 | −50.23% | −29.53% | 2023-10-16→2024-10-16 | **+0.05%** | +0.05% | +57.21% | +0.28 | −35.18% | −28.85% | · | 325 | 3,922 |
| 9 | 2022-10-17→2024-10-16 | −26.76% | −14.43% | 2024-10-16→2025-10-16 | **−28.76%** | −28.78% | +69.72% | −0.14 | −61.11% | −70.92% | · | 343 | 4,135 |
| 10 ◈ | 2023-10-16→2025-10-16 | −23.10% | −12.30% | 2025-10-16→2026-10-16 | **+22.03%** | +22.04% | +72.40% | +0.64 | −45.89% | +38.55% | · | 344 | 12,715 |

## Summary

* validate windows: **10**, win rate **60%**
* mean validate return **+56.14%** (median +11.04%, worst −34.62%, best +366.25%)
* mean validate CAGR **+56.29%** vs mean train CAGR +33.53% → decay **+22.76%**
* mean validate Sharpe +0.61, worst validate max drawdown −61.11%
* 3404 fill(s) inside validate windows
* runtime 1102.7s (scratch 0.1s, screen 25.7s)

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

