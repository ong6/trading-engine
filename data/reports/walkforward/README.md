# Walk-forward re-validation of league rules

_18 book(s) re-validated · protocol **train 24mo → validate 12mo, step 12mo, 10 folds, anchored 2026-09-25** · generated 2026-09-27 09:04 UTC._

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
| [ew_voltarget](ew_voltarget.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **INDISTINGUISHABLE** | 10 | 80% | 40% | +23.69% | −2.88% | [−8.09%, +1.48%] | +10.18% | −2.01% | +6.05% | −35.67% |
| [ew_trend_gated](ew_trend_gated.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **distinguishable −** | 10 | 60% | 40% | +22.44% | −4.12% | [−7.99%, −0.53%] | −6.58% | −18.78% | +4.33% | −37.12% |
| [dual_momentum_gated](dual_momentum_gated.md) | `fixed_etf_history` | spy_benchmark | REVIEW | **distinguishable −** | 10 | 70% | 30% | +9.13% | −6.51% | [−11.09%, −2.20%] | +14.24% | −3.67% | +1.88% | −17.47% |
| [turtle_breakout](turtle_breakout.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **distinguishable −** | 10 | 40% | 10% | +6.90% | −19.66% | [−30.92%, −8.88%] | −15.09% | −27.28% | +0.25% | −33.85% |
| [mr_overlay_gated](mr_overlay_gated.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **distinguishable −** | 10 | 50% | 20% | +2.94% | −23.63% | [−41.82%, −8.22%] | +4.52% | −7.67% | +1.62% | −13.64% |
| [mr_overlay](mr_overlay.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **distinguishable −** | 10 | 60% | 20% | +1.68% | −24.88% | [−42.12%, −10.91%] | +1.89% | −10.30% | +1.34% | −17.54% |
| [template_top10_banded_gated](template_top10_banded_gated.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 50% | 30% | +32.41% | +5.85% | [−13.36%, +29.43%] | +2.22% | −9.98% | +5.03% | −47.44% |
| [template_top10_banded](template_top10_banded.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 50% | 20% | +30.63% | +4.07% | [−13.46%, +27.33%] | +9.06% | −3.14% | +8.10% | −49.36% |
| [momo_stopped](momo_stopped.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 50% | 20% | +29.22% | +2.66% | [−13.12%, +21.18%] | +3.49% | −8.70% | +6.28% | −49.63% |
| [sector_momentum](sector_momentum.md) | `fixed_etf_history` | spy_benchmark | WATCH | **INDISTINGUISHABLE** | 9 | 100% | 33% | +14.14% | −1.37% | [−6.57%, +4.50%] | +26.38% | +8.47% | +2.24% | −31.86% |
| [high_52wk](high_52wk.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **distinguishable −** | 10 | 70% | 40% | +10.33% | −16.24% | [−36.04%, −0.26%] | +15.06% | +2.87% | +5.01% | −32.32% |
| [dual_momentum](dual_momentum.md) | `fixed_etf_history` | spy_benchmark | WATCH | **distinguishable −** | 10 | 60% | 40% | +9.66% | −5.98% | [−11.51%, −0.75%] | +18.61% | +0.70% | +3.15% | −33.69% |
| [template_top5_gated](template_top5_gated.md) | `current_universe_survivor_biased` | ew_benchmark | PASS | **INDISTINGUISHABLE** | 10 | 60% | 60% | +58.46% | +31.90% | [−9.87%, +85.61%] | +38.68% | +26.48% | +19.66% | −49.00% |
| [template_top5](template_top5.md) | `current_universe_survivor_biased` | ew_benchmark | PASS | **INDISTINGUISHABLE** | 10 | 60% | 50% | +57.73% | +31.17% | [−11.24%, +83.94%] | +61.44% | +49.25% | +27.49% | −61.59% |
| [xs_momentum_12_1](xs_momentum_12_1.md) | `current_universe_survivor_biased` | ew_benchmark | PASS | **INDISTINGUISHABLE** | 10 | 80% | 90% | +33.81% | +7.25% | [−5.12%, +17.09%] | +20.37% | +8.17% | +4.85% | −42.52% |
| [low_vol](low_vol.md) | `static_fundamental_lookahead` | ew_benchmark | no-benchmark | _no interval_ | 10 | 80% | · | +14.92% | · | · | +20.89% | · | +3.70% | −21.51% |
| [ew_benchmark](ew_benchmark.md) | `current_universe_survivor_biased` | — | reference | — | 10 | 70% | · | +26.56% | · | · | +12.19% | · | +6.90% | −37.86% |
| [spy_benchmark](spy_benchmark.md) | `fixed_etf_history` | — | reference | — | 10 | 90% | · | +15.64% | · | · | +17.91% | · | +1.42% | −32.53% |

## Latest validate window (2025-09-25 → 2026-09-25)

| Book | Train window | Train ret | Train CAGR | Validate window | Validate ret | CAGR | Vol | Sharpe | Max DD | vs EW | vs SPY | Fills | Universe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| template_top5 | 2023-09-25→2025-09-25 | −43.34% | −24.71% | 2025-09-25→2026-09-25 | **+61.44%** | +61.50% | +72.64% | +1.03 | −45.89% | +49.25% | · | 344 | 12,609 |
| template_top5_gated | 2023-09-25→2025-09-25 | −24.08% | −12.86% | 2025-09-25→2026-09-25 | **+38.68%** | +38.71% | +70.99% | +0.82 | −45.89% | +26.48% | · | 327 | 12,609 |
| sector_momentum | 2023-09-25→2025-09-25 | +39.61% | +18.14% | 2025-09-25→2026-09-25 | **+26.38%** | +26.40% | +13.48% | +1.81 | −7.91% | · | +8.47% | 40 | 12,609 |
| low_vol | 2023-09-25→2025-09-25 | +64.05% | +28.06% | 2025-09-25→2026-09-25 | **+20.89%** | +20.91% | +11.50% | +1.71 | −6.18% | · | · | 181 | 12,609 |
| xs_momentum_12_1 | 2023-09-25→2025-09-25 | +107.33% | +43.95% | 2025-09-25→2026-09-25 | **+20.37%** | +20.38% | +51.98% | +0.62 | −30.29% | +8.17% | · | 739 | 12,609 |
| dual_momentum | 2023-09-25→2025-09-25 | +44.83% | +20.33% | 2025-09-25→2026-09-25 | **+18.61%** | +18.62% | +15.16% | +1.21 | −11.42% | · | +0.70% | 10 | 12,609 |
| spy_benchmark | 2023-09-25→2025-09-25 | +56.17% | +24.95% | 2025-09-25→2026-09-25 | **+17.91%** | +17.92% | +12.62% | +1.37 | −8.64% | · | +0.00% | 0 | 12,609 |
| high_52wk | 2023-09-25→2025-09-25 | +55.36% | +24.62% | 2025-09-25→2026-09-25 | **+15.06%** | +15.07% | +15.41% | +0.99 | −11.25% | +2.87% | · | 553 | 12,609 |
| dual_momentum_gated | 2023-09-25→2025-09-25 | +27.57% | +12.94% | 2025-09-25→2026-09-25 | **+14.24%** | +14.25% | +14.06% | +1.02 | −11.42% | · | −3.67% | 10 | 12,609 |
| ew_benchmark | 2023-09-25→2025-09-25 | +54.17% | +24.15% | 2025-09-25→2026-09-25 | **+12.19%** | +12.20% | +55.90% | +0.49 | −37.13% | +0.00% | · | 903 | 12,609 |
| ew_voltarget | 2023-09-25→2025-09-25 | +68.23% | +29.68% | 2025-09-25→2026-09-25 | **+10.18%** | +10.19% | +51.36% | +0.45 | −32.44% | −2.01% | · | 912 | 12,609 |
| template_top10_banded | 2023-09-25→2025-09-25 | +7.98% | +3.91% | 2025-09-25→2026-09-25 | **+9.06%** | +9.07% | +70.53% | +0.48 | −42.80% | −3.14% | · | 766 | 12,609 |
| mr_overlay_gated | 2023-09-25→2025-09-25 | +19.21% | +9.18% | 2025-09-25→2026-09-25 | **+4.52%** | +4.52% | +16.43% | +0.35 | −9.14% | −7.67% | · | 435 | 12,609 |
| momo_stopped | 2023-09-25→2025-09-25 | +11.52% | +5.60% | 2025-09-25→2026-09-25 | **+3.49%** | +3.49% | +68.02% | +0.40 | −43.63% | −8.70% | · | 782 | 12,609 |
| template_top10_banded_gated | 2023-09-25→2025-09-25 | +5.47% | +2.70% | 2025-09-25→2026-09-25 | **+2.22%** | +2.22% | +69.47% | +0.39 | −42.80% | −9.98% | · | 739 | 12,609 |
| mr_overlay | 2023-09-25→2025-09-25 | +17.14% | +8.22% | 2025-09-25→2026-09-25 | **+1.89%** | +1.89% | +16.82% | +0.20 | −9.14% | −10.30% | · | 451 | 12,609 |
| ew_trend_gated | 2023-09-25→2025-09-25 | +44.06% | +20.01% | 2025-09-25→2026-09-25 | **−6.58%** | −6.59% | +54.99% | +0.15 | −37.12% | −18.78% | · | 848 | 12,609 |
| turtle_breakout | 2023-09-25→2025-09-25 | +16.80% | +8.07% | 2025-09-25→2026-09-25 | **−15.09%** | −15.10% | +30.09% | −0.39 | −33.85% | −27.28% | · | 165 | 12,609 |

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
