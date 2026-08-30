# Template Top 5 (regime-gated) — walk-forward re-validation

_`template_top5_gated` · template_top5 · weekly cadence · verdict **PASS** · generated 2026-08-30T06:27:34+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-08-28. Each fold is an independent replay starting at $39,000. Span 2014-08-28 → 2026-08-28 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,106,099 passing rows).

**Pre-registered expectation.** Same upside as top5 in risk-on, materially lower drawdown in bear markets (drifts to cash).

**Pre-registered kill criterion.** Does not reduce max drawdown vs ungated top5 across a full risk-off episode.

**Measured against `ew_benchmark` on the same folds:** beats it in 50% of 10 window(s), mean excess +23.38%, latest −6.85% → **PASS**.

**90% CI on mean excess vs `ew_benchmark`:** [−14.65%, +79.29%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
   lose money.** That is WHY the headline comparison here is **vs EW (same
   universe, same screen), fold by fold** — the bias is largely common to both
   sides of that difference. Absolute return is context, not evidence, and a fold
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
| 1 | 2014-08-28→2016-08-26 | −8.88% | −4.55% | 2016-08-26→2017-08-28 | **+12.58%** | +12.51% | +35.35% | +0.51 | −19.49% | +4.25% | −1.56% | 329 | 2,684 |
| 2 | 2015-08-28→2017-08-28 | +36.34% | +16.75% | 2017-08-28→2018-08-28 | **+66.49%** | +66.55% | +40.63% | +1.46 | −23.33% | +23.72% | +46.74% | 322 | 2,827 |
| 3 | 2016-08-29→2018-08-28 | +83.55% | +35.57% | 2018-08-28→2019-08-28 | **+1.37%** | +1.37% | +30.17% | +0.20 | −37.40% | +0.87% | −0.09% | 218 | 2,933 |
| 4 | 2017-08-28→2019-08-28 | +65.39% | +28.63% | 2019-08-28→2020-08-28 | **+54.32%** | +54.18% | +47.17% | +1.15 | −31.76% | +29.46% | +31.89% | 250 | 3,049 |
| 5 | 2018-08-28→2020-08-28 | +49.16% | +22.12% | 2020-08-28→2021-08-27 | **+417.96%** | +420.90% | +86.60% | +2.32 | −32.49% | +289.65% | +388.87% | 337 | 3,294 |
| 6 | 2019-08-28→2021-08-27 | +748.10% | +191.44% | 2021-08-27→2022-08-26 | **−13.77%** | −13.81% | +40.88% | −0.16 | −45.74% | −5.62% | −5.33% | 188 | 3,438 |
| 7 | 2020-08-28→2022-08-26 | +356.82% | +114.29% | 2022-08-26→2023-08-28 | **−22.62%** | −22.53% | +37.34% | −0.51 | −32.62% | −14.18% | −33.17% | 218 | 3,552 |
| 8 | 2021-08-30→2023-08-28 | −38.39% | −21.57% | 2023-08-28→2024-08-28 | **−11.22%** | −11.20% | +56.51% | +0.07 | −43.89% | −25.92% | −38.10% | 328 | 3,713 |
| 9 | 2022-08-29→2024-08-28 | −31.41% | −17.19% | 2024-08-28→2025-08-28 | **−40.33%** | −40.35% | +60.64% | −0.55 | −51.01% | −61.60% | −57.44% | 285 | 3,905 |
| 10 ◈ | 2023-08-28→2025-08-28 | −46.63% | −26.93% | 2025-08-28→2026-08-28 | **+20.75%** | +20.76% | +70.81% | +0.63 | −45.99% | −6.85% | +1.45% | 320 | 12,105 |

## Summary

* validate windows: **10**, win rate **60%**
* mean validate return **+48.55%** (median +6.98%, worst −40.33%, best +417.96%)
* mean validate CAGR **+48.84%** vs mean train CAGR +33.85% → decay **+14.99%**
* mean validate Sharpe +0.51, worst validate max drawdown −51.01%
* 2795 fill(s) inside validate windows
* runtime 621.3s (scratch 19.5s, screen 25.7s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.


**The interval is new information, not a new rule (added 2026-08-20).** The
PASS / WATCH / REVIEW rule above is unchanged: it still reads the beat rate and
the *mean* excess exactly as it was pre-registered, and no verdict in this
report has been recomputed, softened or overridden by an interval. What is new
is the **90% bootstrap CI on mean excess vs EW** in the column beside it, and a
mechanical `INDISTINGUISHABLE` label for any book whose interval contains 0.

Read the two together: a **PASS whose interval straddles zero is a PASS on a
number this evidence cannot separate from the benchmark**, and a REVIEW whose
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

