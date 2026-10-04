# Template Top 10 (banded) — walk-forward re-validation

_`template_top10_banded` · template_top10_banded · weekly cadence · verdict **WATCH** · generated 2026-10-04T06:24:02+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-10-02. Each fold is an independent replay starting at $39,000. Span 2014-10-02 → 2026-10-02 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,120,910 passing rows).

**Provenance.** Source `d0bd517ea958c0cd36effb93747c04d9a2b5fa43e016aa622ba5e35e55c1189d`; config `e3fbf7485f3da5770b0e9a7ceb4a3451330bd54d81c58c8684ed69da15601353`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `39c8ea0953a0761a486ca6bf24f2938d0d5cb2f3e265ab01ba7d963354e539d0`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Similar return to top5 with lower turnover and drawdown; banding cuts whipsaw churn.

**Pre-registered kill criterion.** Turnover fails to fall below template_top5, or trails ew_benchmark by >15% over 6 months.

**Measured against `ew_benchmark` on the same folds:** beats it in 20% of 10 window(s), mean excess +2.89%, latest −4.55% → **WATCH**.

**90% CI on mean excess vs `ew_benchmark`:** [−13.81%, +24.13%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-10-02→2016-09-30 | +3.40% | +1.69% | 2016-09-30→2017-10-02 | **+0.87%** | +0.86% | +27.23% | +0.17 | −14.11% | −16.17% | · | 742 | 2,779 |
| 2 | 2015-10-02→2017-10-02 | +4.65% | +2.30% | 2017-10-02→2018-10-02 | **+16.80%** | +16.82% | +31.29% | +0.65 | −18.46% | −16.52% | · | 707 | 2,931 |
| 3 | 2016-10-03→2018-10-02 | +19.23% | +9.21% | 2018-10-02→2019-10-02 | **−30.30%** | −30.32% | +32.72% | −0.94 | −43.00% | −14.07% | · | 755 | 3,048 |
| 4 | 2017-10-02→2019-10-02 | −18.35% | −9.64% | 2019-10-02→2020-10-02 | **+96.54%** | +96.27% | +46.94% | +1.67 | −45.44% | +33.79% | · | 772 | 3,178 |
| 5 | 2018-10-02→2020-10-02 | +46.02% | +20.82% | 2020-10-02→2021-10-01 | **+220.85%** | +222.14% | +58.87% | +2.28 | −30.90% | +102.94% | · | 794 | 3,441 |
| 6 | 2019-10-02→2021-10-01 | +517.48% | +148.65% | 2021-10-01→2022-09-30 | **−26.93%** | −27.01% | +45.24% | −0.47 | −42.12% | −8.94% | · | 820 | 3,583 |
| 7 | 2020-10-02→2022-09-30 | +137.36% | +54.29% | 2022-09-30→2023-10-02 | **−11.12%** | −11.07% | +34.12% | −0.18 | −28.42% | −9.54% | · | 750 | 3,706 |
| 8 | 2021-10-04→2023-10-02 | −36.19% | −20.18% | 2023-10-02→2024-10-02 | **+21.91%** | +21.86% | +43.03% | +0.67 | −30.09% | −2.71% | · | 744 | 3,874 |
| 9 | 2022-10-03→2024-10-02 | +11.47% | +5.58% | 2024-10-02→2025-10-02 | **−0.79%** | −0.79% | +54.26% | +0.26 | −49.36% | −35.34% | · | 783 | 4,089 |
| 10 ◈ | 2023-10-02→2025-10-02 | +21.14% | +10.05% | 2025-10-02→2026-10-02 | **+5.30%** | +5.30% | +70.70% | +0.44 | −42.80% | −4.55% | · | 761 | 12,643 |

## Summary

* validate windows: **10**, win rate **60%**
* mean validate return **+29.31%** (median +3.08%, worst −30.30%, best +220.85%)
* mean validate CAGR **+29.41%** vs mean train CAGR +22.28% → decay **+7.13%**
* mean validate Sharpe +0.46, worst validate max drawdown −49.36%
* 7628 fill(s) inside validate windows
* runtime 1415.0s (scratch 0.1s, screen 25.4s)

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

