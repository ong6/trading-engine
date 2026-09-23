# Template Top 5 — walk-forward re-validation

_`template_top5` · template_top5 · weekly cadence · verdict **PASS** · generated 2026-09-23T16:14:42+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-09-22. Each fold is an independent replay starting at $39,000. Span 2014-09-22 → 2026-09-22 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,117,447 passing rows).

**Provenance.** Source `e41e0968a995a82ddca7ebea7aa09c09a9b5351e58b343f7155c30e5b2778dda`; config `98bb6fc4717af8df5153bf49b309de631bb087d5debc3465a0197a4a640b647f`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `315382aa846d597a2feffa8bbd2d170de62f535c07a1f6313d73681bef4e676f`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Concentrated momentum: higher return and higher drawdown than the broad benchmark in risk-on regimes.

**Pre-registered kill criterion.** Trails ew_benchmark by >15% over any rolling 6 months, or max drawdown exceeds 40%.

**Measured against `ew_benchmark` on the same folds:** beats it in 50% of 10 window(s), mean excess +31.22%, latest +36.59% → **PASS**.

**90% CI on mean excess vs `ew_benchmark`:** [−9.90%, +80.49%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-09-22→2016-09-22 | −33.38% | −18.36% | 2016-09-22→2017-09-22 | **+20.78%** | +20.80% | +33.84% | +0.73 | −20.28% | +6.67% | · | 320 | 2,755 |
| 2 | 2015-09-22→2017-09-22 | −1.76% | −0.88% | 2017-09-22→2018-09-21 | **+71.56%** | +71.88% | +41.00% | +1.53 | −22.10% | +32.61% | · | 325 | 2,906 |
| 3 | 2016-09-22→2018-09-21 | +105.16% | +43.34% | 2018-09-21→2019-09-20 | **−21.72%** | −21.79% | +40.58% | −0.40 | −54.28% | −11.18% | · | 359 | 3,018 |
| 4 | 2017-09-22→2019-09-20 | +33.34% | +15.53% | 2019-09-20→2020-09-22 | **+150.74%** | +149.03% | +62.50% | +1.78 | −44.01% | +111.08% | · | 363 | 3,144 |
| 5 | 2018-09-24→2020-09-22 | +88.11% | +37.24% | 2020-09-22→2021-09-22 | **+389.32%** | +389.86% | +84.68% | +2.28 | −32.67% | +260.11% | · | 329 | 3,401 |
| 6 | 2019-09-23→2021-09-22 | +1054.05% | +240.00% | 2021-09-22→2022-09-22 | **−25.38%** | −25.40% | +49.54% | −0.34 | −40.82% | −9.68% | · | 314 | 3,555 |
| 7 | 2020-09-22→2022-09-22 | +304.32% | +101.17% | 2022-09-22→2023-09-22 | **−26.70%** | −26.71% | +43.81% | −0.50 | −37.56% | −20.52% | · | 355 | 3,666 |
| 8 | 2021-09-22→2023-09-22 | −48.57% | −28.30% | 2023-09-22→2024-09-20 | **+5.27%** | +5.29% | +56.03% | +0.37 | −42.54% | −25.47% | · | 336 | 3,837 |
| 9 | 2022-09-22→2024-09-20 | −17.15% | −9.00% | 2024-09-20→2025-09-22 | **−40.57%** | −40.42% | +67.53% | −0.44 | −61.59% | −67.97% | · | 354 | 4,046 |
| 10 ◈ | 2023-09-22→2025-09-22 | −36.80% | −20.49% | 2025-09-22→2026-09-22 | **+47.65%** | +47.69% | +72.77% | +0.91 | −45.89% | +36.59% | · | 344 | 12,565 |

## Summary

* validate windows: **10**, win rate **60%**
* mean validate return **+57.10%** (median +13.03%, worst −40.57%, best +389.32%)
* mean validate CAGR **+57.02%** vs mean train CAGR +36.03% → decay **+21.00%**
* mean validate Sharpe +0.59, worst validate max drawdown −61.59%
* 3399 fill(s) inside validate windows
* runtime 992.2s (scratch 39.3s, screen 25.2s)

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

