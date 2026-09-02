# Charter — `xs_momentum_12_1`

_Pre-registration, 2026-09-02. **League book** (registered in
`sim/strategies/configs.py`; `sim.league --init` creates its `portfolios` row at the
next nightly, and its first monthly signal is the last session of 2026-09)._

Status: **book — the control** · Class: `sim/strategies/xs_momentum_12_1.py`
(shared scan in `sim/strategies/xs_common.py`) · Cadence: **monthly**, matching
`ew_benchmark` so the spread is attributable to selection and not to trading frequency.

## Hypothesis

Every comparison in this store is "vs `ew_benchmark`", and `ew_benchmark` *is* the
Minervini trend-template screen: the top 50 passers by RS, equal weight, monthly.
"The screen is the edge" (`docs/evaluation-2026-09-02.md` §2) is therefore the
untested assumption underneath every other result. The template is a dressed-up
momentum filter — RS rank, price above rising 150/200-day averages, within 25% of
the 52-week high — so the null hypothesis is:

> **H0.** The screen's return is plain cross-sectional momentum. A book that ranks the
> same liquid universe by trailing 12-month return, skips the last month, and holds the
> top 50 equal-weight is INDISTINGUISHABLE from `ew_benchmark` on median excess return
> and worst-fold drawdown.

The alternative, which the store has implicitly assumed since July, is that the
template's trend-structure conditions add value *beyond* the momentum rank.

## Mechanism (what the book does, exactly)

1. Universe: `universe.active AND liquid AND NOT etf`, close ≥ $5, at least 253 stored
   sessions. No screen, no fundamentals, no RS rank.
2. Signal: total return (price + dividends going ex in the window) from the close 252
   sessions ago to the close 21 sessions ago — Jegadeesh–Titman 12-1. The most recent
   month is skipped because the one-month effect is a *reversal* (see `xs_reversal_1m`)
   and would contaminate the rank.
3. Selection: top 50 by that return. Equal weight 1/50. Monthly at the last session of
   the month, filled at the next open through the standard fill model.
4. **No banding, no stops, no regime gate.** A held name that falls out of the top 50 is
   sold. This is deliberate: banding is a rule, and the control tests no rules.

Design decisions and why:

| Choice | Value | Reason |
|---|---|---|
| `n` | 50 | Matches `ew_benchmark`'s `cap`, so the book is EW's basket size with a different ranking and nothing else differs. Top *decile* of ~2.9k names would be ~290 slots of $135 each — dust against `MIN_ORDER_USD` and a 6× larger fill count for no informational gain. |
| `lookback` / `skip` | 252 / 21 sessions | The literature's 12-1 in sessions rather than calendar months, consistent with every other lookback in this repo. |
| `min_price` | $5 | Standard academic filter. `liquid` already floors at $3; $5 keeps a rank from being won by a low-priced name doubling on nothing. |
| `min_bars` | 253 | A name is either scored on the full window or excluded, never on a shorter one. |
| Return type | total | `base.total_return`'s convention (dividends as unreinvested cash), applied set-wide in SQL. Price-only would penalise every dividend payer against non-payers. |

## What changes vs `ew_benchmark`, and only that

The **ranking and eligibility rule**. Universe policy (today's `universe` flags),
basket size, weighting, cadence, fill model and dividend treatment are identical.

## Expectation, including the negative case

**If H0 holds** (the honest prior): median excess vs `ew_benchmark` near zero with a wide
CI, similar worst-fold drawdown, similar momentum crashes (2009-style, 2020-11, 2022).
Then the screen has been shown to be a complicated way to buy momentum, and every
"vs EW" verdict in the store is a "vs momentum" verdict — which is fine, but it should
be said that way.

**If the template adds value:** `ew_benchmark` beats this book on median excess with a
CI excluding zero *and* has a lower worst-fold drawdown. The template's trend-structure
conditions would then be worth their turnover and the screen's cost.

**If the control wins:** the screen *subtracts* from momentum — plausible, because the
template's "within 25% of 52-week high" and tight-base conditions select for
late-stage, lower-volatility momentum and the equal-weight top-50 of a 2.9k-name
universe is a far more concentrated bet on the extreme tail of the momentum
distribution. That tail is also where survivorship bias is largest (see below), so a
control win must be discounted before it is believed.

## Comparison

- **Primary:** `ew_benchmark`, identical folds, identical universe, median excess validate
  return, beat rate, worst-fold drawdown, 90% bootstrap CI.
- **Secondary:** `template_top10_banded` — the live template book with the most
  evidence. That spread measures the whole template *family* (screen + top-10
  concentration + banding) against plain momentum.
- Never against SPY alone: a survivor-universe single-name book vs an index is a universe
  comparison, and it flatters everything in this store.

## Kill criterion (verbatim from `configs.py`)

> Control: retired only once its question is answered. Kill if `ew_benchmark` beats it in
> ≥ 70% of walk-forward folds with a 90% CI on median excess that excludes 0 AND a lower
> worst-fold drawdown (screen shown to add value), or if any fold is inert, or if live max
> drawdown exceeds 55%.

The 55% line is deliberately looser than the template books' 40%: an unhedged top-50
momentum book has a documented −50%-class crash profile (2009), and killing the control
for behaving like momentum would defeat its purpose.

## Expected turnover

Roughly 30–40% of names replaced per month, i.e. **~4–5× equity one-way per year**.
Lower than `ew_benchmark` (whose passers churn on the screen's binary conditions) and far
below the weekly template books. At the fill model's 10–30 bp per side this is a
~2–3 pp/yr cost, similar in kind to EW's.

## Known biases, all inherited from the store

1. **Survivorship, and it scales with concentration.** `prices` holds only tickers listed
   today; `universe.active/liquid/etf` are today's flags (snapshots only since 2026-07-16).
   The top 50 of a 12-month return rank is *exactly* the population where delisting,
   acquisition and blow-up are most frequent, so this book inherits *more* survivor lift
   than a 50-name screen basket, not the same amount (`evaluation-2026-09-02.md` §2). A
   backtested edge over EW is therefore an upper bound; a backtested deficit is more
   credible than a surplus.
2. **Today's liquidity flag.** A name that is liquid in 2026 may have been a $6k/day
   micro-cap in 2023 — the 3y replay produced exactly one such `illiquid` rejection. The
   fill model's 1%-of-median-$vol guard catches the worst cases; it does not correct the
   selection.
3. **Fill model v2:** t+1 open, 10–30 bp per side by liquidity tier, no partial fills. A
   $39k book holding 50 names is small enough that the guard almost never binds; the live
   record will have the same cost structure as the backtest.
4. **Universe policy `all`:** leveraged ETNs filed as `etf = FALSE` could enter. None did in
   the 3y replay or on the 2026-09-01 signal; the `ex-leveraged` policy is not applied
   here because `ew_benchmark` does not apply it either, and the comparison must be
   like-for-like.

## First evidence — 3-year replay, run AFTER registration (2026-09-02)

Real `farm/backtest/replay.py` machinery against a read-only copy of the store,
window 2023-07-17 → 2026-07-16 (the farm's `3y`), fill model v2, policy `all`,
$39,000 notional. Controls re-run in the same session with identical code. One window;
**not** the 10-fold protocol, and the window is the strongest three momentum years since
2020. Numbers are context, not a verdict.

| book | total | CAGR | vol | Sharpe | max DD | worst month | fills | turnover (1-way/yr) |
|---|---|---|---|---|---|---|---|---|
| **xs_momentum_12_1** | +126.8% | +31.4% | 42.9% | 0.85 | −37.1% | −19.1% | 2,124 | 4.45 |
| ew_benchmark | +61.4% | +17.3% | 41.5% | 0.60 | −33.3% | −23.6% | 2,534 | 6.52 |
| template_top10_banded | −1.0% | −0.3% | 57.2% | 0.28 | −47.8% | −29.2% | 2,243 | 14.98 |
| spy_benchmark (context) | +71.3% | +19.7% | 15.0% | 1.28 | −18.4% | −5.5% | 1 | — |

Daily-return correlation with `ew_benchmark`: **0.87**. `ew_benchmark` beat the control
in **12 of 36** calendar months. Turnover came in at the expected ~4.5× and below EW's.

Reading, stated with the bias attached: on this window the unscreened control out-ran the
screen by 14 pp CAGR at 4 pp *more* drawdown, and out-ran the template family by 32 pp.
That is consistent with "the screen is momentum minus something", but the something may
well be survivorship lift concentrated in the control's tail. The 10-fold walk-forward
with the 90% CI is the pre-registered test; this table is not it.
