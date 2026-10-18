# Walk-forward re-validation of league rules

_18 book(s) re-validated · protocol **train 24mo → validate 12mo, step 12mo, 10 folds, anchored 2026-10-16** · generated 2026-10-18 08:48 UTC._

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
   lose money.** That is WHY the headline comparison for single-name books is
   **vs EW (same universe, same screen), fold by fold** — the bias is largely
   common to both sides of that difference. Newly generated ETF/asset-allocation
   artifacts declare SPY as their comparison. Absolute return is context, not evidence, and a fold
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


**Verdict rule (mechanical exploratory triage, NOT an automatic kill).** For
each book, against the versioned comparison declared in its result artifact:

* **PASS** — beats its control in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails its control.

REVIEW means the book goes on the Sunday review agenda against its own frozen
kill criterion (printed on its page). The prose criterion decides; this flag
only decides what gets read. Historical comparator choices are exploratory,
not proof of pre-registration or positive edge. Benchmarks are not judged.


**The interval is new information, not a new rule (added 2026-08-20).** The
PASS / WATCH / REVIEW rule reads the beat rate and the *mean* excess; the
interval does not soften or override that triage label. It is the **90%
bootstrap CI on mean excess vs the declared control** in the column beside it, and a
mechanical `INDISTINGUISHABLE` label for any book whose interval contains 0.

Read the two together: a **PASS whose interval straddles zero is a PASS on a
number this evidence cannot separate from the control**, and a REVIEW whose
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


Retained retired evidence is included in this cohort and labelled `RETIRED`; it is neither scheduled nor traded. A retained result without `source_sha256` is explicitly legacy/unstamped and is not used to admit any unstamped active result into the cohort.

⚑ = the fold's train window was clamped to the book's data floor. ◈ = the validate window extends past league inception (2026-07-17) and so partly shadows the live record.

## Summary — all books, all folds

**8 of 16 judged book(s) are `INDISTINGUISHABLE` from their declared control** at 90% confidence on mean excess. Read every verdict in the next column with that column beside it.

| Book | Evidence class | Control | Verdict | Distinguishable? | Folds | Validate win rate | Beats control | Mean validate | Mean excess | 90% CI on mean excess | Latest validate | Latest excess | Mean decay (CAGR) | Worst validate DD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [ew_trend_gated](ew_trend_gated.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **distinguishable −** | 10 | 60% | 40% | +20.68% | −3.67% | [−6.40%, −1.11%] | −30.49% | −13.96% | +0.28% | −37.08% |
| [dual_momentum](dual_momentum.md) | `fixed_etf_history` | spy_benchmark | REVIEW | **distinguishable −** | 10 | 60% | 40% | +9.40% | −6.32% | [−12.73%, −0.37%] | +15.31% | −0.95% | +2.66% | −33.69% |
| [dual_momentum_gated](dual_momentum_gated.md) | `fixed_etf_history` | spy_benchmark | REVIEW | **distinguishable −** | 10 | 70% | 30% | +8.97% | −6.75% | [−12.11%, −1.86%] | +11.06% | −5.20% | +1.42% | −17.47% |
| [turtle_breakout](turtle_breakout.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **distinguishable −** | 10 | 50% | 20% | +5.20% | −19.15% | [−31.71%, −7.07%] | −21.16% | −4.64% | −2.25% | −33.39% |
| [template_top10_banded_gated](template_top10_banded_gated.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 50% | 30% | +31.03% | +6.68% | [−13.75%, +31.36%] | −24.33% | −7.81% | +1.96% | −46.80% |
| [template_top10_banded](template_top10_banded.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 50% | 30% | +28.73% | +4.38% | [−14.49%, +28.52%] | −19.26% | −2.73% | +4.72% | −49.62% |
| [momo_stopped](momo_stopped.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 50% | 30% | +28.24% | +3.89% | [−13.42%, +24.06%] | −20.21% | −3.68% | +3.63% | −49.68% |
| [ew_voltarget](ew_voltarget.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 70% | 50% | +21.52% | −2.83% | [−8.03%, +1.61%] | −16.76% | −0.24% | +2.19% | −36.63% |
| [sector_momentum](sector_momentum.md) | `fixed_etf_history` | spy_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 100% | 30% | +13.96% | −1.76% | [−6.61%, +3.81%] | +30.14% | +13.88% | +2.87% | −31.86% |
| [high_52wk](high_52wk.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 80% | 30% | +10.62% | −13.73% | [−29.77%, +0.50%] | +7.42% | +23.95% | +4.62% | −32.26% |
| [mr_overlay_gated](mr_overlay_gated.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **distinguishable −** | 10 | 50% | 30% | +3.62% | −20.73% | [−37.53%, −4.89%] | +7.02% | +23.54% | +1.53% | −13.64% |
| [mr_overlay](mr_overlay.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **distinguishable −** | 10 | 70% | 20% | +2.49% | −21.86% | [−37.61%, −7.44%] | +4.33% | +20.85% | +1.49% | −23.68% |
| [template_top5](template_top5.md) | `current_universe_survivor_biased` | ew_benchmark | PASS | **INDISTINGUISHABLE** | 10 | 60% | 50% | +56.14% | +31.79% | [−10.12%, +81.61%] | +22.03% | +38.55% | +22.76% | −61.11% |
| [template_top5_gated](template_top5_gated.md) | `current_universe_survivor_biased` | ew_benchmark | PASS | **INDISTINGUISHABLE** | 10 | 60% | 50% | +51.64% | +27.29% | [−7.26%, +67.83%] | +4.79% | +21.32% | +9.05% | −47.35% |
| [xs_momentum_12_1](xs_momentum_12_1.md) | `current_universe_survivor_biased` | ew_benchmark | PASS | **distinguishable +** | 10 | 80% | 90% | +33.81% | +9.46% | [+0.71%, +16.80%] | −0.82% | +15.71% | +2.64% | −42.23% |
| [low_vol](low_vol.md) | `static_fundamental_lookahead` | ew_benchmark | no-benchmark | _no interval_ | 10 | 90% | · | +10.81% | · | · | +4.40% | · | +0.31% | −34.13% |
| [ew_benchmark](ew_benchmark.md) | `current_universe_survivor_biased` | — | reference | — | 10 | 60% | · | +24.35% | · | · | −16.52% | · | +2.65% | −38.78% |
| [spy_benchmark](spy_benchmark.md) | `fixed_etf_history` | — | reference | — | 10 | 90% | · | +15.72% | · | · | +16.26% | · | +1.81% | −32.53% |

## Latest validate window (2025-10-16 → 2026-10-16)

| Book | Train window | Train ret | Train CAGR | Validate window | Validate ret | CAGR | Vol | Sharpe | Max DD | vs EW | vs SPY | Fills | Universe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sector_momentum | 2023-10-16→2025-10-16 | +41.98% | +19.14% | 2025-10-16→2026-10-16 | **+30.14%** | +30.16% | +12.93% | +2.11 | −7.91% | · | +13.88% | 40 | 12,715 |
| template_top5 | 2023-10-16→2025-10-16 | −23.10% | −12.30% | 2025-10-16→2026-10-16 | **+22.03%** | +22.04% | +72.40% | +0.64 | −45.89% | +38.55% | · | 344 | 12,715 |
| spy_benchmark | 2023-10-16→2025-10-16 | +55.42% | +24.65% | 2025-10-16→2026-10-16 | **+16.26%** | +16.27% | +12.37% | +1.28 | −8.64% | · | +0.00% | 0 | 12,715 |
| dual_momentum | 2023-10-16→2025-10-16 | +48.40% | +21.80% | 2025-10-16→2026-10-16 | **+15.31%** | +15.32% | +14.97% | +1.03 | −11.42% | · | −0.95% | 11 | 12,715 |
| dual_momentum_gated | 2023-10-16→2025-10-16 | +30.97% | +14.43% | 2025-10-16→2026-10-16 | **+11.06%** | +11.07% | +13.85% | +0.83 | −11.42% | · | −5.20% | 11 | 12,715 |
| high_52wk | 2023-10-16→2025-10-16 | +60.73% | +26.76% | 2025-10-16→2026-10-16 | **+7.42%** | +7.43% | +15.50% | +0.54 | −11.46% | +23.95% | · | 543 | 12,715 |
| mr_overlay_gated | 2023-10-16→2025-10-16 | +25.72% | +12.12% | 2025-10-16→2026-10-16 | **+7.02%** | +7.02% | +17.12% | +0.48 | −9.98% | +23.54% | · | 435 | 12,715 |
| template_top5_gated | 2023-10-16→2025-10-16 | +0.99% | +0.49% | 2025-10-16→2026-10-16 | **+4.79%** | +4.79% | +70.71% | +0.42 | −45.89% | +21.32% | · | 326 | 12,715 |
| low_vol | 2023-10-16→2025-10-16 | +38.03% | +17.47% | 2025-10-16→2026-10-16 | **+4.40%** | +4.40% | +9.23% | +0.51 | −8.83% | · | · | 198 | 12,715 |
| mr_overlay | 2023-10-16→2025-10-16 | +23.13% | +10.96% | 2025-10-16→2026-10-16 | **+4.33%** | +4.33% | +17.49% | +0.33 | −9.98% | +20.85% | · | 451 | 12,715 |
| xs_momentum_12_1 | 2023-10-16→2025-10-16 | +142.50% | +55.68% | 2025-10-16→2026-10-16 | **−0.82%** | −0.82% | +50.85% | +0.24 | −28.41% | +15.71% | · | 732 | 12,715 |
| ew_benchmark | 2023-10-16→2025-10-16 | +93.68% | +39.14% | 2025-10-16→2026-10-16 | **−16.52%** | −16.54% | +55.66% | −0.05 | −37.10% | +0.00% | · | 898 | 12,715 |
| ew_voltarget | 2023-10-16→2025-10-16 | +108.01% | +44.19% | 2025-10-16→2026-10-16 | **−16.76%** | −16.77% | +50.97% | −0.11 | −34.39% | −0.24% | · | 914 | 12,715 |
| template_top10_banded | 2023-10-16→2025-10-16 | +41.34% | +18.87% | 2025-10-16→2026-10-16 | **−19.26%** | −19.27% | +69.76% | +0.05 | −44.49% | −2.73% | · | 767 | 12,715 |
| momo_stopped | 2023-10-16→2025-10-16 | +44.37% | +20.14% | 2025-10-16→2026-10-16 | **−20.21%** | −20.22% | +66.95% | +0.01 | −44.19% | −3.68% | · | 787 | 12,715 |
| turtle_breakout | 2023-10-16→2025-10-16 | +31.15% | +14.51% | 2025-10-16→2026-10-16 | **−21.16%** | −21.18% | +29.54% | −0.66 | −33.39% | −4.64% | · | 168 | 12,715 |
| template_top10_banded_gated | 2023-10-16→2025-10-16 | +40.33% | +18.45% | 2025-10-16→2026-10-16 | **−24.33%** | −24.35% | +68.68% | −0.06 | −44.49% | −7.81% | · | 740 | 12,715 |
| ew_trend_gated | 2023-10-16→2025-10-16 | +81.09% | +34.54% | 2025-10-16→2026-10-16 | **−30.49%** | −30.50% | +54.71% | −0.39 | −37.08% | −13.96% | · | 842 | 12,715 |

## Books NOT walk-forwarded

* **pead_ear** — no historical earnings dates — `earnings_calendar` spans only 2026-04→2026-10, so the entry signal cannot be computed. Forward record only.
* **discretionary** — human book — orders come from UI tickets, not code.
* **macro_composite** — its inputs are point-in-time by `fetch_as_of`, and the production `macro_signals` backfill stamps fetch_as_of = today (honest: we did not have those series in 2019). A historical replay therefore sees an empty signal table and the book is inert, not wrong. Needs a labelled `--pit-lag` reconstruction backfill before it can be walk-forwarded.

## How this is produced

```sh
# enumerate / enqueue the weekly grid (one job per active book)
.venv/bin/python -m farm.walkforward.grid --list
.venv/bin/python -m farm.walkforward.grid --enqueue
.venv/bin/python -m engine.queue_runner --run
```

Intended cadence: **Sunday**, ahead of the weekly review. The weekday nightly (`engine/run_daily.sh`, cron `30 22 * * 1-5`) never runs on a Sunday, so this workload is enqueued by its own cron entry rather than by the nightly — see BUILDLOG.
