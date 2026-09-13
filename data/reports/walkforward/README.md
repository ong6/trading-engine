# Walk-forward re-validation of league rules

_10 book(s) re-validated · protocol **train 24mo → validate 12mo, step 12mo, 10 folds, anchored 2026-09-11** · generated 2026-09-13 06:33 UTC._

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

**1 of 9 judged book(s) are `INDISTINGUISHABLE` from their declared control** at 90% confidence on mean excess. Read every verdict in the next column with that column beside it.

| Book | Evidence class | Control | Verdict | Distinguishable? | Folds | Validate win rate | Beats control | Mean validate | Mean excess | 90% CI on mean excess | Latest validate | Latest excess | Mean decay (CAGR) | Worst validate DD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [dual_momentum_gated](dual_momentum_gated.md) | `fixed_etf_history` | spy_benchmark | REVIEW | **distinguishable −** | 10 | 70% | 20% | +9.32% | −5.96% | [−9.14%, −2.74%] | +15.87% | −1.11% | +2.20% | −17.47% |
| [sector_momentum](sector_momentum.md) | `fixed_etf_history` | spy_benchmark | WATCH | **INDISTINGUISHABLE** | 9 | 89% | 33% | +13.94% | −1.00% | [−6.22%, +4.98%] | +26.09% | +9.11% | +1.52% | −31.86% |
| [dual_momentum](dual_momentum.md) | `fixed_etf_history` | spy_benchmark | WATCH | **distinguishable −** | 10 | 60% | 50% | +9.80% | −5.47% | [−9.85%, −1.30%] | +20.30% | +3.33% | +3.44% | −33.69% |
| [template_top5](template_top5.md) | `current_universe_survivor_biased` | ew_benchmark | no-benchmark | _no interval_ | 10 | 50% | · | +68.53% | · | · | +80.63% | · | +32.32% | −61.59% |
| [template_top5_gated](template_top5_gated.md) | `current_universe_survivor_biased` | ew_benchmark | no-benchmark | _no interval_ | 10 | 50% | · | +63.15% | · | · | +55.16% | · | +21.11% | −49.00% |
| [template_top10_banded_gated](template_top10_banded_gated.md) | `current_universe_survivor_biased` | ew_benchmark | no-benchmark | _no interval_ | 10 | 50% | · | +32.01% | · | · | +8.70% | · | +8.04% | −47.44% |
| [template_top10_banded](template_top10_banded.md) | `current_universe_survivor_biased` | ew_benchmark | no-benchmark | _no interval_ | 10 | 50% | · | +31.13% | · | · | +16.02% | · | +10.66% | −49.37% |
| [high_52wk](high_52wk.md) | `current_universe_survivor_biased` | ew_benchmark | no-benchmark | _no interval_ | 10 | 70% | · | +10.81% | · | · | +18.18% | · | +5.13% | −32.32% |
| [low_vol](low_vol.md) | `static_fundamental_lookahead` | ew_benchmark | no-benchmark | _no interval_ | 10 | 100% | · | +10.24% | · | · | +3.34% | · | −1.33% | −35.83% |
| [spy_benchmark](spy_benchmark.md) | `fixed_etf_history` | — | reference | — | 10 | 90% | · | +15.28% | · | · | +16.97% | · | +1.78% | −32.41% |

## Latest validate window (2025-09-11 → 2026-09-11)

| Book | Train window | Train ret | Train CAGR | Validate window | Validate ret | CAGR | Vol | Sharpe | Max DD | vs EW | vs SPY | Fills | Universe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| template_top5 | 2023-09-11→2025-09-11 | −55.80% | −33.50% | 2025-09-11→2026-09-11 | **+80.63%** | +80.70% | +72.93% | +1.18 | −45.89% | · | · | 343 | 12,517 |
| template_top5_gated | 2023-09-11→2025-09-11 | −40.79% | −23.04% | 2025-09-11→2026-09-11 | **+55.16%** | +55.21% | +71.30% | +0.98 | −45.89% | · | · | 326 | 12,517 |
| sector_momentum | 2023-09-11→2025-09-11 | +38.10% | +17.50% | 2025-09-11→2026-09-11 | **+26.09%** | +26.11% | +13.47% | +1.80 | −7.91% | · | +9.11% | 40 | 12,517 |
| dual_momentum | 2023-09-11→2025-09-11 | +44.34% | +20.13% | 2025-09-11→2026-09-11 | **+20.30%** | +20.32% | +14.94% | +1.32 | −11.42% | · | +3.33% | 10 | 12,517 |
| high_52wk | 2023-09-11→2025-09-11 | +50.72% | +22.75% | 2025-09-11→2026-09-11 | **+18.18%** | +18.19% | +15.68% | +1.15 | −11.25% | · | · | 553 | 12,517 |
| spy_benchmark | 2023-09-11→2025-09-11 | +50.00% | +22.46% | 2025-09-11→2026-09-11 | **+16.97%** | +16.99% | +12.50% | +1.32 | −8.64% | · | +0.00% | 0 | 12,517 |
| template_top10_banded | 2023-09-11→2025-09-11 | −13.37% | −6.92% | 2025-09-11→2026-09-11 | **+16.02%** | +16.03% | +70.84% | +0.57 | −42.80% | · | · | 764 | 12,517 |
| dual_momentum_gated | 2023-09-11→2025-09-11 | +27.14% | +12.75% | 2025-09-11→2026-09-11 | **+15.87%** | +15.88% | +13.82% | +1.14 | −11.42% | · | −1.11% | 10 | 12,517 |
| template_top10_banded_gated | 2023-09-11→2025-09-11 | −15.36% | −8.00% | 2025-09-11→2026-09-11 | **+8.70%** | +8.71% | +69.79% | +0.48 | −42.80% | · | · | 736 | 12,517 |
| low_vol | 2023-09-11→2025-09-11 | +39.28% | +18.00% | 2025-09-11→2026-09-11 | **+3.34%** | +3.34% | +9.09% | +0.41 | −5.56% | · | · | 199 | 12,517 |

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
