# Adaptive MR — Frozen Twin — walk-forward re-validation

_`adaptive_mr_frozen` · mr_overlay · daily cadence · verdict **REVIEW** · generated 2026-08-09T09:55:23+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-07. Each fold is an independent replay starting at $39,000. Span 2018-08-07 → 2026-08-07 (2011 sessions); data floor 1994-01-27; screen source `hist` (798,415 passing rows).

**Pre-registered expectation.** Tracks mr_overlay closely from its own inception.

**Pre-registered kill criterion.** Control book — not killed.

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess −23.80%, latest −24.87% → **REVIEW**.

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
| 1 | 2018-08-07→2020-08-07 | −6.51% | −3.31% | 2020-08-07→2021-08-06 | **+31.58%** | +31.70% | +16.11% | +1.79 | −12.55% | −91.21% | −1.15% | 436 |
| 2 | 2019-08-07→2021-08-06 | +35.23% | +16.30% | 2021-08-06→2022-08-05 | **−6.17%** | −6.19% | +12.33% | −0.46 | −14.94% | +6.44% | −1.11% | 380 |
| 3 | 2020-08-07→2022-08-05 | +22.33% | +10.64% | 2022-08-05→2023-08-07 | **−11.24%** | −11.19% | +13.60% | −0.81 | −16.96% | −19.61% | −21.52% | 438 |
| 4 | 2021-08-09→2023-08-07 | −17.24% | −9.06% | 2023-08-07→2024-08-07 | **−2.81%** | −2.81% | +11.29% | −0.20 | −10.20% | +4.64% | −18.95% | 444 |
| 5 | 2022-08-08→2024-08-07 | −14.17% | −7.36% | 2024-08-07→2025-08-07 | **+13.70%** | +13.71% | +14.33% | +0.97 | −17.30% | −18.17% | −8.99% | 459 |
| 6 ◈ | 2023-08-07→2025-08-07 | +9.78% | +4.77% | 2025-08-07→2026-08-07 | **+7.85%** | +7.86% | +16.57% | +0.54 | −8.96% | −24.87% | −15.06% | 466 |

## Summary

* validate windows: **6**, win rate **50%**
* mean validate return **+5.48%** (median +2.52%, worst −11.24%, best +31.58%)
* mean validate CAGR **+5.51%** vs mean train CAGR +2.00% → decay **+3.51%**
* mean validate Sharpe +0.31, worst validate max drawdown −17.30%
* 2623 fill(s) inside validate windows
* runtime 2985.4s (scratch 11.3s, screen 14.5s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

