# Reverse splits, stranded cash, and why the fix is the fill model — not the universe

> **Historical snapshot.** This records the 2026-08-20 analysis. See
> [`execution-capital-data-hardening-2026-09-06.md`](execution-capital-data-hardening-2026-09-06.md)
> for current fill-model behavior.

_Main-loop synthesis, 2026-08-20, reconciling the fill-model audit and the leveraged-ETF
audit. Every number here was measured read-only against the live store._

## Three findings that looked like three problems

1. **Fill audit:** 2,634 orders rejected for insufficient cash across the fold replays.
   **436 of them (16.6%) are leveraged/inverse ETFs, carrying 90.8% of all stranded cash.**
   Worst case from the 08-19 log: `DRIP buy 0.7027 shares @ $47,988.54, cash $29,569.57 —
   rejected`, leaving 76% of that book idle.
2. **Leverage audit:** 812 of 12,459 universe names are leveraged/inverse; 265 are liquid;
   **every stored screen has passed 6-25 of them** (median 17, 42 distinct tickers). Four
   live books hold `DLLL` (2x DELL) today. 35 flagged names carry an implausible
   back-adjusted price.
3. **Also found:** `TNXP` (Tonix Pharmaceuticals, not leveraged at all) has a max close of
   **$19,200,000,000**. 32 tickers in the store exceed $100,000.

## They are one problem, and it is not the one it looks like

`engine/collect.py:88` fetches with `auto_adjust=False`, which in yfinance leaves dividends
unadjusted but still **split-adjusts OHLC**. A name with large cumulative REVERSE splits
therefore has its old prices multiplied up without limit. TNXP:

| year | median close | median volume | median dollar-volume |
|---|---|---|---|
| 2018 | $31,712,000 | **2 shares** | $76.3M |
| 2019 | $748,800 | **1 share** | $1.4M |
| 2024 | $72.00 | 12,030 | $1.1M |
| 2025 | $22.77 | 842,383 | $20.5M |
| 2026 | $13.38 | 405,350 | $5.3M |

**Volume is divided down by the same factor the price is multiplied up.** Two consequences,
and the second is the only real bug:

- **Dollar-volume is preserved, so the liquidity filter is SOUND.** `collect.py:161-172`
  screens on `median(close * volume) >= 5_000_000`, and that product is split-invariant.
  There is no liquidity-filter bug here. The `last_close >= 3` price floor is also fine for
  a LIVE screen, since it reads today's price.
- **The whole-share clamp breaks.** `sim/portfolio.py:128` does
  `affordable = math.floor(cash / px)`. A $39,000 book facing a $31,712,000 adjusted price
  computes `floor(0.0012) = 0` and rejects the order, stranding whatever cash the target
  weight had allocated. This is the DRIP case exactly, generalised: **any name with heavy
  cumulative reverse splits is untradeable in historical replay for a purely arithmetic
  reason.**

**The prices are not wrong.** Back-adjustment preserves returns, which is what a backtest
consumes. They were simply never market prices, and only a rule keyed on absolute price
per share notices — of which there is exactly one, and it is the clamp.

## The decisive detail

The live books hold **fractional** quantities: `template_top10_banded` holds
`DLLL qty 102.384263`, `momo_stopped` holds `120.824008`. Every sizing path in the engine
is fractional (`base.py:386`, `turtle_breakout.py:70`, `pead_ear.py:104`). The
`trading-execution-design.md` §2 spec defines next-open fills, slippage tiers and the
1%-of-dollar-volume guard and **says nothing about lot size**; `BUILDLOG.md:284` records the
`floor()` as a 2026-07-18 negative-cash safety fix.

**Whole-share trading is incidental, not designed.** It is the one place the engine rounds,
and it is the one place the stranded cash comes from.

## Decision

**Fix the clamp. Do not touch the universe for this, and do not "correct" the prices.**

- `affordable = cash / px` (fractional), plus a dust floor on the reject branch so a
  sub-dollar residual does not generate a fill.
- This resolves the leveraged-ETF stranding — 90.8% of the stranded dollars — as a side
  effect, **without** invalidating the screen, without removing 812 names, and without the
  4 collateral losses (CHE, MTB, OFG, QCRH) that the universe exclusion would cost by
  shifting the RS percentile.
- It also fixes TNXP-class names, which the universe exclusion would NOT have fixed, since
  Tonix is not a leveraged fund.

**What it invalidates, stated plainly:** all 65 stored fold JSONs, the 4 sweep grids, and
the live forward record since 2026-07-17 were produced under the current model. The change
must therefore land **version-stamped** (`fillmodel=v2`) with a scheduled regeneration, not
silently. The measured size of the average effect is small — 1-3 bp/yr — so there is no
urgency; the exposure is in the tail, where **50 rejects strand >10% of a book** across
~200 folds.

## Still open, and separate

- **The leveraged-ETF question is a STRATEGY question, not a data bug**, and it survives
  this fix untouched: a momentum screen that ranks 3x leveraged funds by relative strength
  mechanically selects the most leveraged exposure to whatever just rose. That is worth
  deciding on its own merits, and the recommendation from the leverage audit stands — run
  `ew_benchmark` under both universe policies and publish the pair rather than flipping a
  default that redefines the benchmark every other book is judged against.
- **`SPYU`, a 4X ETN, has passed 15 stored screens.** Whatever is decided about 2x/3x, a
  4x ETN in an equity screen deserves a look on its own.
