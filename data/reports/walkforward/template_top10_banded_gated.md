# Template Top 10 banded (regime-gated) — walk-forward re-validation

_`template_top10_banded_gated` · template_top10_banded · weekly cadence · verdict **WATCH** · generated 2026-08-09T06:38:53+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-07. Each fold is an independent replay starting at $39,000. Span 2018-08-07 → 2026-08-07 (2011 sessions); data floor 1994-01-27; screen source `hist` (798,415 passing rows).

**Pre-registered expectation.** Lowest-drawdown of the template family; modest return give-up.

**Pre-registered kill criterion.** No drawdown improvement vs ungated banded across a risk-off episode.

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess +10.93%, latest −25.51% → **WATCH**.

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
| 1 | 2018-08-07→2020-08-07 | +33.89% | +15.70% | 2020-08-07→2021-08-06 | **+259.79%** | +261.37% | +58.71% | +2.49 | −30.37% | +137.00% | +227.06% | 779 |
| 2 | 2019-08-07→2021-08-06 | +376.61% | +118.43% | 2021-08-06→2022-08-05 | **+0.95%** | +0.96% | +33.89% | +0.20 | −32.21% | +13.56% | +6.01% | 445 |
| 3 | 2020-08-07→2022-08-05 | +254.75% | +88.76% | 2022-08-05→2023-08-07 | **−7.62%** | −7.59% | +26.74% | −0.16 | −16.94% | −16.00% | −17.90% | 424 |
| 4 | 2021-08-09→2023-08-07 | −5.20% | −2.64% | 2023-08-07→2024-08-07 | **−26.65%** | −26.61% | +42.12% | −0.53 | −30.59% | −19.21% | −42.79% | 727 |
| 5 | 2022-08-08→2024-08-07 | −32.21% | −17.68% | 2024-08-07→2025-08-07 | **+7.58%** | +7.58% | +52.56% | +0.40 | −40.88% | −24.29% | −15.11% | 629 |
| 6 ◈ | 2023-08-07→2025-08-07 | −14.66% | −7.62% | 2025-08-07→2026-08-07 | **+7.21%** | +7.22% | +69.91% | +0.46 | −43.69% | −25.51% | −15.70% | 716 |

## Summary

* validate windows: **6**, win rate **67%**
* mean validate return **+40.21%** (median +4.08%, worst −26.65%, best +259.79%)
* mean validate CAGR **+40.49%** vs mean train CAGR +32.49% → decay **+8.00%**
* mean validate Sharpe +0.48, worst validate max drawdown −43.69%
* 3720 fill(s) inside validate windows
* runtime 347.1s (scratch 11.9s, screen 14.5s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

