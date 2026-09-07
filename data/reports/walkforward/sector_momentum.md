# Sector ETF Rotation — walk-forward re-validation

_`sector_momentum` · sector_momentum · monthly cadence · verdict **WATCH** · generated 2026-09-07T11:29:18+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 9 fold(s), anchored 2026-09-04. Each fold is an independent replay starting at $39,000. Span 2016-10-07 → 2026-09-04 (2491 sessions); data floor 2016-10-07; screen source `not-used`.

**Provenance.** Source `7727bc6b9af2964075d782037983414929cb53d9ffb78c59fa889b3974d29d9a`; config `c72300f5e438958572985c2257f7bcdf800dfe2cfe89c73f55c471850cc6e67a`.

**Evidence and execution.** Data quality `fixed_etf_history`; execution profile `baseline_v1`; data snapshot `b1b031ac37c5b658034fd5b6234fdbe61facab5cba9cdd4afb1159c542fa3785`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Market-like return with lower drawdown — it wins by losing less in downturns, not by out-running the index.

**Pre-registered kill criterion.** Trails spy_benchmark by >10% over 12 months without delivering a lower max drawdown.

**Measured against `spy_benchmark` on the same folds:** beats it in 33% of 9 window(s), mean excess −1.17%, latest +10.01% → **WATCH**.

**90% CI on mean excess vs `spy_benchmark`:** [−6.50%, +4.86%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 2 ⚑ | 2016-10-07→2017-09-01 | +9.07% | +10.11% | 2017-09-01→2018-09-04 | **+20.72%** | +20.55% | +13.97% | +1.42 | −9.78% | · | +2.46% | 36 | 2,827 |
| 3 ⚑ | 2016-10-07→2018-09-04 | +31.67% | +15.51% | 2018-09-04→2019-09-04 | **+0.97%** | +0.97% | +14.69% | +0.14 | −14.93% | · | −2.25% | 45 | 2,933 |
| 4 | 2017-09-05→2019-09-04 | +19.05% | +9.13% | 2019-09-04→2020-09-04 | **+10.52%** | +10.49% | +31.84% | +0.47 | −31.86% | · | −7.31% | 42 | 3,051 |
| 5 | 2018-09-04→2020-09-04 | +9.26% | +4.53% | 2020-09-04→2021-09-03 | **+22.51%** | +22.60% | +17.24% | +1.27 | −10.96% | · | −10.30% | 40 | 3,295 |
| 6 | 2019-09-04→2021-09-03 | +34.84% | +16.13% | 2021-09-03→2022-09-02 | **+10.15%** | +10.19% | +18.87% | +0.61 | −14.85% | · | +21.96% | 49 | 3,441 |
| 7 | 2020-09-04→2022-09-02 | +35.55% | +16.48% | 2022-09-02→2023-09-01 | **+5.30%** | +5.32% | +15.41% | +0.41 | −12.12% | · | −10.69% | 34 | 3,552 |
| 8 | 2021-09-07→2023-09-01 | +21.75% | +10.44% | 2023-09-01→2024-09-04 | **+14.47%** | +14.32% | +13.76% | +1.05 | −9.37% | · | −8.51% | 41 | 3,716 |
| 9 | 2022-09-06→2024-09-04 | +30.45% | +14.25% | 2024-09-04→2025-09-04 | **+12.74%** | +12.75% | +17.20% | +0.79 | −17.18% | · | −5.93% | 41 | 3,908 |
| 10 ◈ | 2023-09-05→2025-09-04 | +35.32% | +16.34% | 2025-09-04→2026-09-04 | **+29.39%** | +29.42% | +13.45% | +1.98 | −7.91% | · | +10.01% | 40 | 12,105 |
| 1 | 2014-09-04→2016-09-04 | — | — | 2016-09-04→2017-09-04 | **dropped**: validate window opens 2016-09-04, at or before this book's data floor 2016-10-07 | | | | | | | |

## Summary

* validate windows: **9**, win rate **100%**
* mean validate return **+14.09%** (median +12.74%, worst +0.97%, best +29.39%)
* mean validate CAGR **+14.07%** vs mean train CAGR +12.55% → decay **+1.52%**
* mean validate Sharpe +0.91, worst validate max drawdown −31.86%
* 368 fill(s) inside validate windows
* runtime 504.1s (scratch 23.1s, screen 0.0s)

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

