# Momentum Top 10 (stop-managed) — walk-forward re-validation

_`momo_stopped` · momo_stopped · daily cadence · verdict **WATCH** · generated 2026-09-13T07:18:18+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-09-11. Each fold is an independent replay starting at $39,000. Span 2014-09-11 → 2026-09-11 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,114,750 passing rows).

**Provenance.** Source `2a45f846b7a4628661c4539adf71074377c529a450c90cb07cd4125aafed7d75`; config `25cac3722d4dded026ce3b8501bcdac09a1cbca0069f40f25b16afb5ecb3642e`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `039bd02c7cdb5678f28e5cf93098393c7e695625c4fc37fc5281d2e8e19fa80e`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Similar upside to Template Top 10 (banded) with materially lower drawdown, the daily stop cutting losers between weekly rebalances.

**Pre-registered kill criterion.** Fails to reduce max drawdown vs template_top10_banded over 6 months, or trails it by >5% cumulative return with no drawdown benefit.

**Measured against `ew_benchmark` on the same folds:** beats it in 30% of 10 window(s), mean excess +2.32%, latest −12.38% → **WATCH**.

**90% CI on mean excess vs `ew_benchmark`:** [−13.14%, +21.37%] → **INDISTINGUISHABLE**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-09-11→2016-09-09 | −13.27% | −6.89% | 2016-09-09→2017-09-11 | **+1.99%** | +1.98% | +27.77% | +0.21 | −14.93% | −16.50% | · | 728 | 2,743 |
| 2 | 2015-09-11→2017-09-11 | −8.53% | −4.36% | 2017-09-11→2018-09-11 | **+40.56%** | +40.59% | +30.03% | +1.28 | −18.10% | −2.69% | · | 711 | 2,891 |
| 3 | 2016-09-12→2018-09-11 | +36.23% | +16.76% | 2018-09-11→2019-09-11 | **−24.31%** | −24.32% | +32.09% | −0.71 | −47.99% | −10.91% | · | 750 | 3,000 |
| 4 | 2017-09-11→2019-09-11 | +7.24% | +3.56% | 2019-09-11→2020-09-11 | **+65.35%** | +65.18% | +44.15% | +1.36 | −37.05% | +32.97% | · | 801 | 3,125 |
| 5 | 2018-09-11→2020-09-11 | +26.95% | +12.66% | 2020-09-11→2021-09-10 | **+237.94%** | +239.35% | +56.20% | +2.46 | −34.79% | +92.07% | · | 778 | 3,380 |
| 6 | 2019-09-11→2021-09-10 | +473.72% | +139.67% | 2021-09-10→2022-09-09 | **−11.27%** | −11.31% | +43.40% | −0.06 | −35.29% | +0.39% | · | 820 | 3,538 |
| 7 | 2020-09-11→2022-09-09 | +194.36% | +71.89% | 2022-09-09→2023-09-11 | **−16.24%** | −16.17% | +34.75% | −0.34 | −24.20% | −15.44% | · | 766 | 3,645 |
| 8 | 2021-09-13→2023-09-11 | −17.16% | −9.01% | 2023-09-11→2024-09-11 | **−2.55%** | −2.54% | +41.85% | +0.15 | −30.08% | −9.09% | · | 759 | 3,820 |
| 9 | 2022-09-12→2024-09-11 | −12.24% | −6.32% | 2024-09-11→2025-09-11 | **−10.81%** | −10.81% | +52.76% | +0.05 | −49.63% | −35.25% | · | 789 | 4,023 |
| 10 ◈ | 2023-09-11→2025-09-11 | −8.20% | −4.19% | 2025-09-11→2026-09-11 | **+7.80%** | +7.80% | +68.36% | +0.46 | −43.63% | −12.38% | · | 780 | 12,517 |

## Summary

* validate windows: **10**, win rate **50%**
* mean validate return **+28.85%** (median −0.28%, worst −24.31%, best +237.94%)
* mean validate CAGR **+28.98%** vs mean train CAGR +21.38% → decay **+7.60%**
* mean validate Sharpe +0.49, worst validate max drawdown −49.63%
* 7682 fill(s) inside validate windows
* runtime 2659.4s (scratch 27.4s, screen 25.8s)

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

