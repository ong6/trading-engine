# Low-Volatility Defensive — walk-forward re-validation

_`low_vol` · low_vol · monthly cadence · verdict **no-benchmark** · generated 2026-09-20T06:32:24+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-09-18. Each fold is an independent replay starting at $39,000. Span 2014-09-18 → 2026-09-18 (3018 sessions); data floor 1994-01-27; screen source `not-used`.

**Provenance.** Source `158dd063aa57e6e37448fdf630ca3e2f244043f4d1bd2520a7b30edcc76b2371`; config `b46dccde55935659cad3c95b3c09a15974b37b10755a5b7b501f9485574aeed7`.

**Evidence and execution.** Data quality `static_fundamental_lookahead`; execution profile `baseline_v1`; data snapshot `c868f4fcc1655450840ca9fb0f244fb9c3c708ec50ec181d46905f33faba08b8`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Market-like return at noticeably lower volatility; expect it to lag melt-ups and hold up in selloffs.

**Pre-registered kill criterion.** Realized volatility is not below spy_benchmark's over 6 months, or max drawdown exceeds SPY's in the same window.

**Measured against `ew_benchmark` on the same folds:** beats it in · of 0 window(s), mean excess ·, latest · → **no-benchmark**.

**90% CI on mean excess vs `ew_benchmark`:** · → _no interval_. The verdict above is unchanged by this interval — see the note below the fold table.

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


## Folds

| Fold | Train window | Train ret | Train CAGR | Validate window | Validate ret | CAGR | Vol | Sharpe | Max DD | vs EW | vs SPY | Fills | Universe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2014-09-18→2016-09-16 | +24.03% | +11.39% | 2016-09-16→2017-09-18 | **+13.32%** | +13.25% | +6.64% | +1.92 | −4.25% | · | · | 167 | 2,752 |
| 2 | 2015-09-18→2017-09-18 | +29.43% | +13.76% | 2017-09-18→2018-09-18 | **+10.44%** | +10.45% | +7.87% | +1.30 | −8.19% | · | · | 193 | 2,902 |
| 3 | 2016-09-19→2018-09-18 | +24.44% | +11.58% | 2018-09-18→2019-09-18 | **+15.24%** | +15.25% | +8.80% | +1.66 | −8.92% | · | · | 167 | 3,014 |
| 4 | 2017-09-18→2019-09-18 | +26.67% | +12.56% | 2019-09-18→2020-09-18 | **+0.44%** | +0.44% | +28.28% | +0.16 | −35.83% | · | · | 231 | 3,143 |
| 5 | 2018-09-18→2020-09-18 | +13.92% | +6.73% | 2020-09-18→2021-09-17 | **+23.08%** | +23.16% | +9.85% | +2.17 | −5.40% | · | · | 211 | 3,398 |
| 6 | 2019-09-18→2021-09-17 | +23.83% | +11.29% | 2021-09-17→2022-09-16 | **+2.11%** | +2.12% | +12.53% | +0.23 | −10.74% | · | · | 208 | 3,555 |
| 7 | 2020-09-18→2022-09-16 | +27.89% | +13.14% | 2022-09-16→2023-09-18 | **+3.67%** | +3.65% | +10.93% | +0.39 | −8.43% | · | · | 193 | 3,663 |
| 8 | 2021-09-20→2023-09-18 | +5.79% | +2.87% | 2023-09-18→2024-09-18 | **+17.33%** | +17.30% | +8.21% | +1.99 | −5.13% | · | · | 175 | 3,837 |
| 9 | 2022-09-19→2024-09-18 | +29.11% | +13.63% | 2024-09-18→2025-09-18 | **+10.90%** | +10.91% | +12.01% | +0.93 | −8.30% | · | · | 215 | 4,045 |
| 10 ◈ | 2023-09-18→2025-09-18 | +37.17% | +17.11% | 2025-09-18→2026-09-18 | **+3.67%** | +3.67% | +9.06% | +0.44 | −5.89% | · | · | 199 | 12,565 |

## Summary

* validate windows: **10**, win rate **100%**
* mean validate return **+10.02%** (median +10.67%, worst +0.44%, best +23.08%)
* mean validate CAGR **+10.02%** vs mean train CAGR +11.40% → decay **−1.38%**
* mean validate Sharpe +1.12, worst validate max drawdown −35.83%
* 1959 fill(s) inside validate windows
* runtime 1390.2s (scratch 33.0s, screen 0.0s)

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

