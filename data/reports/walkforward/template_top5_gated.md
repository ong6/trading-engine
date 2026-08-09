# Template Top 5 (regime-gated) — walk-forward re-validation

_`template_top5_gated` · template_top5 · weekly cadence · verdict **WATCH** · generated 2026-08-09T06:48:37+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-07. Each fold is an independent replay starting at $39,000. Span 2018-08-07 → 2026-08-07 (2011 sessions); data floor 1994-01-27; screen source `hist` (798,415 passing rows).

**Pre-registered expectation.** Same upside as top5 in risk-on, materially lower drawdown in bear markets (drifts to cash).

**Pre-registered kill criterion.** Does not reduce max drawdown vs ungated top5 across a full risk-off episode.

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess +27.31%, latest −5.98% → **WATCH**.

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
| 1 | 2018-08-07→2020-08-07 | +74.78% | +32.18% | 2020-08-07→2021-08-06 | **+404.50%** | +407.31% | +86.74% | +2.29 | −32.49% | +281.72% | +371.78% | 327 |
| 2 | 2019-08-07→2021-08-06 | +751.25% | +191.98% | 2021-08-06→2022-08-05 | **−10.50%** | −10.54% | +40.81% | −0.07 | −45.19% | +2.10% | −5.45% | 201 |
| 3 | 2020-08-07→2022-08-05 | +344.85% | +111.46% | 2022-08-05→2023-08-07 | **−13.73%** | −13.67% | +34.40% | −0.26 | −32.62% | −22.11% | −24.01% | 197 |
| 4 | 2021-08-09→2023-08-07 | −21.55% | −11.46% | 2023-08-07→2024-08-07 | **−33.72%** | −33.66% | +55.32% | −0.47 | −48.22% | −26.27% | −49.86% | 333 |
| 5 | 2022-08-08→2024-08-07 | −42.95% | −24.48% | 2024-08-07→2025-08-07 | **−33.76%** | −33.78% | +61.55% | −0.36 | −55.20% | −65.63% | −56.44% | 280 |
| 6 ◈ | 2023-08-07→2025-08-07 | −55.35% | −33.16% | 2025-08-07→2026-08-07 | **+26.74%** | +26.76% | +71.31% | +0.69 | −45.99% | −5.98% | +3.83% | 319 |

## Summary

* validate windows: **6**, win rate **33%**
* mean validate return **+56.59%** (median −12.12%, worst −33.76%, best +404.50%)
* mean validate CAGR **+57.07%** vs mean train CAGR +44.42% → decay **+12.65%**
* mean validate Sharpe +0.30, worst validate max drawdown −55.20%
* 1657 fill(s) inside validate windows
* runtime 312.3s (scratch 11.7s, screen 14.7s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

