# EW Screen — 200d Trend Gated — walk-forward re-validation

_`ew_trend_gated` · ew_trend_gated · monthly cadence · verdict **REVIEW** · generated 2026-09-07T12:16:47+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-09-04. Each fold is an independent replay starting at $39,000. Span 2014-09-04 → 2026-09-04 (3019 sessions); data floor 2008-05-29; screen source `hist` (1,107,457 passing rows).

**Provenance.** Source `7727bc6b9af2964075d782037983414929cb53d9ffb78c59fa889b3974d29d9a`; config `bca58f64dc0aaad72a668c87f82e633a979a2fa77bb9732738145ec500296e3e`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `b1b031ac37c5b658034fd5b6234fdbe61facab5cba9cdd4afb1159c542fa3785`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Materially lower max drawdown than ew_benchmark across a full risk-off episode, paid for in whipsaw during choppy sideways tapes. The honest prior is negative: the existing entry-block gates bought only ~4pp of drawdown relief (top10_banded -47.81% ungated vs -43.69% gated), and a 200-day filter on a monthly basket is slow.

**Pre-registered kill criterion.** No max-drawdown improvement vs ew_benchmark across a full risk-off fold, or trails ew_benchmark by >15% cumulative over 12 months without a lower max drawdown.

**Measured against `ew_benchmark` on the same folds:** beats it in 20% of 10 window(s), mean excess −4.34%, latest −22.06% → **REVIEW**.

**90% CI on mean excess vs `ew_benchmark`:** [−8.09%, −1.51%] → **distinguishable −**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-09-04→2016-09-02 | +5.49% | +2.71% | 2016-09-02→2017-09-01 | **+16.10%** | +16.16% | +20.70% | +0.83 | −9.85% | +0.09% | · | 732 | 2,685 |
| 2 | 2015-09-04→2017-09-01 | +14.13% | +6.85% | 2017-09-01→2018-09-04 | **+41.29%** | +40.92% | +22.69% | +1.64 | −15.52% | −0.02% | · | 720 | 2,827 |
| 3 | 2016-09-06→2018-09-04 | +61.95% | +27.37% | 2018-09-04→2019-09-04 | **−9.26%** | −9.26% | +20.29% | −0.38 | −22.52% | −7.00% | · | 497 | 2,933 |
| 4 | 2017-09-05→2019-09-04 | +24.71% | +11.70% | 2019-09-04→2020-09-04 | **+15.13%** | +15.10% | +24.62% | +0.69 | −16.52% | −1.88% | · | 658 | 3,051 |
| 5 | 2018-09-04→2020-09-04 | +2.92% | +1.45% | 2020-09-04→2021-09-03 | **+151.21%** | +152.00% | +43.04% | +2.37 | −22.64% | +0.01% | · | 859 | 3,295 |
| 6 | 2019-09-04→2021-09-03 | +234.32% | +82.92% | 2021-09-03→2022-09-02 | **−15.18%** | −15.23% | +26.86% | −0.48 | −34.16% | −0.16% | · | 539 | 3,441 |
| 7 | 2020-09-04→2022-09-02 | +94.22% | +39.52% | 2022-09-02→2023-09-01 | **−2.85%** | −2.86% | +21.58% | −0.03 | −17.09% | −5.57% | · | 647 | 3,552 |
| 8 | 2021-09-07→2023-09-01 | −14.72% | −7.72% | 2023-09-01→2024-09-04 | **+0.23%** | +0.23% | +31.08% | +0.16 | −20.62% | −2.91% | · | 755 | 3,716 |
| 9 | 2022-09-06→2024-09-04 | −2.88% | −1.46% | 2024-09-04→2025-09-04 | **+16.10%** | +16.11% | +33.45% | +0.62 | −27.37% | −3.87% | · | 740 | 3,908 |
| 10 ◈ | 2023-09-05→2025-09-04 | +27.62% | +12.98% | 2025-09-04→2026-09-04 | **+8.36%** | +8.36% | +55.28% | +0.42 | −36.63% | −22.06% | · | 849 | 12,105 |

## Summary

* validate windows: **10**, win rate **70%**
* mean validate return **+22.11%** (median +11.74%, worst −15.18%, best +151.21%)
* mean validate CAGR **+22.15%** vs mean train CAGR +17.63% → decay **+4.52%**
* mean validate Sharpe +0.58, worst validate max drawdown −36.63%
* 6996 fill(s) inside validate windows
* runtime 1459.2s (scratch 21.8s, screen 26.4s)

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

