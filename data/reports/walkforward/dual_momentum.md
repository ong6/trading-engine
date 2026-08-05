# Dual Momentum (GEM) — walk-forward re-validation

_`dual_momentum` · dual_momentum · monthly cadence · verdict **REVIEW** · generated 2026-08-04T23:01:40+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-04. Each fold is an independent replay starting at $39,000. Span 2018-08-06 → 2026-08-04 (2009 sessions); data floor 2008-05-29; screen source `not-used`.

**Pre-registered expectation.** Lower drawdown than buy-and-hold via the cash switch; lags in strong bull runs.

**Pre-registered kill criterion.** Underperforms spy_benchmark by >20% over 2 years while not delivering a lower max drawdown.

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess −14.74%, latest −4.43% → **REVIEW**.

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
| 1 | 2018-08-06→2020-08-04 | −15.57% | −8.13% | 2020-08-04→2021-08-04 | **+34.70%** | +34.73% | +14.78% | +2.09 | −9.38% | −82.51% | +1.26% | 1 |
| 2 | 2019-08-05→2021-08-04 | +27.15% | +12.77% | 2021-08-04→2022-08-04 | **−4.54%** | −4.54% | +17.56% | −0.18 | −18.13% | +7.79% | −0.37% | 2 |
| 3 | 2020-08-04→2022-08-04 | +21.17% | +10.09% | 2022-08-04→2023-08-04 | **−3.28%** | −3.28% | +4.79% | −0.67 | −4.99% | −14.37% | −12.44% | 5 |
| 4 | 2021-08-04→2023-08-04 | −10.52% | −5.41% | 2023-08-04→2024-08-02 | **+18.24%** | +18.31% | +11.96% | +1.47 | −9.52% | +21.80% | −1.88% | 5 |
| 5 | 2022-08-04→2024-08-02 | +14.35% | +6.95% | 2024-08-02→2025-08-04 | **+11.23%** | +11.17% | +20.20% | +0.63 | −18.75% | −16.70% | −7.93% | 9 |
| 6 ◈ | 2023-08-04→2025-08-04 | +31.41% | +14.62% | 2025-08-04→2026-08-04 | **+26.00%** | +26.02% | +14.86% | +1.64 | −11.41% | −4.43% | +3.26% | 12 |

## Summary

* validate windows: **6**, win rate **67%**
* mean validate return **+13.73%** (median +14.73%, worst −4.54%, best +34.70%)
* mean validate CAGR **+13.74%** vs mean train CAGR +5.15% → decay **+8.59%**
* mean validate Sharpe +0.83, worst validate max drawdown −18.75%
* 34 fill(s) inside validate windows
* runtime 162.6s (scratch 11.5s, screen 0.0s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

