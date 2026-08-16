# Template Top 5 — walk-forward re-validation

_`template_top5` · template_top5 · weekly cadence · verdict **WATCH** · generated 2026-08-16T06:41:39+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-14. Each fold is an independent replay starting at $39,000. Span 2018-08-14 → 2026-08-14 (2011 sessions); data floor 1994-01-27; screen source `hist` (799,705 passing rows).

**Pre-registered expectation.** Concentrated momentum: higher return and higher drawdown than the broad benchmark in risk-on regimes.

**Pre-registered kill criterion.** Trails ew_benchmark by >15% over any rolling 6 months, or max drawdown exceeds 40%.

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess +32.85%, latest +35.11% → **WATCH**.

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
| 1 | 2018-08-14→2020-08-14 | +71.88% | +31.08% | 2020-08-14→2021-08-13 | **+415.85%** | +418.76% | +86.54% | +2.32 | −32.49% | +284.73% | +383.02% | 328 |
| 2 | 2019-08-14→2021-08-13 | +808.25% | +201.60% | 2021-08-13→2022-08-12 | **−12.69%** | −12.73% | +54.47% | +0.02 | −44.78% | −4.72% | −9.90% | 344 |
| 3 | 2020-08-14→2022-08-12 | +357.33% | +114.41% | 2022-08-12→2023-08-14 | **−1.31%** | −1.30% | +43.05% | +0.18 | −30.79% | −1.23% | −7.57% | 351 |
| 4 | 2021-08-16→2023-08-14 | −6.66% | −3.40% | 2023-08-14→2024-08-14 | **−33.12%** | −33.06% | +55.53% | −0.45 | −50.24% | −34.57% | −55.25% | 347 |
| 5 | 2022-08-15→2024-08-14 | −35.97% | −19.99% | 2024-08-14→2025-08-14 | **−57.09%** | −57.11% | +66.41% | −0.95 | −68.96% | −82.20% | −76.51% | 346 |
| 6 ◈ | 2023-08-14→2025-08-14 | −68.25% | −43.63% | 2025-08-14→2026-08-14 | **+68.78%** | +68.85% | +72.57% | +1.09 | −45.98% | +35.11% | +47.75% | 330 |

## Summary

* validate windows: **6**, win rate **33%**
* mean validate return **+63.41%** (median −7.00%, worst −57.09%, best +415.85%)
* mean validate CAGR **+63.90%** vs mean train CAGR +46.68% → decay **+17.22%**
* mean validate Sharpe +0.37, worst validate max drawdown −68.96%
* 2046 fill(s) inside validate windows
* runtime 269.2s (scratch 11.8s, screen 14.3s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

