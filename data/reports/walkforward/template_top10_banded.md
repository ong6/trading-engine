# Template Top 10 (banded) — walk-forward re-validation

_`template_top10_banded` · template_top10_banded · weekly cadence · verdict **WATCH** · generated 2026-08-09T06:33:06+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-07. Each fold is an independent replay starting at $39,000. Span 2018-08-07 → 2026-08-07 (2011 sessions); data floor 1994-01-27; screen source `hist` (798,415 passing rows).

**Pre-registered expectation.** Similar return to top5 with lower turnover and drawdown; banding cuts whipsaw churn.

**Pre-registered kill criterion.** Turnover fails to fall below template_top5, or trails ew_benchmark by >15% over 6 months.

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess +11.78%, latest −18.19% → **WATCH**.

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
| 1 | 2018-08-07→2020-08-07 | +26.64% | +12.53% | 2020-08-07→2021-08-06 | **+259.59%** | +261.18% | +58.71% | +2.49 | −30.38% | +136.81% | +226.87% | 778 |
| 2 | 2019-08-07→2021-08-06 | +370.07% | +116.93% | 2021-08-06→2022-08-05 | **−8.84%** | −8.87% | +43.88% | +0.01 | −35.77% | +3.77% | −3.78% | 787 |
| 3 | 2020-08-07→2022-08-05 | +220.36% | +79.34% | 2022-08-05→2023-08-07 | **−0.83%** | −0.82% | +34.43% | +0.15 | −22.82% | −9.20% | −11.10% | 767 |
| 4 | 2021-08-09→2023-08-07 | −8.06% | −4.13% | 2023-08-07→2024-08-07 | **−24.62%** | −24.57% | +41.96% | −0.46 | −30.09% | −17.17% | −40.76% | 758 |
| 5 | 2022-08-08→2024-08-07 | −28.04% | −15.18% | 2024-08-07→2025-08-07 | **+6.54%** | +6.54% | +55.15% | +0.39 | −47.81% | −25.33% | −16.15% | 752 |
| 6 ◈ | 2023-08-07→2025-08-07 | −13.11% | −6.78% | 2025-08-07→2026-08-07 | **+14.52%** | +14.53% | +71.00% | +0.56 | −43.69% | −18.19% | −8.38% | 743 |

## Summary

* validate windows: **6**, win rate **50%**
* mean validate return **+41.06%** (median +2.85%, worst −24.62%, best +259.59%)
* mean validate CAGR **+41.33%** vs mean train CAGR +30.45% → decay **+10.88%**
* mean validate Sharpe +0.52, worst validate max drawdown −47.81%
* 4585 fill(s) inside validate windows
* runtime 386.9s (scratch 11.2s, screen 14.4s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

