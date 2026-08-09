# Stop-Tuned Turtle (AI) — walk-forward re-validation

_`stop_tuner_turtle` · turtle_breakout · daily cadence · verdict **REVIEW** · generated 2026-08-09T08:00:27+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-07. Each fold is an independent replay starting at $39,000. Span 2018-08-07 → 2026-08-07 (2011 sessions); data floor 1994-01-27; screen source `hist` (798,415 passing rows).

**Pre-registered expectation.** The stop multiple is the single parameter a trend book is most sensitive to; if any tuning loop pays, this is the one. It still has to beat leaving it alone.

**Pre-registered kill criterion.** AGENT LOOP killed if the AI book trails turtle_breakout net of costs at 26 weeks (2027-02-01).

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess −23.57%, latest −37.84% → **REVIEW**.

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
| 1 | 2018-08-07→2020-08-07 | −15.41% | −8.02% | 2020-08-07→2021-08-06 | **+57.48%** | +57.73% | +35.87% | +1.45 | −17.02% | −65.30% | +24.76% | 161 |
| 2 | 2019-08-07→2021-08-06 | +52.52% | +23.52% | 2021-08-06→2022-08-05 | **−11.86%** | −11.90% | +24.11% | −0.41 | −26.38% | +0.75% | −6.80% | 120 |
| 3 | 2020-08-07→2022-08-05 | +60.23% | +26.69% | 2022-08-05→2023-08-07 | **−6.77%** | −6.74% | +15.51% | −0.38 | −13.34% | −15.15% | −17.05% | 88 |
| 4 | 2021-08-09→2023-08-07 | −16.98% | −8.92% | 2023-08-07→2024-08-07 | **−0.69%** | −0.69% | +25.53% | +0.10 | −23.23% | +6.76% | −16.83% | 176 |
| 5 | 2022-08-08→2024-08-07 | −7.41% | −3.78% | 2024-08-07→2025-08-07 | **+1.23%** | +1.23% | +25.49% | +0.18 | −31.00% | −30.63% | −21.45% | 155 |
| 6 ◈ | 2023-08-07→2025-08-07 | −11.84% | −6.10% | 2025-08-07→2026-08-07 | **−5.12%** | −5.13% | +30.25% | −0.02 | −29.03% | −37.84% | −28.03% | 157 |

## Summary

* validate windows: **6**, win rate **33%**
* mean validate return **+5.71%** (median −2.91%, worst −11.86%, best +57.48%)
* mean validate CAGR **+5.75%** vs mean train CAGR +3.90% → decay **+1.85%**
* mean validate Sharpe +0.15, worst validate max drawdown −31.00%
* 857 fill(s) inside validate windows
* runtime 628.5s (scratch 11.2s, screen 14.5s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.

