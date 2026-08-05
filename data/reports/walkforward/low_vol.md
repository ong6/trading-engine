# Low-Volatility Defensive — walk-forward re-validation

_`low_vol` · low_vol · monthly cadence · verdict **REVIEW** · generated 2026-08-04T23:23:47+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-04. Each fold is an independent replay starting at $39,000. Span 2018-08-06 → 2026-08-04 (2009 sessions); data floor 1994-01-27; screen source `not-used`.

**Pre-registered expectation.** Market-like return at noticeably lower volatility; expect it to lag melt-ups and hold up in selloffs.

**Pre-registered kill criterion.** Realized volatility is not below spy_benchmark's over 6 months, or max drawdown exceeds SPY's in the same window.

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess −17.67%, latest −23.18% → **REVIEW**.

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
| 1 | 2018-08-06→2020-08-04 | +14.71% | +7.12% | 2020-08-04→2021-08-04 | **+25.28%** | +25.30% | +10.27% | +2.25 | −5.23% | −91.93% | −8.17% | 216 |
| 2 | 2019-08-05→2021-08-04 | +25.36% | +11.97% | 2021-08-04→2022-08-04 | **+5.82%** | +5.82% | +11.82% | +0.54 | −10.74% | +18.15% | +9.99% | 197 |
| 3 | 2020-08-04→2022-08-04 | +32.10% | +14.95% | 2022-08-04→2023-08-04 | **−1.39%** | −1.39% | +11.53% | −0.06 | −13.95% | −12.48% | −10.56% | 198 |
| 4 | 2021-08-04→2023-08-04 | +2.81% | +1.40% | 2023-08-04→2024-08-02 | **+13.46%** | +13.51% | +7.68% | +1.70 | −6.21% | +17.02% | −6.66% | 167 |
| 5 | 2022-08-04→2024-08-02 | +17.21% | +8.28% | 2024-08-02→2025-08-04 | **+14.32%** | +14.25% | +12.29% | +1.16 | −8.22% | −13.61% | −4.84% | 204 |
| 6 ◈ | 2023-08-04→2025-08-04 | +32.34% | +15.03% | 2025-08-04→2026-08-04 | **+7.25%** | +7.25% | +9.14% | +0.81 | −5.54% | −23.18% | −15.49% | 189 |

## Summary

* validate windows: **6**, win rate **83%**
* mean validate return **+10.79%** (median +10.36%, worst −1.39%, best +25.28%)
* mean validate CAGR **+10.79%** vs mean train CAGR +9.79% → decay **+1.00%**
* mean validate Sharpe +1.06, worst validate max drawdown −13.95%
* 1171 fill(s) inside validate windows
* runtime 359.6s (scratch 11.1s, screen 0.0s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

