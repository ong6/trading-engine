# Mean-Reversion Overlay (regime-gated) — walk-forward re-validation

_`mr_overlay_gated` · mr_overlay · daily cadence · verdict **REVIEW** · generated 2026-09-27T08:54:00+00:00_

**Protocol.** train 24mo → validate 12mo, step 12mo, 10 fold(s), anchored 2026-09-25. Each fold is an independent replay starting at $39,000. Span 2014-09-25 → 2026-09-25 (3018 sessions); data floor 1994-01-27; screen source `hist` (1,119,401 passing rows).

**Provenance.** Source `5358bb7b805e61939b93281f7ebaa8e40f0c296d61e49e1bfed205ad5eb25093`; config `733f1b12222d04238953cc8e119f149512e06a0bf2eb647f9a659173a85070fa`.

**Evidence and execution.** Data quality `current_universe_survivor_biased`; execution profile `baseline_v1`; data snapshot `adc34a49b33dbf0425bc008751d43a32d09b1445ffd750e1cab2fe7c8dc2632e`; comparison protocol `wf-controls-2026-09-07-v1`.

**Pre-registered expectation.** Fewer trades and lower drawdown than ungated MR; avoids catching falling knives in bear tapes.

**Pre-registered kill criterion.** No drawdown/expectancy improvement vs ungated MR.

**Measured against `ew_benchmark` on the same folds:** beats it in 20% of 10 window(s), mean excess −23.63%, latest −7.67% → **REVIEW**.

**90% CI on mean excess vs `ew_benchmark`:** [−41.82%, −8.22%] → **distinguishable −**. The verdict above is unchanged by this interval — see the note below the fold table.

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
| 1 | 2014-09-25→2016-09-23 | −3.47% | −1.75% | 2016-09-23→2017-09-25 | **−7.99%** | −7.95% | +9.26% | −0.85 | −9.12% | −20.89% | · | 411 | 2,769 |
| 2 | 2015-09-25→2017-09-25 | −11.20% | −5.76% | 2017-09-25→2018-09-25 | **+6.70%** | +6.71% | +13.68% | +0.54 | −9.13% | −39.08% | · | 442 | 2,920 |
| 3 | 2016-09-26→2018-09-25 | −0.43% | −0.22% | 2018-09-25→2019-09-25 | **−4.67%** | −4.67% | +9.60% | −0.45 | −9.00% | +8.68% | · | 288 | 3,033 |
| 4 | 2017-09-25→2019-09-25 | +2.83% | +1.41% | 2019-09-25→2020-09-25 | **−0.10%** | −0.10% | +11.77% | +0.05 | −13.59% | −39.77% | · | 352 | 3,164 |
| 5 | 2018-09-25→2020-09-25 | −6.51% | −3.31% | 2020-09-25→2021-09-24 | **+29.33%** | +29.45% | +15.84% | +1.71 | −11.76% | −107.86% | · | 446 | 3,419 |
| 6 | 2019-09-25→2021-09-24 | +28.51% | +13.37% | 2021-09-24→2022-09-23 | **−9.17%** | −9.20% | +8.76% | −1.06 | −11.42% | +12.64% | · | 161 | 3,571 |
| 7 | 2020-09-25→2022-09-23 | +16.99% | +8.19% | 2022-09-23→2023-09-25 | **−7.92%** | −7.88% | +9.00% | −0.88 | −8.29% | −7.03% | · | 304 | 3,682 |
| 8 | 2021-09-27→2023-09-25 | −13.00% | −6.75% | 2023-09-25→2024-09-25 | **+6.29%** | +6.28% | +11.12% | +0.60 | −10.20% | −20.93% | · | 456 | 3,857 |
| 9 | 2022-09-26→2024-09-25 | −2.12% | −1.07% | 2024-09-25→2025-09-25 | **+12.36%** | +12.37% | +13.31% | +0.95 | −13.64% | −14.33% | · | 398 | 4,066 |
| 10 ◈ | 2023-09-25→2025-09-25 | +19.21% | +9.18% | 2025-09-25→2026-09-25 | **+4.52%** | +4.52% | +16.43% | +0.35 | −9.14% | −7.67% | · | 435 | 12,609 |

## Summary

* validate windows: **10**, win rate **50%**
* mean validate return **+2.94%** (median +2.21%, worst −9.17%, best +29.33%)
* mean validate CAGR **+2.95%** vs mean train CAGR +1.33% → decay **+1.62%**
* mean validate Sharpe +0.10, worst validate max drawdown −13.64%
* 3693 fill(s) inside validate windows
* runtime 5076.9s (scratch 17.9s, screen 23.9s)

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

