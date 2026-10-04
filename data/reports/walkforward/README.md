# Walk-forward re-validation of league rules

_18 book(s) re-validated · protocol **train 24mo → validate 12mo, step 12mo, 10 folds, anchored 2026-10-02** · generated 2026-10-04 08:02 UTC._

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
| [ew_voltarget](ew_voltarget.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **INDISTINGUISHABLE** | 10 | 80% | 40% | +23.42% | −3.01% | [−8.16%, +1.39%] | +7.23% | −2.61% | +4.75% | −35.67% |
| [ew_trend_gated](ew_trend_gated.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **distinguishable −** | 10 | 60% | 30% | +22.32% | −4.11% | [−7.58%, −0.98%] | −8.54% | −18.39% | +2.66% | −37.13% |
| [high_52wk](high_52wk.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **distinguishable −** | 10 | 70% | 20% | +10.23% | −16.20% | [−33.27%, −1.80%] | +7.05% | −2.79% | +4.60% | −32.39% |
| [dual_momentum](dual_momentum.md) | `fixed_etf_history` | spy_benchmark | REVIEW | **distinguishable −** | 10 | 60% | 40% | +9.42% | −6.24% | [−12.49%, −0.39%] | +14.78% | −0.98% | +3.10% | −33.69% |
| [dual_momentum_gated](dual_momentum_gated.md) | `fixed_etf_history` | spy_benchmark | REVIEW | **distinguishable −** | 10 | 70% | 30% | +8.95% | −6.71% | [−11.93%, −1.90%] | +10.55% | −5.21% | +1.85% | −17.47% |
| [turtle_breakout](turtle_breakout.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **distinguishable −** | 10 | 50% | 20% | +6.35% | −20.07% | [−32.44%, −8.15%] | −14.70% | −24.54% | +0.17% | −32.64% |
| [mr_overlay_gated](mr_overlay_gated.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **distinguishable −** | 10 | 60% | 20% | +3.29% | −23.13% | [−39.69%, −8.34%] | +5.53% | −4.31% | +1.62% | −13.64% |
| [mr_overlay](mr_overlay.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **distinguishable −** | 10 | 60% | 20% | +2.01% | −24.42% | [−39.73%, −11.23%] | +2.88% | −6.97% | +1.26% | −18.07% |
| [template_top10_banded_gated](template_top10_banded_gated.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 50% | 30% | +31.31% | +4.89% | [−13.60%, +27.11%] | −1.32% | −11.16% | +4.29% | −45.61% |
| [template_top10_banded](template_top10_banded.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 60% | 20% | +29.31% | +2.89% | [−13.81%, +24.13%] | +5.30% | −4.55% | +7.13% | −49.36% |
| [momo_stopped](momo_stopped.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 50% | 20% | +28.42% | +2.00% | [−13.57%, +20.15%] | +1.83% | −8.01% | +5.88% | −49.63% |
| [sector_momentum](sector_momentum.md) | `fixed_etf_history` | spy_benchmark | WATCH | **INDISTINGUISHABLE** | 9 | 89% | 33% | +13.87% | −1.51% | [−6.47%, +4.08%] | +25.01% | +9.25% | +2.29% | −31.86% |
| [template_top5](template_top5.md) | `current_universe_survivor_biased` | ew_benchmark | PASS | **INDISTINGUISHABLE** | 10 | 60% | 50% | +56.05% | +29.63% | [−9.53%, +75.02%] | +67.38% | +57.53% | +25.90% | −61.59% |
| [template_top5_gated](template_top5_gated.md) | `current_universe_survivor_biased` | ew_benchmark | PASS | **INDISTINGUISHABLE** | 10 | 60% | 60% | +52.39% | +25.97% | [−7.92%, +65.40%] | +43.78% | +33.93% | +13.93% | −48.00% |
| [xs_momentum_12_1](xs_momentum_12_1.md) | `current_universe_survivor_biased` | ew_benchmark | PASS | **INDISTINGUISHABLE** | 10 | 80% | 90% | +33.72% | +7.29% | [−2.57%, +14.90%] | +17.61% | +7.77% | +4.32% | −42.66% |
| [low_vol](low_vol.md) | `static_fundamental_lookahead` | ew_benchmark | no-benchmark | _no interval_ | 10 | 90% | · | +9.78% | · | · | +0.31% | · | −0.16% | −34.12% |
| [ew_benchmark](ew_benchmark.md) | `current_universe_survivor_biased` | — | reference | — | 10 | 70% | · | +26.42% | · | · | +9.84% | · | +5.49% | −37.86% |
| [spy_benchmark](spy_benchmark.md) | `fixed_etf_history` | — | reference | — | 10 | 90% | · | +15.66% | · | · | +15.76% | · | +1.67% | −32.53% |

## Latest validate window (2025-10-02 → 2026-10-02)

| Book | Train window | Train ret | Train CAGR | Validate window | Validate ret | CAGR | Vol | Sharpe | Max DD | vs EW | vs SPY | Fills | Universe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| template_top5 | 2023-10-02→2025-10-02 | −36.21% | −20.12% | 2025-10-02→2026-10-02 | **+67.38%** | +67.44% | +72.97% | +1.08 | −45.89% | +57.53% | · | 342 | 12,643 |
| template_top5_gated | 2023-10-02→2025-10-02 | −14.49% | −7.52% | 2025-10-02→2026-10-02 | **+43.78%** | +43.81% | +71.34% | +0.87 | −45.89% | +33.93% | · | 325 | 12,643 |
| sector_momentum | 2023-10-02→2025-10-02 | +44.60% | +20.23% | 2025-10-02→2026-10-02 | **+25.01%** | +25.03% | +13.48% | +1.73 | −7.91% | · | +9.25% | 40 | 12,643 |
| xs_momentum_12_1 | 2023-10-02→2025-10-02 | +137.56% | +54.08% | 2025-10-02→2026-10-02 | **+17.61%** | +17.62% | +52.57% | +0.57 | −31.42% | +7.77% | · | 743 | 12,643 |
| spy_benchmark | 2023-10-02→2025-10-02 | +60.38% | +26.62% | 2025-10-02→2026-10-02 | **+15.76%** | +15.77% | +12.67% | +1.22 | −8.65% | · | +0.00% | 0 | 12,643 |
| dual_momentum | 2023-10-02→2025-10-02 | +50.32% | +22.59% | 2025-10-02→2026-10-02 | **+14.78%** | +14.79% | +15.21% | +0.99 | −11.42% | · | −0.98% | 11 | 12,643 |
| dual_momentum_gated | 2023-10-02→2025-10-02 | +32.67% | +15.17% | 2025-10-02→2026-10-02 | **+10.55%** | +10.56% | +14.11% | +0.78 | −11.42% | · | −5.21% | 11 | 12,643 |
| ew_benchmark | 2023-10-02→2025-10-02 | +75.19% | +32.33% | 2025-10-02→2026-10-02 | **+9.84%** | +9.85% | +55.88% | +0.45 | −37.13% | +0.00% | · | 901 | 12,643 |
| ew_voltarget | 2023-10-02→2025-10-02 | +89.61% | +37.67% | 2025-10-02→2026-10-02 | **+7.23%** | +7.23% | +51.30% | +0.39 | −32.44% | −2.61% | · | 917 | 12,643 |
| high_52wk | 2023-10-02→2025-10-02 | +62.12% | +27.31% | 2025-10-02→2026-10-02 | **+7.05%** | +7.06% | +16.01% | +0.51 | −11.50% | −2.79% | · | 546 | 12,643 |
| mr_overlay_gated | 2023-10-02→2025-10-02 | +21.29% | +10.13% | 2025-10-02→2026-10-02 | **+5.53%** | +5.54% | +16.67% | +0.41 | −9.06% | −4.31% | · | 432 | 12,643 |
| template_top10_banded | 2023-10-02→2025-10-02 | +21.14% | +10.05% | 2025-10-02→2026-10-02 | **+5.30%** | +5.30% | +70.70% | +0.44 | −42.80% | −4.55% | · | 761 | 12,643 |
| mr_overlay | 2023-10-02→2025-10-02 | +19.19% | +9.17% | 2025-10-02→2026-10-02 | **+2.88%** | +2.88% | +17.06% | +0.25 | −9.06% | −6.97% | · | 448 | 12,643 |
| momo_stopped | 2023-10-02→2025-10-02 | +21.56% | +10.25% | 2025-10-02→2026-10-02 | **+1.83%** | +1.83% | +68.05% | +0.38 | −43.63% | −8.01% | · | 770 | 12,643 |
| low_vol | 2023-10-02→2025-10-02 | +35.62% | +16.44% | 2025-10-02→2026-10-02 | **+0.31%** | +0.31% | +9.09% | +0.08 | −8.83% | · | · | 197 | 12,643 |
| template_top10_banded_gated | 2023-10-02→2025-10-02 | +18.33% | +8.77% | 2025-10-02→2026-10-02 | **−1.32%** | −1.32% | +69.65% | +0.34 | −42.80% | −11.16% | · | 734 | 12,643 |
| ew_trend_gated | 2023-10-02→2025-10-02 | +63.75% | +27.94% | 2025-10-02→2026-10-02 | **−8.54%** | −8.55% | +54.98% | +0.11 | −37.13% | −18.39% | · | 846 | 12,643 |
| turtle_breakout | 2023-10-02→2025-10-02 | +23.78% | +11.25% | 2025-10-02→2026-10-02 | **−14.70%** | −14.70% | +30.18% | −0.38 | −32.64% | −24.54% | · | 165 | 12,643 |

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
