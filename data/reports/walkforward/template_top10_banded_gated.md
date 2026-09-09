# Template Top 10 banded (regime-gated) — walk-forward re-validation

_`template_top10_banded_gated` · template_top10_banded · weekly cadence · verdict **WATCH** · generated 2026-09-09T00:01:40+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-09-04. Each fold is an independent replay starting at $39,000. Span 2014-09-04 → 2026-09-04 (3019 sessions); data floor 1994-01-27; screen source `hist` (1,107,456 passing rows).

**Provenance.** Source `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`; config `6b7b393d1530b1ecf6dbc87df74c75d052267e40ad24f8ef79d21e3498bd4b4d`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `a3823b32b5f04344fb909d1fd72c6db6e27812752f8ec99ce8408ed28ff4d668`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Lowest-drawdown of the template family; modest return give-up.

**Pre-registered kill criterion.** No drawdown improvement vs ungated banded across a risk-off episode.

**Measured against `ew_benchmark` on the same folds:** beats it in 40% of 10 window(s), mean excess +7.49%, latest −19.11% → **WATCH**.

**90% CI on mean excess vs `ew_benchmark`:** [−13.20%, +39.59%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-09-04→2016-09-02 | −3.89% | −1.97% | 2016-09-02→2017-09-01 | **−2.11%** | −2.12% | +29.32% | +0.07 | −16.55% | −18.12% | · | 695 | 2,685 |
| 2 | 2015-09-04→2017-09-01 | +12.86% | +6.26% | 2017-09-01→2018-09-04 | **+47.53%** | +47.10% | +29.47% | +1.47 | −17.12% | +6.22% | · | 714 | 2,827 |
| 3 | 2016-09-06→2018-09-04 | +56.57% | +25.22% | 2018-09-04→2019-09-04 | **−6.10%** | −6.11% | +26.03% | −0.11 | −34.05% | −3.84% | · | 494 | 2,933 |
| 4 | 2017-09-05→2019-09-04 | +41.00% | +18.79% | 2019-09-04→2020-09-04 | **+17.11%** | +17.07% | +35.61% | +0.62 | −28.47% | +0.09% | · | 561 | 3,051 |
| 5 | 2018-09-04→2020-09-04 | +13.51% | +6.54% | 2020-09-04→2021-09-03 | **+311.09%** | +313.09% | +57.48% | +2.76 | −30.41% | +159.89% | · | 773 | 3,295 |
| 6 | 2019-09-04→2021-09-03 | +415.63% | +127.20% | 2021-09-03→2022-09-02 | **−6.69%** | −6.71% | +32.90% | −0.05 | −32.26% | +8.33% | · | 385 | 3,441 |
| 7 | 2020-09-04→2022-09-02 | +301.43% | +100.83% | 2022-09-02→2023-09-01 | **−10.41%** | −10.45% | +29.60% | −0.23 | −22.25% | −13.13% | · | 469 | 3,552 |
| 8 | 2021-09-07→2023-09-01 | −17.25% | −9.11% | 2023-09-01→2024-09-04 | **−17.53%** | −17.37% | +42.62% | −0.24 | −30.10% | −20.68% | · | 731 | 3,716 |
| 9 | 2022-09-06→2024-09-04 | −26.10% | −14.06% | 2024-09-04→2025-09-04 | **−4.79%** | −4.79% | +51.95% | +0.16 | −46.46% | −24.76% | · | 641 | 3,908 |
| 10 ◈ | 2023-09-05→2025-09-04 | −17.06% | −8.94% | 2025-09-04→2026-09-04 | **+11.30%** | +11.31% | +69.54% | +0.51 | −43.55% | −19.11% | · | 725 | 12,105 |

## Summary

* validate windows: **10**, win rate **40%**
* mean validate return **+33.94%** (median −3.45%, worst −17.53%, best +311.09%)
* mean validate CAGR **+34.10%** vs mean train CAGR +25.08% → decay **+9.03%**
* mean validate Sharpe +0.50, worst validate max drawdown −46.46%
* 6188 fill(s) inside validate windows
* runtime 1141.9s (scratch 26.1s, screen 23.4s)

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

