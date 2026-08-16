# Earnings-Context PEAD (AI) — walk-forward re-validation

_`earnings_context_pead` · pead_ear · daily cadence · verdict **REVIEW** · generated 2026-08-16T07:02:49+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-14. Each fold is an independent replay starting at $39,000. Span 2018-08-14 → 2026-08-14 (2011 sessions); data floor 1994-01-27; screen source `not-used`.

**Pre-registered expectation.** PEAD drift is stronger after guidance-driven surprises than after one-offs; if headlines separate those classes, vetoing the weak class should raise the sleeve's hit rate.

**Pre-registered kill criterion.** AGENT LOOP killed if the AI book trails pead_ear net of costs at 26 weeks (2027-02-01).

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess −30.55%, latest −33.67% → **REVIEW**.

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
| 1 | 2018-08-14→2020-08-14 | +0.00% | +0.00% | 2020-08-14→2021-08-13 | **+0.00%** | +0.00% | +0.00% | · | +0.00% | −131.12% | −32.83% | 0 |
| 2 | 2019-08-14→2021-08-13 | +0.00% | +0.00% | 2021-08-13→2022-08-12 | **+0.00%** | +0.00% | +0.00% | · | +0.00% | +7.97% | +2.79% | 0 |
| 3 | 2020-08-14→2022-08-12 | +0.00% | +0.00% | 2022-08-12→2023-08-14 | **+0.00%** | +0.00% | +0.00% | · | +0.00% | +0.08% | −6.26% | 0 |
| 4 | 2021-08-16→2023-08-14 | +0.00% | +0.00% | 2023-08-14→2024-08-14 | **+0.00%** | +0.00% | +0.00% | · | +0.00% | −1.45% | −22.14% | 0 |
| 5 | 2022-08-15→2024-08-14 | +0.00% | +0.00% | 2024-08-14→2025-08-14 | **+0.00%** | +0.00% | +0.00% | · | +0.00% | −25.11% | −19.43% | 0 |
| 6 ◈ | 2023-08-14→2025-08-14 | +0.00% | +0.00% | 2025-08-14→2026-08-14 | **+0.00%** | +0.00% | +0.00% | · | +0.00% | −33.67% | −21.04% | 0 |

## Summary

* validate windows: **6**, win rate **0%**
* mean validate return **+0.00%** (median +0.00%, worst +0.00%, best +0.00%)
* mean validate CAGR **+0.00%** vs mean train CAGR +0.00% → decay **+0.00%**
* mean validate Sharpe ·, worst validate max drawdown +0.00%
* 0 fill(s) inside validate windows
* runtime 296.7s (scratch 11.2s, screen 0.0s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

