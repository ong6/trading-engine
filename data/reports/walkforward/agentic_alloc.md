# Agentic Sleeve Allocator (AI) — walk-forward re-validation

_`agentic_alloc` · sleeve_alloc · weekly cadence · verdict **REVIEW** · generated 2026-08-09T06:55:44+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-07. Each fold is an independent replay starting at $39,000. Span 2018-08-07 → 2026-08-07 (2011 sessions); data floor 1994-01-27; screen source `not-used`.

**Pre-registered expectation.** A regime-aware weighting should beat a fixed one mainly by being defensive at the right times; expect the spread to be made in drawdowns, not in melt-ups.

**Pre-registered kill criterion.** AGENT LOOP killed if the AI book trails agentic_alloc_frozen net of costs at 26 weeks (2027-02-01).

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess −21.88%, latest −22.97% → **REVIEW**.

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
| 1 | 2018-08-07→2020-08-07 | +7.63% | +3.74% | 2020-08-07→2021-08-06 | **+14.83%** | +14.89% | +8.27% | +1.72 | −5.22% | −107.95% | −17.89% | 225 |
| 2 | 2019-08-07→2021-08-06 | +16.51% | +7.95% | 2021-08-06→2022-08-05 | **+0.88%** | +0.89% | +10.04% | +0.14 | −9.37% | +13.49% | +5.94% | 238 |
| 3 | 2020-08-07→2022-08-05 | +15.65% | +7.57% | 2022-08-05→2023-08-07 | **−0.22%** | −0.21% | +8.56% | +0.02 | −8.26% | −8.59% | −10.49% | 202 |
| 4 | 2021-08-09→2023-08-07 | +0.16% | +0.08% | 2023-08-07→2024-08-07 | **+5.93%** | +5.92% | +6.24% | +0.95 | −6.08% | +13.38% | −10.21% | 174 |
| 5 | 2022-08-08→2024-08-07 | +4.48% | +2.22% | 2024-08-07→2025-08-07 | **+13.20%** | +13.21% | +9.57% | +1.35 | −8.39% | −18.66% | −9.48% | 198 |
| 6 ◈ | 2023-08-07→2025-08-07 | +20.14% | +9.60% | 2025-08-07→2026-08-07 | **+9.75%** | +9.76% | +5.58% | +1.70 | −4.59% | −22.97% | −13.16% | 229 |

## Summary

* validate windows: **6**, win rate **83%**
* mean validate return **+7.40%** (median +7.84%, worst −0.22%, best +14.83%)
* mean validate CAGR **+7.41%** vs mean train CAGR +5.19% → decay **+2.22%**
* mean validate Sharpe +0.98, worst validate max drawdown −9.37%
* 1266 fill(s) inside validate windows
* runtime 426.8s (scratch 11.7s, screen 0.0s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

