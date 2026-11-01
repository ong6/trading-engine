# Momentum Top 10 (stop-managed) — walk-forward re-validation

_`momo_stopped` · momo_stopped · daily cadence · verdict **WATCH** · generated 2026-11-01T07:51:48+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-10-30. Each fold is an independent replay starting at $39,000. Span 2014-10-30 → 2026-10-30 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,132,131 passing rows).

**Provenance.** Source `75fea67fdebd95883443c0460a9f95d28a006d58d3a56c88f605331b7341dd7c`; config `25cac3722d4dded026ce3b8501bcdac09a1cbca0069f40f25b16afb5ecb3642e`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `d149a66d3d234041d859f43b47ed718a7a538c9f892bbeee2fd22e81f813c05e`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Similar upside to Template Top 10 (banded) with materially lower drawdown, the daily stop cutting losers between weekly rebalances.

**Pre-registered kill criterion.** Fails to reduce max drawdown vs template_top10_banded over 6 months, or trails it by >5% cumulative return with no drawdown benefit.

**Measured against `ew_benchmark` on the same folds:** beats it in 30% of 10 window(s), mean excess +7.29%, latest −2.40% → **WATCH**.

**90% CI on mean excess vs `ew_benchmark`:** [−13.43%, +32.41%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-10-30→2016-10-28 | −6.00% | −3.05% | 2016-10-28→2017-10-30 | **−0.13%** | −0.13% | +27.23% | +0.13 | −19.18% | −26.92% | · | 745 | 2,830 |
| 2 | 2015-10-30→2017-10-30 | −6.02% | −3.06% | 2017-10-30→2018-10-30 | **+3.20%** | +3.20% | +32.60% | +0.26 | −30.80% | −4.63% | · | 703 | 2,983 |
| 3 | 2016-10-31→2018-10-30 | +4.70% | +2.33% | 2018-10-30→2019-10-30 | **−8.56%** | −8.56% | +30.36% | −0.14 | −29.75% | −13.85% | · | 759 | 3,104 |
| 4 | 2017-10-30→2019-10-30 | −6.13% | −3.12% | 2019-10-30→2020-10-30 | **+89.58%** | +89.33% | +46.55% | +1.60 | −37.92% | +48.39% | · | 783 | 3,248 |
| 5 | 2018-10-30→2020-10-30 | +76.96% | +33.00% | 2020-10-30→2021-10-29 | **+265.32%** | +266.95% | +56.42% | +2.59 | −33.19% | +120.53% | · | 802 | 3,508 |
| 6 | 2019-10-30→2021-10-29 | +583.33% | +161.58% | 2021-10-29→2022-10-28 | **−23.36%** | −23.43% | +43.05% | −0.40 | −41.99% | −6.58% | · | 830 | 3,652 |
| 7 | 2020-10-30→2022-10-28 | +173.76% | +65.74% | 2022-10-28→2023-10-30 | **−30.72%** | −30.60% | +33.94% | −0.92 | −34.78% | −17.75% | · | 762 | 3,783 |
| 8 | 2021-11-01→2023-10-30 | −52.00% | −30.81% | 2023-10-30→2024-10-30 | **+54.99%** | +54.85% | +41.88% | +1.26 | −29.27% | +19.02% | · | 755 | 3,961 |
| 9 | 2022-10-31→2024-10-30 | +2.42% | +1.20% | 2024-10-30→2025-10-30 | **−8.11%** | −8.12% | +56.05% | +0.13 | −49.68% | −42.90% | · | 781 | 4,178 |
| 10 ◈ | 2023-10-30→2025-10-30 | +36.32% | +16.74% | 2025-10-30→2026-10-30 | **−11.80%** | −11.81% | +66.15% | +0.15 | −43.64% | −2.40% | · | 789 | 12,736 |

## Summary

* validate windows: **10**, win rate **40%**
* mean validate return **+33.04%** (median −4.12%, worst −30.72%, best +265.32%)
* mean validate CAGR **+33.17%** vs mean train CAGR +24.06% → decay **+9.11%**
* mean validate Sharpe +0.47, worst validate max drawdown −49.68%
* 7709 fill(s) inside validate windows
* runtime 6676.2s (scratch 0.1s, screen 27.8s)

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

