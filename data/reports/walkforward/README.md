# Walk-forward re-validation of league rules

_11 book(s) re-validated · protocol **train 24mo → validate 12mo, step 12mo, 10 folds, anchored 2026-10-23** · generated 2026-10-25 07:59 UTC._

**Not yet re-validated: 7 of 18 scheduled book(s).** Only results produced by the current code (fill model `v5`, runtime contract revision 2, source `e0310995858c`) are shown; older results are stale and are not evidence until the book is re-run. Missing: `ew_trend_gated`, `low_vol`, `mr_overlay`, `mr_overlay_gated`, `template_top10_banded`, `template_top10_banded_gated`, `turtle_breakout`.

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
7. **An undefined statistic is `null` in the result file and `·` here.** A
   window with fewer than two returns or zero return volatility (a book that sat
   in cash) has no Sharpe, and one with fewer than two month-ends has no worst
   month. Result files are strict JSON: never NaN, infinity or a stand-in zero.


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

**6 of 9 judged book(s) are `INDISTINGUISHABLE` from their declared control** at 90% confidence on mean excess. Read every verdict in the next column with that column beside it.

| Book | Evidence class | Control | Verdict | Distinguishable? | Folds | Validate win rate | Beats control | Mean validate | Mean excess | 90% CI on mean excess | Latest validate | Latest excess | Mean decay (CAGR) | Worst validate DD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [dual_momentum](dual_momentum.md) | `fixed_etf_history` | spy_benchmark | REVIEW | **distinguishable −** | 10 | 60% | 40% | +9.48% | −6.12% | [−11.45%, −1.11%] | +12.91% | −1.05% | +2.89% | −33.69% |
| [dual_momentum_gated](dual_momentum_gated.md) | `fixed_etf_history` | spy_benchmark | REVIEW | **distinguishable −** | 10 | 70% | 30% | +9.01% | −6.58% | [−10.83%, −2.60%] | +8.75% | −5.21% | +1.60% | −17.47% |
| [momo_stopped](momo_stopped.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 40% | 30% | +29.21% | +4.93% | [−13.01%, +25.75%] | −8.75% | −1.39% | +5.29% | −49.68% |
| [ew_voltarget](ew_voltarget.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 60% | 60% | +21.30% | −2.98% | [−8.41%, +1.54%] | −6.87% | +0.48% | +3.07% | −36.63% |
| [sector_momentum](sector_momentum.md) | `fixed_etf_history` | spy_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 100% | 30% | +14.10% | −1.49% | [−6.25%, +3.93%] | +29.27% | +15.30% | +2.80% | −31.86% |
| [high_52wk](high_52wk.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 70% | 30% | +10.17% | −14.11% | [−31.39%, +0.01%] | +9.23% | +16.59% | +4.58% | −31.29% |
| [template_top5](template_top5.md) | `current_universe_survivor_biased` | ew_benchmark | PASS | **INDISTINGUISHABLE** | 10 | 60% | 50% | +55.11% | +30.83% | [−9.23%, +79.24%] | +38.58% | +45.93% | +21.59% | −61.11% |
| [template_top5_gated](template_top5_gated.md) | `current_universe_survivor_biased` | ew_benchmark | PASS | **INDISTINGUISHABLE** | 10 | 60% | 50% | +52.70% | +28.42% | [−6.88%, +70.49%] | +19.02% | +26.38% | +10.98% | −47.35% |
| [xs_momentum_12_1](xs_momentum_12_1.md) | `current_universe_survivor_biased` | ew_benchmark | PASS | **distinguishable +** | 10 | 90% | 90% | +35.44% | +11.17% | [+0.98%, +19.57%] | +7.57% | +14.93% | +4.21% | −42.01% |
| [ew_benchmark](ew_benchmark.md) | `current_universe_survivor_biased` | — | reference | — | 10 | 60% | · | +24.28% | · | · | −7.36% | · | +3.65% | −38.78% |
| [spy_benchmark](spy_benchmark.md) | `fixed_etf_history` | — | reference | — | 10 | 90% | · | +15.60% | · | · | +13.96% | · | +1.71% | −32.53% |

## Latest validate window (2025-10-23 → 2026-10-23)

| Book | Train window | Train ret | Train CAGR | Validate window | Validate ret | CAGR | Vol | Sharpe | Max DD | vs EW | vs SPY | Fills | Universe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| template_top5 | 2023-10-23→2025-10-23 | −26.37% | −14.18% | 2025-10-23→2026-10-23 | **+38.58%** | +38.61% | +71.50% | +0.82 | −45.89% | +45.93% | · | 343 | 12,717 |
| sector_momentum | 2023-10-23→2025-10-23 | +44.40% | +20.15% | 2025-10-23→2026-10-23 | **+29.27%** | +29.29% | +12.92% | +2.06 | −7.91% | · | +15.30% | 40 | 12,717 |
| template_top5_gated | 2023-10-23→2025-10-23 | −6.73% | −3.42% | 2025-10-23→2026-10-23 | **+19.02%** | +19.03% | +69.81% | +0.60 | −45.89% | +26.38% | · | 325 | 12,717 |
| spy_benchmark | 2023-10-23→2025-10-23 | +62.15% | +27.32% | 2025-10-23→2026-10-23 | **+13.96%** | +13.97% | +12.43% | +1.12 | −8.67% | · | +0.00% | 0 | 12,717 |
| dual_momentum | 2023-10-23→2025-10-23 | +50.89% | +22.82% | 2025-10-23→2026-10-23 | **+12.91%** | +12.92% | +14.99% | +0.89 | −11.42% | · | −1.05% | 11 | 12,717 |
| high_52wk | 2023-10-23→2025-10-23 | +57.74% | +25.57% | 2025-10-23→2026-10-23 | **+9.23%** | +9.24% | +15.40% | +0.65 | −11.45% | +16.59% | · | 541 | 12,717 |
| dual_momentum_gated | 2023-10-23→2025-10-23 | +33.18% | +15.39% | 2025-10-23→2026-10-23 | **+8.75%** | +8.76% | +13.87% | +0.68 | −11.42% | · | −5.21% | 11 | 12,717 |
| xs_momentum_12_1 | 2023-10-23→2025-10-23 | +150.95% | +58.36% | 2025-10-23→2026-10-23 | **+7.57%** | +7.58% | +50.43% | +0.40 | −27.97% | +14.93% | · | 732 | 12,717 |
| ew_voltarget | 2023-10-23→2025-10-23 | +88.86% | +37.40% | 2025-10-23→2026-10-23 | **−6.87%** | −6.88% | +50.27% | +0.11 | −34.42% | +0.48% | · | 914 | 12,717 |
| ew_benchmark | 2023-10-23→2025-10-23 | +76.92% | +32.99% | 2025-10-23→2026-10-23 | **−7.36%** | −7.36% | +55.08% | +0.14 | −37.30% | +0.00% | · | 898 | 12,717 |
| momo_stopped | 2023-10-23→2025-10-23 | +32.37% | +15.04% | 2025-10-23→2026-10-23 | **−8.75%** | −8.76% | +66.22% | +0.20 | −43.64% | −1.39% | · | 789 | 12,717 |

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
