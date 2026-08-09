# Mean-Reversion Overlay (regime-gated) — walk-forward re-validation

_`mr_overlay_gated` · mr_overlay · daily cadence · verdict **no-benchmark** · generated 2026-08-05T01:47:59+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-04. Each fold is an independent replay starting at $39,000. Span 2018-08-06 → 2026-08-04 (2009 sessions); data floor 1994-01-27; screen source `hist` (796,840 passing rows).

**Pre-registered expectation.** Fewer trades and lower drawdown than ungated MR; avoids catching falling knives in bear tapes.

**Pre-registered kill criterion.** No drawdown/expectancy improvement vs ungated MR.

**Measured against `ew_benchmark` on the same folds:** beats it in · of 0 window(s), mean excess ·, latest · → **no-benchmark**.

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
| 1 | 2018-08-06→2020-08-04 | −4.39% | −2.22% | 2020-08-04→2021-08-04 | **+28.32%** | +28.34% | +15.93% | +1.65 | −12.55% | · | · | 441 |
| 2 | 2019-08-05→2021-08-04 | +22.66% | +10.76% | 2021-08-04→2022-08-04 | **−5.80%** | −5.80% | +9.92% | −0.55 | −12.33% | · | · | 226 |
| 3 | 2020-08-04→2022-08-04 | +20.55% | +9.80% | 2022-08-04→2023-08-04 | **−3.69%** | −3.69% | +8.03% | −0.43 | −8.29% | · | · | 244 |
| 4 | 2021-08-04→2023-08-04 | −8.63% | −4.42% | 2023-08-04→2024-08-02 | **−2.96%** | −2.97% | +11.28% | −0.21 | −9.47% | · | · | 441 |
| 5 | 2022-08-04→2024-08-02 | −6.54% | −3.33% | 2024-08-02→2025-08-04 | **+15.17%** | +15.09% | +12.97% | +1.16 | −13.64% | · | · | 401 |
| 6 ◈ | 2023-08-04→2025-08-04 | +11.15% | +5.42% | 2025-08-04→2026-08-04 | **+9.84%** | +9.85% | +16.19% | +0.66 | −8.04% | · | · | 453 |

## Summary

* validate windows: **6**, win rate **50%**
* mean validate return **+6.81%** (median +3.44%, worst −5.80%, best +28.32%)
* mean validate CAGR **+6.80%** vs mean train CAGR +2.67% → decay **+4.13%**
* mean validate Sharpe +0.38, worst validate max drawdown −13.64%
* 2206 fill(s) inside validate windows
* runtime 2569.1s (scratch 11.3s, screen 14.6s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

