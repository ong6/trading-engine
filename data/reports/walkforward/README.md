# Walk-forward re-validation of league rules

_9 book(s) re-validated · protocol **train 24mo → validate 12mo, step 12mo, 10 folds, anchored 2026-11-06** · generated 2026-11-08 07:54 UTC._

**Not yet re-validated: 9 of 18 scheduled book(s).** Only results produced by the current code (fill model `v5`, runtime contract revision 2, source `75fea67fdebd`) are shown; older results are stale and are not evidence until the book is re-run. Missing: `dual_momentum_gated`, `ew_trend_gated`, `low_vol`, `mr_overlay`, `mr_overlay_gated`, `template_top10_banded`, `template_top10_banded_gated`, `template_top5_gated`, `turtle_breakout`.

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

**6 of 7 judged book(s) are `INDISTINGUISHABLE` from their declared control** at 90% confidence on mean excess. Read every verdict in the next column with that column beside it.

| Book | Evidence class | Control | Verdict | Distinguishable? | Folds | Validate win rate | Beats control | Mean validate | Mean excess | 90% CI on mean excess | Latest validate | Latest excess | Mean decay (CAGR) | Worst validate DD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [ew_voltarget](ew_voltarget.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **INDISTINGUISHABLE** | 10 | 60% | 40% | +22.04% | −3.34% | [−9.08%, +1.41%] | −7.11% | −1.72% | +5.47% | −37.89% |
| [dual_momentum](dual_momentum.md) | `fixed_etf_history` | spy_benchmark | REVIEW | **distinguishable −** | 10 | 60% | 40% | +9.58% | −6.05% | [−11.32%, −1.16%] | +9.32% | −1.28% | +3.95% | −33.69% |
| [momo_stopped](momo_stopped.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 50% | 40% | +33.91% | +8.53% | [−11.82%, +32.44%] | −4.22% | +1.17% | +7.61% | −49.68% |
| [sector_momentum](sector_momentum.md) | `fixed_etf_history` | spy_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 100% | 40% | +14.03% | −1.59% | [−7.17%, +4.83%] | +26.70% | +16.10% | +6.89% | −31.86% |
| [high_52wk](high_52wk.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 70% | 40% | +10.80% | −14.58% | [−33.75%, +0.74%] | +9.47% | +14.86% | +5.53% | −31.15% |
| [template_top5](template_top5.md) | `current_universe_survivor_biased` | ew_benchmark | PASS | **INDISTINGUISHABLE** | 10 | 60% | 50% | +58.53% | +33.15% | [−6.44%, +81.60%] | +18.51% | +23.90% | +20.92% | −61.11% |
| [xs_momentum_12_1](xs_momentum_12_1.md) | `current_universe_survivor_biased` | ew_benchmark | PASS | **INDISTINGUISHABLE** | 10 | 90% | 90% | +35.37% | +9.99% | [−2.18%, +19.90%] | +16.51% | +21.89% | +7.57% | −41.29% |
| [ew_benchmark](ew_benchmark.md) | `current_universe_survivor_biased` | — | reference | — | 10 | 60% | · | +25.38% | · | · | −5.39% | · | +6.90% | −40.14% |
| [spy_benchmark](spy_benchmark.md) | `fixed_etf_history` | — | reference | — | 10 | 90% | · | +15.63% | · | · | +10.60% | · | +2.25% | −32.53% |

## Latest validate window (2025-11-06 → 2026-11-06)

| Book | Train window | Train ret | Train CAGR | Validate window | Validate ret | CAGR | Vol | Sharpe | Max DD | vs EW | vs SPY | Fills | Universe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sector_momentum | 2023-11-06→2025-11-06 | +33.77% | +15.65% | 2025-11-06→2026-11-06 | **+26.70%** | +26.72% | +12.75% | +1.93 | −6.16% | · | +16.10% | 41 | 12,755 |
| template_top5 | 2023-11-06→2025-11-06 | −1.31% | −0.65% | 2025-11-06→2026-11-06 | **+18.51%** | +18.53% | +71.18% | +0.60 | −45.89% | +23.90% | · | 345 | 12,755 |
| xs_momentum_12_1 | 2023-11-06→2025-11-06 | +93.72% | +39.15% | 2025-11-06→2026-11-06 | **+16.51%** | +16.52% | +51.43% | +0.56 | −34.77% | +21.89% | · | 725 | 12,755 |
| spy_benchmark | 2023-11-06→2025-11-06 | +56.97% | +25.27% | 2025-11-06→2026-11-06 | **+10.60%** | +10.61% | +13.21% | +0.83 | −8.67% | · | +0.00% | 0 | 12,755 |
| high_52wk | 2023-11-06→2025-11-06 | +53.20% | +23.75% | 2025-11-06→2026-11-06 | **+9.47%** | +9.48% | +15.49% | +0.66 | −11.45% | +14.86% | · | 533 | 12,755 |
| dual_momentum | 2023-11-06→2025-11-06 | +41.82% | +19.07% | 2025-11-06→2026-11-06 | **+9.32%** | +9.33% | +15.49% | +0.65 | −11.42% | · | −1.28% | 11 | 12,755 |
| momo_stopped | 2023-11-06→2025-11-06 | +25.93% | +12.21% | 2025-11-06→2026-11-06 | **−4.22%** | −4.22% | +65.67% | +0.27 | −44.38% | +1.17% | · | 784 | 12,755 |
| ew_benchmark | 2023-11-06→2025-11-06 | +58.48% | +25.87% | 2025-11-06→2026-11-06 | **−5.39%** | −5.39% | +55.17% | +0.18 | −40.14% | +0.00% | · | 911 | 12,755 |
| ew_voltarget | 2023-11-06→2025-11-06 | +71.24% | +30.83% | 2025-11-06→2026-11-06 | **−7.11%** | −7.11% | +50.38% | +0.11 | −37.89% | −1.72% | · | 925 | 12,755 |

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
