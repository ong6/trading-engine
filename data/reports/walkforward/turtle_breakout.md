# Turtle Breakout (ATR-stopped) — walk-forward re-validation

_`turtle_breakout` · turtle_breakout · daily cadence · verdict **REVIEW** · generated 2026-08-05T00:30:37+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-04. Each fold is an independent replay starting at $39,000. Span 2018-08-06 → 2026-08-04 (2009 sessions); data floor 1994-01-27; screen source `hist` (796,840 passing rows).

**Pre-registered expectation.** Positive-skew trend capture: roughly a 40% win rate with the winners carrying the book, and drawdown well below Template Top 5 thanks to ATR sizing and the trail.

**Pre-registered kill criterion.** Max drawdown exceeds 25%, or trails ew_benchmark by >15% over any rolling 6 months.

**Measured against `ew_benchmark` on the same folds:** beats it in 17% of 6 window(s), mean excess −22.81%, latest −35.54% → **REVIEW**.

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
| 1 | 2018-08-06→2020-08-04 | −11.39% | −5.88% | 2020-08-04→2021-08-04 | **+59.77%** | +59.82% | +35.80% | +1.48 | −17.02% | −57.44% | +26.32% | 160 |
| 2 | 2019-08-05→2021-08-04 | +63.35% | +27.83% | 2021-08-04→2022-08-04 | **−13.59%** | −13.60% | +24.20% | −0.48 | −26.38% | −1.25% | −9.42% | 122 |
| 3 | 2020-08-04→2022-08-04 | +46.61% | +21.10% | 2022-08-04→2023-08-04 | **−6.62%** | −6.62% | +15.51% | −0.37 | −13.34% | −17.70% | −15.78% | 88 |
| 4 | 2021-08-04→2023-08-04 | −14.33% | −7.45% | 2023-08-04→2024-08-02 | **−0.50%** | −0.50% | +25.45% | +0.11 | −23.36% | +3.06% | −20.62% | 172 |
| 5 | 2022-08-04→2024-08-02 | −7.08% | −3.61% | 2024-08-02→2025-08-04 | **−0.07%** | −0.07% | +25.62% | +0.13 | −31.00% | −28.00% | −19.23% | 158 |
| 6 ◈ | 2023-08-04→2025-08-04 | −13.26% | −6.86% | 2025-08-04→2026-08-04 | **−5.11%** | −5.12% | +30.29% | −0.02 | −29.03% | −35.54% | −27.85% | 158 |

## Summary

* validate windows: **6**, win rate **17%**
* mean validate return **+5.65%** (median −2.81%, worst −13.59%, best +59.77%)
* mean validate CAGR **+5.65%** vs mean train CAGR +4.19% → decay **+1.47%**
* mean validate Sharpe +0.14, worst validate max drawdown −31.00%
* 858 fill(s) inside validate windows
* runtime 803.1s (scratch 10.9s, screen 14.8s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

