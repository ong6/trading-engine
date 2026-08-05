# Template Top 5 — walk-forward re-validation

_`template_top5` · template_top5 · weekly cadence · verdict **WATCH** · generated 2026-08-04T23:42:04+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-04. Each fold is an independent replay starting at $39,000. Span 2018-08-06 → 2026-08-04 (2009 sessions); data floor 1994-01-27; screen source `hist` (796,840 passing rows).

**Pre-registered expectation.** Concentrated momentum: higher return and higher drawdown than the broad benchmark in risk-on regimes.

**Pre-registered kill criterion.** Trails ew_benchmark by >15% over any rolling 6 months, or max drawdown exceeds 40%.

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess +26.14%, latest +13.20% → **WATCH**.

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
| 1 | 2018-08-06→2020-08-04 | +79.54% | +34.07% | 2020-08-04→2021-08-04 | **+385.77%** | +386.29% | +87.02% | +2.23 | −32.44% | +268.55% | +352.32% | 328 |
| 2 | 2019-08-05→2021-08-04 | +799.06% | +200.07% | 2021-08-04→2022-08-04 | **−18.93%** | −18.94% | +54.30% | −0.11 | −44.78% | −6.60% | −14.76% | 345 |
| 3 | 2020-08-04→2022-08-04 | +305.00% | +101.34% | 2022-08-04→2023-08-04 | **+5.12%** | +5.13% | +42.62% | +0.33 | −30.79% | −5.97% | −4.04% | 344 |
| 4 | 2021-08-04→2023-08-04 | −12.44% | −6.43% | 2023-08-04→2024-08-02 | **−37.58%** | −37.68% | +55.54% | −0.58 | −51.02% | −34.02% | −57.70% | 350 |
| 5 | 2022-08-04→2024-08-02 | −36.93% | −20.62% | 2024-08-02→2025-08-04 | **−50.38%** | −50.21% | +66.44% | −0.73 | −68.98% | −78.31% | −69.53% | 352 |
| 6 ◈ | 2023-08-04→2025-08-04 | −69.21% | −44.49% | 2025-08-04→2026-08-04 | **+43.63%** | +43.67% | +73.04% | +0.87 | −45.99% | +13.20% | +20.89% | 333 |

## Summary

* validate windows: **6**, win rate **50%**
* mean validate return **+54.60%** (median −6.91%, worst −50.38%, best +385.77%)
* mean validate CAGR **+54.71%** vs mean train CAGR +43.99% → decay **+10.72%**
* mean validate Sharpe +0.33, worst validate max drawdown −68.98%
* 2052 fill(s) inside validate windows
* runtime 264.9s (scratch 11.8s, screen 14.7s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

