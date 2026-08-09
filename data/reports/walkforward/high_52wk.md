# 52-Week-High Momentum — walk-forward re-validation

_`high_52wk` · high_52wk · monthly cadence · verdict **REVIEW** · generated 2026-08-09T06:18:28+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-07. Each fold is an independent replay starting at $39,000. Span 2018-08-07 → 2026-08-07 (2011 sessions); data floor 1994-01-27; screen source `not-used`.

**Pre-registered expectation.** Momentum-like returns without the long-run reversal that dogs raw RS ranking, and lower churn than the RS books.

**Pre-registered kill criterion.** Trails ew_benchmark by >15% over any rolling 6 months, or max drawdown exceeds 35%.

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess −19.31%, latest −13.39% → **REVIEW**.

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
| 1 | 2018-08-07→2020-08-07 | +13.35% | +6.46% | 2020-08-07→2021-08-06 | **+20.26%** | +20.34% | +18.80% | +1.08 | −10.42% | −102.52% | −12.46% | 526 |
| 2 | 2019-08-07→2021-08-06 | +43.31% | +19.73% | 2021-08-06→2022-08-05 | **+3.32%** | +3.33% | +16.58% | +0.28 | −11.68% | +15.93% | +8.38% | 506 |
| 3 | 2020-08-07→2022-08-05 | +23.57% | +11.20% | 2022-08-05→2023-08-07 | **−14.81%** | −14.75% | +19.36% | −0.74 | −21.54% | −23.19% | −25.09% | 502 |
| 4 | 2021-08-09→2023-08-07 | −15.29% | −7.99% | 2023-08-07→2024-08-07 | **+7.45%** | +7.44% | +11.76% | +0.67 | −7.63% | +14.90% | −8.69% | 524 |
| 5 | 2022-08-08→2024-08-07 | −6.52% | −3.32% | 2024-08-07→2025-08-07 | **+24.28%** | +24.30% | +13.56% | +1.68 | −8.72% | −7.59% | +1.59% | 526 |
| 6 ◈ | 2023-08-07→2025-08-07 | +33.31% | +15.45% | 2025-08-07→2026-08-07 | **+19.33%** | +19.35% | +16.07% | +1.18 | −11.67% | −13.39% | −3.57% | 562 |

## Summary

* validate windows: **6**, win rate **83%**
* mean validate return **+9.97%** (median +13.39%, worst −14.81%, best +24.28%)
* mean validate CAGR **+10.00%** vs mean train CAGR +6.92% → decay **+3.08%**
* mean validate Sharpe +0.69, worst validate max drawdown −21.54%
* 3146 fill(s) inside validate windows
* runtime 399.3s (scratch 11.3s, screen 0.0s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

