# Walk-forward re-validation of the active league rules

_22 book(s) re-validated · protocol **train 24mo → validate 12mo, step 12mo, 6 folds, anchored 2026-08-14** · generated 2026-08-16 10:05 UTC._

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
| [dual_momentum](dual_momentum.md) | REVIEW | 6 | 67% | 33% | +13.63% | −16.92% | +24.83% | −8.84% | +7.84% | −18.75% |
| [low_vol](low_vol.md) | REVIEW | 6 | 83% | 33% | +10.60% | −19.95% | +7.00% | −26.68% | +0.27% | −13.95% |
| [high_52wk](high_52wk.md) | REVIEW | 6 | 83% | 33% | +10.47% | −20.08% | +18.47% | −15.21% | +3.36% | −21.54% |
| [dual_momentum_gated](dual_momentum_gated.md) | REVIEW | 6 | 67% | 17% | +9.68% | −20.87% | +20.29% | −13.38% | +3.33% | −17.42% |
| [agentic_alloc](agentic_alloc.md) | REVIEW | 6 | 83% | 33% | +7.58% | −22.97% | +10.07% | −23.60% | +2.09% | −9.36% |
| [agentic_alloc_frozen](agentic_alloc_frozen.md) | REVIEW | 6 | 83% | 33% | +7.58% | −22.97% | +10.07% | −23.60% | +2.09% | −9.36% |
| [adaptive_mr](adaptive_mr.md) | REVIEW | 6 | 50% | 17% | +5.46% | −25.09% | +8.60% | −25.07% | +3.10% | −17.30% |
| [adaptive_mr_frozen](adaptive_mr_frozen.md) | REVIEW | 6 | 50% | 17% | +5.46% | −25.09% | +8.60% | −25.07% | +3.10% | −17.30% |
| [mr_overlay](mr_overlay.md) | REVIEW | 6 | 50% | 17% | +5.46% | −25.09% | +8.60% | −25.07% | +3.10% | −17.30% |
| [stop_tuner_turtle](stop_tuner_turtle.md) | REVIEW | 6 | 33% | 17% | +5.18% | −25.37% | −5.86% | −39.53% | +0.91% | −31.00% |
| [turtle_breakout](turtle_breakout.md) | REVIEW | 6 | 33% | 17% | +5.18% | −25.37% | −5.86% | −39.53% | +0.91% | −31.00% |
| [earnings_context_pead](earnings_context_pead.md) | REVIEW | 6 | 0% | 33% | +0.00% | −30.55% | +0.00% | −33.67% | +0.00% | +0.00% |
| [template_top5](template_top5.md) | WATCH | 6 | 33% | 33% | +63.41% | +32.85% | +68.78% | +35.11% | +17.22% | −68.96% |
| [template_top5_gated](template_top5_gated.md) | WATCH | 6 | 33% | 33% | +60.65% | +30.10% | +44.53% | +10.86% | +14.71% | −55.20% |
| [template_top10_banded](template_top10_banded.md) | WATCH | 6 | 33% | 33% | +42.05% | +11.50% | +27.43% | −6.24% | +10.70% | −47.81% |
| [template_top10_banded_gated](template_top10_banded_gated.md) | WATCH | 6 | 50% | 33% | +40.92% | +10.37% | +19.23% | −14.44% | +8.19% | −43.69% |
| [momo_stopped](momo_stopped.md) | WATCH | 6 | 50% | 33% | +35.34% | +4.79% | +19.17% | −14.50% | +2.50% | −48.01% |
| [news_gated_momo](news_gated_momo.md) | WATCH | 6 | 50% | 33% | +35.34% | +4.79% | +19.17% | −14.50% | +2.50% | −48.01% |
| [sector_momentum](sector_momentum.md) | WATCH | 6 | 100% | 50% | +16.14% | −14.41% | +28.69% | −4.98% | +5.49% | −17.18% |
| [mr_overlay_gated](mr_overlay_gated.md) | no-benchmark | 6 | 50% | · | +7.12% | · | +12.55% | · | +4.58% | −13.64% |
| [ew_benchmark](ew_benchmark.md) | reference | 6 | 67% | 0% | +30.55% | +0.00% | +33.67% | +0.00% | +9.62% | −36.48% |
| [spy_benchmark](spy_benchmark.md) | reference | 6 | 83% | 50% | +16.48% | −14.07% | +21.04% | −12.63% | +1.74% | −22.22% |

## Latest validate window (2025-08-14 → 2026-08-14)

| Book | Train window | Train ret | Train CAGR | Validate window | Validate ret | CAGR | Vol | Sharpe | Max DD | vs EW | vs SPY | Fills |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| template_top5 | 2023-08-14→2025-08-14 | −68.25% | −43.63% | 2025-08-14→2026-08-14 | **+68.78%** | +68.85% | +72.57% | +1.09 | −45.98% | +35.11% | +47.75% | 330 |
| template_top5_gated | 2023-08-14→2025-08-14 | −54.07% | −32.21% | 2025-08-14→2026-08-14 | **+44.53%** | +44.56% | +70.97% | +0.88 | −45.98% | +10.86% | +23.49% | 317 |
| ew_benchmark | 2023-08-14→2025-08-14 | +25.33% | +11.94% | 2025-08-14→2026-08-14 | **+33.67%** | +33.70% | +56.44% | +0.80 | −36.48% | +0.00% | +12.63% | 909 |
| sector_momentum | 2023-08-14→2025-08-14 | +26.56% | +12.49% | 2025-08-14→2026-08-14 | **+28.69%** | +28.71% | +13.58% | +1.93 | −7.91% | −4.98% | +7.65% | 40 |
| template_top10_banded | 2023-08-14→2025-08-14 | −15.38% | −8.01% | 2025-08-14→2026-08-14 | **+27.43%** | +27.45% | +70.73% | +0.71 | −43.70% | −6.24% | +6.40% | 742 |
| dual_momentum | 2023-08-14→2025-08-14 | +34.27% | +15.86% | 2025-08-14→2026-08-14 | **+24.83%** | +24.85% | +14.83% | +1.58 | −11.41% | −8.84% | +3.80% | 12 |
| spy_benchmark | 2023-08-14→2025-08-14 | +47.36% | +21.38% | 2025-08-14→2026-08-14 | **+21.04%** | +21.05% | +12.49% | +1.60 | −8.64% | −12.63% | +0.00% | 0 |
| dual_momentum_gated | 2023-08-14→2025-08-14 | +18.30% | +8.76% | 2025-08-14→2026-08-14 | **+20.29%** | +20.31% | +13.72% | +1.42 | −11.42% | −13.38% | −0.75% | 11 |
| template_top10_banded_gated | 2023-08-14→2025-08-14 | −16.83% | −8.80% | 2025-08-14→2026-08-14 | **+19.23%** | +19.25% | +69.64% | +0.61 | −43.69% | −14.44% | −1.80% | 714 |
| momo_stopped | 2023-08-14→2025-08-14 | −10.10% | −5.18% | 2025-08-14→2026-08-14 | **+19.17%** | +19.19% | +68.10% | +0.61 | −44.28% | −14.50% | −1.86% | 755 |
| news_gated_momo | 2023-08-14→2025-08-14 | −10.10% | −5.18% | 2025-08-14→2026-08-14 | **+19.17%** | +19.19% | +68.10% | +0.61 | −44.28% | −14.50% | −1.86% | 755 |
| high_52wk | 2023-08-14→2025-08-14 | +34.41% | +15.92% | 2025-08-14→2026-08-14 | **+18.47%** | +18.48% | +16.03% | +1.14 | −11.67% | −15.21% | −2.57% | 562 |
| agentic_alloc | 2023-08-14→2025-08-14 | +22.67% | +10.75% | 2025-08-14→2026-08-14 | **+10.07%** | +10.08% | +5.57% | +1.76 | −4.59% | −23.60% | −10.97% | 230 |
| agentic_alloc_frozen | 2023-08-14→2025-08-14 | +22.67% | +10.75% | 2025-08-14→2026-08-14 | **+10.07%** | +10.08% | +5.57% | +1.76 | −4.59% | −23.60% | −10.97% | 230 |
| adaptive_mr | 2023-08-14→2025-08-14 | +7.03% | +3.45% | 2025-08-14→2026-08-14 | **+8.60%** | +8.60% | +16.41% | +0.59 | −8.96% | −25.07% | −12.44% | 462 |
| adaptive_mr_frozen | 2023-08-14→2025-08-14 | +7.03% | +3.45% | 2025-08-14→2026-08-14 | **+8.60%** | +8.60% | +16.41% | +0.59 | −8.96% | −25.07% | −12.44% | 462 |
| mr_overlay | 2023-08-14→2025-08-14 | +7.03% | +3.45% | 2025-08-14→2026-08-14 | **+8.60%** | +8.60% | +16.41% | +0.59 | −8.96% | −25.07% | −12.44% | 462 |
| low_vol | 2023-08-14→2025-08-14 | +32.96% | +15.30% | 2025-08-14→2026-08-14 | **+7.00%** | +7.00% | +9.14% | +0.79 | −5.54% | −26.68% | −14.04% | 188 |
| stop_tuner_turtle | 2023-08-14→2025-08-14 | −10.03% | −5.14% | 2025-08-14→2026-08-14 | **−5.86%** | −5.86% | +30.15% | −0.05 | −29.03% | −39.53% | −26.90% | 160 |
| turtle_breakout | 2023-08-14→2025-08-14 | −10.03% | −5.14% | 2025-08-14→2026-08-14 | **−5.86%** | −5.86% | +30.15% | −0.05 | −29.03% | −39.53% | −26.90% | 160 |
| earnings_context_pead | 2023-08-14→2025-08-14 | +0.00% | +0.00% | 2025-08-14→2026-08-14 | **+0.00%** | +0.00% | +0.00% | · | +0.00% | −33.67% | −21.04% | 0 |

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
