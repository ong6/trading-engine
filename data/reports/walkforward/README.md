# Walk-forward re-validation of the active league rules

_22 book(s) re-validated · protocol **train 24mo → validate 12mo, step 12mo, 6 folds, anchored 2026-08-07** · generated 2026-08-09 10:37 UTC._

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
| [sector_momentum](sector_momentum.md) | REVIEW | 6 | 100% | 33% | +15.65% | −13.63% | +27.10% | −5.61% | +6.02% | −17.18% |
| [dual_momentum](dual_momentum.md) | REVIEW | 6 | 67% | 33% | +13.67% | −15.61% | +27.23% | −5.49% | +8.52% | −18.75% |
| [low_vol](low_vol.md) | REVIEW | 6 | 83% | 33% | +10.64% | −18.64% | +6.74% | −25.98% | +0.80% | −13.95% |
| [high_52wk](high_52wk.md) | REVIEW | 6 | 83% | 33% | +9.97% | −19.31% | +19.33% | −13.39% | +3.08% | −21.54% |
| [dual_momentum_gated](dual_momentum_gated.md) | REVIEW | 6 | 67% | 33% | +9.76% | −19.52% | +22.60% | −10.12% | +4.03% | −17.42% |
| [agentic_alloc](agentic_alloc.md) | REVIEW | 6 | 83% | 33% | +7.40% | −21.88% | +9.75% | −22.97% | +2.22% | −9.37% |
| [agentic_alloc_frozen](agentic_alloc_frozen.md) | REVIEW | 6 | 83% | 33% | +7.40% | −21.88% | +9.75% | −22.97% | +2.22% | −9.37% |
| [stop_tuner_turtle](stop_tuner_turtle.md) | REVIEW | 6 | 33% | 33% | +5.71% | −23.57% | −5.12% | −37.84% | +1.85% | −31.00% |
| [turtle_breakout](turtle_breakout.md) | REVIEW | 6 | 33% | 33% | +5.71% | −23.57% | −5.12% | −37.84% | +1.85% | −31.00% |
| [adaptive_mr](adaptive_mr.md) | REVIEW | 6 | 50% | 33% | +5.48% | −23.80% | +7.85% | −24.87% | +3.51% | −17.30% |
| [adaptive_mr_frozen](adaptive_mr_frozen.md) | REVIEW | 6 | 50% | 33% | +5.48% | −23.80% | +7.85% | −24.87% | +3.51% | −17.30% |
| [mr_overlay](mr_overlay.md) | REVIEW | 6 | 50% | 33% | +5.48% | −23.80% | +7.85% | −24.87% | +3.51% | −17.30% |
| [earnings_context_pead](earnings_context_pead.md) | REVIEW | 6 | 0% | 33% | +0.00% | −29.28% | +0.00% | −32.72% | +0.00% | +0.00% |
| [template_top5](template_top5.md) | WATCH | 6 | 50% | 33% | +59.26% | +29.98% | +47.97% | +15.25% | +15.94% | −69.02% |
| [template_top5_gated](template_top5_gated.md) | WATCH | 6 | 33% | 33% | +56.59% | +27.31% | +26.74% | −5.98% | +12.65% | −55.20% |
| [template_top10_banded](template_top10_banded.md) | WATCH | 6 | 50% | 33% | +41.06% | +11.78% | +14.52% | −18.19% | +10.88% | −47.81% |
| [template_top10_banded_gated](template_top10_banded_gated.md) | WATCH | 6 | 67% | 33% | +40.21% | +10.93% | +7.21% | −25.51% | +8.00% | −43.69% |
| [momo_stopped](momo_stopped.md) | WATCH | 6 | 50% | 33% | +34.16% | +4.88% | +8.09% | −24.62% | +2.80% | −48.01% |
| [news_gated_momo](news_gated_momo.md) | WATCH | 6 | 50% | 33% | +34.16% | +4.88% | +8.09% | −24.62% | +2.80% | −48.01% |
| [mr_overlay_gated](mr_overlay_gated.md) | no-benchmark | 6 | 50% | · | +6.81% | · | +9.84% | · | +4.13% | −13.64% |
| [ew_benchmark](ew_benchmark.md) | reference | 6 | 67% | 0% | +29.28% | +0.00% | +32.72% | +0.00% | +9.23% | −36.48% |
| [spy_benchmark](spy_benchmark.md) | reference | 6 | 83% | 50% | +16.61% | −12.67% | +22.91% | −9.81% | +2.73% | −22.24% |

## Latest validate window (2025-08-07 → 2026-08-07)

| Book | Train window | Train ret | Train CAGR | Validate window | Validate ret | CAGR | Vol | Sharpe | Max DD | vs EW | vs SPY | Fills |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| template_top5 | 2023-08-07→2025-08-07 | −69.16% | −44.44% | 2025-08-07→2026-08-07 | **+47.97%** | +48.01% | +72.95% | +0.91 | −46.00% | +15.25% | +25.06% | 331 |
| ew_benchmark | 2023-08-07→2025-08-07 | +23.59% | +11.16% | 2025-08-07→2026-08-07 | **+32.72%** | +32.74% | +56.56% | +0.79 | −36.48% | +0.00% | +9.81% | 909 |
| dual_momentum | 2023-08-07→2025-08-07 | +31.64% | +14.72% | 2025-08-07→2026-08-07 | **+27.23%** | +27.25% | +14.86% | +1.70 | −11.41% | −5.49% | +4.32% | 12 |
| sector_momentum | 2023-08-07→2025-08-07 | +24.23% | +11.45% | 2025-08-07→2026-08-07 | **+27.10%** | +27.12% | +13.56% | +1.84 | −7.91% | −5.61% | +4.20% | 40 |
| template_top5_gated | 2023-08-07→2025-08-07 | −55.35% | −33.16% | 2025-08-07→2026-08-07 | **+26.74%** | +26.76% | +71.31% | +0.69 | −45.99% | −5.98% | +3.83% | 319 |
| spy_benchmark | 2023-08-07→2025-08-07 | +43.87% | +19.93% | 2025-08-07→2026-08-07 | **+22.91%** | +22.92% | +12.51% | +1.72 | −8.63% | −9.81% | +0.00% | 0 |
| dual_momentum_gated | 2023-08-07→2025-08-07 | +15.98% | +7.69% | 2025-08-07→2026-08-07 | **+22.60%** | +22.61% | +13.76% | +1.56 | −11.42% | −10.12% | −0.31% | 11 |
| high_52wk | 2023-08-07→2025-08-07 | +33.31% | +15.45% | 2025-08-07→2026-08-07 | **+19.33%** | +19.35% | +16.07% | +1.18 | −11.67% | −13.39% | −3.57% | 562 |
| template_top10_banded | 2023-08-07→2025-08-07 | −13.11% | −6.78% | 2025-08-07→2026-08-07 | **+14.52%** | +14.53% | +71.00% | +0.56 | −43.69% | −18.19% | −8.38% | 743 |
| agentic_alloc | 2023-08-07→2025-08-07 | +20.14% | +9.60% | 2025-08-07→2026-08-07 | **+9.75%** | +9.76% | +5.58% | +1.70 | −4.59% | −22.97% | −13.16% | 229 |
| agentic_alloc_frozen | 2023-08-07→2025-08-07 | +20.14% | +9.60% | 2025-08-07→2026-08-07 | **+9.75%** | +9.76% | +5.58% | +1.70 | −4.59% | −22.97% | −13.16% | 229 |
| momo_stopped | 2023-08-07→2025-08-07 | −9.50% | −4.87% | 2025-08-07→2026-08-07 | **+8.09%** | +8.10% | +68.31% | +0.46 | −44.29% | −24.62% | −14.81% | 753 |
| news_gated_momo | 2023-08-07→2025-08-07 | −9.50% | −4.87% | 2025-08-07→2026-08-07 | **+8.09%** | +8.10% | +68.31% | +0.46 | −44.29% | −24.62% | −14.81% | 753 |
| adaptive_mr | 2023-08-07→2025-08-07 | +9.78% | +4.77% | 2025-08-07→2026-08-07 | **+7.85%** | +7.86% | +16.57% | +0.54 | −8.96% | −24.87% | −15.06% | 466 |
| adaptive_mr_frozen | 2023-08-07→2025-08-07 | +9.78% | +4.77% | 2025-08-07→2026-08-07 | **+7.85%** | +7.86% | +16.57% | +0.54 | −8.96% | −24.87% | −15.06% | 466 |
| mr_overlay | 2023-08-07→2025-08-07 | +9.78% | +4.77% | 2025-08-07→2026-08-07 | **+7.85%** | +7.86% | +16.57% | +0.54 | −8.96% | −24.87% | −15.06% | 466 |
| template_top10_banded_gated | 2023-08-07→2025-08-07 | −14.66% | −7.62% | 2025-08-07→2026-08-07 | **+7.21%** | +7.22% | +69.91% | +0.46 | −43.69% | −25.51% | −15.70% | 716 |
| low_vol | 2023-08-07→2025-08-07 | +32.91% | +15.28% | 2025-08-07→2026-08-07 | **+6.74%** | +6.74% | +9.14% | +0.76 | −5.54% | −25.98% | −16.17% | 188 |
| stop_tuner_turtle | 2023-08-07→2025-08-07 | −11.84% | −6.10% | 2025-08-07→2026-08-07 | **−5.12%** | −5.13% | +30.25% | −0.02 | −29.03% | −37.84% | −28.03% | 157 |
| turtle_breakout | 2023-08-07→2025-08-07 | −11.84% | −6.10% | 2025-08-07→2026-08-07 | **−5.12%** | −5.13% | +30.25% | −0.02 | −29.03% | −37.84% | −28.03% | 157 |
| earnings_context_pead | 2023-08-07→2025-08-07 | +0.00% | +0.00% | 2025-08-07→2026-08-07 | **+0.00%** | +0.00% | +0.00% | · | +0.00% | −32.72% | −22.91% | 0 |

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
