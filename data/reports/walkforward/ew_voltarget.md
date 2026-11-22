# EW Screen — Inverse-Vol Weighted — walk-forward re-validation

_`ew_voltarget` · ew_voltarget · monthly cadence · verdict **WATCH** · generated 2026-11-22T08:00:54+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-11-20. Each fold is an independent replay starting at $39,000. Span 2014-11-20 → 2026-11-20 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,135,396 passing rows).

**Provenance.** Source `0cb29b7a14b52c026c41ba49c0123b64089afd113344e80d034803ab7db9c35a`; config `955385ddf7d3def847c0908d10094b7afc26a7c443d5cb503f1480feac9cc8f8`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `959ad8683fd601611fafaaadbc2416528da6498b69f40b7444cdc3b817200eac`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Lower drawdown and lower volatility than ew_benchmark at a small CAGR toll, because the screen's worst drawdowns are driven by its highest-vol names. The honest prior is that inverse-vol weighting mostly re-expresses a low-vol tilt, and low_vol already trails EW by -19.95% mean excess.

**Pre-registered kill criterion.** Fails to reduce max drawdown vs ew_benchmark across a full risk-off fold, or trails ew_benchmark by >10% cumulative over 12 months without a lower max drawdown.

**Measured against `ew_benchmark` on the same folds:** beats it in 50% of 10 window(s), mean excess −2.75%, latest −1.68% → **WATCH**.

**90% CI on mean excess vs `ew_benchmark`:** [−7.98%, +1.60%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-11-20→2016-11-18 | −4.37% | −2.22% | 2016-11-18→2017-11-20 | **+28.67%** | +28.52% | +18.56% | +1.45 | −7.73% | +0.27% | · | 765 | 2,850 |
| 2 | 2015-11-20→2017-11-20 | +15.86% | +7.63% | 2017-11-20→2018-11-20 | **+0.81%** | +0.82% | +25.63% | +0.16 | −21.76% | −3.13% | · | 832 | 2,992 |
| 3 | 2016-11-21→2018-11-20 | +26.06% | +12.30% | 2018-11-20→2019-11-20 | **+2.82%** | +2.83% | +20.12% | +0.24 | −17.07% | −4.10% | · | 869 | 3,115 |
| 4 | 2017-11-20→2019-11-20 | +7.02% | +3.45% | 2019-11-20→2020-11-20 | **+50.62%** | +50.49% | +38.90% | +1.25 | −36.63% | −9.25% | · | 839 | 3,268 |
| 5 | 2018-11-20→2020-11-20 | +46.93% | +21.20% | 2020-11-20→2021-11-19 | **+82.33%** | +82.71% | +36.27% | +1.85 | −22.49% | −27.44% | · | 857 | 3,534 |
| 6 | 2019-11-20→2021-11-19 | +169.17% | +64.12% | 2021-11-19→2022-11-18 | **−13.80%** | −13.85% | +35.22% | −0.25 | −30.20% | +2.36% | · | 940 | 3,666 |
| 7 | 2020-11-20→2022-11-18 | +51.23% | +23.06% | 2022-11-18→2023-11-20 | **−7.47%** | −7.43% | +23.26% | −0.22 | −17.95% | +3.84% | · | 877 | 3,806 |
| 8 | 2021-11-22→2023-11-20 | −17.71% | −9.32% | 2023-11-20→2024-11-20 | **+54.14%** | +54.00% | +30.28% | +1.58 | −18.75% | +7.74% | · | 843 | 3,976 |
| 9 | 2022-11-21→2024-11-20 | +41.53% | +18.98% | 2024-11-20→2025-11-20 | **+2.78%** | +2.78% | +36.82% | +0.26 | −32.04% | +3.85% | · | 889 | 4,204 |
| 10 ◈ | 2023-11-20→2025-11-20 | +57.63% | +25.53% | 2025-11-20→2026-11-20 | **−9.49%** | −9.50% | +46.91% | +0.02 | −41.21% | −1.68% | · | 901 | 12,755 |

## Summary

* validate windows: **10**, win rate **70%**
* mean validate return **+19.14%** (median +2.80%, worst −13.80%, best +82.33%)
* mean validate CAGR **+19.14%** vs mean train CAGR +16.47% → decay **+2.66%**
* mean validate Sharpe +0.63, worst validate max drawdown −41.21%
* 8612 fill(s) inside validate windows
* runtime 7217.0s (scratch 0.1s, screen 28.1s)

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

