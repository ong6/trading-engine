# EW Screen — 200d Trend Gated — walk-forward re-validation

_`ew_trend_gated` · ew_trend_gated · monthly cadence · verdict **REVIEW** · generated 2026-09-23T16:53:20+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-09-22. Each fold is an independent replay starting at $39,000. Span 2014-09-22 → 2026-09-22 (3018 sessions); data floor 2008-05-29; screen source `hist` (1,117,447 passing rows).

**Provenance.** Source `e41e0968a995a82ddca7ebea7aa09c09a9b5351e58b343f7155c30e5b2778dda`; config `bca58f64dc0aaad72a668c87f82e633a979a2fa77bb9732738145ec500296e3e`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `315382aa846d597a2feffa8bbd2d170de62f535c07a1f6313d73681bef4e676f`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Materially lower max drawdown than ew_benchmark across a full risk-off episode, paid for in whipsaw during choppy sideways tapes. The honest prior is negative: the existing entry-block gates bought only ~4pp of drawdown relief (top10_banded -47.81% ungated vs -43.69% gated), and a 200-day filter on a monthly basket is slow.

**Pre-registered kill criterion.** No max-drawdown improvement vs ew_benchmark across a full risk-off fold, or trails ew_benchmark by >15% cumulative over 12 months without a lower max drawdown.

**Measured against `ew_benchmark` on the same folds:** beats it in 20% of 10 window(s), mean excess −3.99%, latest −18.59% → **REVIEW**.

**90% CI on mean excess vs `ew_benchmark`:** [−7.33%, −1.08%] → **distinguishable −**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-09-22→2016-09-22 | +6.32% | +3.11% | 2016-09-22→2017-09-22 | **+14.11%** | +14.12% | +20.03% | +0.76 | −10.69% | −0.00% | · | 733 | 2,755 |
| 2 | 2015-09-22→2017-09-22 | +13.51% | +6.54% | 2017-09-22→2018-09-21 | **+38.93%** | +39.09% | +23.54% | +1.52 | −16.08% | −0.02% | · | 718 | 2,906 |
| 3 | 2016-09-22→2018-09-21 | +58.09% | +25.79% | 2018-09-21→2019-09-20 | **−15.70%** | −15.75% | +20.68% | −0.73 | −22.41% | −5.15% | · | 501 | 3,018 |
| 4 | 2017-09-22→2019-09-20 | +15.23% | +7.37% | 2019-09-20→2020-09-22 | **+37.37%** | +37.04% | +25.83% | +1.35 | −16.95% | −2.29% | · | 660 | 3,144 |
| 5 | 2018-09-24→2020-09-22 | +11.56% | +5.63% | 2020-09-22→2021-09-22 | **+129.22%** | +129.35% | +42.88% | +2.15 | −22.92% | +0.00% | · | 862 | 3,401 |
| 6 | 2019-09-23→2021-09-22 | +235.58% | +83.27% | 2021-09-22→2022-09-22 | **−11.86%** | −11.87% | +26.13% | −0.35 | −34.16% | +3.83% | · | 539 | 3,555 |
| 7 | 2020-09-22→2022-09-22 | +93.55% | +39.15% | 2022-09-22→2023-09-22 | **−15.71%** | −15.72% | +22.13% | −0.66 | −20.56% | −9.53% | · | 650 | 3,666 |
| 8 | 2021-09-22→2023-09-22 | −25.62% | −13.76% | 2023-09-22→2024-09-20 | **+27.14%** | +27.24% | +31.46% | +0.93 | −20.57% | −3.61% | · | 751 | 3,837 |
| 9 | 2022-09-22→2024-09-20 | +7.06% | +3.48% | 2024-09-20→2025-09-22 | **+22.86%** | +22.74% | +33.31% | +0.79 | −27.88% | −4.55% | · | 739 | 4,046 |
| 10 ◈ | 2023-09-22→2025-09-22 | +48.40% | +21.80% | 2025-09-22→2026-09-22 | **−7.52%** | −7.52% | +54.99% | +0.13 | −37.12% | −18.59% | · | 848 | 12,565 |

## Summary

* validate windows: **10**, win rate **60%**
* mean validate return **+21.88%** (median +18.49%, worst −15.71%, best +129.22%)
* mean validate CAGR **+21.87%** vs mean train CAGR +18.24% → decay **+3.63%**
* mean validate Sharpe +0.59, worst validate max drawdown −37.12%
* 7001 fill(s) inside validate windows
* runtime 1716.5s (scratch 20.8s, screen 24.7s)

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

