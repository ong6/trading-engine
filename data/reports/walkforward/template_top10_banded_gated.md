# Template Top 10 banded (regime-gated) — walk-forward re-validation

_`template_top10_banded_gated` · template_top10_banded · weekly cadence · verdict **WATCH** · generated 2026-08-16T06:37:10+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-14. Each fold is an independent replay starting at $39,000. Span 2018-08-14 → 2026-08-14 (2011 sessions); data floor 1994-01-27; screen source `hist` (799,705 passing rows).

**Pre-registered expectation.** Lowest-drawdown of the template family; modest return give-up.

**Pre-registered kill criterion.** No drawdown improvement vs ungated banded across a risk-off episode.

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess +10.37%, latest −14.44% → **WATCH**.

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
| 1 | 2018-08-14→2020-08-14 | +35.64% | +16.45% | 2020-08-14→2021-08-13 | **+259.44%** | +261.02% | +58.56% | +2.49 | −30.37% | +128.32% | +226.61% | 779 |
| 2 | 2019-08-14→2021-08-13 | +381.72% | +119.60% | 2021-08-13→2022-08-12 | **+2.20%** | +2.21% | +33.73% | +0.23 | −32.21% | +10.17% | +5.00% | 428 |
| 3 | 2020-08-14→2022-08-12 | +254.60% | +88.72% | 2022-08-12→2023-08-14 | **−11.65%** | −11.59% | +27.74% | −0.31 | −16.94% | −11.56% | −17.91% | 441 |
| 4 | 2021-08-16→2023-08-14 | −9.61% | −4.94% | 2023-08-14→2024-08-14 | **−14.35%** | −14.32% | +42.20% | −0.16 | −30.09% | −15.80% | −36.48% | 721 |
| 5 | 2022-08-15→2024-08-14 | −24.29% | −13.00% | 2024-08-14→2025-08-14 | **−9.37%** | −9.37% | +52.51% | +0.07 | −43.43% | −34.48% | −28.80% | 632 |
| 6 ◈ | 2023-08-14→2025-08-14 | −16.83% | −8.80% | 2025-08-14→2026-08-14 | **+19.23%** | +19.25% | +69.64% | +0.61 | −43.69% | −14.44% | −1.80% | 714 |

## Summary

* validate windows: **6**, win rate **50%**
* mean validate return **+40.92%** (median −3.58%, worst −14.35%, best +259.44%)
* mean validate CAGR **+41.20%** vs mean train CAGR +33.00% → decay **+8.19%**
* mean validate Sharpe +0.49, worst validate max drawdown −43.69%
* 3715 fill(s) inside validate windows
* runtime 376.4s (scratch 11.3s, screen 14.7s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

