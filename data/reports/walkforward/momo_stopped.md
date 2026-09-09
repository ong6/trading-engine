# Momentum Top 10 (stop-managed) — walk-forward re-validation

_`momo_stopped` · momo_stopped · daily cadence · verdict **WATCH** · generated 2026-09-09T00:44:56+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-09-04. Each fold is an independent replay starting at $39,000. Span 2014-09-04 → 2026-09-04 (3019 sessions); data floor 1994-01-27; screen source `hist` (1,107,456 passing rows).

**Provenance.** Source `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`; config `25cac3722d4dded026ce3b8501bcdac09a1cbca0069f40f25b16afb5ecb3642e`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `a3823b32b5f04344fb909d1fd72c6db6e27812752f8ec99ce8408ed28ff4d668`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Similar upside to Template Top 10 (banded) with materially lower drawdown, the daily stop cutting losers between weekly rebalances.

**Pre-registered kill criterion.** Fails to reduce max drawdown vs template_top10_banded over 6 months, or trails it by >5% cumulative return with no drawdown benefit.

**Measured against `ew_benchmark` on the same folds:** beats it in 40% of 10 window(s), mean excess +4.27%, latest −19.65% → **WATCH**.

**90% CI on mean excess vs `ew_benchmark`:** [−11.82%, +26.12%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-09-04→2016-09-02 | −16.25% | −8.50% | 2016-09-02→2017-09-01 | **−3.88%** | −3.89% | +29.23% | +0.01 | −16.11% | −19.89% | · | 693 | 2,685 |
| 2 | 2015-09-04→2017-09-01 | −4.90% | −2.49% | 2017-09-01→2018-09-04 | **+47.64%** | +47.21% | +29.31% | +1.48 | −16.94% | +6.33% | · | 708 | 2,827 |
| 3 | 2016-09-06→2018-09-04 | +52.85% | +23.72% | 2018-09-04→2019-09-04 | **−7.77%** | −7.77% | +30.84% | −0.11 | −47.31% | −5.51% | · | 755 | 2,933 |
| 4 | 2017-09-05→2019-09-04 | +38.65% | +17.79% | 2019-09-04→2020-09-04 | **+32.81%** | +32.73% | +42.84% | +0.87 | −36.17% | +15.79% | · | 795 | 3,051 |
| 5 | 2018-09-04→2020-09-04 | +26.24% | +12.35% | 2020-09-04→2021-09-03 | **+262.41%** | +264.02% | +55.82% | +2.60 | −33.92% | +111.22% | · | 776 | 3,295 |
| 6 | 2019-09-04→2021-09-03 | +415.55% | +127.19% | 2021-09-03→2022-09-02 | **−9.64%** | −9.68% | +42.78% | −0.02 | −34.30% | +5.37% | · | 813 | 3,441 |
| 7 | 2020-09-04→2022-09-02 | +240.55% | +84.93% | 2022-09-02→2023-09-01 | **−9.66%** | −9.69% | +35.25% | −0.11 | −21.96% | −12.38% | · | 750 | 3,552 |
| 8 | 2021-09-07→2023-09-01 | −18.76% | −9.95% | 2023-09-01→2024-09-04 | **−13.33%** | −13.21% | +41.19% | −0.14 | −29.74% | −16.48% | · | 769 | 3,716 |
| 9 | 2022-09-06→2024-09-04 | −21.22% | −11.26% | 2024-09-04→2025-09-04 | **−2.11%** | −2.11% | +53.49% | +0.23 | −47.94% | −22.08% | · | 785 | 3,908 |
| 10 ◈ | 2023-09-05→2025-09-04 | −10.30% | −5.30% | 2025-09-04→2026-09-04 | **+10.77%** | +10.78% | +68.00% | +0.50 | −44.38% | −19.65% | · | 769 | 12,105 |

## Summary

* validate windows: **10**, win rate **40%**
* mean validate return **+30.72%** (median −2.99%, worst −13.33%, best +262.41%)
* mean validate CAGR **+30.84%** vs mean train CAGR +22.85% → decay **+7.99%**
* mean validate Sharpe +0.53, worst validate max drawdown −47.94%
* 7613 fill(s) inside validate windows
* runtime 2453.6s (scratch 22.1s, screen 24.5s)

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

