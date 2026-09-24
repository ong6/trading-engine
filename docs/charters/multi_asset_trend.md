# Charter — `multi_asset_trend`

_Pre-registration, 2026-09-02. This preserves the original league-book thesis;
the dated outcome addendum records its later retirement._

Status: **retired 2026-09-06** · Class: `sim/strategies/multi_asset_trend.py` · Cadence: **monthly**
(matching `dual_momentum`).

## Outcome addendum — 2026-09-06

The pre-registered 10-fold validation returned **0.51 median validate Sharpe**
versus **0.88** for `dual_momentum`, directly breaching the diversification kill
criterion. It also trailed SPY by a median **0.86% per month** (90% CI
**[-1.18%, -0.51%]**), despite materially reducing drawdown. The configuration
and database portfolio are inactive; the book had no orders, fills, or positions.
Historical artifacts remain for provenance, but the strategy is not active and
must not be described as a current league book.

## Hypothesis

`dual_momentum` promises drawdown protection and, on 15 years of replay, did not deliver
it (CAGR 7.9% vs SPY 13.1% *with a worse max DD*, `../history/evaluation-2026-09-02.md` §1). Its
structural problem is not the absolute-momentum hurdle — it is that the book is 100%
in **one** asset at all times, so every switch is a whole-book bet and every whipsaw is
paid in full.

> **H.** Applying the same 12-month-total-return-vs-BIL hurdle **per asset** across
> eight asset classes — each in a fixed 1/8 slot that sits in BIL when its own trend
> fails — delivers a materially lower max drawdown than `spy_benchmark` and a higher
> Sharpe than `dual_momentum`, at the cost of lagging SPY in US-led bull runs. This is
> time-series momentum (Moskowitz–Ooi–Pedersen 2012; Faber 2007 in ETF form), the one
> gap in §5 of the evaluation whose backtest does **not** depend on the survivor
> universe, because the instruments are ETFs that still exist.

## Mechanism (what the book does, exactly)

1. Assets: **SPY, EFA, EEM, TLT, IEF, GLD, DBC, VNQ** — US equity, developed ex-US,
   emerging, 20y+ Treasuries, 7–10y Treasuries, gold, broad commodities, US REITs. All
   eight are in the store with continuous history (first bars: SPY 1993-01, EFA 2001-08,
   TLT/IEF 2002-07, EEM 2003-04, VNQ 2004-09, GLD 2004-11, DBC 2006-02; checked
   2026-09-02). Cash proxy **BIL** (2007-05).
2. Signal per asset: 252-session **total** return (price + dividends ex in the window)
   compared with BIL's 252-session total return.
3. Slot rule: each asset owns a fixed **12.5%** slot. Held in the asset if its return
   **exceeds** BIL's; parked in BIL otherwise. An asset with insufficient history is
   skipped — its slot goes to BIL, never scored on a shorter window.
4. Monthly at the last session, filled at the next open.

Design decisions and why:

| Choice | Value | Reason |
|---|---|---|
| Fixed 1/N slots, not equal-weight among holders | 12.5% each | With "equal weight among holders", seven failing assets would leave the book 100% in the eighth — `dual_momentum`'s concentration problem reintroduced exactly when correlations converge. Fixed slots are what make the sleeve diversified in the bad state. |
| Hurdle | BIL total return | The Antonacci absolute-momentum gate, per asset. BIL's price is flat and its whole return is coupon, so a price-only hurdle would degenerate to 0 (the `dual_momentum` bug fixed 2026-07-29). |
| Lookback | 252 sessions | The canonical 12-month TSMOM window; same as `dual_momentum`, so the two books differ only in breadth and the slot rule. |
| No blended lookbacks, no vol scaling | — | Each is a legitimate variant and each is a second variable. The book tests breadth. Vol-scaling in particular would be `ew_gross_voltarget`'s question in another costume. |
| Asset list | 8, no UUP/SHY/TIP | UUP (dollar) is a hedge instrument with negative carry; SHY/TIP are near-cash and would be BIL by another name. The eight cover the classical risk premia. |

## What changes vs `dual_momentum`, and only that

Breadth (2 → 8 assets) and the slot rule (winner-take-all → fixed slots with per-asset
hurdle). Lookback, hurdle instrument, return convention, cadence and fill model are
identical.

## Expectation, including the negative case

**Positive case.** Max drawdown under half of SPY's in a full risk-off episode, Sharpe
above `dual_momentum`'s, CAGR several points below SPY in US-led bull runs. A reasonable
success shape is **SPY-like Sharpe or better at half the drawdown**, which is what the
TSMOM literature reports for diversified long-only ETF implementations.

**Negative case.** (a) 2022-style: equities, bonds and REITs all trend down together and
the sleeve is 75% BIL for a year — that is the design working, but it will read as
"missed the recovery" for the first months of the next bull. (b) A twelve-month lookback
is slow; in a V-shaped crash (2020-03) the book takes most of the drawdown and only
de-risks near the low, then re-risks late. (c) The gold/commodity slots add real
diversification only when they trend, and DBC has spent long stretches below BIL. The
honest prior is that the book **does** cut drawdown materially — the mechanism is
well-documented and does not rest on a survivor universe — and gives up 5–8 pp of CAGR
against SPY in a strong US bull market for it.

## Comparison

- **`dual_momentum`** (the book this extends): median validate Sharpe and worst-fold
  drawdown over the 10-fold protocol. This is the test of the *breadth* hypothesis.
- **`spy_benchmark`**: max drawdown across a full risk-off episode and the 2-year return
  gap. This is the test of the *drawdown-reducer* claim.
- Not `ew_benchmark`: a multi-asset ETF sleeve against a single-name momentum screen
  compares universes, not rules.

## Kill criterion (verbatim from `configs.py`)

> Fails to deliver a lower max drawdown than `spy_benchmark` across a full risk-off
> episode, or trails `spy_benchmark` by >20% over 2 years without a lower max drawdown,
> or has a lower median validate Sharpe than `dual_momentum` over the 10-fold
> walk-forward (the diversification claim is then false).

## Expected turnover

Low: **~1.5–2× equity one-way per year**, most of it monthly drift-rebalancing of eight
slots plus a handful of asset↔BIL switches. Fill cost is negligible (all eight ETFs and
BIL sit in the 5 bp half-spread tier).

## Known biases

1. **No single-name survivorship.** The one new book for which the store's structural
   bias does not apply: every instrument exists today *and* existed throughout the
   window. This is the strongest reason to weight its backtest more than the other two.
2. **ETF-selection hindsight, mild.** The eight were chosen in 2026 knowing they became
   the liquid standard-bearers of their asset classes; an investor in 2007 might have
   picked IYR over VNQ or GSG over DBC. The effect on a 1/8-slot trend rule is second
   order.
3. **Fill model v2** at a $39k notional: trivially satisfied; the liquidity guard never
   binds on these ETFs. Dividends are credited as cash and redeployed at the next
   rebalance, the same convention `total_return` uses, so signal and P&L agree.
4. **BIL's history starts 2007-05**: `farm/backtest/replay.py` `REQUIRED` now lists all
   nine tickers, so a `max` window clamps to 2008-05 rather than replaying un-funded BIL
   slots. `sector_momentum`-style skipping handles the risk assets.

## First evidence — 3-year replay, run AFTER registration (2026-09-02)

Same machinery, window and session as the other two charters (2023-07-17 → 2026-07-16,
fill model v2, $39,000, read-only store copy; controls re-run with identical code). One
window; not the protocol. Notably the window contains no full risk-off episode (the
2025-04 drawdown was two months), so the book's *primary* claim is untested here.

| book | total | CAGR | vol | Sharpe | max DD | worst month | fills | turnover (1-way/yr) |
|---|---|---|---|---|---|---|---|---|
| **multi_asset_trend** | +39.5% | +11.7% | 7.9% | 1.45 | −7.2% | −3.3% | 202 | 1.85 |
| dual_momentum | +60.4% | +17.1% | 16.0% | 1.07 | −18.8% | −7.8% | 25 | 1.86 |
| spy_benchmark | +71.3% | +19.7% | 15.0% | 1.28 | −18.4% | −5.5% | 1 | — |

Daily-return correlation: 0.79 with `dual_momentum`, 0.75 with SPY, 0.65 with
`ew_benchmark`.

Reading: the shape predicted in the expectation — Sharpe above both controls (1.45 vs
1.07 / 1.28), max drawdown at **39% of SPY's**, and an 8 pp CAGR lag in a US-led bull
market, which is inside the "5–8 pp" the charter allows. The 2-year kill clause is not
triggered because the drawdown is lower. On the 2026-09-01 signal the book holds
SPY/EFA/EEM/GLD/DBC/VNQ and parks the TLT and IEF slots in BIL (25%).
