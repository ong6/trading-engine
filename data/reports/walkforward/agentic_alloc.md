# Agentic Sleeve Allocator (AI) — walk-forward re-validation

_`agentic_alloc` · sleeve_alloc · weekly cadence · verdict **REVIEW** · generated 2026-08-16T06:52:02+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-14. Each fold is an independent replay starting at $39,000. Span 2018-08-14 → 2026-08-14 (2011 sessions); data floor 1994-01-27; screen source `not-used`.

**Pre-registered expectation.** A regime-aware weighting should beat a fixed one mainly by being defensive at the right times; expect the spread to be made in drawdowns, not in melt-ups.

**Pre-registered kill criterion.** AGENT LOOP killed if the AI book trails agentic_alloc_frozen net of costs at 26 weeks (2027-02-01).

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess −22.97%, latest −23.60% → **REVIEW**.

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
| 1 | 2018-08-14→2020-08-14 | +6.78% | +3.33% | 2020-08-14→2021-08-13 | **+15.26%** | +15.31% | +8.22% | +1.78 | −5.22% | −115.86% | −17.57% | 224 |
| 2 | 2019-08-14→2021-08-13 | +16.38% | +7.89% | 2021-08-13→2022-08-12 | **+1.83%** | +1.84% | +10.07% | +0.23 | −9.36% | +9.80% | +4.63% | 236 |
| 3 | 2020-08-14→2022-08-12 | +17.05% | +8.22% | 2022-08-12→2023-08-14 | **−1.66%** | −1.65% | +8.53% | −0.15 | −8.26% | −1.58% | −7.92% | 200 |
| 4 | 2021-08-16→2023-08-14 | −0.24% | −0.12% | 2023-08-14→2024-08-14 | **+7.79%** | +7.77% | +6.34% | +1.21 | −6.08% | +6.33% | −14.35% | 173 |
| 5 | 2022-08-15→2024-08-14 | +5.97% | +2.94% | 2024-08-14→2025-08-14 | **+12.18%** | +12.19% | +9.52% | +1.26 | −8.39% | −12.93% | −7.24% | 201 |
| 6 ◈ | 2023-08-14→2025-08-14 | +22.67% | +10.75% | 2025-08-14→2026-08-14 | **+10.07%** | +10.08% | +5.57% | +1.76 | −4.59% | −23.60% | −10.97% | 230 |

## Summary

* validate windows: **6**, win rate **83%**
* mean validate return **+7.58%** (median +8.93%, worst −1.66%, best +15.26%)
* mean validate CAGR **+7.59%** vs mean train CAGR +5.50% → decay **+2.09%**
* mean validate Sharpe +1.01, worst validate max drawdown −9.36%
* 1264 fill(s) inside validate windows
* runtime 364.7s (scratch 11.2s, screen 0.0s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

