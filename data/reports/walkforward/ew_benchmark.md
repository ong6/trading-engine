# Equal-Weight Benchmark — walk-forward re-validation

_`ew_benchmark` · ew_benchmark · monthly cadence · verdict **reference** · generated 2026-08-04T23:59:21+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-04. Each fold is an independent replay starting at $39,000. Span 2018-08-06 → 2026-08-04 (2009 sessions); data floor 1994-01-27; screen source `hist` (796,840 passing rows).

**Pre-registered expectation.** Captures the screen's breadth; the bar every active strategy must clear.

**Pre-registered kill criterion.** Reference benchmark — not killed.

**Measured against `ew_benchmark` on the same folds:** beats it in 0% of 6 window(s), mean excess +0.00%, latest +0.00% → **reference**.

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
| 1 | 2018-08-06→2020-08-04 | +22.80% | +10.84% | 2020-08-04→2021-08-04 | **+117.21%** | +117.33% | +44.34% | +1.97 | −22.59% | +0.00% | +83.76% | 850 |
| 2 | 2019-08-05→2021-08-04 | +172.88% | +65.25% | 2021-08-04→2022-08-04 | **−12.33%** | −12.34% | +36.97% | −0.17 | −34.16% | +0.00% | −8.16% | 886 |
| 3 | 2020-08-04→2022-08-04 | +86.39% | +36.56% | 2022-08-04→2023-08-04 | **+11.09%** | +11.10% | +24.72% | +0.55 | −15.77% | +0.00% | +1.92% | 859 |
| 4 | 2021-08-04→2023-08-04 | −7.44% | −3.79% | 2023-08-04→2024-08-02 | **−3.56%** | −3.57% | +30.54% | +0.03 | −17.45% | +0.00% | −23.68% | 829 |
| 5 | 2022-08-04→2024-08-02 | +1.65% | +0.82% | 2024-08-02→2025-08-04 | **+27.93%** | +27.78% | +37.50% | +0.85 | −33.25% | +0.00% | +8.77% | 850 |
| 6 ◈ | 2023-08-04→2025-08-04 | +25.81% | +12.15% | 2025-08-04→2026-08-04 | **+30.43%** | +30.45% | +56.56% | +0.76 | −36.48% | +0.00% | +7.69% | 909 |

## Summary

* validate windows: **6**, win rate **67%**
* mean validate return **+28.46%** (median +19.51%, worst −12.33%, best +117.21%)
* mean validate CAGR **+28.46%** vs mean train CAGR +20.30% → decay **+8.15%**
* mean validate Sharpe +0.67, worst validate max drawdown −36.48%
* 5183 fill(s) inside validate windows
* runtime 779.7s (scratch 11.2s, screen 14.6s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

