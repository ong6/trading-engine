# Template Top 5 (regime-gated) — walk-forward re-validation

_`template_top5_gated` · template_top5 · weekly cadence · verdict **WATCH** · generated 2026-08-04T23:46:22+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-04. Each fold is an independent replay starting at $39,000. Span 2018-08-06 → 2026-08-04 (2009 sessions); data floor 1994-01-27; screen source `hist` (796,840 passing rows).

**Pre-registered expectation.** Same upside as top5 in risk-on, materially lower drawdown in bear markets (drifts to cash).

**Pre-registered kill criterion.** Does not reduce max drawdown vs ungated top5 across a full risk-off episode.

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess +24.67%, latest −7.20% → **WATCH**.

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
| 1 | 2018-08-06→2020-08-04 | +82.99% | +35.36% | 2020-08-04→2021-08-04 | **+386.82%** | +387.35% | +87.01% | +2.24 | −32.49% | +269.61% | +353.37% | 327 |
| 2 | 2019-08-05→2021-08-04 | +750.47% | +191.84% | 2021-08-04→2022-08-04 | **−10.42%** | −10.43% | +40.90% | −0.06 | −45.19% | +1.91% | −6.25% | 201 |
| 3 | 2020-08-04→2022-08-04 | +344.85% | +111.02% | 2022-08-04→2023-08-04 | **−14.88%** | −14.89% | +34.37% | −0.30 | −32.62% | −25.97% | −24.04% | 189 |
| 4 | 2021-08-04→2023-08-04 | −21.91% | −11.64% | 2023-08-04→2024-08-02 | **−34.03%** | −34.12% | +55.32% | −0.48 | −48.23% | −30.47% | −54.15% | 335 |
| 5 | 2022-08-04→2024-08-02 | −43.96% | −25.18% | 2024-08-02→2025-08-04 | **−31.91%** | −31.78% | +61.59% | −0.32 | −55.20% | −59.84% | −51.07% | 287 |
| 6 ◈ | 2023-08-04→2025-08-04 | −55.44% | −33.23% | 2025-08-04→2026-08-04 | **+23.23%** | +23.24% | +71.46% | +0.65 | −46.00% | −7.20% | +0.49% | 318 |

## Summary

* validate windows: **6**, win rate **33%**
* mean validate return **+53.13%** (median −12.65%, worst −34.03%, best +386.82%)
* mean validate CAGR **+53.23%** vs mean train CAGR +44.70% → decay **+8.53%**
* mean validate Sharpe +0.29, worst validate max drawdown −55.20%
* 1657 fill(s) inside validate windows
* runtime 257.4s (scratch 11.1s, screen 14.6s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

