# Walk-forward re-validation of the active league rules

_24 book(s) re-validated · protocol **train 24mo → validate 12mo, step 12mo, 6 folds, anchored 2026-08-14** · generated 2026-08-30 09:17 UTC._

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
| [ew_trend_gated](ew_trend_gated.md) | REVIEW | **distinguishable −** | 10 | 70% | 10% | +20.83% | −4.34% | [−8.04%, −1.63%] | +6.03% | −21.56% | +4.98% | −36.46% |
| [dual_momentum](dual_momentum.md) | REVIEW | **distinguishable −** | 10 | 70% | 40% | +9.61% | −15.57% | [−32.50%, −1.92%] | +23.09% | −4.51% | +3.71% | −33.69% |
| [high_52wk](high_52wk.md) | REVIEW | **distinguishable −** | 10 | 80% | 40% | +9.46% | −15.71% | [−34.18%, −1.71%] | +18.92% | −8.68% | +4.60% | −30.28% |
| [dual_momentum_gated](dual_momentum_gated.md) | REVIEW | **distinguishable −** | 10 | 70% | 30% | +9.29% | −15.89% | [−32.56%, −2.98%] | +18.55% | −9.04% | +2.54% | −17.47% |
| [turtle_breakout](turtle_breakout.md) | REVIEW | **distinguishable −** | 10 | 50% | 20% | +5.06% | −20.11% | [−32.58%, −9.05%] | −8.79% | −36.39% | +0.85% | −31.00% |
| [mr_overlay_gated](mr_overlay_gated.md) | REVIEW | **distinguishable −** | 10 | 50% | 20% | +3.59% | −21.58% | [−37.22%, −8.66%] | +10.70% | −16.90% | +2.78% | −15.47% |
| [mr_overlay](mr_overlay.md) | REVIEW | **distinguishable −** | 10 | 50% | 10% | +2.53% | −22.65% | [−37.96%, −10.53%] | +7.91% | −19.68% | +2.30% | −17.95% |
| [template_top10_banded](template_top10_banded.md) | WATCH | **INDISTINGUISHABLE** | 10 | 40% | 40% | +29.97% | +4.79% | [−12.75%, +30.44%] | +10.36% | −17.24% | +10.18% | −48.61% |
| [momo_stopped](momo_stopped.md) | WATCH | **INDISTINGUISHABLE** | 10 | 50% | 40% | +28.15% | +2.98% | [−11.67%, +21.21%] | +3.82% | −23.78% | +7.89% | −48.03% |
| [ew_voltarget](ew_voltarget.md) | WATCH | **INDISTINGUISHABLE** | 10 | 70% | 50% | +22.89% | −2.29% | [−7.40%, +1.97%] | +26.26% | −1.34% | +6.60% | −35.39% |
| [sector_momentum](sector_momentum.md) | WATCH | **INDISTINGUISHABLE** | 9 | 89% | 44% | +14.16% | −12.89% | [−36.13%, +3.50%] | +28.58% | +0.98% | +2.77% | −31.84% |
| [low_vol](low_vol.md) | WATCH | **INDISTINGUISHABLE** | 10 | 90% | 50% | +10.10% | −15.08% | [−33.94%, +0.54%] | +5.18% | −22.42% | −0.94% | −35.73% |
| [template_top5](template_top5.md) | PASS | **INDISTINGUISHABLE** | 10 | 50% | 60% | +50.60% | +25.43% | [−15.02%, +79.70%] | +41.01% | +13.41% | +20.19% | −65.26% |
| [template_top5_gated](template_top5_gated.md) | PASS | **INDISTINGUISHABLE** | 10 | 60% | 50% | +48.55% | +23.38% | [−14.65%, +79.29%] | +20.75% | −6.85% | +14.99% | −51.01% |
| [template_top10_banded_gated](template_top10_banded_gated.md) | PASS | **INDISTINGUISHABLE** | 10 | 50% | 50% | +29.85% | +4.67% | [−13.20%, +30.24%] | +3.46% | −24.14% | +8.33% | −46.39% |
| [news_gated_momo](news_gated_momo.md) | no-benchmark | _no interval_ | 6 | 50% | · | +35.34% | · | · | +19.17% | · | +2.50% | −48.01% |
| [agentic_alloc](agentic_alloc.md) | no-benchmark | _no interval_ | 6 | 83% | · | +7.58% | · | · | +10.07% | · | +2.09% | −9.36% |
| [agentic_alloc_frozen](agentic_alloc_frozen.md) | no-benchmark | _no interval_ | 6 | 83% | · | +7.58% | · | · | +10.07% | · | +2.09% | −9.36% |
| [adaptive_mr](adaptive_mr.md) | no-benchmark | _no interval_ | 6 | 50% | · | +5.46% | · | · | +8.60% | · | +3.10% | −17.30% |
| [adaptive_mr_frozen](adaptive_mr_frozen.md) | no-benchmark | _no interval_ | 6 | 50% | · | +5.46% | · | · | +8.60% | · | +3.10% | −17.30% |
| [stop_tuner_turtle](stop_tuner_turtle.md) | no-benchmark | _no interval_ | 6 | 33% | · | +5.18% | · | · | −5.86% | · | +0.91% | −31.00% |
| [ew_benchmark](ew_benchmark.md) | reference | — | 10 | 80% | 0% | +25.18% | +0.00% | [+0.00%, +0.00%] | +27.60% | +0.00% | +7.02% | −37.54% |
| [spy_benchmark](spy_benchmark.md) | reference | — | 10 | 90% | 40% | +15.23% | −9.95% | [−28.11%, +3.86%] | +19.30% | −8.30% | +1.72% | −32.30% |

## Latest validate window (2025-08-28 → 2026-08-28)

| Book | Train window | Train ret | Train CAGR | Validate window | Validate ret | CAGR | Vol | Sharpe | Max DD | vs EW | vs SPY | Fills | Universe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| template_top5 | 2023-08-28→2025-08-28 | −63.15% | −39.27% | 2025-08-28→2026-08-28 | **+41.01%** | +41.04% | +72.47% | +0.84 | −45.99% | +13.41% | +21.70% | 330 | 12,105 |
| sector_momentum | 2023-08-28→2025-08-28 | +27.15% | +12.75% | 2025-08-28→2026-08-28 | **+28.58%** | +28.60% | +13.56% | +1.93 | −7.91% | +0.98% | +9.27% | 41 | 12,105 |
| ew_benchmark | 2023-08-28→2025-08-28 | +29.63% | +13.85% | 2025-08-28→2026-08-28 | **+27.60%** | +27.62% | +56.20% | +0.72 | −36.48% | +0.00% | +8.30% | 910 | 12,105 |
| ew_voltarget | 2023-08-28→2025-08-28 | +46.22% | +20.90% | 2025-08-28→2026-08-28 | **+26.26%** | +26.28% | +51.66% | +0.71 | −31.74% | −1.34% | +6.96% | 905 | 12,105 |
| dual_momentum | 2023-08-28→2025-08-28 | +35.14% | +16.24% | 2025-08-28→2026-08-28 | **+23.09%** | +23.11% | +14.84% | +1.48 | −11.42% | −4.51% | +3.79% | 11 | 12,105 |
| template_top5_gated | 2023-08-28→2025-08-28 | −46.63% | −26.93% | 2025-08-28→2026-08-28 | **+20.75%** | +20.76% | +70.81% | +0.63 | −45.99% | −6.85% | +1.45% | 320 | 12,105 |
| spy_benchmark | 2023-08-28→2025-08-28 | +49.61% | +22.30% | 2025-08-28→2026-08-28 | **+19.30%** | +19.32% | +12.48% | +1.48 | −8.65% | −8.30% | +0.00% | 0 | 12,105 |
| high_52wk | 2023-08-28→2025-08-28 | +37.89% | +17.41% | 2025-08-28→2026-08-28 | **+18.92%** | +18.93% | +16.04% | +1.16 | −11.67% | −8.68% | −0.39% | 566 | 12,105 |
| dual_momentum_gated | 2023-08-28→2025-08-28 | +19.03% | +9.10% | 2025-08-28→2026-08-28 | **+18.55%** | +18.57% | +13.71% | +1.31 | −11.42% | −9.04% | −0.75% | 11 | 12,105 |
| mr_overlay_gated | 2023-08-28→2025-08-28 | +12.66% | +6.14% | 2025-08-28→2026-08-28 | **+10.70%** | +10.71% | +16.15% | +0.71 | −8.04% | −16.90% | −8.60% | 443 | 12,105 |
| template_top10_banded | 2023-08-28→2025-08-28 | −16.01% | −8.35% | 2025-08-28→2026-08-28 | **+10.36%** | +10.36% | +70.76% | +0.50 | −43.70% | −17.24% | −8.94% | 744 | 12,105 |
| mr_overlay | 2023-08-28→2025-08-28 | +10.71% | +5.21% | 2025-08-28→2026-08-28 | **+7.91%** | +7.92% | +16.55% | +0.54 | −8.96% | −19.68% | −11.39% | 459 | 12,105 |
| ew_trend_gated | 2023-08-28→2025-08-28 | +21.70% | +10.31% | 2025-08-28→2026-08-28 | **+6.03%** | +6.04% | +55.32% | +0.38 | −36.46% | −21.56% | −13.27% | 852 | 12,105 |
| low_vol | 2023-08-28→2025-08-28 | +33.49% | +15.52% | 2025-08-28→2026-08-28 | **+5.18%** | +5.19% | +9.11% | +0.60 | −5.56% | −22.42% | −14.12% | 189 | 12,105 |
| momo_stopped | 2023-08-28→2025-08-28 | −11.03% | −5.67% | 2025-08-28→2026-08-28 | **+3.82%** | +3.82% | +68.18% | +0.40 | −44.47% | −23.78% | −15.49% | 757 | 12,105 |
| template_top10_banded_gated | 2023-08-28→2025-08-28 | −17.45% | −9.13% | 2025-08-28→2026-08-28 | **+3.46%** | +3.46% | +69.68% | +0.41 | −43.69% | −24.14% | −15.84% | 715 | 12,105 |
| turtle_breakout | 2023-08-28→2025-08-28 | −7.24% | −3.68% | 2025-08-28→2026-08-28 | **−8.79%** | −8.79% | +29.95% | −0.16 | −30.08% | −36.39% | −28.09% | 159 | 12,105 |

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
