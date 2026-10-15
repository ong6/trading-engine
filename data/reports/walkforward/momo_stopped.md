# Momentum Top 10 (stop-managed) — walk-forward re-validation

_`momo_stopped` · momo_stopped · daily cadence · verdict **WATCH** · generated 2026-10-11T07:25:19+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-10-09. Each fold is an independent replay starting at $39,000. Span 2014-10-09 → 2026-10-09 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,123,518 passing rows).

**Provenance.** Source `63f0126debbdf7f1f4d1b5a53d3bc3937d356acaa12e131d1d18c8292a7d939f`; config `25cac3722d4dded026ce3b8501bcdac09a1cbca0069f40f25b16afb5ecb3642e`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `700dbccad7fb0abbbd708b6a689d1ec632d4df83d43d756735652a0d065a6be5`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Similar upside to Template Top 10 (banded) with materially lower drawdown, the daily stop cutting losers between weekly rebalances.

**Pre-registered kill criterion.** Fails to reduce max drawdown vs template_top10_banded over 6 months, or trails it by >5% cumulative return with no drawdown benefit.

**Measured against `ew_benchmark` on the same folds:** beats it in 30% of 10 window(s), mean excess +4.40%, latest −9.20% → **WATCH**.

**90% CI on mean excess vs `ew_benchmark`:** [−13.14%, +25.37%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-10-09→2016-10-07 | +8.53% | +4.19% | 2016-10-07→2017-10-09 | **+2.12%** | +2.11% | +27.28% | +0.21 | −15.76% | −17.04% | · | 742 | 2,791 |
| 2 | 2015-10-09→2017-10-09 | −1.14% | −0.57% | 2017-10-09→2018-10-09 | **+7.99%** | +8.00% | +31.24% | +0.40 | −20.36% | −14.70% | · | 706 | 2,945 |
| 3 | 2016-10-10→2018-10-09 | +17.92% | +8.61% | 2018-10-09→2019-10-09 | **−19.64%** | −19.65% | +31.90% | −0.53 | −36.50% | −10.40% | · | 763 | 3,059 |
| 4 | 2017-10-09→2019-10-09 | −11.70% | −6.04% | 2019-10-09→2020-10-09 | **+126.82%** | +126.44% | +45.50% | +2.02 | −37.92% | +55.29% | · | 783 | 3,194 |
| 5 | 2018-10-09→2020-10-09 | +90.74% | +38.08% | 2020-10-09→2021-10-08 | **+196.10%** | +197.21% | +56.45% | +2.21 | −31.88% | +92.90% | · | 796 | 3,456 |
| 6 | 2019-10-09→2021-10-08 | +552.79% | +155.66% | 2021-10-08→2022-10-07 | **−26.40%** | −26.47% | +43.67% | −0.48 | −40.98% | −9.55% | · | 830 | 3,598 |
| 7 | 2020-10-09→2022-10-07 | +120.01% | +48.53% | 2022-10-07→2023-10-09 | **−10.30%** | −10.25% | +33.73% | −0.15 | −28.38% | −7.35% | · | 748 | 3,723 |
| 8 | 2021-10-11→2023-10-09 | −35.50% | −19.75% | 2023-10-09→2024-10-09 | **+28.61%** | +28.54% | +41.87% | +0.81 | −30.08% | +4.19% | · | 745 | 3,896 |
| 9 | 2022-10-10→2024-10-09 | +12.35% | +6.00% | 2024-10-09→2025-10-09 | **+3.09%** | +3.10% | +53.57% | +0.33 | −49.77% | −40.12% | · | 796 | 4,113 |
| 10 ◈ | 2023-10-09→2025-10-09 | +33.28% | +15.44% | 2025-10-09→2026-10-09 | **−7.34%** | −7.34% | +67.94% | +0.24 | −43.63% | −9.20% | · | 781 | 12,674 |

## Summary

* validate windows: **10**, win rate **60%**
* mean validate return **+30.11%** (median +2.61%, worst −26.40%, best +196.10%)
* mean validate CAGR **+30.17%** vs mean train CAGR +25.01% → decay **+5.15%**
* mean validate Sharpe +0.51, worst validate max drawdown −49.77%
* 7690 fill(s) inside validate windows
* runtime 3559.0s (scratch 0.1s, screen 26.5s)

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

