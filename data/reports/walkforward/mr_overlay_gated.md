# Mean-Reversion Overlay (regime-gated) — walk-forward re-validation

_`mr_overlay_gated` · mr_overlay · daily cadence · verdict **no-benchmark** · generated 2026-08-17T23:42:12+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-17. Each fold is an independent replay starting at $39,000. Span 2018-08-17 → 2026-08-17 (2009 sessions); data floor 1994-01-27; screen source `hist` (799,273 passing rows).

**Pre-registered expectation.** Fewer trades and lower drawdown than ungated MR; avoids catching falling knives in bear tapes.

**Pre-registered kill criterion.** No drawdown/expectancy improvement vs ungated MR.

**Measured against `ew_benchmark` on the same folds:** beats it in · of 0 window(s), mean excess ·, latest · → **no-benchmark**.

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
| 1 | 2018-08-17→2020-08-17 | −0.81% | −0.41% | 2020-08-17→2021-08-17 | **+31.18%** | +31.21% | +15.99% | +1.78 | −12.55% | · | · | 438 |
| 2 | 2019-08-19→2021-08-17 | +25.83% | +12.20% | 2021-08-17→2022-08-17 | **−7.22%** | −7.22% | +9.55% | −0.74 | −12.33% | · | · | 213 |
| 3 | 2020-08-17→2022-08-17 | +19.40% | +9.28% | 2022-08-17→2023-08-17 | **−4.76%** | −4.77% | +8.37% | −0.54 | −8.29% | · | · | 259 |
| 4 | 2021-08-17→2023-08-17 | −12.78% | −6.61% | 2023-08-17→2024-08-16 | **+0.31%** | +0.31% | +11.24% | +0.08 | −10.20% | · | · | 442 |
| 5 | 2022-08-17→2024-08-16 | −4.47% | −2.26% | 2024-08-16→2025-08-15 | **+10.89%** | +10.93% | +13.14% | +0.86 | −13.64% | · | · | 404 |
| 6 ◈ | 2023-08-17→2025-08-15 | +13.92% | +6.75% | 2025-08-15→2026-08-17 | **+11.38%** | +11.32% | +16.00% | +0.76 | −8.04% | · | · | 446 |

## Summary

* validate windows: **6**, win rate **67%**
* mean validate return **+6.96%** (median +5.60%, worst −7.22%, best +31.18%)
* mean validate CAGR **+6.96%** vs mean train CAGR +3.16% → decay **+3.81%**
* mean validate Sharpe +0.37, worst validate max drawdown −13.64%
* 2202 fill(s) inside validate windows
* runtime 1747.2s (scratch 11.4s, screen 14.6s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

