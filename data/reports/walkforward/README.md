# Walk-forward re-validation of the active league rules

_24 book(s) re-validated · protocol **train 24mo → validate 12mo, step 12mo, 6 folds, anchored 2026-08-14** · generated 2026-08-23 09:20 UTC._

Every book below is replayed by its OWN live strategy code through the real `sim/league.py` day-step — real orders, real t+1-open fills with the league's slippage and liquidity guards, real dividend crediting. The config replayed is the JSON frozen in the live `portfolios` row (D-WF4), i.e. the rule the league is actually trading. Nothing is reimplemented for this report and no bar is ever invented.

This is the input to the **Sunday review loop** (execution design §6): changes are made at reviews, one at a time, justified by walk-forward evidence rather than last week's P&L.

## Disclosures — read before any number below

1. **Survivor universe, and it is NOT a constant.** `prices` holds only tickers
   listed TODAY, so every name delisted, acquired or bankrupted inside a fold is
   absent entirely. The house lesson has priced this at roughly **+7pp/yr of fake
   return** for a screen-driven book — but that flat figure is wrong in SHAPE, and
   the `Universe` column on every fold table below exists to show it. Measured
   2026-08-20 against World Bank listed-company counts, the store covers
   **~11% of the companies that existed in 1996, ~24% in 2003 and ~42% in 2014**
   (ex-ETF). The bias therefore grows monotonically as a window moves back, and an
   early fold rests on a thinner, more winner-selected cross-section than a late
   one. Not one 2008 casualty is present: LEH, BSC, ENE, WCOM, CFC, MER, SIVB and
   FRC are all absent, so **a fold spanning 2008 is one in which those names cannot
   lose money.** That is WHY the headline comparison here is **vs EW (same
   universe, same screen), fold by fold** — the bias is largely common to both
   sides of that difference. Absolute return is context, not evidence, and a fold
   with a small `Universe` count deserves proportionally less weight.
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


**The interval is new information, not a new rule (added 2026-08-20).** The
PASS / WATCH / REVIEW rule above is unchanged: it still reads the beat rate and
the *mean* excess exactly as it was pre-registered, and no verdict in this
report has been recomputed, softened or overridden by an interval. What is new
is the **90% bootstrap CI on mean excess vs EW** in the column beside it, and a
mechanical `INDISTINGUISHABLE` label for any book whose interval contains 0.

Read the two together: a **PASS whose interval straddles zero is a PASS on a
number this evidence cannot separate from the benchmark**, and a REVIEW whose
interval straddles zero is not proof the book is broken either. The verdict says
what gets read on Sunday. The interval says how much the number underneath it
is worth.

**Method.** Percentile bootstrap over FOLDS, 10,000 resamples, fixed seed
`20260820` so the report re-renders identically from unchanged inputs. Folds are
the resampling unit because each is an independent replay from the reference
notional (D-WF2) over a validate window no other fold's validate window touches
(D-WF1). Folds with status other than `ok` — including `inert`, a book that
placed zero fills — are excluded before resampling; an inert fold is not
evidence. Fewer than 3 comparable folds gets **no interval**, printed as
`·`, never a zero.

**Caveat that cuts against us.** Adjacent folds share twelve months of TRAIN
window (train 24mo, step 12mo) and all folds come from one market history, so an
i.i.d. bootstrap UNDERSTATES the true uncertainty. These intervals are a floor
on the error bar. At 10 folds the bootstrap can reject a large effect and cannot
confirm a small one; methods that could (block or stationary bootstrap) need a
fold count in the high tens and are deliberately not used here.


⚑ = the fold's train window was clamped to the book's data floor. ◈ = the validate window extends past league inception (2026-07-17) and so partly shadows the live record.

## Summary — all books, all folds

**8 of 21 judged book(s) are `INDISTINGUISHABLE` from `ew_benchmark`** at 90% confidence on mean excess. Read every verdict in the next column with that column beside it.

| Book | Verdict | Distinguishable from EW? | Folds | Validate win rate | Beats EW | Mean validate | Mean excess vs EW | 90% CI on mean excess | Latest validate | Latest vs EW | Mean decay (CAGR) | Worst validate DD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [ew_trend_gated](ew_trend_gated.md) | REVIEW | **distinguishable −** | 10 | 60% | 10% | +19.46% | −4.61% | [−8.75%, −1.68%] | +18.37% | −24.07% | +4.60% | −36.46% |
| [sector_momentum](sector_momentum.md) | REVIEW | **INDISTINGUISHABLE** | 9 | 89% | 33% | +14.40% | −12.54% | [−31.23%, +1.62%] | +32.33% | −10.12% | +3.67% | −31.84% |
| [dual_momentum](dual_momentum.md) | REVIEW | **distinguishable −** | 10 | 60% | 30% | +9.69% | −14.38% | [−28.65%, −1.99%] | +26.27% | −16.17% | +4.22% | −33.69% |
| [high_52wk](high_52wk.md) | REVIEW | **distinguishable −** | 10 | 80% | 30% | +9.38% | −14.70% | [−30.55%, −1.94%] | +21.62% | −20.82% | +4.75% | −30.28% |
| [dual_momentum_gated](dual_momentum_gated.md) | REVIEW | **distinguishable −** | 10 | 70% | 30% | +9.26% | −14.81% | [−28.32%, −3.25%] | +21.62% | −20.82% | +2.96% | −17.47% |
| [turtle_breakout](turtle_breakout.md) | REVIEW | **distinguishable −** | 10 | 50% | 20% | +4.60% | −19.47% | [−30.65%, −9.03%] | −3.12% | −45.57% | −3.09% | −31.00% |
| [mr_overlay_gated](mr_overlay_gated.md) | REVIEW | **distinguishable −** | 10 | 50% | 10% | +3.33% | −20.74% | [−34.22%, −8.81%] | +13.30% | −29.15% | +2.54% | −15.47% |
| [mr_overlay](mr_overlay.md) | REVIEW | **distinguishable −** | 10 | 50% | 0% | +2.25% | −21.82% | [−34.99%, −10.69%] | +10.45% | −32.00% | +2.04% | −17.95% |
| [template_top5](template_top5.md) | WATCH | **INDISTINGUISHABLE** | 10 | 40% | 40% | +48.47% | +24.39% | [−12.07%, +68.57%] | +89.57% | +47.12% | +19.28% | −68.54% |
| [template_top10_banded](template_top10_banded.md) | WATCH | **INDISTINGUISHABLE** | 10 | 60% | 30% | +28.05% | +3.98% | [−12.37%, +27.14%] | +32.90% | −9.55% | +8.17% | −48.61% |
| [template_top10_banded_gated](template_top10_banded_gated.md) | WATCH | **INDISTINGUISHABLE** | 10 | 70% | 30% | +27.82% | +3.74% | [−12.92%, +26.61%] | +24.60% | −17.84% | +5.73% | −46.39% |
| [momo_stopped](momo_stopped.md) | WATCH | **INDISTINGUISHABLE** | 10 | 70% | 30% | +26.22% | +2.15% | [−11.95%, +19.07%] | +24.19% | −18.25% | +5.69% | −48.03% |
| [ew_voltarget](ew_voltarget.md) | WATCH | **INDISTINGUISHABLE** | 10 | 70% | 50% | +22.18% | −1.90% | [−6.35%, +1.94%] | +40.65% | −1.80% | +7.08% | −35.39% |
| [low_vol](low_vol.md) | WATCH | **INDISTINGUISHABLE** | 10 | 90% | 50% | +10.09% | −13.99% | [−30.40%, +0.45%] | +4.51% | −37.93% | −0.99% | −35.73% |
| [template_top5_gated](template_top5_gated.md) | PASS | **INDISTINGUISHABLE** | 10 | 50% | 50% | +44.30% | +20.23% | [−12.67%, +62.73%] | +62.34% | +19.90% | +11.66% | −55.64% |
| [news_gated_momo](news_gated_momo.md) | no-benchmark | _no interval_ | 6 | 50% | · | +35.34% | · | · | +19.17% | · | +2.50% | −48.01% |
| [agentic_alloc](agentic_alloc.md) | no-benchmark | _no interval_ | 6 | 83% | · | +7.58% | · | · | +10.07% | · | +2.09% | −9.36% |
| [agentic_alloc_frozen](agentic_alloc_frozen.md) | no-benchmark | _no interval_ | 6 | 83% | · | +7.58% | · | · | +10.07% | · | +2.09% | −9.36% |
| [adaptive_mr](adaptive_mr.md) | no-benchmark | _no interval_ | 6 | 50% | · | +5.46% | · | · | +8.60% | · | +3.10% | −17.30% |
| [adaptive_mr_frozen](adaptive_mr_frozen.md) | no-benchmark | _no interval_ | 6 | 50% | · | +5.46% | · | · | +8.60% | · | +3.10% | −17.30% |
| [stop_tuner_turtle](stop_tuner_turtle.md) | no-benchmark | _no interval_ | 6 | 33% | · | +5.18% | · | · | −5.86% | · | +0.91% | −31.00% |
| [ew_benchmark](ew_benchmark.md) | reference | — | 10 | 70% | 0% | +24.07% | +0.00% | [+0.00%, +0.00%] | +42.45% | +0.00% | +7.06% | −37.54% |
| [spy_benchmark](spy_benchmark.md) | reference | — | 10 | 90% | 50% | +14.97% | −9.10% | [−24.01%, +3.26%] | +21.20% | −21.25% | +1.31% | −32.41% |

## Latest validate window (2025-08-21 → 2026-08-21)

| Book | Train window | Train ret | Train CAGR | Validate window | Validate ret | CAGR | Vol | Sharpe | Max DD | vs EW | vs SPY | Fills | Universe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| template_top5 | 2023-08-21→2025-08-21 | −70.05% | −45.25% | 2025-08-21→2026-08-21 | **+89.57%** | +89.65% | +72.49% | +1.25 | −45.99% | +47.12% | +68.37% | 332 | 12,105 |
| template_top5_gated | 2023-08-21→2025-08-21 | −56.63% | −34.12% | 2025-08-21→2026-08-21 | **+62.34%** | +62.40% | +70.86% | +1.05 | −45.99% | +19.90% | +41.15% | 321 | 12,105 |
| ew_benchmark | 2023-08-21→2025-08-21 | +20.21% | +9.63% | 2025-08-21→2026-08-21 | **+42.45%** | +42.48% | +56.29% | +0.91 | −36.48% | +0.00% | +21.25% | 910 | 12,105 |
| ew_voltarget | 2023-08-21→2025-08-21 | +35.59% | +16.43% | 2025-08-21→2026-08-21 | **+40.65%** | +40.68% | +51.76% | +0.92 | −31.74% | −1.80% | +19.45% | 905 | 12,105 |
| template_top10_banded | 2023-08-21→2025-08-21 | −20.47% | −10.81% | 2025-08-21→2026-08-21 | **+32.90%** | +32.92% | +70.66% | +0.77 | −43.70% | −9.55% | +11.70% | 744 | 12,105 |
| sector_momentum | 2023-08-21→2025-08-21 | +24.47% | +11.56% | 2025-08-21→2026-08-21 | **+32.33%** | +32.35% | +13.59% | +2.14 | −7.91% | −10.12% | +11.13% | 41 | 12,105 |
| dual_momentum | 2023-08-21→2025-08-21 | +32.37% | +15.04% | 2025-08-21→2026-08-21 | **+26.27%** | +26.29% | +14.89% | +1.65 | −11.42% | −16.17% | +5.08% | 11 | 12,105 |
| template_top10_banded_gated | 2023-08-21→2025-08-21 | −21.87% | −11.60% | 2025-08-21→2026-08-21 | **+24.60%** | +24.62% | +69.59% | +0.67 | −43.70% | −17.84% | +3.40% | 717 | 12,105 |
| momo_stopped | 2023-08-21→2025-08-21 | −15.79% | −8.23% | 2025-08-21→2026-08-21 | **+24.19%** | +24.21% | +68.12% | +0.67 | −44.47% | −18.25% | +2.99% | 759 | 12,105 |
| high_52wk | 2023-08-21→2025-08-21 | +34.97% | +16.16% | 2025-08-21→2026-08-21 | **+21.62%** | +21.64% | +16.17% | +1.30 | −11.67% | −20.82% | +0.42% | 566 | 12,105 |
| dual_momentum_gated | 2023-08-21→2025-08-21 | +16.59% | +7.97% | 2025-08-21→2026-08-21 | **+21.62%** | +21.64% | +13.77% | +1.50 | −11.42% | −20.82% | +0.42% | 11 | 12,105 |
| spy_benchmark | 2023-08-21→2025-08-21 | +47.09% | +21.26% | 2025-08-21→2026-08-21 | **+21.20%** | +21.21% | +12.55% | +1.60 | −8.65% | −21.25% | +0.00% | 0 | 12,105 |
| ew_trend_gated | 2023-08-21→2025-08-21 | +12.85% | +6.23% | 2025-08-21→2026-08-21 | **+18.37%** | +18.39% | +55.43% | +0.58 | −36.46% | −24.07% | −2.82% | 852 | 12,105 |
| mr_overlay_gated | 2023-08-21→2025-08-21 | +10.95% | +5.33% | 2025-08-21→2026-08-21 | **+13.30%** | +13.31% | +16.09% | +0.86 | −8.04% | −29.15% | −7.90% | 448 | 12,105 |
| mr_overlay | 2023-08-21→2025-08-21 | +9.02% | +4.41% | 2025-08-21→2026-08-21 | **+10.45%** | +10.46% | +16.50% | +0.69 | −8.96% | −32.00% | −10.75% | 464 | 12,105 |
| low_vol | 2023-08-21→2025-08-21 | +34.57% | +15.99% | 2025-08-21→2026-08-21 | **+4.51%** | +4.51% | +9.11% | +0.53 | −5.56% | −37.93% | −16.69% | 189 | 12,105 |
| turtle_breakout | 2023-08-21→2025-08-21 | −1.56% | −0.78% | 2025-08-21→2026-08-21 | **−3.12%** | −3.12% | +30.02% | +0.05 | −29.09% | −45.57% | −24.32% | 155 | 12,105 |

## Books NOT walk-forwarded

* **pead_ear** — no historical earnings dates — `earnings_calendar` spans only 2026-04→2026-10, so the entry signal cannot be computed. Forward record only.
* **discretionary** — human book — orders come from UI tickets, not code.
* **macro_composite** — its inputs are point-in-time by `fetch_as_of`, and the production `macro_signals` backfill stamps fetch_as_of = today (honest: we did not have those series in 2019). A historical replay therefore sees an empty signal table and the book is inert, not wrong. Needs a labelled `--pit-lag` reconstruction backfill before it can be walk-forwarded.
* **earnings_context_pead** — INERT: 0 fills in 6 fold(s). The book replayed without error and never traded, so it has no return, no drawdown and no verdict. Usually a config the strategy can never satisfy — check its params before reading anything into it.

## How this is produced

```sh
# enumerate / enqueue the weekly grid (one job per active book)
.venv/bin/python farm/walkforward/grid.py --list
.venv/bin/python farm/walkforward/grid.py --enqueue
.venv/bin/python engine/queue_runner.py --run
```

Intended cadence: **Sunday**, ahead of the weekly review. The weekday nightly (`engine/run_daily.sh`, cron `30 22 * * 1-5`) never runs on a Sunday, so this workload is enqueued by its own cron entry rather than by the nightly — see BUILDLOG.
