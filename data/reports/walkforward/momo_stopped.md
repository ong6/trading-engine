# Momentum Top 10 (stop-managed) — walk-forward re-validation

_`momo_stopped` · momo_stopped · daily cadence · verdict **WATCH** · generated 2026-08-05T00:17:14+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-04. Each fold is an independent replay starting at $39,000. Span 2018-08-06 → 2026-08-04 (2009 sessions); data floor 1994-01-27; screen source `hist` (796,840 passing rows).

**Pre-registered expectation.** Similar upside to Template Top 10 (banded) with materially lower drawdown, the daily stop cutting losers between weekly rebalances.

**Pre-registered kill criterion.** Fails to reduce max drawdown vs template_top10_banded over 6 months, or trails it by >5% cumulative return with no drawdown benefit.

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess +5.04%, latest −27.91% → **WATCH**.

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
| 1 | 2018-08-06→2020-08-04 | +50.21% | +22.61% | 2020-08-04→2021-08-04 | **+215.24%** | +215.49% | +57.03% | +2.30 | −33.76% | +98.03% | +181.79% | 781 |
| 2 | 2019-08-05→2021-08-04 | +374.45% | +117.94% | 2021-08-04→2022-08-04 | **−8.14%** | −8.15% | +42.43% | +0.01 | −34.23% | +4.19% | −3.97% | 798 |
| 3 | 2020-08-04→2022-08-04 | +184.69% | +68.79% | 2022-08-04→2023-08-04 | **+2.70%** | +2.70% | +34.23% | +0.25 | −22.80% | −8.39% | −6.47% | 757 |
| 4 | 2021-08-04→2023-08-04 | −7.39% | −3.77% | 2023-08-04→2024-08-02 | **−23.58%** | −23.65% | +40.44% | −0.47 | −30.74% | −20.02% | −43.70% | 772 |
| 5 | 2022-08-04→2024-08-02 | −23.30% | −12.45% | 2024-08-02→2025-08-04 | **+12.28%** | +12.22% | +54.18% | +0.49 | −48.02% | −15.65% | −6.88% | 784 |
| 6 ◈ | 2023-08-04→2025-08-04 | −11.96% | −6.16% | 2025-08-04→2026-08-04 | **+2.52%** | +2.52% | +68.53% | +0.39 | −44.29% | −27.91% | −20.22% | 753 |

## Summary

* validate windows: **6**, win rate **67%**
* mean validate return **+33.50%** (median +2.61%, worst −23.58%, best +215.24%)
* mean validate CAGR **+33.52%** vs mean train CAGR +31.16% → decay **+2.36%**
* mean validate Sharpe +0.49, worst validate max drawdown −48.02%
* 4645 fill(s) inside validate windows
* runtime 1072.1s (scratch 11.1s, screen 14.9s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

