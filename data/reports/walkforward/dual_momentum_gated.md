# Dual Momentum (regime-gated) — walk-forward re-validation

_`dual_momentum_gated` · dual_momentum · monthly cadence · verdict **REVIEW** · generated 2026-08-09T06:05:58+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-07. Each fold is an independent replay starting at $39,000. Span 2018-08-07 → 2026-08-07 (2011 sessions); data floor 2008-05-29; screen source `not-used`.

**Pre-registered expectation.** Near-identical to ungated GEM; gate is a belt-and-braces check.

**Pre-registered kill criterion.** Diverges materially from ungated GEM (would signal a gate bug).

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess −19.52%, latest −10.12% → **REVIEW**.

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
| 1 | 2018-08-07→2020-08-07 | +3.47% | +1.72% | 2020-08-07→2021-08-06 | **+34.05%** | +34.18% | +14.82% | +2.06 | −9.38% | −88.74% | +1.32% | 2 |
| 2 | 2019-08-07→2021-08-06 | +53.27% | +23.82% | 2021-08-06→2022-08-05 | **−10.23%** | −10.27% | +13.54% | −0.73 | −17.42% | +2.37% | −5.18% | 4 |
| 3 | 2020-08-07→2022-08-05 | +14.90% | +7.22% | 2022-08-05→2023-08-07 | **−2.46%** | −2.44% | +4.87% | −0.49 | −4.99% | −10.83% | −12.73% | 5 |
| 4 | 2021-08-09→2023-08-07 | −14.50% | −7.56% | 2023-08-07→2024-08-07 | **+5.81%** | +5.80% | +11.64% | +0.54 | −9.52% | +13.26% | −10.33% | 5 |
| 5 | 2022-08-08→2024-08-07 | +3.20% | +1.59% | 2024-08-07→2025-08-07 | **+8.79%** | +8.80% | +12.84% | +0.73 | −10.10% | −23.07% | −13.89% | 7 |
| 6 ◈ | 2023-08-07→2025-08-07 | +15.98% | +7.69% | 2025-08-07→2026-08-07 | **+22.60%** | +22.61% | +13.76% | +1.56 | −11.42% | −10.12% | −0.31% | 11 |

## Summary

* validate windows: **6**, win rate **67%**
* mean validate return **+9.76%** (median +7.30%, worst −10.23%, best +34.05%)
* mean validate CAGR **+9.78%** vs mean train CAGR +5.75% → decay **+4.03%**
* mean validate Sharpe +0.61, worst validate max drawdown −17.42%
* 34 fill(s) inside validate windows
* runtime 168.7s (scratch 11.5s, screen 0.0s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

