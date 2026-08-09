# Dual Momentum (GEM) — walk-forward re-validation

_`dual_momentum` · dual_momentum · monthly cadence · verdict **REVIEW** · generated 2026-08-09T06:03:10+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-07. Each fold is an independent replay starting at $39,000. Span 2018-08-07 → 2026-08-07 (2011 sessions); data floor 2008-05-29; screen source `not-used`.

**Pre-registered expectation.** Lower drawdown than buy-and-hold via the cash switch; lags in strong bull runs.

**Pre-registered kill criterion.** Underperforms spy_benchmark by >20% over 2 years while not delivering a lower max drawdown.

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess −15.61%, latest −5.49% → **REVIEW**.

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
| 1 | 2018-08-07→2020-08-07 | −14.43% | −7.49% | 2020-08-07→2021-08-06 | **+33.95%** | +34.09% | +14.80% | +2.06 | −9.38% | −88.83% | +1.23% | 1 |
| 2 | 2019-08-07→2021-08-06 | +28.16% | +13.22% | 2021-08-06→2022-08-05 | **−5.30%** | −5.31% | +17.58% | −0.22 | −18.13% | +7.31% | −0.24% | 2 |
| 3 | 2020-08-07→2022-08-05 | +21.17% | +10.11% | 2022-08-05→2023-08-07 | **−2.46%** | −2.45% | +4.86% | −0.49 | −4.99% | −10.83% | −12.74% | 5 |
| 4 | 2021-08-09→2023-08-07 | −9.77% | −5.03% | 2023-08-07→2024-08-07 | **+14.13%** | +14.10% | +12.30% | +1.14 | −9.52% | +21.58% | −2.01% | 5 |
| 5 | 2022-08-08→2024-08-07 | +11.31% | +5.51% | 2024-08-07→2025-08-07 | **+14.47%** | +14.48% | +19.97% | +0.78 | −18.75% | −17.40% | −8.22% | 9 |
| 6 ◈ | 2023-08-07→2025-08-07 | +31.64% | +14.72% | 2025-08-07→2026-08-07 | **+27.23%** | +27.25% | +14.86% | +1.70 | −11.41% | −5.49% | +4.32% | 12 |

## Summary

* validate windows: **6**, win rate **67%**
* mean validate return **+13.67%** (median +14.30%, worst −5.30%, best +33.95%)
* mean validate CAGR **+13.69%** vs mean train CAGR +5.17% → decay **+8.52%**
* mean validate Sharpe +0.83, worst validate max drawdown −18.75%
* 34 fill(s) inside validate windows
* runtime 187.5s (scratch 12.1s, screen 0.0s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

