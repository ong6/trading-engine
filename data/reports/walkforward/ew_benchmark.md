# Equal-Weight Benchmark — walk-forward re-validation

_`ew_benchmark` · ew_benchmark · monthly cadence · verdict **reference** · generated 2026-08-09T07:17:49+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-07. Each fold is an independent replay starting at $39,000. Span 2018-08-07 → 2026-08-07 (2011 sessions); data floor 1994-01-27; screen source `hist` (798,415 passing rows).

**Pre-registered expectation.** Captures the screen's breadth; the bar every active strategy must clear.

**Pre-registered kill criterion.** Reference benchmark — not killed.

**Measured against `ew_benchmark` on the same folds:** beats it in 0% of 6 window(s), mean excess +0.00%, latest +0.00% → **reference**.

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
| 1 | 2018-08-07→2020-08-07 | +22.26% | +10.56% | 2020-08-07→2021-08-06 | **+122.78%** | +123.40% | +44.25% | +2.04 | −22.59% | +0.00% | +90.06% | 850 |
| 2 | 2019-08-07→2021-08-06 | +178.68% | +67.00% | 2021-08-06→2022-08-05 | **−12.61%** | −12.65% | +37.06% | −0.18 | −34.16% | +0.00% | −7.55% | 886 |
| 3 | 2020-08-07→2022-08-05 | +89.75% | +37.90% | 2022-08-05→2023-08-07 | **+8.37%** | +8.33% | +24.67% | +0.45 | −15.77% | +0.00% | −1.90% | 859 |
| 4 | 2021-08-09→2023-08-07 | −8.07% | −4.14% | 2023-08-07→2024-08-07 | **−7.45%** | −7.43% | +30.78% | −0.10 | −20.53% | +0.00% | −23.59% | 829 |
| 5 | 2022-08-08→2024-08-07 | −3.12% | −1.57% | 2024-08-07→2025-08-07 | **+31.86%** | +31.89% | +37.22% | +0.94 | −33.25% | +0.00% | +9.18% | 850 |
| 6 ◈ | 2023-08-07→2025-08-07 | +23.59% | +11.16% | 2025-08-07→2026-08-07 | **+32.72%** | +32.74% | +56.56% | +0.79 | −36.48% | +0.00% | +9.81% | 909 |

## Summary

* validate windows: **6**, win rate **67%**
* mean validate return **+29.28%** (median +20.12%, worst −12.61%, best +122.78%)
* mean validate CAGR **+29.38%** vs mean train CAGR +20.15% → decay **+9.23%**
* mean validate Sharpe +0.66, worst validate max drawdown −36.48%
* 5183 fill(s) inside validate windows
* runtime 599.0s (scratch 11.3s, screen 14.6s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

