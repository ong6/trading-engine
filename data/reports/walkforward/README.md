# Walk-forward re-validation of the active league rules

_22 book(s) re-validated · protocol **train 24mo → validate 12mo, step 12mo, 6 folds, anchored 2026-08-14** · generated 2026-08-20 11:06 UTC._

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

**12 of 19 judged book(s) are `INDISTINGUISHABLE` from `ew_benchmark`** at 90% confidence on mean excess. Read every verdict in the next column with that column beside it.

| Book | Verdict | Distinguishable from EW? | Folds | Validate win rate | Beats EW | Mean validate | Mean excess vs EW | 90% CI on mean excess | Latest validate | Latest vs EW | Mean decay (CAGR) | Worst validate DD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [dual_momentum](dual_momentum.md) | REVIEW | **INDISTINGUISHABLE** | 6 | 67% | 33% | +13.63% | −16.92% | [−47.31%, +4.29%] | +24.83% | −8.84% | +7.84% | −18.75% |
| [low_vol](low_vol.md) | REVIEW | **INDISTINGUISHABLE** | 6 | 83% | 33% | +10.60% | −19.95% | [−52.39%, +3.75%] | +7.00% | −26.68% | +0.27% | −13.95% |
| [high_52wk](high_52wk.md) | REVIEW | **INDISTINGUISHABLE** | 6 | 83% | 33% | +10.47% | −20.08% | [−53.13%, +2.59%] | +18.47% | −15.21% | +3.36% | −21.54% |
| [dual_momentum_gated](dual_momentum_gated.md) | REVIEW | **distinguishable −** | 6 | 67% | 17% | +9.68% | −20.87% | [−49.49%, −1.16%] | +20.29% | −13.38% | +3.33% | −17.42% |
| [agentic_alloc](agentic_alloc.md) | REVIEW | **INDISTINGUISHABLE** | 6 | 83% | 33% | +7.58% | −22.97% | [−58.60%, +1.07%] | +10.07% | −23.60% | +2.09% | −9.36% |
| [agentic_alloc_frozen](agentic_alloc_frozen.md) | REVIEW | **INDISTINGUISHABLE** | 6 | 83% | 33% | +7.58% | −22.97% | [−58.60%, +1.07%] | +10.07% | −23.60% | +2.09% | −9.36% |
| [adaptive_mr](adaptive_mr.md) | REVIEW | **distinguishable −** | 6 | 50% | 17% | +5.46% | −25.09% | [−53.24%, −6.46%] | +8.60% | −25.07% | +3.10% | −17.30% |
| [adaptive_mr_frozen](adaptive_mr_frozen.md) | REVIEW | **distinguishable −** | 6 | 50% | 17% | +5.46% | −25.09% | [−53.24%, −6.46%] | +8.60% | −25.07% | +3.10% | −17.30% |
| [mr_overlay](mr_overlay.md) | REVIEW | **distinguishable −** | 6 | 50% | 17% | +5.46% | −25.09% | [−53.24%, −6.46%] | +8.60% | −25.07% | +3.10% | −17.30% |
| [stop_tuner_turtle](stop_tuner_turtle.md) | REVIEW | **distinguishable −** | 6 | 33% | 17% | +5.18% | −25.37% | [−45.20%, −7.45%] | −5.86% | −39.53% | +0.91% | −31.00% |
| [turtle_breakout](turtle_breakout.md) | REVIEW | **distinguishable −** | 6 | 33% | 17% | +5.18% | −25.37% | [−45.20%, −7.45%] | −5.86% | −39.53% | +0.91% | −31.00% |
| [template_top5](template_top5.md) | WATCH | **INDISTINGUISHABLE** | 6 | 33% | 33% | +63.41% | +32.85% | [−33.86%, +127.67%] | +68.78% | +35.11% | +17.22% | −68.96% |
| [template_top5_gated](template_top5_gated.md) | WATCH | **INDISTINGUISHABLE** | 6 | 33% | 33% | +60.65% | +30.10% | [−31.33%, +125.94%] | +44.53% | +10.86% | +14.71% | −55.20% |
| [template_top10_banded](template_top10_banded.md) | WATCH | **INDISTINGUISHABLE** | 6 | 33% | 33% | +42.05% | +11.50% | [−17.83%, +56.37%] | +27.43% | −6.24% | +10.70% | −47.81% |
| [template_top10_banded_gated](template_top10_banded_gated.md) | WATCH | **INDISTINGUISHABLE** | 6 | 50% | 33% | +40.92% | +10.37% | [−19.69%, +54.56%] | +19.23% | −14.44% | +8.19% | −43.69% |
| [momo_stopped](momo_stopped.md) | WATCH | **INDISTINGUISHABLE** | 6 | 50% | 33% | +35.34% | +4.79% | [−18.53%, +36.00%] | +19.17% | −14.50% | +2.50% | −48.01% |
| [news_gated_momo](news_gated_momo.md) | WATCH | **INDISTINGUISHABLE** | 6 | 50% | 33% | +35.34% | +4.79% | [−18.53%, +36.00%] | +19.17% | −14.50% | +2.50% | −48.01% |
| [sector_momentum](sector_momentum.md) | WATCH | **INDISTINGUISHABLE** | 6 | 100% | 50% | +16.14% | −14.41% | [−50.30%, +9.27%] | +28.69% | −4.98% | +5.49% | −17.18% |
| [mr_overlay_gated](mr_overlay_gated.md) | no-benchmark | _no interval_ | 6 | 67% | · | +6.96% | · | · | +11.38% | · | +3.81% | −13.64% |
| [ew_benchmark](ew_benchmark.md) | reference | — | 6 | 67% | 0% | +30.55% | +0.00% | [+0.00%, +0.00%] | +33.67% | +0.00% | +9.62% | −36.48% |
| [spy_benchmark](spy_benchmark.md) | reference | — | 6 | 83% | 50% | +16.48% | −14.07% | [−46.17%, +7.77%] | +21.04% | −12.63% | +1.74% | −22.22% |

## Latest validate window (2025-08-17 → 2026-08-17)

| Book | Train window | Train ret | Train CAGR | Validate window | Validate ret | CAGR | Vol | Sharpe | Max DD | vs EW | vs SPY | Fills | Universe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| mr_overlay_gated | 2023-08-17→2025-08-15 | +13.92% | +6.75% | 2025-08-15→2026-08-17 | **+11.38%** | +11.32% | +16.00% | +0.76 | −8.04% | · | · | 446 | · |

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
