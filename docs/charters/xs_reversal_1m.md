# Charter — `xs_reversal_1m`

_Designed 2026-09-02. **NOT registered as a league book.** In the 3-year design replay
(2023-07-17 → 2026-07-16) its daily excess-return correlation with `ew_benchmark` was
0.71 — above the 0.70 kill line written below — and 0.85 with `xs_momentum_12_1`. A
book that fails its own charter before it starts is not pre-registered; the class and
this charter stay on disk for a re-registration under a different hypothesis (e.g. no
200d filter, or a pure bottom-decile book), which would be a NEW charter._

Status: **designed, withdrawn before registration** · Class: `sim/strategies/xs_reversal_1m.py` (shared scan in
`sim/strategies/xs_common.py`) · Cadence: **monthly**.

## Hypothesis

Everything live in the league is a momentum book or a beta dial on one. The store's
one mean-reversion rule, `mr_overlay` (RSI(2) on template passers), failed in 9 of 9
sweep cells — but that tested a *daily technical trigger on momentum names*, not the
documented cross-sectional effect:

> **H.** Among liquid US names in an uptrend, the worst performers of the past month
> earn a positive excess return over the next month (Jegadeesh 1990; Lehmann 1990) —
> the one-month reversal. A long-only, equal-weight book of those names has a return
> source distinct from momentum: **daily excess-return correlation with `ew_benchmark`
> below 0.3** and positive, if modest, absolute return net of the fill model.

The diversification claim is the primary claim. A reversal book that merely tracks
momentum with worse Sharpe has no reason to exist in this league.

## Mechanism (what the book does, exactly)

1. Universe: `universe.active AND liquid AND NOT etf`, close ≥ $5, at least 252 stored
   sessions.
2. Eligibility: close **above its 200-session SMA**. Long-only reversal without a trend
   filter is a falling-knife catcher — the loser decile is dominated by names in
   structural decline, and the literature's short leg is where most of the effect lives.
   Restricting to uptrends buys pullbacks instead. This filter is part of the
   hypothesis, pre-registered, not a knob.
3. Signal: trailing 21-session **total** return (a special dividend must not read as a
   loss).
4. Selection: the **worst 10%** of eligible names, **capped at 50**, each in a fixed 2%
   slot. Unfilled slots stay in cash. With ~1.5k eligible names the decile (~150) is
   always capped, so in practice the book holds the 50 worst-performing uptrending
   names; in a bear tape, when few names sit above their 200d, it shrinks toward cash by
   construction — a documented side effect, not a claim.
5. Monthly, no banding: a reversal position is a one-month bet and is re-underwritten
   every month, so **turnover is close to 100% per month by design**.

Design decisions and why:

| Choice | Value | Reason |
|---|---|---|
| `max_n` / slot | 50 / 2% fixed | Same basket size as `ew_benchmark`/`xs_momentum_12_1`; fixed slots (not 1/n_chosen) so the book cannot concentrate when few names qualify. |
| `frac` | 0.10 | The decile the literature reports; the cap makes it non-binding today and binding only in thin markets. |
| Trend filter | 200-session SMA | The league's regime definition (`regime_risk_off`) applied per name; one convention, not a new one. |
| `min_price` | $5 | As `xs_momentum_12_1`. |
| `lookback` | 21 sessions | One month. Five-day reversal was rejected: at this book's notional the weekly fill cost would swamp the effect. |

## Expectation, including the negative case

**Positive case.** Low correlation to every live book, positive Sharpe, drawdowns that
do not coincide with momentum crashes. Even a Sharpe of 0.3–0.5 would be valuable *if*
the correlation claim holds.

**Negative case, and it is likely.** (a) The post-2000 one-month reversal is weak in
large liquid names and much of it is bid-ask bounce that a next-open fill with 10–30 bp
slippage does not capture. (b) At ~11× one-way turnover per year the fill model charges
roughly 4–5 pp/yr — the effect's whole historical magnitude. (c) **The trend filter may
make the book a momentum-beta book:** names above their 200d SMA that fell last month are
disproportionately last year's winners taking a breather, i.e. the book could end up
buying `xs_momentum_12_1`'s basket one month late. If so the correlation claim fails and
the book is killed on that clause, which is the correct outcome.

## Comparison

**`ew_benchmark`** on identical folds (universe and cadence match), on median excess,
beat rate and worst-fold drawdown; **plus** the 12-month daily-excess correlation with
`ew_benchmark`, which is the falsification test for the diversification claim.

## Kill criterion (verbatim from `configs.py`)

> Trails `ew_benchmark` by >15% cumulative over any 12 months WITHOUT a lower max
> drawdown, or max drawdown exceeds 35%, or 12-month correlation of daily excess returns
> with `ew_benchmark` exceeds 0.7 (the diversification claim is then false), or any
> walk-forward fold is inert.

## Expected turnover

**~90–100% of names per month, ~11× equity one-way per year.** The highest in the
league after the weekly template books; the fill model's slippage is the book's main
enemy and the reason it may not survive costs.

## Known biases

1. **Survivorship.** Same as every single-name book here (today's `prices`, today's
   `universe` flags). For a *loser* book the bias is in the book's favour: the names that
   fell 20% last month and then went to zero are absent, so the backtest's loser decile is
   cleaner than the live one will be.
2. **Fill model v2.** Next-open fills with tiered slippage; two `illiquid` rejections in
   the 3y replay (names with 2023 median $vol under $60k that carry today's `liquid`
   flag). Realistic for a $39k book; the effect's bid-ask component is not captured and
   should not be.
3. **Universe policy `all`** — as `xs_momentum_12_1`.

## First evidence — 3-year replay, run AFTER registration (2026-09-02)

Same machinery, window and controls as the other two charters (2023-07-17 → 2026-07-16,
fill model v2, policy `all`, $39,000, read-only store copy). One window; not the
protocol.

| book | total | CAGR | vol | Sharpe | max DD | worst month | fills | turnover (1-way/yr) |
|---|---|---|---|---|---|---|---|---|
| **xs_reversal_1m** | −8.4% | −2.9% | 32.5% | 0.07 | −37.5% | −17.1% | 3,430 | 11.21 |
| ew_benchmark | +61.4% | +17.3% | 41.5% | 0.60 | −33.3% | −23.6% | 2,534 | 6.52 |
| xs_momentum_12_1 (context) | +126.8% | +31.4% | 42.9% | 0.85 | −37.1% | −19.1% | 2,124 | 4.45 |

Daily-return correlation: **0.71 with `ew_benchmark`, 0.85 with `xs_momentum_12_1`**,
0.74 with SPY.

Reading: negative case (c) is what the window shows. The trend-filtered loser basket
tracked the momentum control at 0.85 and trailed EW by 70 pp over three years at a
*higher* max drawdown. Against the pre-registered kill criterion the book would already
be dead on two clauses (return-without-lower-drawdown, and correlation at 0.71 vs the
0.70 line). Turnover came in at the expected 11×.

**Decision for the owner, recorded here rather than acted on:** the registration stands
as written — nothing in `configs.py` was changed after seeing this table, per the
no-peeking rule. The pre-registered test is the 10-fold walk-forward and the live
record, and the honest expectation is that the correlation clause fires. If the owner
would rather test the *unfiltered* reversal (no 200d SMA condition — the version that
does not smuggle momentum in), that is a **new** pre-registration with a new charter,
not an amendment to this one.
