# Mean-Reversion Overlay — walk-forward re-validation

_`mr_overlay` · mr_overlay · daily cadence · verdict **REVIEW** · generated 2026-09-13T08:43:39+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-09-11. Each fold is an independent replay starting at $39,000. Span 2014-09-11 → 2026-09-11 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,114,750 passing rows).

**Provenance.** Source `2a45f846b7a4628661c4539adf71074377c529a450c90cb07cd4125aafed7d75`; config `cc049dd59ad46b14ff6f16c5878b8ef49789945a7714226a6e6929db25429cb4`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `039bd02c7cdb5678f28e5cf93098393c7e695625c4fc37fc5281d2e8e19fa80e`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Many small quick wins; positive expectancy in trending names bought on pullbacks.

**Pre-registered kill criterion.** Expectancy per trade turns negative over 50+ trades, or max drawdown exceeds 25%.

**Measured against `ew_benchmark` on the same folds:** beats it in 20% of 10 window(s), mean excess −24.59%, latest −19.15% → **REVIEW**.

**90% CI on mean excess vs `ew_benchmark`:** [−44.21%, −8.88%] → **distinguishable −**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-09-11→2016-09-09 | −9.22% | −4.73% | 2016-09-09→2017-09-11 | **−3.74%** | −3.72% | +9.43% | −0.36 | −9.09% | −22.23% | · | 414 | 2,743 |
| 2 | 2015-09-11→2017-09-11 | −8.78% | −4.49% | 2017-09-11→2018-09-11 | **−1.39%** | −1.39% | +10.23% | −0.09 | −6.91% | −44.64% | · | 439 | 2,891 |
| 3 | 2016-09-12→2018-09-11 | −9.03% | −4.63% | 2018-09-11→2019-09-11 | **−4.23%** | −4.23% | +14.02% | −0.24 | −14.95% | +9.17% | · | 380 | 3,000 |
| 4 | 2017-09-11→2019-09-11 | −5.28% | −2.68% | 2019-09-11→2020-09-11 | **+7.45%** | +7.43% | +13.56% | +0.60 | −16.06% | −24.94% | · | 431 | 3,125 |
| 5 | 2018-09-11→2020-09-11 | +2.69% | +1.33% | 2020-09-11→2021-09-10 | **+26.31%** | +26.41% | +16.07% | +1.54 | −12.51% | −119.56% | · | 442 | 3,380 |
| 6 | 2019-09-11→2021-09-10 | +32.59% | +15.16% | 2021-09-10→2022-09-09 | **−8.03%** | −8.06% | +12.35% | −0.62 | −15.38% | +3.63% | · | 373 | 3,538 |
| 7 | 2020-09-11→2022-09-09 | +16.76% | +8.08% | 2022-09-09→2023-09-11 | **−11.06%** | −11.01% | +13.55% | −0.80 | −16.40% | −10.27% | · | 441 | 3,645 |
| 8 | 2021-09-13→2023-09-11 | −19.19% | −10.14% | 2023-09-11→2024-09-11 | **−2.33%** | −2.33% | +11.36% | −0.15 | −10.20% | −8.88% | · | 448 | 3,820 |
| 9 | 2022-09-12→2024-09-11 | −10.42% | −5.35% | 2024-09-11→2025-09-11 | **+15.41%** | +15.42% | +14.67% | +1.06 | −17.30% | −9.04% | · | 464 | 4,023 |
| 10 ◈ | 2023-09-11→2025-09-11 | +12.47% | +6.05% | 2025-09-11→2026-09-11 | **+1.03%** | +1.03% | +16.76% | +0.14 | −9.14% | −19.15% | · | 447 | 12,517 |

## Summary

* validate windows: **10**, win rate **40%**
* mean validate return **+1.94%** (median −1.86%, worst −11.06%, best +26.31%)
* mean validate CAGR **+1.95%** vs mean train CAGR −0.14% → decay **+2.09%**
* mean validate Sharpe +0.11, worst validate max drawdown −17.30%
* 4279 fill(s) inside validate windows
* runtime 5119.5s (scratch 21.8s, screen 24.0s)

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

