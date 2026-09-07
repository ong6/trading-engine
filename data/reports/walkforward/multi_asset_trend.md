# Multi-Asset Trend (8 ETFs, BIL hurdle) — walk-forward re-validation

_`multi_asset_trend` · multi_asset_trend · monthly cadence · verdict **RETIRED (no-benchmark)** · generated 2026-09-06T05:19:51+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-09-04. Each fold is an independent replay starting at $39,000. Span 2014-09-04 → 2026-09-04 (3019 sessions); data floor 2008-05-29; screen source `not-used`.

**Provenance.** **Legacy/unstamped artifact** — this retained historical result predates source/config hashing; no provenance has been inferred or fabricated.

**Evidence and execution.** Data quality `legacy_unclassified`; execution profile `legacy_unstamped`; data snapshot `legacy_unstamped`.

**Pre-registered expectation.** A drawdown reducer with equity-like long-run return: max drawdown well below spy_benchmark's (target: under half of SPY's in a full risk-off episode) and a higher Sharpe than dual_momentum, at the cost of lagging SPY in US-led bull runs. ETFs are the survivors, so this is the one new book whose backtest carries no single-name survivorship.

**Pre-registered kill criterion.** Fails to deliver a lower max drawdown than spy_benchmark across a full risk-off episode, or trails spy_benchmark by >20% over 2 years without a lower max drawdown, or has a lower median validate Sharpe than dual_momentum over the 10-fold walk-forward (the diversification claim is then false).

**Measured against `spy_benchmark` on the same folds:** beats it in · of 0 window(s), mean excess ·, latest · → **no-benchmark**.

**90% CI on mean excess vs `spy_benchmark`:** · → _no interval_. The verdict above is unchanged by this interval — see the note below the fold table.

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
   common to both sides of that difference. ETF/asset-allocation books use SPY,
   their registered benchmark. Absolute return is context, not evidence, and a fold
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
| 1 | 2014-09-04→2016-09-02 | +5.15% | +2.55% | 2016-09-02→2017-09-01 | **+1.78%** | +1.79% | +5.99% | +0.33 | −7.12% | −14.23% | · | 62 | 2,685 |
| 2 | 2015-09-04→2017-09-01 | +5.54% | +2.74% | 2017-09-01→2018-09-04 | **+1.99%** | +1.98% | +6.24% | +0.35 | −6.09% | −39.32% | · | 64 | 2,827 |
| 3 | 2016-09-06→2018-09-04 | +4.44% | +2.20% | 2018-09-04→2019-09-04 | **+2.71%** | +2.71% | +4.16% | +0.67 | −6.66% | +4.97% | · | 45 | 2,933 |
| 4 | 2017-09-05→2019-09-04 | +4.59% | +2.27% | 2019-09-04→2020-09-04 | **−0.26%** | −0.26% | +7.66% | +0.00 | −10.85% | −17.28% | · | 62 | 3,051 |
| 5 | 2018-09-04→2020-09-04 | +1.51% | +0.75% | 2020-09-04→2021-09-03 | **+10.71%** | +10.75% | +7.17% | +1.46 | −3.47% | −140.48% | · | 65 | 3,295 |
| 6 | 2019-09-04→2021-09-03 | +11.66% | +5.67% | 2021-09-03→2022-09-02 | **−2.46%** | −2.47% | +7.12% | −0.32 | −5.87% | +12.55% | · | 57 | 3,441 |
| 7 | 2020-09-04→2022-09-02 | +8.30% | +4.08% | 2022-09-02→2023-09-01 | **+0.49%** | +0.50% | +2.80% | +0.19 | −2.67% | −2.22% | · | 31 | 3,552 |
| 8 | 2021-09-07→2023-09-01 | +0.04% | +0.02% | 2023-09-01→2024-09-04 | **+11.78%** | +11.66% | +5.80% | +1.95 | −3.00% | +8.64% | · | 57 | 3,716 |
| 9 | 2022-09-06→2024-09-04 | +12.53% | +6.09% | 2024-09-04→2025-09-04 | **+9.59%** | +9.60% | +8.63% | +1.11 | −7.22% | −10.38% | · | 70 | 3,908 |
| 10 ◈ | 2023-09-05→2025-09-04 | +24.40% | +11.54% | 2025-09-04→2026-09-04 | **+19.92%** | +19.94% | +9.20% | +2.02 | −5.19% | −10.50% | · | 77 | 12,105 |

## Summary

* validate windows: **10**, win rate **80%**
* mean validate return **+5.63%** (median +2.35%, worst −2.46%, best +19.92%)
* mean validate CAGR **+5.62%** vs mean train CAGR +3.79% → decay **+1.82%**
* mean validate Sharpe +0.78, worst validate max drawdown −10.85%
* 590 fill(s) inside validate windows
* runtime 674.1s (scratch 35.0s, screen 0.0s)

**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against its registered control on the same folds (`ew_benchmark` for
single-name books; `spy_benchmark` for ETF/asset-allocation books):

* **PASS** — beats its control in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails its control.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.


**The interval is new information, not a new rule (added 2026-08-20).** The
PASS / WATCH / REVIEW rule above is unchanged: it still reads the beat rate and
the *mean* excess exactly as it was pre-registered, and no verdict in this
report has been recomputed, softened or overridden by an interval. What is new
is the **90% bootstrap CI on mean excess vs the registered control** in the
column beside it, and a
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

