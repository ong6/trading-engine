# Walk-forward re-validation of the active league rules

_15 book(s) re-validated · protocol **train 24mo → validate 12mo, step 12mo, 6 folds, anchored 2026-08-04** · generated 2026-08-05 01:48 UTC._

Every book below is replayed by its OWN live strategy code through the real `sim/league.py` day-step — real orders, real t+1-open fills with the league's slippage and liquidity guards, real dividend crediting. The config replayed is the JSON frozen in the live `portfolios` row (D-WF4), i.e. the rule the league is actually trading. Nothing is reimplemented for this report and no bar is ever invented.

This is the input to the **Sunday review loop** (execution design §6): changes are made at reviews, one at a time, justified by walk-forward evidence rather than last week's P&L.

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


**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.


⚑ = the fold's train window was clamped to the book's data floor. ◈ = the validate window extends past league inception (2026-07-17) and so partly shadows the live record.

## Summary — all books, all folds

| Book | Verdict | Folds | Validate win rate | Beats EW | Mean validate | Mean excess vs EW | Latest validate | Latest vs EW | Mean decay (CAGR) | Worst validate DD |
|---|---|---|---|---|---|---|---|---|---|---|
| [sector_momentum](sector_momentum.md) | REVIEW | 6 | 100% | 33% | +15.80% | −12.66% | +26.35% | −4.08% | +6.33% | −17.18% |
| [dual_momentum](dual_momentum.md) | REVIEW | 6 | 67% | 33% | +13.73% | −14.74% | +26.00% | −4.43% | +8.59% | −18.75% |
| [low_vol](low_vol.md) | REVIEW | 6 | 83% | 33% | +10.79% | −17.67% | +7.25% | −23.18% | +1.00% | −13.95% |
| [high_52wk](high_52wk.md) | REVIEW | 6 | 83% | 33% | +9.96% | −18.51% | +18.78% | −11.65% | +2.85% | −21.54% |
| [dual_momentum_gated](dual_momentum_gated.md) | REVIEW | 6 | 67% | 33% | +9.79% | −18.67% | +21.42% | −9.01% | +4.10% | −17.42% |
| [mr_overlay_gated](mr_overlay_gated.md) | REVIEW | 6 | 50% | 33% | +6.81% | −21.65% | +9.84% | −20.59% | +4.13% | −13.64% |
| [turtle_breakout](turtle_breakout.md) | REVIEW | 6 | 17% | 17% | +5.65% | −22.81% | −5.11% | −35.54% | +1.47% | −31.00% |
| [mr_overlay](mr_overlay.md) | REVIEW | 6 | 50% | 33% | +5.24% | −23.22% | +7.08% | −23.35% | +3.12% | −17.30% |
| [template_top5](template_top5.md) | WATCH | 6 | 50% | 33% | +54.60% | +26.14% | +43.63% | +13.20% | +10.72% | −68.98% |
| [template_top5_gated](template_top5_gated.md) | WATCH | 6 | 33% | 33% | +53.13% | +24.67% | +23.23% | −7.20% | +8.53% | −55.20% |
| [template_top10_banded](template_top10_banded.md) | WATCH | 6 | 67% | 33% | +40.14% | +11.68% | +7.93% | −22.50% | +9.92% | −47.81% |
| [template_top10_banded_gated](template_top10_banded_gated.md) | WATCH | 6 | 67% | 33% | +39.31% | +10.85% | +1.10% | −29.33% | +6.97% | −43.70% |
| [momo_stopped](momo_stopped.md) | WATCH | 6 | 67% | 33% | +33.50% | +5.04% | +2.52% | −27.91% | +2.36% | −48.02% |
| [ew_benchmark](ew_benchmark.md) | reference | 6 | 67% | 0% | +28.46% | +0.00% | +30.43% | +0.00% | +8.15% | −36.48% |
| [spy_benchmark](spy_benchmark.md) | reference | 6 | 83% | 33% | +16.74% | −11.72% | +22.74% | −7.69% | +2.59% | −22.27% |

## Latest validate window (2025-08-04 → 2026-08-04)

| Book | Train window | Train ret | Train CAGR | Validate window | Validate ret | CAGR | Vol | Sharpe | Max DD | vs EW | vs SPY | Fills |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| template_top5 | 2023-08-04→2025-08-04 | −69.21% | −44.49% | 2025-08-04→2026-08-04 | **+43.63%** | +43.67% | +73.04% | +0.87 | −45.99% | +13.20% | +20.89% | 333 |
| ew_benchmark | 2023-08-04→2025-08-04 | +25.81% | +12.15% | 2025-08-04→2026-08-04 | **+30.43%** | +30.45% | +56.56% | +0.76 | −36.48% | +0.00% | +7.69% | 909 |
| sector_momentum | 2023-08-04→2025-08-04 | +24.53% | +11.58% | 2025-08-04→2026-08-04 | **+26.35%** | +26.37% | +13.57% | +1.80 | −7.91% | −4.08% | +3.61% | 40 |
| dual_momentum | 2023-08-04→2025-08-04 | +31.41% | +14.62% | 2025-08-04→2026-08-04 | **+26.00%** | +26.02% | +14.86% | +1.64 | −11.41% | −4.43% | +3.26% | 12 |
| template_top5_gated | 2023-08-04→2025-08-04 | −55.44% | −33.23% | 2025-08-04→2026-08-04 | **+23.23%** | +23.24% | +71.46% | +0.65 | −46.00% | −7.20% | +0.49% | 318 |
| spy_benchmark | 2023-08-04→2025-08-04 | +43.23% | +19.66% | 2025-08-04→2026-08-04 | **+22.74%** | +22.76% | +12.49% | +1.71 | −8.60% | −7.69% | +0.00% | 0 |
| dual_momentum_gated | 2023-08-04→2025-08-04 | +15.78% | +7.60% | 2025-08-04→2026-08-04 | **+21.42%** | +21.43% | +13.75% | +1.49 | −11.42% | −9.01% | −1.32% | 11 |
| high_52wk | 2023-08-04→2025-08-04 | +34.46% | +15.95% | 2025-08-04→2026-08-04 | **+18.78%** | +18.79% | +16.09% | +1.15 | −11.71% | −11.65% | −3.96% | 561 |
| mr_overlay_gated | 2023-08-04→2025-08-04 | +11.15% | +5.42% | 2025-08-04→2026-08-04 | **+9.84%** | +9.85% | +16.19% | +0.66 | −8.04% | −20.59% | −12.90% | 453 |
| template_top10_banded | 2023-08-04→2025-08-04 | −14.83% | −7.71% | 2025-08-04→2026-08-04 | **+7.93%** | +7.93% | +71.23% | +0.47 | −43.69% | −22.50% | −14.81% | 741 |
| low_vol | 2023-08-04→2025-08-04 | +32.34% | +15.03% | 2025-08-04→2026-08-04 | **+7.25%** | +7.25% | +9.14% | +0.81 | −5.54% | −23.18% | −15.49% | 189 |
| mr_overlay | 2023-08-04→2025-08-04 | +9.22% | +4.51% | 2025-08-04→2026-08-04 | **+7.08%** | +7.08% | +16.59% | +0.50 | −8.96% | −23.35% | −15.66% | 469 |
| momo_stopped | 2023-08-04→2025-08-04 | −11.96% | −6.16% | 2025-08-04→2026-08-04 | **+2.52%** | +2.52% | +68.53% | +0.39 | −44.29% | −27.91% | −20.22% | 753 |
| template_top10_banded_gated | 2023-08-04→2025-08-04 | −16.31% | −8.51% | 2025-08-04→2026-08-04 | **+1.10%** | +1.10% | +70.16% | +0.37 | −43.70% | −29.33% | −21.64% | 712 |
| turtle_breakout | 2023-08-04→2025-08-04 | −13.26% | −6.86% | 2025-08-04→2026-08-04 | **−5.11%** | −5.12% | +30.29% | −0.02 | −29.03% | −35.54% | −27.85% | 158 |

## Books NOT walk-forwarded

* **pead_ear** — no historical earnings dates — `earnings_calendar` spans only 2026-04→2026-10, so the entry signal cannot be computed. Forward record only.
* **discretionary** — human book — orders come from UI tickets, not code.
* **macro_composite** — its inputs are point-in-time by `fetch_as_of`, and the production `macro_signals` backfill stamps fetch_as_of = today (honest: we did not have those series in 2019). A historical replay therefore sees an empty signal table and the book is inert, not wrong. Needs a labelled `--pit-lag` reconstruction backfill before it can be walk-forwarded.

## How this is produced

```sh
# enumerate / enqueue the weekly grid (one job per active book)
.venv/bin/python farm/walkforward/grid.py --list
.venv/bin/python farm/walkforward/grid.py --enqueue
.venv/bin/python engine/queue_runner.py --run
```

Intended cadence: **Sunday**, ahead of the weekly review. The weekday nightly (`engine/run_daily.sh`, cron `30 22 * * 1-5`) never runs on a Sunday, so this workload is enqueued by its own cron entry rather than by the nightly — see BUILDLOG.
