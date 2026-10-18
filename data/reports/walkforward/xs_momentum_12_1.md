# XS Momentum 12-1 (unscreened control) — walk-forward re-validation

_`xs_momentum_12_1` · xs_momentum_12_1 · monthly cadence · verdict **PASS** · generated 2026-10-18T07:10:38+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-10-16. Each fold is an independent replay starting at $39,000. Span 2014-10-16 → 2026-10-16 (3018 sessions); data floor 1994-01-27; screen source `not-used`.

**Provenance.** Source `63f0126debbdf7f1f4d1b5a53d3bc3937d356acaa12e131d1d18c8292a7d939f`; config `fb5a0f0e3472f14ed9b0a5d5bac05a081ec0284f200db91663b11d5d47ab9214`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `45749c2ac18cd407148b1d1006f1fa98ab98065d83802841a009a23e44751dce`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Market-beating in trending years with deep momentum crashes (2009-style, 2020-11, 2022). If the screen adds value beyond momentum, ew_benchmark beats this book on median excess AND drawdown across the 10 folds; the honest prior is that most of ew_benchmark's edge is plain momentum and the two are INDISTINGUISHABLE.

**Pre-registered kill criterion.** Control: retired only once its question is answered. Kill if ew_benchmark beats it in >= 70% of walk-forward folds with a 90% CI on median excess that excludes 0 AND a lower worst-fold drawdown (screen shown to add value), or if any fold is inert, or if live max drawdown exceeds 55%.

**Measured against `ew_benchmark` on the same folds:** beats it in 90% of 10 window(s), mean excess +9.46%, latest +15.71% → **PASS**.

**90% CI on mean excess vs `ew_benchmark`:** [+0.71%, +16.80%] → **distinguishable +**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-10-16→2016-10-14 | +16.69% | +8.04% | 2016-10-14→2017-10-16 | **+33.85%** | +33.67% | +20.75% | +1.51 | −9.52% | +10.34% | · | 653 | 2,803 |
| 2 | 2015-10-16→2017-10-16 | +39.78% | +18.22% | 2017-10-16→2018-10-16 | **+28.08%** | +28.10% | +23.55% | +1.17 | −16.18% | +7.37% | · | 665 | 2,955 |
| 3 | 2016-10-17→2018-10-16 | +68.94% | +30.05% | 2018-10-16→2019-10-16 | **+5.79%** | +5.79% | +28.26% | +0.34 | −25.75% | +13.43% | · | 659 | 3,077 |
| 4 | 2017-10-16→2019-10-16 | +38.49% | +17.69% | 2019-10-16→2020-10-16 | **+93.64%** | +93.37% | +42.08% | +1.78 | −42.23% | +28.76% | · | 699 | 3,215 |
| 5 | 2018-10-16→2020-10-16 | +117.18% | +47.33% | 2020-10-16→2021-10-15 | **+74.72%** | +75.05% | +44.27% | +1.49 | −32.67% | −33.30% | · | 717 | 3,473 |
| 6 | 2019-10-16→2021-10-15 | +227.52% | +81.05% | 2021-10-15→2022-10-14 | **−13.16%** | −13.21% | +40.61% | −0.14 | −33.96% | +5.38% | · | 695 | 3,619 |
| 7 | 2020-10-16→2022-10-14 | +66.83% | +29.28% | 2022-10-14→2023-10-16 | **+16.04%** | +15.96% | +25.04% | +0.72 | −15.99% | +18.01% | · | 724 | 3,746 |
| 8 | 2021-10-18→2023-10-16 | −3.56% | −1.80% | 2023-10-16→2024-10-16 | **+52.53%** | +52.39% | +32.41% | +1.47 | −18.43% | +23.62% | · | 685 | 3,922 |
| 9 | 2022-10-17→2024-10-16 | +58.31% | +25.84% | 2024-10-16→2025-10-16 | **+47.42%** | +47.46% | +48.45% | +1.05 | −38.59% | +5.26% | · | 732 | 4,135 |
| 10 ◈ | 2023-10-16→2025-10-16 | +142.50% | +55.68% | 2025-10-16→2026-10-16 | **−0.82%** | −0.82% | +50.85% | +0.24 | −28.41% | +15.71% | · | 732 | 12,715 |

## Summary

* validate windows: **10**, win rate **80%**
* mean validate return **+33.81%** (median +30.97%, worst −13.16%, best +93.64%)
* mean validate CAGR **+33.78%** vs mean train CAGR +31.14% → decay **+2.64%**
* mean validate Sharpe +0.96, worst validate max drawdown −42.23%
* 6961 fill(s) inside validate windows
* runtime 2546.1s (scratch 0.1s, screen 0.0s)

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

