# Walk-forward re-validation of league rules

_18 book(s) re-validated · protocol **train 24mo → validate 12mo, step 12mo, 10 folds, anchored 2026-10-09** · generated 2026-10-11 08:46 UTC._

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
| [ew_voltarget](ew_voltarget.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **INDISTINGUISHABLE** | 10 | 80% | 40% | +22.69% | −3.02% | [−8.05%, +1.34%] | +0.26% | −1.60% | +3.42% | −36.63% |
| [ew_trend_gated](ew_trend_gated.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **distinguishable −** | 10 | 60% | 20% | +21.78% | −3.93% | [−7.00%, −1.21%] | −15.19% | −17.05% | +1.42% | −37.13% |
| [dual_momentum](dual_momentum.md) | `fixed_etf_history` | spy_benchmark | REVIEW | **distinguishable −** | 10 | 60% | 40% | +9.49% | −6.27% | [−12.34%, −0.67%] | +15.78% | −1.00% | +2.86% | −33.69% |
| [dual_momentum_gated](dual_momentum_gated.md) | `fixed_etf_history` | spy_benchmark | REVIEW | **distinguishable −** | 10 | 70% | 30% | +9.07% | −6.68% | [−11.66%, −2.12%] | +11.51% | −5.26% | +1.65% | −17.47% |
| [turtle_breakout](turtle_breakout.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **distinguishable −** | 10 | 50% | 20% | +6.47% | −19.23% | [−32.11%, −6.88%] | −17.74% | −19.60% | +0.30% | −32.64% |
| [template_top10_banded_gated](template_top10_banded_gated.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 60% | 30% | +33.24% | +7.54% | [−13.12%, +33.34%] | −9.15% | −11.01% | +3.18% | −45.77% |
| [template_top10_banded](template_top10_banded.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 60% | 30% | +31.08% | +5.38% | [−13.61%, +30.96%] | −3.05% | −4.91% | +6.66% | −49.50% |
| [momo_stopped](momo_stopped.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 60% | 30% | +30.11% | +4.40% | [−13.14%, +25.37%] | −7.34% | −9.20% | +5.15% | −49.77% |
| [sector_momentum](sector_momentum.md) | `fixed_etf_history` | spy_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 100% | 30% | +13.85% | −1.90% | [−6.86%, +3.71%] | +28.13% | +11.35% | +1.76% | −31.86% |
| [high_52wk](high_52wk.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **distinguishable −** | 10 | 80% | 30% | +10.49% | −15.22% | [−29.94%, −2.31%] | +10.09% | +8.23% | +4.53% | −32.40% |
| [mr_overlay_gated](mr_overlay_gated.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **distinguishable −** | 10 | 60% | 30% | +3.64% | −22.06% | [−37.69%, −7.74%] | +7.70% | +5.84% | +1.91% | −13.64% |
| [mr_overlay](mr_overlay.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **distinguishable −** | 10 | 60% | 20% | +2.44% | −23.27% | [−37.51%, −10.43%] | +4.99% | +3.13% | +1.71% | −18.42% |
| [template_top5](template_top5.md) | `current_universe_survivor_biased` | ew_benchmark | PASS | **INDISTINGUISHABLE** | 10 | 60% | 50% | +59.77% | +34.07% | [−9.63%, +86.92%] | +55.77% | +53.91% | +26.53% | −61.59% |
| [template_top5_gated](template_top5_gated.md) | `current_universe_survivor_biased` | ew_benchmark | PASS | **INDISTINGUISHABLE** | 10 | 60% | 60% | +51.58% | +25.88% | [−7.64%, +64.94%] | +33.81% | +31.95% | +9.33% | −48.00% |
| [xs_momentum_12_1](xs_momentum_12_1.md) | `current_universe_survivor_biased` | ew_benchmark | PASS | **INDISTINGUISHABLE** | 10 | 90% | 90% | +33.69% | +7.99% | [−1.36%, +15.37%] | +6.29% | +4.43% | +3.35% | −42.49% |
| [low_vol](low_vol.md) | `static_fundamental_lookahead` | ew_benchmark | no-benchmark | _no interval_ | 10 | 90% | · | +10.17% | · | · | +1.64% | · | +0.15% | −34.15% |
| [ew_benchmark](ew_benchmark.md) | `current_universe_survivor_biased` | — | reference | — | 10 | 70% | · | +25.70% | · | · | +1.86% | · | +3.98% | −38.78% |
| [spy_benchmark](spy_benchmark.md) | `fixed_etf_history` | — | reference | — | 10 | 90% | · | +15.75% | · | · | +16.78% | · | +1.49% | −32.53% |

## Latest validate window (2025-10-09 → 2026-10-09)

| Book | Train window | Train ret | Train CAGR | Validate window | Validate ret | CAGR | Vol | Sharpe | Max DD | vs EW | vs SPY | Fills | Universe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| template_top5 | 2023-10-09→2025-10-09 | −29.27% | −15.89% | 2025-10-09→2026-10-09 | **+55.77%** | +55.82% | +72.84% | +0.98 | −45.89% | +53.91% | · | 342 | 12,674 |
| template_top5_gated | 2023-10-09→2025-10-09 | −5.19% | −2.63% | 2025-10-09→2026-10-09 | **+33.81%** | +33.83% | +71.19% | +0.77 | −45.89% | +31.95% | · | 325 | 12,674 |
| sector_momentum | 2023-10-09→2025-10-09 | +43.82% | +19.91% | 2025-10-09→2026-10-09 | **+28.13%** | +28.15% | +13.43% | +1.92 | −7.91% | · | +11.35% | 40 | 12,674 |
| spy_benchmark | 2023-10-09→2025-10-09 | +58.16% | +25.74% | 2025-10-09→2026-10-09 | **+16.78%** | +16.79% | +12.72% | +1.29 | −8.67% | · | +0.00% | 0 | 12,674 |
| dual_momentum | 2023-10-09→2025-10-09 | +50.76% | +22.77% | 2025-10-09→2026-10-09 | **+15.78%** | +15.79% | +15.23% | +1.04 | −11.42% | · | −1.00% | 11 | 12,674 |
| dual_momentum_gated | 2023-10-09→2025-10-09 | +33.06% | +15.34% | 2025-10-09→2026-10-09 | **+11.51%** | +11.52% | +14.13% | +0.84 | −11.42% | · | −5.26% | 11 | 12,674 |
| high_52wk | 2023-10-09→2025-10-09 | +58.03% | +25.69% | 2025-10-09→2026-10-09 | **+10.09%** | +10.10% | +15.62% | +0.70 | −11.50% | +8.23% | · | 544 | 12,674 |
| mr_overlay_gated | 2023-10-09→2025-10-09 | +19.84% | +9.46% | 2025-10-09→2026-10-09 | **+7.70%** | +7.71% | +16.73% | +0.53 | −9.06% | +5.84% | · | 434 | 12,674 |
| xs_momentum_12_1 | 2023-10-09→2025-10-09 | +155.62% | +59.83% | 2025-10-09→2026-10-09 | **+6.29%** | +6.29% | +52.65% | +0.38 | −31.47% | +4.43% | · | 743 | 12,674 |
| mr_overlay | 2023-10-09→2025-10-09 | +17.75% | +8.51% | 2025-10-09→2026-10-09 | **+4.99%** | +5.00% | +17.12% | +0.37 | −9.06% | +3.13% | · | 450 | 12,674 |
| ew_benchmark | 2023-10-09→2025-10-09 | +87.98% | +37.08% | 2025-10-09→2026-10-09 | **+1.86%** | +1.86% | +55.90% | +0.31 | −37.13% | +0.00% | · | 902 | 12,674 |
| low_vol | 2023-10-09→2025-10-09 | +37.19% | +17.12% | 2025-10-09→2026-10-09 | **+1.64%** | +1.64% | +9.15% | +0.22 | −8.81% | · | · | 196 | 12,674 |
| ew_voltarget | 2023-10-09→2025-10-09 | +100.93% | +41.72% | 2025-10-09→2026-10-09 | **+0.26%** | +0.26% | +51.26% | +0.26 | −32.44% | −1.60% | · | 917 | 12,674 |
| template_top10_banded | 2023-10-09→2025-10-09 | +32.92% | +15.28% | 2025-10-09→2026-10-09 | **−3.05%** | −3.05% | +70.60% | +0.32 | −42.80% | −4.91% | · | 766 | 12,674 |
| momo_stopped | 2023-10-09→2025-10-09 | +33.28% | +15.44% | 2025-10-09→2026-10-09 | **−7.34%** | −7.34% | +67.94% | +0.24 | −43.63% | −9.20% | · | 781 | 12,674 |
| template_top10_banded_gated | 2023-10-09→2025-10-09 | +29.82% | +13.93% | 2025-10-09→2026-10-09 | **−9.15%** | −9.15% | +69.54% | +0.22 | −42.80% | −11.01% | · | 737 | 12,674 |
| ew_trend_gated | 2023-10-09→2025-10-09 | +75.70% | +32.53% | 2025-10-09→2026-10-09 | **−15.19%** | −15.20% | +54.99% | −0.03 | −37.13% | −17.05% | · | 847 | 12,674 |
| turtle_breakout | 2023-10-09→2025-10-09 | +13.60% | +6.58% | 2025-10-09→2026-10-09 | **−17.74%** | −17.75% | +30.20% | −0.50 | −32.64% | −19.60% | · | 163 | 12,674 |

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
