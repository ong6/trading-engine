# Mean-Reversion Overlay (regime-gated) — walk-forward re-validation

_`mr_overlay_gated` · mr_overlay · daily cadence · verdict **no-benchmark** · generated 2026-08-10T23:38:36+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-10. Each fold is an independent replay starting at $39,000. Span 2018-08-10 → 2026-08-10 (2009 sessions); data floor 1994-01-27; screen source `hist` (797,881 passing rows).

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
| 1 | 2018-08-10→2020-08-10 | −3.02% | −1.52% | 2020-08-10→2021-08-10 | **+32.63%** | +32.65% | +16.04% | +1.84 | −12.55% | · | · | 437 |
| 2 | 2019-08-12→2021-08-10 | +26.94% | +12.70% | 2021-08-10→2022-08-10 | **−7.82%** | −7.83% | +9.64% | −0.80 | −12.33% | · | · | 220 |
| 3 | 2020-08-10→2022-08-10 | +21.38% | +10.18% | 2022-08-10→2023-08-10 | **−4.91%** | −4.92% | +8.18% | −0.58 | −8.29% | · | · | 251 |
| 4 | 2021-08-10→2023-08-10 | −13.73% | −7.12% | 2023-08-10→2024-08-09 | **−0.73%** | −0.73% | +11.35% | −0.01 | −10.20% | · | · | 441 |
| 5 | 2022-08-10→2024-08-09 | −5.61% | −2.85% | 2024-08-09→2025-08-08 | **+11.03%** | +11.07% | +13.06% | +0.88 | −13.64% | · | · | 402 |
| 6 ◈ | 2023-08-10→2025-08-08 | +7.88% | +3.87% | 2025-08-08→2026-08-10 | **+12.55%** | +12.49% | +16.03% | +0.82 | −8.04% | · | · | 451 |

## Summary

* validate windows: **6**, win rate **50%**
* mean validate return **+7.12%** (median +5.15%, worst −7.82%, best +32.63%)
* mean validate CAGR **+7.12%** vs mean train CAGR +2.54% → decay **+4.58%**
* mean validate Sharpe +0.36, worst validate max drawdown −13.64%
* 2202 fill(s) inside validate windows
* runtime 2340.0s (scratch 11.4s, screen 14.4s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

