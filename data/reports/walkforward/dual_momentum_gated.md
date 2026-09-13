# Dual Momentum (regime-gated) — walk-forward re-validation

_`dual_momentum_gated` · dual_momentum · monthly cadence · verdict **REVIEW** · generated 2026-09-13T06:07:37+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-09-11. Each fold is an independent replay starting at $39,000. Span 2014-09-11 → 2026-09-11 (3018 sessions); data floor 2008-05-29; screen source `not-used`.

**Provenance.** Source `2a45f846b7a4628661c4539adf71074377c529a450c90cb07cd4125aafed7d75`; config `f4c370ee82ba101c9f24b17a981303f4b5c663a49ec05722373fc98a47f86624`.

**Evidence and execution.** Data quality `fixed_etf_history`; execution profile `baseline_v1`; data snapshot `039bd02c7cdb5678f28e5cf93098393c7e695625c4fc37fc5281d2e8e19fa80e`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Near-identical to ungated GEM; gate is a belt-and-braces check.

**Pre-registered kill criterion.** Diverges materially from ungated GEM (would signal a gate bug).

**Measured against `spy_benchmark` on the same folds:** beats it in 20% of 10 window(s), mean excess −5.96%, latest −1.11% → **REVIEW**.

**90% CI on mean excess vs `spy_benchmark`:** [−9.14%, −2.74%] → **distinguishable −**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-09-11→2016-09-09 | +0.71% | +0.36% | 2016-09-09→2017-09-11 | **+21.14%** | +21.03% | +7.99% | +2.44 | −3.97% | · | +2.85% | 6 | 2,743 |
| 2 | 2015-09-11→2017-09-11 | +22.68% | +10.75% | 2017-09-11→2018-09-11 | **+10.48%** | +10.48% | +10.66% | +0.99 | −9.71% | · | −6.86% | 4 | 2,891 |
| 3 | 2016-09-12→2018-09-11 | +31.46% | +14.69% | 2018-09-11→2019-09-11 | **−6.19%** | −6.20% | +11.64% | −0.49 | −12.70% | · | −11.74% | 6 | 3,000 |
| 4 | 2017-09-11→2019-09-11 | +3.18% | +1.58% | 2019-09-11→2020-09-11 | **+10.58%** | +10.56% | +14.35% | +0.77 | −12.91% | · | −2.15% | 5 | 3,125 |
| 5 | 2018-09-11→2020-09-11 | +2.08% | +1.03% | 2020-09-11→2021-09-10 | **+35.30%** | +35.44% | +13.82% | +2.27 | −7.35% | · | +1.42% | 4 | 3,380 |
| 6 | 2019-09-11→2021-09-10 | +50.02% | +22.50% | 2021-09-10→2022-09-09 | **−10.89%** | −10.92% | +13.36% | −0.80 | −17.47% | · | −3.70% | 5 | 3,538 |
| 7 | 2020-09-11→2022-09-09 | +18.68% | +8.97% | 2022-09-09→2023-09-11 | **−4.66%** | −4.64% | +6.01% | −0.77 | −6.64% | · | −16.23% | 6 | 3,645 |
| 8 | 2021-09-13→2023-09-11 | −12.57% | −6.52% | 2023-09-11→2024-09-11 | **+15.69%** | +15.65% | +12.17% | +1.26 | −8.41% | · | −8.79% | 5 | 3,820 |
| 9 | 2022-09-12→2024-09-11 | +10.29% | +5.02% | 2024-09-11→2025-09-11 | **+5.90%** | +5.90% | +12.19% | +0.53 | −10.10% | · | −13.25% | 8 | 4,023 |
| 10 ◈ | 2023-09-11→2025-09-11 | +27.14% | +12.75% | 2025-09-11→2026-09-11 | **+15.87%** | +15.88% | +13.82% | +1.14 | −11.42% | · | −1.11% | 10 | 12,517 |

## Summary

* validate windows: **10**, win rate **70%**
* mean validate return **+9.32%** (median +10.53%, worst −10.89%, best +35.30%)
* mean validate CAGR **+9.32%** vs mean train CAGR +7.11% → decay **+2.20%**
* mean validate Sharpe +0.73, worst validate max drawdown −17.47%
* 59 fill(s) inside validate windows
* runtime 450.9s (scratch 22.2s, screen 0.0s)

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

