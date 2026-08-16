# Sector ETF Rotation — walk-forward re-validation

_`sector_momentum` · sector_momentum · monthly cadence · verdict **WATCH** · generated 2026-08-16T06:09:13+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-14. Each fold is an independent replay starting at $39,000. Span 2018-08-14 → 2026-08-14 (2011 sessions); data floor 2016-10-07; screen source `not-used`.

**Pre-registered expectation.** Market-like return with lower drawdown — it wins by losing less in downturns, not by out-running the index.

**Pre-registered kill criterion.** Trails spy_benchmark by >10% over 12 months without delivering a lower max drawdown.

**Measured against `ew_benchmark` on the same folds:** beats it in 50% of 6 window(s), mean excess −14.41%, latest −4.98% → **WATCH**.

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
| 1 | 2018-08-14→2020-08-14 | +7.97% | +3.91% | 2020-08-14→2021-08-13 | **+23.78%** | +23.87% | +17.94% | +1.28 | −10.92% | −107.34% | −9.05% | 39 |
| 2 | 2019-08-14→2021-08-13 | +35.23% | +16.30% | 2021-08-13→2022-08-12 | **+15.67%** | +15.73% | +18.75% | +0.87 | −14.86% | +23.64% | +18.46% | 49 |
| 3 | 2020-08-14→2022-08-12 | +34.06% | +15.84% | 2022-08-12→2023-08-14 | **+1.50%** | +1.50% | +15.11% | +0.17 | −13.21% | +1.59% | −4.76% | 38 |
| 4 | 2021-08-16→2023-08-14 | +15.30% | +7.41% | 2023-08-14→2024-08-14 | **+11.61%** | +11.59% | +14.14% | +0.85 | −9.36% | +10.16% | −10.53% | 36 |
| 5 | 2022-08-15→2024-08-14 | +16.90% | +8.12% | 2024-08-14→2025-08-14 | **+15.59%** | +15.60% | +17.21% | +0.93 | −17.18% | −9.52% | −3.84% | 42 |
| 6 ◈ | 2023-08-14→2025-08-14 | +26.56% | +12.49% | 2025-08-14→2026-08-14 | **+28.69%** | +28.71% | +13.58% | +1.93 | −7.91% | −4.98% | +7.65% | 40 |

## Summary

* validate windows: **6**, win rate **100%**
* mean validate return **+16.14%** (median +15.63%, worst +1.50%, best +28.69%)
* mean validate CAGR **+16.16%** vs mean train CAGR +10.68% → decay **+5.49%**
* mean validate Sharpe +1.01, worst validate max drawdown −17.18%
* 244 fill(s) inside validate windows
* runtime 220.7s (scratch 11.2s, screen 0.0s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

