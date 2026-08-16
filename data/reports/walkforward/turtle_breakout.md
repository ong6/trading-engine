# Turtle Breakout (ATR-stopped) — walk-forward re-validation

_`turtle_breakout` · turtle_breakout · daily cadence · verdict **REVIEW** · generated 2026-08-16T08:06:31+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-14. Each fold is an independent replay starting at $39,000. Span 2018-08-14 → 2026-08-14 (2011 sessions); data floor 1994-01-27; screen source `hist` (799,705 passing rows).

**Pre-registered expectation.** Positive-skew trend capture: roughly a 40% win rate with the winners carrying the book, and drawdown well below Template Top 5 thanks to ATR sizing and the trail.

**Pre-registered kill criterion.** Max drawdown exceeds 25%, or trails ew_benchmark by >15% over any rolling 6 months.

**Measured against `ew_benchmark` on the same folds:** beats it in 17% of 6 window(s), mean excess −25.37%, latest −39.53% → **REVIEW**.

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
| 1 | 2018-08-14→2020-08-14 | −9.07% | −4.64% | 2020-08-14→2021-08-13 | **+53.50%** | +53.72% | +36.27% | +1.36 | −17.02% | −77.62% | +20.67% | 164 |
| 2 | 2019-08-14→2021-08-13 | +54.24% | +24.21% | 2021-08-13→2022-08-12 | **−9.53%** | −9.56% | +23.42% | −0.31 | −26.38% | −1.56% | −6.73% | 114 |
| 3 | 2020-08-14→2022-08-12 | +42.34% | +19.38% | 2022-08-12→2023-08-14 | **−7.70%** | −7.66% | +15.71% | −0.43 | −13.34% | −7.62% | −13.96% | 97 |
| 4 | 2021-08-16→2023-08-14 | −11.73% | −6.07% | 2023-08-14→2024-08-14 | **+4.23%** | +4.22% | +25.68% | +0.29 | −23.14% | +2.78% | −17.91% | 167 |
| 5 | 2022-08-15→2024-08-14 | −3.80% | −1.92% | 2024-08-14→2025-08-14 | **−3.58%** | −3.59% | +25.37% | −0.02 | −31.00% | −28.69% | −23.01% | 157 |
| 6 ◈ | 2023-08-14→2025-08-14 | −10.03% | −5.14% | 2025-08-14→2026-08-14 | **−5.86%** | −5.86% | +30.15% | −0.05 | −29.03% | −39.53% | −26.90% | 160 |

## Summary

* validate windows: **6**, win rate **33%**
* mean validate return **+5.18%** (median −4.72%, worst −9.53%, best +53.50%)
* mean validate CAGR **+5.21%** vs mean train CAGR +4.30% → decay **+0.91%**
* mean validate Sharpe +0.14, worst validate max drawdown −31.00%
* 859 fill(s) inside validate windows
* runtime 880.0s (scratch 11.6s, screen 14.2s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

