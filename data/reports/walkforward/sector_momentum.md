# Sector ETF Rotation — walk-forward re-validation

_`sector_momentum` · sector_momentum · monthly cadence · verdict **REVIEW** · generated 2026-08-04T23:08:28+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-04. Each fold is an independent replay starting at $39,000. Span 2018-08-06 → 2026-08-04 (2009 sessions); data floor 2016-10-07; screen source `not-used`.

**Pre-registered expectation.** Market-like return with lower drawdown — it wins by losing less in downturns, not by out-running the index.

**Pre-registered kill criterion.** Trails spy_benchmark by >10% over 12 months without delivering a lower max drawdown.

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess −12.66%, latest −4.08% → **REVIEW**.

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
| 1 | 2018-08-06→2020-08-04 | +5.60% | +2.77% | 2020-08-04→2021-08-04 | **+23.57%** | +23.58% | +18.05% | +1.26 | −10.92% | −93.65% | −9.88% | 39 |
| 2 | 2019-08-05→2021-08-04 | +32.04% | +14.92% | 2021-08-04→2022-08-04 | **+13.30%** | +13.31% | +18.66% | +0.76 | −14.86% | +25.63% | +17.47% | 49 |
| 3 | 2020-08-04→2022-08-04 | +28.22% | +13.24% | 2022-08-04→2023-08-04 | **+6.45%** | +6.46% | +15.11% | +0.49 | −13.21% | −4.63% | −2.71% | 38 |
| 4 | 2021-08-04→2023-08-04 | +15.66% | +7.55% | 2023-08-04→2024-08-02 | **+8.47%** | +8.50% | +13.58% | +0.67 | −9.36% | +12.02% | −11.66% | 36 |
| 5 | 2022-08-04→2024-08-02 | +13.95% | +6.76% | 2024-08-02→2025-08-04 | **+16.67%** | +16.58% | +17.71% | +0.97 | −17.18% | −11.27% | −2.49% | 42 |
| 6 ◈ | 2023-08-04→2025-08-04 | +24.53% | +11.58% | 2025-08-04→2026-08-04 | **+26.35%** | +26.37% | +13.57% | +1.80 | −7.91% | −4.08% | +3.61% | 40 |

## Summary

* validate windows: **6**, win rate **100%**
* mean validate return **+15.80%** (median +14.98%, worst +6.45%, best +26.35%)
* mean validate CAGR **+15.80%** vs mean train CAGR +9.47% → decay **+6.33%**
* mean validate Sharpe +0.99, worst validate max drawdown −17.18%
* 244 fill(s) inside validate windows
* runtime 248.1s (scratch 11.2s, screen 0.0s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

