# Walk-forward re-validation of league rules

_18 book(s) re-validated · protocol **train 24mo → validate 12mo, step 12mo, 10 folds, anchored 2026-09-04** · generated 2026-09-09 02:21 UTC._

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
| [ew_voltarget](ew_voltarget.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **INDISTINGUISHABLE** | 10 | 80% | 40% | +23.62% | −2.84% | [−8.88%, +1.90%] | +29.37% | −1.05% | +5.87% | −35.37% |
| [ew_trend_gated](ew_trend_gated.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **distinguishable −** | 10 | 70% | 20% | +22.11% | −4.34% | [−8.09%, −1.51%] | +8.36% | −22.06% | +4.52% | −36.63% |
| [high_52wk](high_52wk.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **distinguishable −** | 10 | 70% | 30% | +10.03% | −16.42% | [−37.73%, −0.93%] | +19.60% | −10.82% | +4.26% | −32.10% |
| [dual_momentum_gated](dual_momentum_gated.md) | `fixed_etf_history` | spy_benchmark | REVIEW | **distinguishable −** | 10 | 70% | 20% | +9.28% | −5.96% | [−9.69%, −2.40%] | +19.20% | −0.18% | +2.05% | −17.47% |
| [turtle_breakout](turtle_breakout.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **distinguishable −** | 10 | 40% | 20% | +4.29% | −22.16% | [−36.27%, −10.35%] | −8.35% | −38.77% | −0.17% | −31.00% |
| [mr_overlay_gated](mr_overlay_gated.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **distinguishable −** | 10 | 50% | 20% | +3.51% | −22.94% | [−43.84%, −6.92%] | +8.77% | −21.65% | +1.99% | −15.47% |
| [mr_overlay](mr_overlay.md) | `current_universe_survivor_biased` | ew_benchmark | REVIEW | **distinguishable −** | 10 | 50% | 10% | +2.42% | −24.04% | [−44.84%, −8.48%] | +6.03% | −24.38% | +1.44% | −17.95% |
| [template_top10_banded_gated](template_top10_banded_gated.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 40% | 40% | +33.94% | +7.49% | [−13.20%, +39.59%] | +11.30% | −19.11% | +9.03% | −46.46% |
| [template_top10_banded](template_top10_banded.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 40% | 30% | +33.72% | +7.27% | [−12.84%, +39.78%] | +18.81% | −11.61% | +11.73% | −48.60% |
| [momo_stopped](momo_stopped.md) | `current_universe_survivor_biased` | ew_benchmark | WATCH | **INDISTINGUISHABLE** | 10 | 40% | 40% | +30.72% | +4.27% | [−11.82%, +26.12%] | +10.77% | −19.65% | +7.99% | −47.94% |
| [sector_momentum](sector_momentum.md) | `fixed_etf_history` | spy_benchmark | WATCH | **INDISTINGUISHABLE** | 9 | 100% | 33% | +14.09% | −1.17% | [−6.50%, +4.86%] | +29.39% | +10.01% | +1.52% | −31.86% |
| [dual_momentum](dual_momentum.md) | `fixed_etf_history` | spy_benchmark | WATCH | **distinguishable −** | 10 | 60% | 50% | +9.67% | −5.57% | [−10.49%, −0.91%] | +23.76% | +4.38% | +3.21% | −33.69% |
| [template_top5](template_top5.md) | `current_universe_survivor_biased` | ew_benchmark | PASS | **INDISTINGUISHABLE** | 10 | 50% | 50% | +60.80% | +34.35% | [−14.80%, +105.18%] | +69.50% | +39.09% | +28.66% | −65.46% |
| [template_top5_gated](template_top5_gated.md) | `current_universe_survivor_biased` | ew_benchmark | PASS | **INDISTINGUISHABLE** | 10 | 50% | 50% | +59.21% | +32.76% | [−14.13%, +104.92%] | +45.56% | +15.14% | +22.08% | −51.43% |
| [xs_momentum_12_1](xs_momentum_12_1.md) | `current_universe_survivor_biased` | ew_benchmark | PASS | **INDISTINGUISHABLE** | 10 | 80% | 80% | +32.87% | +6.42% | [−5.22%, +15.78%] | +44.92% | +14.50% | +4.66% | −43.94% |
| [low_vol](low_vol.md) | `static_fundamental_lookahead` | ew_benchmark | no-benchmark | _no interval_ | 10 | 100% | · | +10.18% | · | · | +4.66% | · | −1.61% | −35.78% |
| [ew_benchmark](ew_benchmark.md) | `current_universe_survivor_biased` | — | reference | — | 10 | 80% | · | +26.45% | · | · | +30.42% | · | +6.67% | −37.49% |
| [spy_benchmark](spy_benchmark.md) | `fixed_etf_history` | — | reference | — | 10 | 90% | · | +15.24% | · | · | +19.38% | · | +1.53% | −32.41% |

## Latest validate window (2025-09-04 → 2026-09-04)

| Book | Train window | Train ret | Train CAGR | Validate window | Validate ret | CAGR | Vol | Sharpe | Max DD | vs EW | vs SPY | Fills | Universe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| template_top5 | 2023-09-05→2025-09-04 | −64.23% | −40.22% | 2025-09-04→2026-09-04 | **+69.50%** | +69.57% | +72.42% | +1.10 | −45.89% | +39.09% | · | 338 | 12,105 |
| template_top5_gated | 2023-09-05→2025-09-04 | −48.33% | −28.13% | 2025-09-04→2026-09-04 | **+45.56%** | +45.60% | +70.78% | +0.89 | −45.89% | +15.14% | · | 324 | 12,105 |
| xs_momentum_12_1 | 2023-09-05→2025-09-04 | +68.02% | +29.65% | 2025-09-04→2026-09-04 | **+44.92%** | +44.95% | +52.08% | +0.97 | −30.54% | +14.50% | · | 747 | 12,105 |
| ew_benchmark | 2023-09-05→2025-09-04 | +35.76% | +16.53% | 2025-09-04→2026-09-04 | **+30.42%** | +30.44% | +56.15% | +0.75 | −36.64% | +0.00% | · | 906 | 12,105 |
| sector_momentum | 2023-09-05→2025-09-04 | +35.32% | +16.34% | 2025-09-04→2026-09-04 | **+29.39%** | +29.42% | +13.45% | +1.98 | −7.91% | · | +10.01% | 40 | 12,105 |
| ew_voltarget | 2023-09-05→2025-09-04 | +51.35% | +23.04% | 2025-09-04→2026-09-04 | **+29.37%** | +29.40% | +51.62% | +0.76 | −31.90% | −1.05% | · | 907 | 12,105 |
| dual_momentum | 2023-09-05→2025-09-04 | +42.47% | +19.38% | 2025-09-04→2026-09-04 | **+23.76%** | +23.78% | +14.82% | +1.51 | −11.42% | · | +4.38% | 10 | 12,105 |
| high_52wk | 2023-09-05→2025-09-04 | +45.41% | +20.60% | 2025-09-04→2026-09-04 | **+19.60%** | +19.62% | +15.94% | +1.20 | −11.28% | −10.82% | · | 554 | 12,105 |
| spy_benchmark | 2023-09-05→2025-09-04 | +47.70% | +21.55% | 2025-09-04→2026-09-04 | **+19.38%** | +19.40% | +12.45% | +1.49 | −8.65% | · | +0.00% | 0 | 12,105 |
| dual_momentum_gated | 2023-09-05→2025-09-04 | +25.49% | +12.03% | 2025-09-04→2026-09-04 | **+19.20%** | +19.22% | +13.70% | +1.35 | −11.42% | · | −0.18% | 10 | 12,105 |
| template_top10_banded | 2023-09-05→2025-09-04 | −15.46% | −8.06% | 2025-09-04→2026-09-04 | **+18.81%** | +18.82% | +70.59% | +0.61 | −43.55% | −11.61% | · | 751 | 12,105 |
| template_top10_banded_gated | 2023-09-05→2025-09-04 | −17.06% | −8.94% | 2025-09-04→2026-09-04 | **+11.30%** | +11.31% | +69.54% | +0.51 | −43.55% | −19.11% | · | 725 | 12,105 |
| momo_stopped | 2023-09-05→2025-09-04 | −10.30% | −5.30% | 2025-09-04→2026-09-04 | **+10.77%** | +10.78% | +68.00% | +0.50 | −44.38% | −19.65% | · | 769 | 12,105 |
| mr_overlay_gated | 2023-09-05→2025-09-04 | +13.56% | +6.57% | 2025-09-04→2026-09-04 | **+8.77%** | +8.78% | +16.03% | +0.60 | −8.04% | −21.65% | · | 440 | 12,105 |
| ew_trend_gated | 2023-09-05→2025-09-04 | +27.62% | +12.98% | 2025-09-04→2026-09-04 | **+8.36%** | +8.36% | +55.28% | +0.42 | −36.63% | −22.06% | · | 849 | 12,105 |
| mr_overlay | 2023-09-05→2025-09-04 | +11.59% | +5.64% | 2025-09-04→2026-09-04 | **+6.03%** | +6.04% | +16.44% | +0.44 | −8.96% | −24.38% | · | 456 | 12,105 |
| low_vol | 2023-09-05→2025-09-04 | +39.03% | +17.93% | 2025-09-04→2026-09-04 | **+4.66%** | +4.67% | +9.12% | +0.55 | −5.56% | · | · | 199 | 12,105 |
| turtle_breakout | 2023-09-05→2025-09-04 | −4.07% | −2.06% | 2025-09-04→2026-09-04 | **−8.35%** | −8.36% | +29.89% | −0.14 | −30.16% | −38.77% | · | 164 | 12,105 |

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
