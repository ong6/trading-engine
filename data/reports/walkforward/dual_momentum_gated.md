# Dual Momentum (regime-gated) — walk-forward re-validation

_`dual_momentum_gated` · dual_momentum · monthly cadence · verdict **REVIEW** · generated 2026-08-04T23:04:20+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-04. Each fold is an independent replay starting at $39,000. Span 2018-08-06 → 2026-08-04 (2009 sessions); data floor 2008-05-29; screen source `not-used`.

**Pre-registered expectation.** Near-identical to ungated GEM; gate is a belt-and-braces check.

**Pre-registered kill criterion.** Diverges materially from ungated GEM (would signal a gate bug).

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess −18.67%, latest −9.01% → **REVIEW**.

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
| 1 | 2018-08-06→2020-08-04 | +2.08% | +1.04% | 2020-08-04→2021-08-04 | **+34.79%** | +34.82% | +14.80% | +2.09 | −9.38% | −82.42% | +1.34% | 2 |
| 2 | 2019-08-05→2021-08-04 | +52.06% | +23.33% | 2021-08-04→2022-08-04 | **−9.52%** | −9.53% | +13.53% | −0.67 | −17.42% | +2.81% | −5.35% | 4 |
| 3 | 2020-08-04→2022-08-04 | +14.90% | +7.19% | 2022-08-04→2023-08-04 | **−3.27%** | −3.27% | +4.79% | −0.67 | −4.99% | −14.36% | −12.44% | 5 |
| 4 | 2021-08-04→2023-08-04 | −15.21% | −7.92% | 2023-08-04→2024-08-02 | **+9.62%** | +9.65% | +11.28% | +0.88 | −9.52% | +13.18% | −10.50% | 5 |
| 5 | 2022-08-04→2024-08-02 | +6.03% | +2.98% | 2024-08-02→2025-08-04 | **+5.71%** | +5.68% | +13.19% | +0.49 | −10.10% | −22.22% | −13.45% | 7 |
| 6 ◈ | 2023-08-04→2025-08-04 | +15.78% | +7.60% | 2025-08-04→2026-08-04 | **+21.42%** | +21.43% | +13.75% | +1.49 | −11.42% | −9.01% | −1.32% | 11 |

## Summary

* validate windows: **6**, win rate **67%**
* mean validate return **+9.79%** (median +7.67%, worst −9.52%, best +34.79%)
* mean validate CAGR **+9.80%** vs mean train CAGR +5.70% → decay **+4.10%**
* mean validate Sharpe +0.60, worst validate max drawdown −17.42%
* 34 fill(s) inside validate windows
* runtime 159.6s (scratch 11.3s, screen 0.0s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

