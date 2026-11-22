# Sector ETF Rotation — walk-forward re-validation

_`sector_momentum` · sector_momentum · monthly cadence · verdict **WATCH** · generated 2026-11-22T06:12:19+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-11-20. Each fold is an independent replay starting at $39,000. Span 2016-10-07 → 2026-11-20 (2545 sessions); data floor 2016-10-07; screen source `not-used`.

**Provenance.** Source `0cb29b7a14b52c026c41ba49c0123b64089afd113344e80d034803ab7db9c35a`; config `c72300f5e438958572985c2257f7bcdf800dfe2cfe89c73f55c471850cc6e67a`.

**Evidence and execution.** Data quality `fixed_etf_history`; execution profile `baseline_v1`; data snapshot `959ad8683fd601611fafaaadbc2416528da6498b69f40b7444cdc3b817200eac`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Market-like return with lower drawdown — it wins by losing less in downturns, not by out-running the index.

**Pre-registered kill criterion.** Trails spy_benchmark by >10% over 12 months without delivering a lower max drawdown.

**Measured against `spy_benchmark` on the same folds:** beats it in 30% of 10 window(s), mean excess −0.53%, latest +23.81% → **WATCH**.

**90% CI on mean excess vs `spy_benchmark`:** [−6.74%, +6.59%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
7. **An undefined statistic is `null` in the result file and `·` here.** A
   window with fewer than two returns or zero return volatility (a book that sat
   in cash) has no Sharpe, and one with fewer than two month-ends has no worst
   month. Result files are strict JSON: never NaN, infinity or a stand-in zero.


## Folds

| Fold | Train window | Train ret | Train CAGR | Validate window | Validate ret | CAGR | Vol | Sharpe | Max DD | vs EW | vs SPY | Fills | Universe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 ⚑ | 2016-10-07→2016-11-18 | −1.26% | −10.44% | 2016-11-18→2017-11-20 | **+16.16%** | +16.08% | +9.19% | +1.68 | −4.66% | · | −3.48% | 43 | 2,850 |
| 2 ⚑ | 2016-10-07→2017-11-20 | +14.70% | +13.03% | 2017-11-20→2018-11-20 | **+5.95%** | +5.95% | +16.31% | +0.44 | −10.73% | · | +1.90% | 35 | 2,992 |
| 3 | 2016-11-21→2018-11-20 | +20.22% | +9.67% | 2018-11-20→2019-11-20 | **+9.79%** | +9.79% | +12.25% | +0.83 | −11.57% | · | −9.25% | 45 | 3,115 |
| 4 | 2017-11-20→2019-11-20 | +13.63% | +6.60% | 2019-11-20→2020-11-20 | **+14.68%** | +14.65% | +33.22% | +0.58 | −31.86% | · | −0.95% | 44 | 3,268 |
| 5 | 2018-11-20→2020-11-20 | +18.82% | +9.00% | 2020-11-20→2021-11-19 | **+19.97%** | +20.04% | +15.25% | +1.28 | −10.96% | · | −12.56% | 42 | 3,534 |
| 6 | 2019-11-20→2021-11-19 | +37.73% | +17.37% | 2021-11-19→2022-11-18 | **+9.11%** | +9.14% | +20.38% | +0.53 | −15.04% | · | +22.99% | 48 | 3,666 |
| 7 | 2020-11-20→2022-11-18 | +26.43% | +12.49% | 2022-11-18→2023-11-20 | **+4.40%** | +4.38% | +13.58% | +0.39 | −10.63% | · | −11.47% | 34 | 3,806 |
| 8 | 2021-11-22→2023-11-20 | +13.64% | +6.62% | 2023-11-20→2024-11-20 | **+22.07%** | +22.02% | +13.17% | +1.58 | −8.88% | · | −8.61% | 41 | 3,976 |
| 9 | 2022-11-21→2024-11-20 | +24.31% | +11.50% | 2024-11-20→2025-11-20 | **+3.75%** | +3.75% | +17.76% | +0.30 | −17.18% | · | −7.72% | 40 | 4,204 |
| 10 ◈ | 2023-11-20→2025-11-20 | +27.48% | +12.90% | 2025-11-20→2026-11-20 | **+30.53%** | +30.56% | +12.62% | +2.18 | −6.27% | · | +23.81% | 41 | 12,755 |

## Summary

* validate windows: **10**, win rate **100%**
* mean validate return **+13.64%** (median +12.24%, worst +3.75%, best +30.53%)
* mean validate CAGR **+13.64%** vs mean train CAGR +8.87% → decay **+4.76%**
* mean validate Sharpe +0.98, worst validate max drawdown −31.86%
* 413 fill(s) inside validate windows
* runtime 722.3s (scratch 15.2s, screen 0.0s)

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

