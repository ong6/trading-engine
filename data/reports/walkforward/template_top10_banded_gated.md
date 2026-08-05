# Template Top 10 banded (regime-gated) — walk-forward re-validation

_`template_top10_banded_gated` · template_top10_banded · weekly cadence · verdict **WATCH** · generated 2026-08-04T23:37:39+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-04. Each fold is an independent replay starting at $39,000. Span 2018-08-06 → 2026-08-04 (2009 sessions); data floor 1994-01-27; screen source `hist` (796,840 passing rows).

**Pre-registered expectation.** Lowest-drawdown of the template family; modest return give-up.

**Pre-registered kill criterion.** No drawdown improvement vs ungated banded across a risk-off episode.

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess +10.85%, latest −29.33% → **WATCH**.

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
| 1 | 2018-08-06→2020-08-04 | +34.42% | +15.98% | 2020-08-04→2021-08-04 | **+255.30%** | +255.61% | +58.79% | +2.45 | −30.37% | +138.09% | +221.85% | 779 |
| 2 | 2019-08-05→2021-08-04 | +372.52% | +117.49% | 2021-08-04→2022-08-04 | **+1.83%** | +1.83% | +33.84% | +0.22 | −32.21% | +14.16% | +6.00% | 445 |
| 3 | 2020-08-04→2022-08-04 | +254.75% | +88.43% | 2022-08-04→2023-08-04 | **−5.88%** | −5.89% | +26.67% | −0.10 | −16.94% | −16.97% | −15.05% | 406 |
| 4 | 2021-08-04→2023-08-04 | −6.07% | −3.08% | 2023-08-04→2024-08-02 | **−25.14%** | −25.21% | +41.77% | −0.49 | −31.75% | −21.58% | −45.26% | 728 |
| 5 | 2022-08-04→2024-08-02 | −29.52% | −16.08% | 2024-08-02→2025-08-04 | **+8.65%** | +8.61% | +52.68% | +0.42 | −40.88% | −19.28% | −10.51% | 643 |
| 6 ◈ | 2023-08-04→2025-08-04 | −16.31% | −8.51% | 2025-08-04→2026-08-04 | **+1.10%** | +1.10% | +70.16% | +0.37 | −43.70% | −29.33% | −21.64% | 712 |

## Summary

* validate windows: **6**, win rate **67%**
* mean validate return **+39.31%** (median +1.46%, worst −25.14%, best +255.30%)
* mean validate CAGR **+39.34%** vs mean train CAGR +32.37% → decay **+6.97%**
* mean validate Sharpe +0.48, worst validate max drawdown −43.70%
* 3713 fill(s) inside validate windows
* runtime 436.7s (scratch 11.1s, screen 14.4s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

