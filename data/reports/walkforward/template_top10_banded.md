# Template Top 10 (banded) — walk-forward re-validation

_`template_top10_banded` · template_top10_banded · weekly cadence · verdict **WATCH** · generated 2026-09-23T16:21:06+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-09-22. Each fold is an independent replay starting at $39,000. Span 2014-09-22 → 2026-09-22 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,117,447 passing rows).

**Provenance.** Source `e41e0968a995a82ddca7ebea7aa09c09a9b5351e58b343f7155c30e5b2778dda`; config `e3fbf7485f3da5770b0e9a7ceb4a3451330bd54d81c58c8684ed69da15601353`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `315382aa846d597a2feffa8bbd2d170de62f535c07a1f6313d73681bef4e676f`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Similar return to top5 with lower turnover and drawdown; banding cuts whipsaw churn.

**Pre-registered kill criterion.** Turnover fails to fall below template_top5, or trails ew_benchmark by >15% over 6 months.

**Measured against `ew_benchmark` on the same folds:** beats it in 30% of 10 window(s), mean excess +2.25%, latest −5.95% → **WATCH**.

**90% CI on mean excess vs `ew_benchmark`:** [−13.46%, +23.16%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-09-22→2016-09-22 | +0.61% | +0.30% | 2016-09-22→2017-09-22 | **−2.23%** | −2.23% | +27.14% | +0.05 | −14.47% | −16.34% | · | 724 | 2,755 |
| 2 | 2015-09-22→2017-09-22 | +1.17% | +0.58% | 2017-09-22→2018-09-21 | **+27.68%** | +27.79% | +30.88% | +0.95 | −18.54% | −11.27% | · | 709 | 2,906 |
| 3 | 2016-09-22→2018-09-21 | +25.61% | +12.10% | 2018-09-21→2019-09-20 | **−23.84%** | −23.91% | +32.70% | −0.68 | −48.11% | −13.30% | · | 747 | 3,018 |
| 4 | 2017-09-22→2019-09-20 | −0.90% | −0.45% | 2019-09-20→2020-09-22 | **+62.57%** | +61.98% | +45.73% | +1.29 | −45.44% | +22.91% | · | 791 | 3,144 |
| 5 | 2018-09-24→2020-09-22 | +20.18% | +9.65% | 2020-09-22→2021-09-22 | **+231.94%** | +232.21% | +58.50% | +2.34 | −31.18% | +102.72% | · | 781 | 3,401 |
| 6 | 2019-09-23→2021-09-22 | +502.13% | +145.53% | 2021-09-22→2022-09-22 | **−15.33%** | −15.34% | +44.82% | −0.15 | −36.29% | +0.37% | · | 813 | 3,555 |
| 7 | 2020-09-22→2022-09-22 | +189.94% | +70.34% | 2022-09-22→2023-09-22 | **−20.15%** | −20.16% | +34.96% | −0.47 | −28.29% | −13.97% | · | 745 | 3,666 |
| 8 | 2021-09-22→2023-09-22 | −36.36% | −20.24% | 2023-09-22→2024-09-20 | **+22.92%** | +23.01% | +43.34% | +0.70 | −30.09% | −7.82% | · | 745 | 3,837 |
| 9 | 2022-09-22→2024-09-20 | +6.22% | +3.07% | 2024-09-20→2025-09-22 | **−7.44%** | −7.40% | +54.05% | +0.13 | −49.36% | −34.85% | · | 789 | 4,046 |
| 10 ◈ | 2023-09-22→2025-09-22 | +14.98% | +7.22% | 2025-09-22→2026-09-22 | **+5.12%** | +5.12% | +70.45% | +0.43 | −42.80% | −5.95% | · | 766 | 12,565 |

## Summary

* validate windows: **10**, win rate **50%**
* mean validate return **+28.12%** (median +1.45%, worst −23.84%, best +231.94%)
* mean validate CAGR **+28.11%** vs mean train CAGR +22.81% → decay **+5.30%**
* mean validate Sharpe +0.46, worst validate max drawdown −49.36%
* 7610 fill(s) inside validate windows
* runtime 1384.3s (scratch 28.2s, screen 24.6s)

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

