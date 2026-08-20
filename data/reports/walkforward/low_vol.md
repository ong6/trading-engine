# Low-Volatility Defensive — walk-forward re-validation

_`low_vol` · low_vol · monthly cadence · verdict **REVIEW** · generated 2026-08-16T06:24:32+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 6 fold(s), anchored 2026-08-14. Each fold is an independent replay starting at $39,000. Span 2018-08-14 → 2026-08-14 (2011 sessions); data floor 1994-01-27; screen source `not-used`.

**Pre-registered expectation.** Market-like return at noticeably lower volatility; expect it to lag melt-ups and hold up in selloffs.

**Pre-registered kill criterion.** Realized volatility is not below spy_benchmark's over 6 months, or max drawdown exceeds SPY's in the same window.

**Measured against `ew_benchmark` on the same folds:** beats it in 33% of 6 window(s), mean excess −19.95%, latest −26.68% → **REVIEW**.

**90% CI on mean excess vs `ew_benchmark`:** [−52.39%, +3.75%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

## Disclosures — read before any number below

1. **Survivor universe.** `prices` holds only tickers listed TODAY, so every
   name delisted, acquired or bankrupted inside a fold is absent entirely. The
   house lesson prices this at roughly **+7pp/yr of fake return** for a
   screen-driven book. That is WHY the headline comparison here is **vs EW
   (same universe, same screen), fold by fold** — the bias is largely common to
   both sides of that difference. Absolute return is context, not evidence.
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


## Folds

| Fold | Train window | Train ret | Train CAGR | Validate window | Validate ret | CAGR | Vol | Sharpe | Max DD | vs EW | vs SPY | Fills |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2018-08-14→2020-08-14 | +16.25% | +7.81% | 2020-08-14→2021-08-13 | **+25.42%** | +25.52% | +10.12% | +2.30 | −5.23% | −105.70% | −7.41% | 216 |
| 2 | 2019-08-14→2021-08-13 | +27.31% | +12.84% | 2021-08-13→2022-08-12 | **+6.73%** | +6.75% | +11.93% | +0.61 | −10.74% | +14.70% | +9.52% | 197 |
| 3 | 2020-08-14→2022-08-12 | +35.39% | +16.42% | 2022-08-12→2023-08-14 | **−3.61%** | −3.60% | +11.46% | −0.27 | −13.95% | −3.53% | −9.88% | 198 |
| 4 | 2021-08-16→2023-08-14 | +3.06% | +1.52% | 2023-08-14→2024-08-14 | **+13.09%** | +13.07% | +8.12% | +1.56 | −5.73% | +11.64% | −9.04% | 167 |
| 5 | 2022-08-15→2024-08-14 | +17.12% | +8.23% | 2024-08-14→2025-08-14 | **+14.95%** | +14.96% | +11.96% | +1.23 | −8.22% | −10.16% | −4.47% | 204 |
| 6 ◈ | 2023-08-14→2025-08-14 | +32.96% | +15.30% | 2025-08-14→2026-08-14 | **+7.00%** | +7.00% | +9.14% | +0.79 | −5.54% | −26.68% | −14.04% | 188 |

## Summary

* validate windows: **6**, win rate **83%**
* mean validate return **+10.60%** (median +10.04%, worst −3.61%, best +25.42%)
* mean validate CAGR **+10.62%** vs mean train CAGR +10.35% → decay **+0.27%**
* mean validate Sharpe +1.04, worst validate max drawdown −13.95%
* 1170 fill(s) inside validate windows
* runtime 372.3s (scratch 11.1s, screen 0.0s)

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

