# Template Top 10 (banded) — walk-forward re-validation

_`template_top10_banded` · template_top10_banded · weekly cadence · verdict **WATCH** · generated 2026-08-04T23:30:22+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-04. Each fold is an independent replay starting at $39,000. Span 2018-08-06 → 2026-08-04 (2009 sessions); data floor 1994-01-27; screen source `hist` (796,840 passing rows).

**Pre-registered expectation.** Similar return to top5 with lower turnover and drawdown; banding cuts whipsaw churn.

**Pre-registered kill criterion.** Turnover fails to fall below template_top5, or trails ew_benchmark by >15% over 6 months.

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess +11.68%, latest −22.50% → **WATCH**.

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
| 1 | 2018-08-06→2020-08-04 | +27.14% | +12.78% | 2020-08-04→2021-08-04 | **+255.10%** | +255.41% | +58.79% | +2.45 | −30.38% | +137.89% | +221.66% | 778 |
| 2 | 2019-08-05→2021-08-04 | +366.04% | +115.99% | 2021-08-04→2022-08-04 | **−10.49%** | −10.49% | +43.73% | −0.03 | −35.77% | +1.85% | −6.31% | 787 |
| 3 | 2020-08-04→2022-08-04 | +211.87% | +76.67% | 2022-08-04→2023-08-04 | **+3.79%** | +3.79% | +34.48% | +0.28 | −22.82% | −7.30% | −5.38% | 749 |
| 4 | 2021-08-04→2023-08-04 | −8.85% | −4.53% | 2023-08-04→2024-08-02 | **−23.14%** | −23.21% | +41.61% | −0.43 | −30.10% | −19.58% | −43.26% | 760 |
| 5 | 2022-08-04→2024-08-02 | −21.92% | −11.66% | 2024-08-02→2025-08-04 | **+7.66%** | +7.62% | +55.27% | +0.41 | −47.81% | −20.27% | −11.50% | 766 |
| 6 ◈ | 2023-08-04→2025-08-04 | −14.83% | −7.71% | 2025-08-04→2026-08-04 | **+7.93%** | +7.93% | +71.23% | +0.47 | −43.69% | −22.50% | −14.81% | 741 |

## Summary

* validate windows: **6**, win rate **67%**
* mean validate return **+40.14%** (median +5.72%, worst −23.14%, best +255.10%)
* mean validate CAGR **+40.18%** vs mean train CAGR +30.26% → decay **+9.92%**
* mean validate Sharpe +0.53, worst validate max drawdown −47.81%
* 4581 fill(s) inside validate windows
* runtime 395.6s (scratch 11.4s, screen 14.7s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

