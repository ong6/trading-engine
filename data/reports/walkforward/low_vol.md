# Low-Volatility Defensive — walk-forward re-validation

_`low_vol` · low_vol · monthly cadence · verdict **REVIEW** · generated 2026-08-09T06:26:39+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-07. Each fold is an independent replay starting at $39,000. Span 2018-08-07 → 2026-08-07 (2011 sessions); data floor 1994-01-27; screen source `not-used`.

**Pre-registered expectation.** Market-like return at noticeably lower volatility; expect it to lag melt-ups and hold up in selloffs.

**Pre-registered kill criterion.** Realized volatility is not below spy_benchmark's over 6 months, or max drawdown exceeds SPY's in the same window.

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess −18.64%, latest −25.98% → **REVIEW**.

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
| 1 | 2018-08-07→2020-08-07 | +15.56% | +7.50% | 2020-08-07→2021-08-06 | **+24.87%** | +24.97% | +10.29% | +2.22 | −5.23% | −97.91% | −7.85% | 216 |
| 2 | 2019-08-07→2021-08-06 | +25.95% | +12.23% | 2021-08-06→2022-08-05 | **+5.02%** | +5.03% | +11.83% | +0.47 | −10.74% | +17.62% | +10.08% | 197 |
| 3 | 2020-08-07→2022-08-05 | +31.79% | +14.85% | 2022-08-05→2023-08-07 | **−0.28%** | −0.27% | +11.56% | +0.03 | −13.95% | −8.65% | −10.55% | 198 |
| 4 | 2021-08-09→2023-08-07 | +3.59% | +1.79% | 2023-08-07→2024-08-07 | **+11.03%** | +11.01% | +8.05% | +1.34 | −6.21% | +18.48% | −5.11% | 167 |
| 5 | 2022-08-08→2024-08-07 | +15.57% | +7.51% | 2024-08-07→2025-08-07 | **+16.45%** | +16.46% | +12.01% | +1.34 | −8.22% | −15.42% | −6.24% | 204 |
| 6 ◈ | 2023-08-07→2025-08-07 | +32.91% | +15.28% | 2025-08-07→2026-08-07 | **+6.74%** | +6.74% | +9.14% | +0.76 | −5.54% | −25.98% | −16.17% | 188 |

## Summary

* validate windows: **6**, win rate **83%**
* mean validate return **+10.64%** (median +8.88%, worst −0.28%, best +24.87%)
* mean validate CAGR **+10.66%** vs mean train CAGR +9.86% → decay **+0.80%**
* mean validate Sharpe +1.03, worst validate max drawdown −13.95%
* 1170 fill(s) inside validate windows
* runtime 491.3s (scratch 11.5s, screen 0.0s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

