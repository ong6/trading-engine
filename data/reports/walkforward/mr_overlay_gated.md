# Mean-Reversion Overlay (regime-gated) — walk-forward re-validation

_`mr_overlay_gated` · mr_overlay · daily cadence · verdict **REVIEW** · generated 2026-10-04T07:52:37+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-10-02. Each fold is an independent replay starting at $39,000. Span 2014-10-02 → 2026-10-02 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,120,910 passing rows).

**Provenance.** Source `d0bd517ea958c0cd36effb93747c04d9a2b5fa43e016aa622ba5e35e55c1189d`; config `733f1b12222d04238953cc8e119f149512e06a0bf2eb647f9a659173a85070fa`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `39c8ea0953a0761a486ca6bf24f2938d0d5cb2f3e265ab01ba7d963354e539d0`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Fewer trades and lower drawdown than ungated MR; avoids catching falling knives in bear tapes.

**Pre-registered kill criterion.** No drawdown/expectancy improvement vs ungated MR.

**Measured against `ew_benchmark` on the same folds:** beats it in 20% of 10 window(s), mean excess −23.13%, latest −4.31% → **REVIEW**.

**90% CI on mean excess vs `ew_benchmark`:** [−39.69%, −8.34%] → **distinguishable −**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-10-02→2016-09-30 | +0.31% | +0.16% | 2016-09-30→2017-10-02 | **−7.32%** | −7.29% | +9.30% | −0.77 | −9.12% | −24.36% | · | 415 | 2,779 |
| 2 | 2015-10-02→2017-10-02 | −10.18% | −5.22% | 2017-10-02→2018-10-02 | **+3.67%** | +3.67% | +13.77% | +0.33 | −9.13% | −29.65% | · | 439 | 2,931 |
| 3 | 2016-10-03→2018-10-02 | −4.44% | −2.25% | 2018-10-02→2019-10-02 | **−4.44%** | −4.44% | +9.46% | −0.43 | −7.56% | +11.80% | · | 287 | 3,048 |
| 4 | 2017-10-02→2019-10-02 | −0.91% | −0.45% | 2019-10-02→2020-10-02 | **+3.70%** | +3.69% | +11.82% | +0.36 | −13.59% | −59.05% | · | 350 | 3,178 |
| 5 | 2018-10-02→2020-10-02 | −1.99% | −1.00% | 2020-10-02→2021-10-01 | **+26.44%** | +26.54% | +15.98% | +1.55 | −11.76% | −91.47% | · | 447 | 3,441 |
| 6 | 2019-10-02→2021-10-01 | +31.13% | +14.52% | 2021-10-01→2022-09-30 | **−8.43%** | −8.46% | +8.47% | −1.00 | −11.38% | +9.56% | · | 155 | 3,583 |
| 7 | 2020-10-02→2022-09-30 | +15.78% | +7.63% | 2022-09-30→2023-10-02 | **−6.86%** | −6.83% | +9.07% | −0.74 | −8.29% | −5.29% | · | 317 | 3,706 |
| 8 | 2021-10-04→2023-10-02 | −11.92% | −6.17% | 2023-10-02→2024-10-02 | **+6.27%** | +6.26% | +11.19% | +0.60 | −10.20% | −18.36% | · | 449 | 3,874 |
| 9 | 2022-10-03→2024-10-02 | −1.02% | −0.51% | 2024-10-02→2025-10-02 | **+14.36%** | +14.37% | +13.58% | +1.06 | −13.64% | −20.19% | · | 401 | 4,089 |
| 10 ◈ | 2023-10-02→2025-10-02 | +21.29% | +10.13% | 2025-10-02→2026-10-02 | **+5.53%** | +5.54% | +16.67% | +0.41 | −9.06% | −4.31% | · | 432 | 12,643 |

## Summary

* validate windows: **10**, win rate **60%**
* mean validate return **+3.29%** (median +3.68%, worst −8.43%, best +26.44%)
* mean validate CAGR **+3.31%** vs mean train CAGR +1.68% → decay **+1.62%**
* mean validate Sharpe +0.14, worst validate max drawdown −13.64%
* 3692 fill(s) inside validate windows
* runtime 5173.0s (scratch 0.1s, screen 25.3s)

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

