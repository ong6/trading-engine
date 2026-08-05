# SPY Buy & Hold — walk-forward re-validation

_`spy_benchmark` · spy_benchmark · once cadence · verdict **reference** · generated 2026-08-04T23:11:24+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-04. Each fold is an independent replay starting at $39,000. Span 2018-08-06 → 2026-08-04 (2009 sessions); data floor 1994-01-27; screen source `not-used`.

**Pre-registered expectation.** Baseline market return; the absolute-return yardstick.

**Pre-registered kill criterion.** Reference benchmark — not killed.

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess −11.72%, latest −7.69% → **reference**.

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
| 1 | 2018-08-06→2020-08-04 | +19.37% | +9.27% | 2020-08-04→2021-08-04 | **+33.45%** | +33.47% | +14.31% | +2.09 | −9.12% | −83.76% | +0.00% | 0 |
| 2 | 2019-08-05→2021-08-04 | +57.22% | +25.41% | 2021-08-04→2022-08-04 | **−4.17%** | −4.17% | +19.73% | −0.12 | −22.27% | +8.16% | +0.00% | 0 |
| 3 | 2020-08-04→2022-08-04 | +28.18% | +13.23% | 2022-08-04→2023-08-04 | **+9.17%** | +9.17% | +18.00% | +0.58 | −16.16% | −1.92% | +0.00% | 0 |
| 4 | 2021-08-04→2023-08-04 | +4.21% | +2.09% | 2023-08-04→2024-08-02 | **+20.12%** | +20.20% | +11.38% | +1.68 | −8.35% | +23.68% | +0.00% | 0 |
| 5 | 2022-08-04→2024-08-02 | +32.88% | +15.31% | 2024-08-02→2025-08-04 | **+19.16%** | +19.06% | +19.42% | +1.01 | −18.10% | −8.77% | +0.00% | 0 |
| 6 ◈ | 2023-08-04→2025-08-04 | +43.23% | +19.66% | 2025-08-04→2026-08-04 | **+22.74%** | +22.76% | +12.49% | +1.71 | −8.60% | −7.69% | +0.00% | 0 |

## Summary

* validate windows: **6**, win rate **83%**
* mean validate return **+16.74%** (median +19.64%, worst −4.17%, best +33.45%)
* mean validate CAGR **+16.75%** vs mean train CAGR +14.16% → decay **+2.59%**
* mean validate Sharpe +1.16, worst validate max drawdown −22.27%
* 0 fill(s) inside validate windows
* runtime 175.2s (scratch 11.3s, screen 0.0s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

