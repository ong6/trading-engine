# Walk-forward re-validation of league rules

_18 book(s) re-validated · protocol **train 24mo → validate 12mo, step 12mo, 10 folds, anchored 2026-09-22** · generated 2026-09-23 18:54 UTC._

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
| [ew_voltarget](ew_voltarget.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **INDISTINGUISHABLE** | 10 | 70% | 40% | +23.16% | −2.71% | [−7.75%, +1.55%] | +9.72% | −1.34% | +5.18% | −35.49% |
| [ew_trend_gated](ew_trend_gated.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **distinguishable −** | 10 | 60% | 20% | +21.88% | −3.99% | [−7.33%, −1.08%] | −7.52% | −18.59% | +3.63% | −37.12% |
| [dual_momentum_gated](dual_momentum_gated.md) | `fixed_etf_history` | spy_benchmark | REVIEW | **distinguishable −** | 10 | 70% | 30% | +9.07% | −6.43% | [−10.63%, −2.39%] | +13.74% | −2.99% | +1.70% | −17.47% |
| [turtle_breakout](turtle_breakout.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **distinguishable −** | 10 | 50% | 10% | +6.06% | −19.81% | [−30.92%, −9.62%] | −19.89% | −30.96% | −1.61% | −33.22% |
| [mr_overlay_gated](mr_overlay_gated.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **distinguishable −** | 10 | 60% | 20% | +3.16% | −22.72% | [−39.55%, −8.56%] | +5.34% | −5.73% | +1.84% | −13.73% |
| [mr_overlay](mr_overlay.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **distinguishable −** | 10 | 60% | 20% | +2.04% | −23.84% | [−39.92%, −10.81%] | +2.69% | −8.38% | +1.37% | −17.30% |
| [template_top10_banded_gated](template_top10_banded_gated.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 40% | 30% | +29.49% | +3.61% | [−13.21%, +24.56%] | −1.49% | −12.55% | +2.93% | −47.44% |
| [template_top10_banded](template_top10_banded.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 50% | 30% | +28.12% | +2.25% | [−13.46%, +23.16%] | +5.12% | −5.95% | +5.30% | −49.36% |
| [momo_stopped](momo_stopped.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 40% | 30% | +26.55% | +0.68% | [−13.15%, +16.83%] | −2.39% | −13.46% | +3.45% | −49.63% |
| [sector_momentum](sector_momentum.md) | `fixed_etf_history` | spy_benchmark | WATCH | **INDISTINGUISHABLE** | 9 | 89% | 33% | +14.01% | −1.39% | [−6.72%, +4.75%] | +24.08% | +7.34% | +1.81% | −31.86% |
| [high_52wk](high_52wk.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **distinguishable −** | 10 | 70% | 30% | +10.21% | −15.67% | [−33.65%, −1.53%] | +14.23% | +3.17% | +4.70% | −32.32% |
| [dual_momentum](dual_momentum.md) | `fixed_etf_history` | spy_benchmark | WATCH | **distinguishable −** | 10 | 60% | 40% | +9.60% | −5.90% | [−11.08%, −1.01%] | +18.09% | +1.36% | +2.98% | −33.69% |
| [template_top5](template_top5.md) | `current_universe_survivor_biased` | ew_benchmark | PASS | **INDISTINGUISHABLE** | 10 | 60% | 50% | +57.10% | +31.22% | [−9.90%, +80.49%] | +47.65% | +36.59% | +21.00% | −61.59% |
| [template_top5_gated](template_top5_gated.md) | `current_universe_survivor_biased` | ew_benchmark | PASS | **INDISTINGUISHABLE** | 10 | 60% | 60% | +52.91% | +27.03% | [−7.88%, +68.37%] | +26.84% | +15.77% | +8.38% | −49.00% |
| [xs_momentum_12_1](xs_momentum_12_1.md) | `current_universe_survivor_biased` | ew_benchmark | PASS | **INDISTINGUISHABLE** | 10 | 90% | 90% | +32.91% | +7.04% | [−4.93%, +15.98%] | +22.37% | +11.30% | +3.74% | −42.92% |
| [low_vol](low_vol.md) | `static_fundamental_lookahead` | ew_benchmark | no-benchmark | _no interval_ | 10 | 90% | · | +9.71% | · | · | +3.08% | · | −1.63% | −35.83% |
| [ew_benchmark](ew_benchmark.md) | `current_universe_survivor_biased` | — | reference | — | 10 | 70% | · | +25.87% | · | · | +11.07% | · | +5.80% | −37.76% |
| [spy_benchmark](spy_benchmark.md) | `fixed_etf_history` | — | reference | — | 10 | 90% | · | +15.50% | · | · | +16.74% | · | +1.40% | −32.52% |

## Latest validate window (2025-09-22 → 2026-09-22)

| Book | Train window | Train ret | Train CAGR | Validate window | Validate ret | CAGR | Vol | Sharpe | Max DD | vs EW | vs SPY | Fills | Universe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| template_top5 | 2023-09-22→2025-09-22 | −36.80% | −20.49% | 2025-09-22→2026-09-22 | **+47.65%** | +47.69% | +72.77% | +0.91 | −45.89% | +36.59% | · | 344 | 12,565 |
| template_top5_gated | 2023-09-22→2025-09-22 | −15.28% | −7.95% | 2025-09-22→2026-09-22 | **+26.84%** | +26.86% | +71.12% | +0.69 | −45.89% | +15.77% | · | 327 | 12,565 |
| sector_momentum | 2023-09-22→2025-09-22 | +41.78% | +19.06% | 2025-09-22→2026-09-22 | **+24.08%** | +24.10% | +13.52% | +1.67 | −7.91% | · | +7.34% | 40 | 12,565 |
| xs_momentum_12_1 | 2023-09-22→2025-09-22 | +111.73% | +45.47% | 2025-09-22→2026-09-22 | **+22.37%** | +22.39% | +51.88% | +0.65 | −30.89% | +11.30% | · | 739 | 12,565 |
| dual_momentum | 2023-09-22→2025-09-22 | +46.76% | +21.13% | 2025-09-22→2026-09-22 | **+18.09%** | +18.11% | +15.06% | +1.18 | −11.42% | · | +1.36% | 10 | 12,565 |
| spy_benchmark | 2023-09-22→2025-09-22 | +58.43% | +25.85% | 2025-09-22→2026-09-22 | **+16.74%** | +16.75% | +12.65% | +1.29 | −8.66% | · | +0.00% | 0 | 12,565 |
| high_52wk | 2023-09-22→2025-09-22 | +54.45% | +24.26% | 2025-09-22→2026-09-22 | **+14.23%** | +14.24% | +15.47% | +0.94 | −11.25% | +3.17% | · | 553 | 12,565 |
| dual_momentum_gated | 2023-09-22→2025-09-22 | +29.27% | +13.69% | 2025-09-22→2026-09-22 | **+13.74%** | +13.75% | +13.95% | +1.00 | −11.42% | · | −2.99% | 10 | 12,565 |
| ew_benchmark | 2023-09-22→2025-09-22 | +58.46% | +25.86% | 2025-09-22→2026-09-22 | **+11.07%** | +11.07% | +55.90% | +0.47 | −37.13% | +0.00% | · | 903 | 12,565 |
| ew_voltarget | 2023-09-22→2025-09-22 | +73.45% | +31.68% | 2025-09-22→2026-09-22 | **+9.72%** | +9.73% | +51.34% | +0.44 | −32.44% | −1.34% | · | 912 | 12,565 |
| mr_overlay_gated | 2023-09-22→2025-09-22 | +20.81% | +9.91% | 2025-09-22→2026-09-22 | **+5.34%** | +5.34% | +16.40% | +0.40 | −9.14% | −5.73% | · | 436 | 12,565 |
| template_top10_banded | 2023-09-22→2025-09-22 | +14.98% | +7.22% | 2025-09-22→2026-09-22 | **+5.12%** | +5.12% | +70.45% | +0.43 | −42.80% | −5.95% | · | 766 | 12,565 |
| low_vol | 2023-09-22→2025-09-22 | +37.07% | +17.07% | 2025-09-22→2026-09-22 | **+3.08%** | +3.08% | +9.08% | +0.38 | −6.50% | · | · | 199 | 12,565 |
| mr_overlay | 2023-09-22→2025-09-22 | +18.71% | +8.95% | 2025-09-22→2026-09-22 | **+2.69%** | +2.69% | +16.80% | +0.24 | −9.14% | −8.38% | · | 452 | 12,565 |
| template_top10_banded_gated | 2023-09-22→2025-09-22 | +12.21% | +5.93% | 2025-09-22→2026-09-22 | **−1.49%** | −1.49% | +69.40% | +0.33 | −42.80% | −12.55% | · | 739 | 12,565 |
| momo_stopped | 2023-09-22→2025-09-22 | +20.52% | +9.78% | 2025-09-22→2026-09-22 | **−2.39%** | −2.39% | +67.95% | +0.31 | −43.63% | −13.46% | · | 786 | 12,565 |
| ew_trend_gated | 2023-09-22→2025-09-22 | +48.40% | +21.80% | 2025-09-22→2026-09-22 | **−7.52%** | −7.52% | +54.99% | +0.13 | −37.12% | −18.59% | · | 848 | 12,565 |
| turtle_breakout | 2023-09-22→2025-09-22 | +21.58% | +10.25% | 2025-09-22→2026-09-22 | **−19.89%** | −19.91% | +30.19% | −0.58 | −33.22% | −30.96% | · | 166 | 12,565 |

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
