# SPY Buy & Hold — walk-forward re-validation

_`spy_benchmark` · spy_benchmark · once cadence · verdict **reference** · generated 2026-08-09T06:11:48+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-07. Each fold is an independent replay starting at $39,000. Span 2018-08-07 → 2026-08-07 (2011 sessions); data floor 1994-01-27; screen source `not-used`.

**Pre-registered expectation.** Baseline market return; the absolute-return yardstick.

**Pre-registered kill criterion.** Reference benchmark — not killed.

**Measured against `ew_benchmark` on the same folds:** beats it in 50% of 6 window(s), mean excess −12.67%, latest −9.81% → **reference**.

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
| 1 | 2018-08-07→2020-08-07 | +20.94% | +9.96% | 2020-08-07→2021-08-06 | **+32.72%** | +32.85% | +14.33% | +2.06 | −9.12% | −90.06% | +0.00% | 0 |
| 2 | 2019-08-07→2021-08-06 | +56.31% | +25.04% | 2021-08-06→2022-08-05 | **−5.06%** | −5.08% | +19.74% | −0.17 | −22.24% | +7.55% | +0.00% | 0 |
| 3 | 2020-08-07→2022-08-05 | +26.67% | +12.59% | 2022-08-05→2023-08-07 | **+10.28%** | +10.22% | +18.05% | +0.63 | −16.18% | +1.90% | +0.00% | 0 |
| 4 | 2021-08-09→2023-08-07 | +4.55% | +2.26% | 2023-08-07→2024-08-07 | **+16.14%** | +16.11% | +11.77% | +1.33 | −8.39% | +23.59% | +0.00% | 0 |
| 5 | 2022-08-08→2024-08-07 | +28.91% | +13.55% | 2024-08-07→2025-08-07 | **+22.68%** | +22.70% | +19.31% | +1.16 | −18.20% | −9.18% | +0.00% | 0 |
| 6 ◈ | 2023-08-07→2025-08-07 | +43.87% | +19.93% | 2025-08-07→2026-08-07 | **+22.91%** | +22.92% | +12.51% | +1.72 | −8.63% | −9.81% | +0.00% | 0 |

## Summary

* validate windows: **6**, win rate **83%**
* mean validate return **+16.61%** (median +19.41%, worst −5.06%, best +32.72%)
* mean validate CAGR **+16.62%** vs mean train CAGR +13.89% → decay **+2.73%**
* mean validate Sharpe +1.12, worst validate max drawdown −22.24%
* 0 fill(s) inside validate windows
* runtime 154.8s (scratch 11.4s, screen 0.0s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

