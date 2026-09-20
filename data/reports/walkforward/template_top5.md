# Template Top 5 — walk-forward re-validation

_`template_top5` · template_top5 · weekly cadence · verdict **PASS** · generated 2026-09-20T06:25:09+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-09-18. Each fold is an independent replay starting at $39,000. Span 2014-09-18 → 2026-09-18 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,116,920 passing rows).

**Provenance.** Source `158dd063aa57e6e37448fdf630ca3e2f244043f4d1bd2520a7b30edcc76b2371`; config `98bb6fc4717af8df5153bf49b309de631bb087d5debc3465a0197a4a640b647f`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `c868f4fcc1655450840ca9fb0f244fb9c3c708ec50ec181d46905f33faba08b8`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Concentrated momentum: higher return and higher drawdown than the broad benchmark in risk-on regimes.

**Pre-registered kill criterion.** Trails ew_benchmark by >15% over any rolling 6 months, or max drawdown exceeds 40%.

**Measured against `ew_benchmark` on the same folds:** beats it in 50% of 10 window(s), mean excess +28.68%, latest +38.11% → **PASS**.

**90% CI on mean excess vs `ew_benchmark`:** [−10.18%, +74.82%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-09-18→2016-09-16 | −38.20% | −21.43% | 2016-09-16→2017-09-18 | **+24.17%** | +24.04% | +33.94% | +0.81 | −20.28% | +5.40% | · | 324 | 2,752 |
| 2 | 2015-09-18→2017-09-18 | −16.69% | −8.72% | 2017-09-18→2018-09-18 | **+74.67%** | +74.73% | +40.84% | +1.57 | −22.07% | +32.62% | · | 323 | 2,902 |
| 3 | 2016-09-19→2018-09-18 | +112.82% | +46.00% | 2018-09-18→2019-09-18 | **−24.12%** | −24.13% | +40.59% | −0.48 | −54.28% | −8.99% | · | 359 | 3,014 |
| 4 | 2017-09-18→2019-09-18 | +34.09% | +15.81% | 2019-09-18→2020-09-18 | **+144.27%** | +143.82% | +62.51% | +1.73 | −44.01% | +103.21% | · | 356 | 3,143 |
| 5 | 2018-09-18→2020-09-18 | +91.56% | +38.37% | 2020-09-18→2021-09-17 | **+375.94%** | +378.50% | +84.28% | +2.26 | −33.63% | +240.98% | · | 326 | 3,398 |
| 6 | 2019-09-18→2021-09-17 | +979.58% | +228.84% | 2021-09-17→2022-09-16 | **−25.56%** | −25.63% | +51.58% | −0.32 | −39.75% | −11.24% | · | 323 | 3,555 |
| 7 | 2020-09-18→2022-09-16 | +329.10% | +107.67% | 2022-09-16→2023-09-18 | **−21.46%** | −21.37% | +43.55% | −0.34 | −30.87% | −19.76% | · | 363 | 3,663 |
| 8 | 2021-09-20→2023-09-18 | −41.88% | −23.83% | 2023-09-18→2024-09-18 | **−6.35%** | −6.34% | +56.13% | +0.16 | −42.54% | −24.56% | · | 336 | 3,837 |
| 9 | 2022-09-19→2024-09-18 | −16.71% | −8.74% | 2024-09-18→2025-09-18 | **−44.20%** | −44.23% | +67.42% | −0.53 | −61.59% | −68.95% | · | 348 | 4,045 |
| 10 ◈ | 2023-09-18→2025-09-18 | −40.35% | −22.76% | 2025-09-18→2026-09-18 | **+53.33%** | +53.37% | +72.61% | +0.96 | −45.89% | +38.11% | · | 342 | 12,565 |

## Summary

* validate windows: **10**, win rate **50%**
* mean validate return **+55.07%** (median +8.91%, worst −44.20%, best +375.94%)
* mean validate CAGR **+55.28%** vs mean train CAGR +35.12% → decay **+20.16%**
* mean validate Sharpe +0.58, worst validate max drawdown −61.59%
* 3400 fill(s) inside validate windows
* runtime 942.9s (scratch 45.3s, screen 26.2s)

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

