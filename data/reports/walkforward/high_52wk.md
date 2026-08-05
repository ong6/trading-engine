# 52-Week-High Momentum — walk-forward re-validation

_`high_52wk` · high_52wk · monthly cadence · verdict **REVIEW** · generated 2026-08-04T23:17:47+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-04. Each fold is an independent replay starting at $39,000. Span 2018-08-06 → 2026-08-04 (2009 sessions); data floor 1994-01-27; screen source `not-used`.

**Pre-registered expectation.** Momentum-like returns without the long-run reversal that dogs raw RS ranking, and lower churn than the RS books.

**Pre-registered kill criterion.** Trails ew_benchmark by >15% over any rolling 6 months, or max drawdown exceeds 35%.

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess −18.51%, latest −11.65% → **REVIEW**.

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
| 1 | 2018-08-06→2020-08-04 | +14.04% | +6.81% | 2020-08-04→2021-08-04 | **+19.66%** | +19.67% | +18.80% | +1.05 | −10.42% | −97.56% | −13.79% | 526 |
| 2 | 2019-08-05→2021-08-04 | +43.45% | +19.79% | 2021-08-04→2022-08-04 | **+2.50%** | +2.50% | +16.51% | +0.23 | −11.68% | +14.83% | +6.67% | 506 |
| 3 | 2020-08-04→2022-08-04 | +22.16% | +10.53% | 2022-08-04→2023-08-04 | **−14.45%** | −14.46% | +19.38% | −0.71 | −21.54% | −25.54% | −23.61% | 502 |
| 4 | 2021-08-04→2023-08-04 | −15.90% | −8.30% | 2023-08-04→2024-08-02 | **+10.70%** | +10.74% | +11.47% | +0.95 | −7.63% | +14.26% | −9.42% | 524 |
| 5 | 2022-08-04→2024-08-02 | −4.39% | −2.22% | 2024-08-02→2025-08-04 | **+22.55%** | +22.43% | +13.85% | +1.55 | −8.72% | −5.38% | +3.39% | 526 |
| 6 ◈ | 2023-08-04→2025-08-04 | +34.46% | +15.95% | 2025-08-04→2026-08-04 | **+18.78%** | +18.79% | +16.09% | +1.15 | −11.71% | −11.65% | −3.96% | 561 |

## Summary

* validate windows: **6**, win rate **83%**
* mean validate return **+9.96%** (median +14.74%, worst −14.45%, best +22.55%)
* mean validate CAGR **+9.95%** vs mean train CAGR +7.09% → decay **+2.85%**
* mean validate Sharpe +0.70, worst validate max drawdown −21.54%
* 3145 fill(s) inside validate windows
* runtime 383.3s (scratch 11.1s, screen 0.0s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

