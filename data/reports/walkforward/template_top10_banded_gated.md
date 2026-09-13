# Template Top 10 banded (regime-gated) — walk-forward re-validation

_`template_top10_banded_gated` · template_top10_banded · weekly cadence · verdict **WATCH** · generated 2026-09-13T06:27:35+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-09-11. Each fold is an independent replay starting at $39,000. Span 2014-09-11 → 2026-09-11 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,114,750 passing rows).

**Provenance.** Source `2a45f846b7a4628661c4539adf71074377c529a450c90cb07cd4125aafed7d75`; config `6b7b393d1530b1ecf6dbc87df74c75d052267e40ad24f8ef79d21e3498bd4b4d`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `039bd02c7cdb5678f28e5cf93098393c7e695625c4fc37fc5281d2e8e19fa80e`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Lowest-drawdown of the template family; modest return give-up.

**Pre-registered kill criterion.** No drawdown improvement vs ungated banded across a risk-off episode.

**Measured against `ew_benchmark` on the same folds:** beats it in 30% of 10 window(s), mean excess +5.48%, latest −11.47% → **WATCH**.

**90% CI on mean excess vs `ew_benchmark`:** [−13.56%, +33.08%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-09-11→2016-09-09 | −0.72% | −0.36% | 2016-09-09→2017-09-11 | **+4.28%** | +4.26% | +27.77% | +0.29 | −13.79% | −14.21% | · | 733 | 2,743 |
| 2 | 2015-09-11→2017-09-11 | +13.14% | +6.36% | 2017-09-11→2018-09-11 | **+39.71%** | +39.74% | +30.22% | +1.26 | −17.75% | −3.54% | · | 712 | 2,891 |
| 3 | 2016-09-12→2018-09-11 | +38.76% | +17.84% | 2018-09-11→2019-09-11 | **−19.19%** | −19.20% | +27.17% | −0.65 | −32.27% | −5.79% | · | 489 | 3,000 |
| 4 | 2017-09-11→2019-09-11 | +13.74% | +6.65% | 2019-09-11→2020-09-11 | **+46.88%** | +46.76% | +36.73% | +1.23 | −27.84% | +14.50% | · | 572 | 3,125 |
| 5 | 2018-09-11→2020-09-11 | +20.33% | +9.69% | 2020-09-11→2021-09-10 | **+283.82%** | +285.60% | +58.35% | +2.61 | −31.18% | +137.96% | · | 776 | 3,380 |
| 6 | 2019-09-11→2021-09-10 | +479.46% | +140.86% | 2021-09-10→2022-09-09 | **−8.30%** | −8.32% | +32.94% | −0.10 | −33.56% | +3.36% | · | 374 | 3,538 |
| 7 | 2020-09-11→2022-09-09 | +245.03% | +86.14% | 2022-09-09→2023-09-11 | **−15.10%** | −15.03% | +29.48% | −0.41 | −22.25% | −14.30% | · | 503 | 3,645 |
| 8 | 2021-09-13→2023-09-11 | −12.53% | −6.50% | 2023-09-11→2024-09-11 | **−7.23%** | −7.21% | +43.29% | +0.04 | −30.09% | −13.77% | · | 722 | 3,820 |
| 9 | 2022-09-12→2024-09-11 | −21.23% | −11.26% | 2024-09-11→2025-09-11 | **−13.46%** | −13.47% | +51.11% | −0.03 | −47.44% | −37.90% | · | 642 | 4,023 |
| 10 ◈ | 2023-09-11→2025-09-11 | −15.36% | −8.00% | 2025-09-11→2026-09-11 | **+8.70%** | +8.71% | +69.79% | +0.48 | −42.80% | −11.47% | · | 736 | 12,517 |

## Summary

* validate windows: **10**, win rate **50%**
* mean validate return **+32.01%** (median −1.47%, worst −19.19%, best +283.82%)
* mean validate CAGR **+32.18%** vs mean train CAGR +24.14% → decay **+8.04%**
* mean validate Sharpe +0.47, worst validate max drawdown −47.44%
* 6259 fill(s) inside validate windows
* runtime 1112.1s (scratch 28.2s, screen 25.2s)

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

