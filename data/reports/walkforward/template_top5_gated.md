# Template Top 5 (regime-gated) — walk-forward re-validation

_`template_top5_gated` · template_top5 · weekly cadence · verdict **PASS** · generated 2026-10-11T06:26:20+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-10-09. Each fold is an independent replay starting at $39,000. Span 2014-10-09 → 2026-10-09 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,123,518 passing rows).

**Provenance.** Source `63f0126debbdf7f1f4d1b5a53d3bc3937d356acaa12e131d1d18c8292a7d939f`; config `fc20325eea7310c0b00cdb724aaa92b3e6e0e067d04b8c7c609f11d3b5807c09`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `700dbccad7fb0abbbd708b6a689d1ec632d4df83d43d756735652a0d065a6be5`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Same upside as top5 in risk-on, materially lower drawdown in bear markets (drifts to cash).

**Pre-registered kill criterion.** Does not reduce max drawdown vs ungated top5 across a full risk-off episode.

**Measured against `ew_benchmark` on the same folds:** beats it in 60% of 10 window(s), mean excess +25.88%, latest +31.95% → **PASS**.

**90% CI on mean excess vs `ew_benchmark`:** [−7.64%, +64.94%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-10-09→2016-10-07 | +8.29% | +4.07% | 2016-10-07→2017-10-09 | **+40.96%** | +40.73% | +34.11% | +1.18 | −20.30% | +21.80% | · | 347 | 2,791 |
| 2 | 2015-10-09→2017-10-09 | +55.92% | +24.85% | 2017-10-09→2018-10-09 | **+35.83%** | +35.86% | +41.57% | +0.94 | −23.86% | +13.14% | · | 323 | 2,945 |
| 3 | 2016-10-10→2018-10-09 | +107.73% | +44.24% | 2018-10-09→2019-10-09 | **−13.12%** | −13.13% | +32.02% | −0.28 | −32.31% | −3.88% | · | 231 | 3,059 |
| 4 | 2017-10-09→2019-10-09 | +20.78% | +9.91% | 2019-10-09→2020-10-09 | **+181.24%** | +180.64% | +53.95% | +2.17 | −33.59% | +109.71% | · | 260 | 3,194 |
| 5 | 2018-10-09→2020-10-09 | +172.15% | +64.91% | 2020-10-09→2021-10-08 | **+298.31%** | +300.20% | +83.92% | +2.05 | −33.88% | +195.10% | · | 309 | 3,456 |
| 6 | 2019-10-09→2021-10-08 | +988.77% | +230.23% | 2021-10-08→2022-10-07 | **−15.99%** | −16.04% | +34.16% | −0.34 | −40.54% | +0.86% | · | 134 | 3,598 |
| 7 | 2020-10-09→2022-10-07 | +301.91% | +100.96% | 2022-10-07→2023-10-09 | **−43.34%** | −43.19% | +38.74% | −1.28 | −45.43% | −40.39% | · | 268 | 3,723 |
| 8 | 2021-10-11→2023-10-09 | −54.68% | −32.77% | 2023-10-09→2024-10-09 | **+13.03%** | +13.00% | +55.36% | +0.49 | −40.22% | −11.39% | · | 323 | 3,896 |
| 9 | 2022-10-10→2024-10-09 | −36.06% | −20.05% | 2024-10-09→2025-10-09 | **−14.89%** | −14.89% | +62.98% | +0.06 | −48.00% | −58.10% | · | 280 | 4,113 |
| 10 ◈ | 2023-10-09→2025-10-09 | −5.19% | −2.63% | 2025-10-09→2026-10-09 | **+33.81%** | +33.83% | +71.19% | +0.77 | −45.89% | +31.95% | · | 325 | 12,674 |

## Summary

* validate windows: **10**, win rate **60%**
* mean validate return **+51.58%** (median +23.42%, worst −43.34%, best +298.31%)
* mean validate CAGR **+51.70%** vs mean train CAGR +42.37% → decay **+9.33%**
* mean validate Sharpe +0.58, worst validate max drawdown −48.00%
* 2800 fill(s) inside validate windows
* runtime 981.5s (scratch 0.1s, screen 26.0s)

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

