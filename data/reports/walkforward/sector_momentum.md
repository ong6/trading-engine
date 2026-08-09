# Sector ETF Rotation — walk-forward re-validation

_`sector_momentum` · sector_momentum · monthly cadence · verdict **REVIEW** · generated 2026-08-09T06:09:13+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-07. Each fold is an independent replay starting at $39,000. Span 2018-08-07 → 2026-08-07 (2011 sessions); data floor 2016-10-07; screen source `not-used`.

**Pre-registered expectation.** Market-like return with lower drawdown — it wins by losing less in downturns, not by out-running the index.

**Pre-registered kill criterion.** Trails spy_benchmark by >10% over 12 months without delivering a lower max drawdown.

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess −13.63%, latest −5.61% → **REVIEW**.

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
| 1 | 2018-08-07→2020-08-07 | +7.17% | +3.52% | 2020-08-07→2021-08-06 | **+23.68%** | +23.77% | +18.04% | +1.27 | −10.92% | −99.10% | −9.04% | 39 |
| 2 | 2019-08-07→2021-08-06 | +34.12% | +15.82% | 2021-08-06→2022-08-05 | **+12.08%** | +12.12% | +18.67% | +0.71 | −14.86% | +24.68% | +17.14% | 49 |
| 3 | 2020-08-07→2022-08-05 | +28.84% | +13.56% | 2022-08-05→2023-08-07 | **+6.95%** | +6.92% | +15.13% | +0.52 | −13.21% | −1.42% | −3.32% | 38 |
| 4 | 2021-08-09→2023-08-07 | +16.76% | +8.08% | 2023-08-07→2024-08-07 | **+4.92%** | +4.91% | +13.92% | +0.41 | −9.36% | +12.37% | −11.22% | 36 |
| 5 | 2022-08-08→2024-08-07 | +11.29% | +5.50% | 2024-08-07→2025-08-07 | **+19.17%** | +19.19% | +17.39% | +1.10 | −17.18% | −12.69% | −3.51% | 42 |
| 6 ◈ | 2023-08-07→2025-08-07 | +24.23% | +11.45% | 2025-08-07→2026-08-07 | **+27.10%** | +27.12% | +13.56% | +1.84 | −7.91% | −5.61% | +4.20% | 40 |

## Summary

* validate windows: **6**, win rate **100%**
* mean validate return **+15.65%** (median +15.62%, worst +4.92%, best +27.10%)
* mean validate CAGR **+15.67%** vs mean train CAGR +9.66% → decay **+6.02%**
* mean validate Sharpe +0.98, worst validate max drawdown −17.18%
* 244 fill(s) inside validate windows
* runtime 195.0s (scratch 11.2s, screen 0.0s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

