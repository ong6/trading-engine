# News-Gated Momentum (AI) — walk-forward re-validation

_`news_gated_momo` · momo_stopped · daily cadence · verdict **WATCH** · generated 2026-08-09T07:49:59+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-07. Each fold is an independent replay starting at $39,000. Span 2018-08-07 → 2026-08-07 (2011 sessions); data floor 1994-01-27; screen source `hist` (798,415 passing rows).

**Pre-registered expectation.** Same book as momo_stopped minus a handful of entries that headlines said were about to break. If the agent adds value it shows up as a positive spread vs the twin with fewer, not more, trades.

**Pre-registered kill criterion.** AGENT LOOP killed if the AI book trails momo_stopped net of costs at the 26-week evaluation (2027-02-01). The algo book itself is never killed by this test.

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess +4.88%, latest −24.62% → **WATCH**.

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
| 1 | 2018-08-07→2020-08-07 | +49.61% | +22.30% | 2020-08-07→2021-08-06 | **+219.49%** | +220.76% | +56.94% | +2.34 | −33.76% | +96.70% | +186.76% | 781 |
| 2 | 2019-08-07→2021-08-06 | +378.91% | +118.96% | 2021-08-06→2022-08-05 | **−6.52%** | −6.54% | +42.58% | +0.05 | −34.23% | +6.09% | −1.46% | 798 |
| 3 | 2020-08-07→2022-08-05 | +192.43% | +71.32% | 2022-08-05→2023-08-07 | **−1.78%** | −1.77% | +34.17% | +0.12 | −22.80% | −10.15% | −12.05% | 774 |
| 4 | 2021-08-09→2023-08-07 | −6.54% | −3.34% | 2023-08-07→2024-08-07 | **−23.31%** | −23.27% | +40.60% | −0.45 | −29.68% | −15.86% | −39.45% | 768 |
| 5 | 2022-08-08→2024-08-07 | −27.55% | −14.89% | 2024-08-07→2025-08-07 | **+9.01%** | +9.02% | +54.17% | +0.43 | −48.01% | −22.85% | −13.67% | 770 |
| 6 ◈ | 2023-08-07→2025-08-07 | −9.50% | −4.87% | 2025-08-07→2026-08-07 | **+8.09%** | +8.10% | +68.31% | +0.46 | −44.29% | −24.62% | −14.81% | 753 |

## Summary

* validate windows: **6**, win rate **50%**
* mean validate return **+34.16%** (median +3.16%, worst −23.31%, best +219.49%)
* mean validate CAGR **+34.38%** vs mean train CAGR +31.58% → decay **+2.80%**
* mean validate Sharpe +0.49, worst validate max drawdown −48.01%
* 4644 fill(s) inside validate windows
* runtime 1088.4s (scratch 11.2s, screen 14.6s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

