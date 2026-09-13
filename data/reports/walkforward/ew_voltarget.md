# EW Screen — Inverse-Vol Weighted — walk-forward re-validation

_`ew_voltarget` · ew_voltarget · monthly cadence · verdict **REVIEW** · generated 2026-09-13T07:05:55+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-09-11. Each fold is an independent replay starting at $39,000. Span 2014-09-11 → 2026-09-11 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,114,750 passing rows).

**Provenance.** Source `2a45f846b7a4628661c4539adf71074377c529a450c90cb07cd4125aafed7d75`; config `955385ddf7d3def847c0908d10094b7afc26a7c443d5cb503f1480feac9cc8f8`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `039bd02c7cdb5678f28e5cf93098393c7e695625c4fc37fc5281d2e8e19fa80e`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Lower drawdown and lower volatility than ew_benchmark at a small CAGR toll, because the screen's worst drawdowns are driven by its highest-vol names. The honest prior is that inverse-vol weighting mostly re-expresses a low-vol tilt, and low_vol already trails EW by -19.95% mean excess.

**Pre-registered kill criterion.** Fails to reduce max drawdown vs ew_benchmark across a full risk-off fold, or trails ew_benchmark by >10% cumulative over 12 months without a lower max drawdown.

**Measured against `ew_benchmark` on the same folds:** beats it in 40% of 10 window(s), mean excess −2.83%, latest −1.45% → **REVIEW**.

**90% CI on mean excess vs `ew_benchmark`:** [−8.64%, +1.82%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-09-11→2016-09-09 | +0.08% | +0.04% | 2016-09-09→2017-09-11 | **+17.18%** | +17.09% | +19.35% | +0.92 | −9.84% | −1.31% | · | 807 | 2,743 |
| 2 | 2015-09-11→2017-09-11 | +9.48% | +4.63% | 2017-09-11→2018-09-11 | **+38.67%** | +38.70% | +22.23% | +1.58 | −16.22% | −4.58% | · | 791 | 2,891 |
| 3 | 2016-09-12→2018-09-11 | +56.12% | +25.01% | 2018-09-11→2019-09-11 | **−16.02%** | −16.03% | +23.47% | −0.63 | −29.19% | −2.62% | · | 860 | 3,000 |
| 4 | 2017-09-11→2019-09-11 | +13.87% | +6.71% | 2019-09-11→2020-09-11 | **+25.66%** | +25.60% | +36.05% | +0.81 | −35.24% | −6.72% | · | 868 | 3,125 |
| 5 | 2018-09-11→2020-09-11 | +3.82% | +1.89% | 2020-09-11→2021-09-10 | **+114.80%** | +115.37% | +37.60% | +2.23 | −22.28% | −31.06% | · | 871 | 3,380 |
| 6 | 2019-09-11→2021-09-10 | +177.39% | +66.61% | 2021-09-10→2022-09-09 | **−9.85%** | −9.88% | +35.73% | −0.11 | −31.61% | +1.81% | · | 915 | 3,538 |
| 7 | 2020-09-11→2022-09-09 | +76.49% | +32.98% | 2022-09-09→2023-09-11 | **+3.00%** | +2.98% | +23.92% | +0.24 | −13.62% | +3.80% | · | 899 | 3,645 |
| 8 | 2021-09-13→2023-09-11 | −5.76% | −2.93% | 2023-09-11→2024-09-11 | **+14.45%** | +14.42% | +29.33% | +0.61 | −18.02% | +7.91% | · | 868 | 3,820 |
| 9 | 2022-09-12→2024-09-11 | +24.98% | +11.80% | 2024-09-11→2025-09-11 | **+30.35%** | +30.37% | +32.72% | +0.98 | −31.01% | +5.90% | · | 894 | 4,023 |
| 10 ◈ | 2023-09-11→2025-09-11 | +57.91% | +25.64% | 2025-09-11→2026-09-11 | **+18.72%** | +18.73% | +51.49% | +0.59 | −32.44% | −1.45% | · | 910 | 12,517 |

## Summary

* validate windows: **10**, win rate **80%**
* mean validate return **+23.70%** (median +17.95%, worst −16.02%, best +114.80%)
* mean validate CAGR **+23.74%** vs mean train CAGR +17.24% → decay **+6.50%**
* mean validate Sharpe +0.72, worst validate max drawdown −35.24%
* 8683 fill(s) inside validate windows
* runtime 1920.1s (scratch 24.7s, screen 28.7s)

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

