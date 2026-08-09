# Template Top 5 — walk-forward re-validation

_`template_top5` · template_top5 · weekly cadence · verdict **WATCH** · generated 2026-08-09T06:43:24+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-07. Each fold is an independent replay starting at $39,000. Span 2018-08-07 → 2026-08-07 (2011 sessions); data floor 1994-01-27; screen source `hist` (798,415 passing rows).

**Pre-registered expectation.** Concentrated momentum: higher return and higher drawdown than the broad benchmark in risk-on regimes.

**Pre-registered kill criterion.** Trails ew_benchmark by >15% over any rolling 6 months, or max drawdown exceeds 40%.

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess +29.98%, latest +15.25% → **WATCH**.

## Disclosures — read before any number below

1. **Survivor universe.** `prices` holds only tickers listed TODAY, so every
   name delisted, acquired or bankrupted inside a fold is absent entirely. The
   house lesson prices this at roughly **+7pp/yr of fake return** for a
   screen-driven book. That is WHY the headline comparison here is **vs EW
   (same universe, same screen), fold by fold** — the bias is largely common to
   both sides of that difference. Absolute return is context, not evidence.
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

| Fold | Train window | Train ret | Train CAGR | Validate window | Validate ret | CAGR | Vol | Sharpe | Max DD | vs EW | vs SPY | Fills |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2018-08-07→2020-08-07 | +71.48% | +30.93% | 2020-08-07→2021-08-06 | **+409.05%** | +411.90% | +86.73% | +2.30 | −32.44% | +286.26% | +376.32% | 328 |
| 2 | 2019-08-07→2021-08-06 | +789.91% | +198.54% | 2021-08-06→2022-08-05 | **−14.91%** | −14.96% | +54.43% | −0.02 | −44.78% | −2.30% | −9.85% | 345 |
| 3 | 2020-08-07→2022-08-05 | +320.77% | +105.63% | 2022-08-05→2023-08-07 | **+2.55%** | +2.53% | +42.47% | +0.27 | −30.79% | −5.83% | −7.73% | 352 |
| 4 | 2021-08-09→2023-08-07 | −12.15% | −6.29% | 2023-08-07→2024-08-07 | **−37.30%** | −37.24% | +55.53% | −0.56 | −51.02% | −29.85% | −53.44% | 349 |
| 5 | 2022-08-08→2024-08-07 | −38.51% | −21.60% | 2024-08-07→2025-08-07 | **−51.81%** | −51.83% | +66.42% | −0.77 | −69.02% | −83.67% | −74.49% | 345 |
| 6 ◈ | 2023-08-07→2025-08-07 | −69.16% | −44.44% | 2025-08-07→2026-08-07 | **+47.97%** | +48.01% | +72.95% | +0.91 | −46.00% | +15.25% | +25.06% | 331 |

## Summary

* validate windows: **6**, win rate **50%**
* mean validate return **+59.26%** (median −6.18%, worst −51.81%, best +409.05%)
* mean validate CAGR **+59.74%** vs mean train CAGR +43.79% → decay **+15.94%**
* mean validate Sharpe +0.35, worst validate max drawdown −69.02%
* 2050 fill(s) inside validate windows
* runtime 270.7s (scratch 11.1s, screen 14.5s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

