# EW Screen — Inverse-Vol Weighted — walk-forward re-validation

_`ew_voltarget` · ew_voltarget · monthly cadence · verdict **REVIEW** · generated 2026-09-23T16:58:31+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-09-22. Each fold is an independent replay starting at $39,000. Span 2014-09-22 → 2026-09-22 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,117,447 passing rows).

**Provenance.** Source `e41e0968a995a82ddca7ebea7aa09c09a9b5351e58b343f7155c30e5b2778dda`; config `955385ddf7d3def847c0908d10094b7afc26a7c443d5cb503f1480feac9cc8f8`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `315382aa846d597a2feffa8bbd2d170de62f535c07a1f6313d73681bef4e676f`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Lower drawdown and lower volatility than ew_benchmark at a small CAGR toll, because the screen's worst drawdowns are driven by its highest-vol names. The honest prior is that inverse-vol weighting mostly re-expresses a low-vol tilt, and low_vol already trails EW by -19.95% mean excess.

**Pre-registered kill criterion.** Fails to reduce max drawdown vs ew_benchmark across a full risk-off fold, or trails ew_benchmark by >10% cumulative over 12 months without a lower max drawdown.

**Measured against `ew_benchmark` on the same folds:** beats it in 40% of 10 window(s), mean excess −2.71%, latest −1.34% → **REVIEW**.

**90% CI on mean excess vs `ew_benchmark`:** [−7.75%, +1.55%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-09-22→2016-09-22 | +4.06% | +2.01% | 2016-09-22→2017-09-22 | **+13.37%** | +13.38% | +19.01% | +0.76 | −9.58% | −0.74% | · | 804 | 2,755 |
| 2 | 2015-09-22→2017-09-22 | +10.10% | +4.93% | 2017-09-22→2018-09-21 | **+34.04%** | +34.17% | +22.67% | +1.41 | −16.22% | −4.91% | · | 791 | 2,906 |
| 3 | 2016-09-22→2018-09-21 | +52.16% | +23.41% | 2018-09-21→2019-09-20 | **−13.06%** | −13.10% | +23.45% | −0.48 | −29.12% | −2.51% | · | 861 | 3,018 |
| 4 | 2017-09-22→2019-09-20 | +15.06% | +7.29% | 2019-09-20→2020-09-22 | **+31.38%** | +31.11% | +36.44% | +0.93 | −35.49% | −8.29% | · | 870 | 3,144 |
| 5 | 2018-09-24→2020-09-22 | +9.87% | +4.83% | 2020-09-22→2021-09-22 | **+102.43%** | +102.52% | +37.80% | +2.06 | −22.28% | −26.79% | · | 873 | 3,401 |
| 6 | 2019-09-23→2021-09-22 | +179.77% | +67.32% | 2021-09-22→2022-09-22 | **−14.02%** | −14.03% | +35.64% | −0.24 | −31.61% | +1.67% | · | 915 | 3,555 |
| 7 | 2020-09-22→2022-09-22 | +67.22% | +29.34% | 2022-09-22→2023-09-22 | **−2.07%** | −2.07% | +23.78% | +0.03 | −16.18% | +4.11% | · | 899 | 3,666 |
| 8 | 2021-09-22→2023-09-22 | −15.11% | −7.87% | 2023-09-22→2024-09-20 | **+38.70%** | +38.85% | +29.39% | +1.27 | −18.02% | +7.95% | · | 868 | 3,837 |
| 9 | 2022-09-22→2024-09-20 | +36.41% | +16.83% | 2024-09-20→2025-09-22 | **+31.13%** | +30.96% | +32.74% | +1.00 | −31.01% | +3.72% | · | 893 | 4,046 |
| 10 ◈ | 2023-09-22→2025-09-22 | +73.45% | +31.68% | 2025-09-22→2026-09-22 | **+9.72%** | +9.73% | +51.34% | +0.44 | −32.44% | −1.34% | · | 912 | 12,565 |

## Summary

* validate windows: **10**, win rate **70%**
* mean validate return **+23.16%** (median +22.25%, worst −14.02%, best +102.43%)
* mean validate CAGR **+23.15%** vs mean train CAGR +17.98% → decay **+5.18%**
* mean validate Sharpe +0.72, worst validate max drawdown −35.49%
* 8686 fill(s) inside validate windows
* runtime 2023.6s (scratch 23.9s, screen 24.7s)

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

