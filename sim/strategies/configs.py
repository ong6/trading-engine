"""Pre-registered strategy configs — the paper league's 17 portfolios.

Each config is frozen up front (id, name, description, cadence, params,
expectation, kill_criterion) so the forward record is honest out-of-sample:
the hypothesis and the failure condition are written *before* the evidence
accrues, not fitted to it afterward. `strategy` names the module in this package
whose Strategy subclass runs the portfolio.
"""
from __future__ import annotations

CONFIGS: list[dict] = [
    {
        "id": "template_top5",
        "name": "Template Top 5",
        "strategy": "template_top5",
        "cadence": "weekly",
        "params": {"n": 5, "weight": 0.20},
        "description": "Weekly hold of the top 5 passes_template names by RS, "
                       "equal-weight 20% slots. Sell drop-outs, buy new entrants.",
        "expectation": "Concentrated momentum: higher return and higher drawdown "
                       "than the broad benchmark in risk-on regimes.",
        "kill_criterion": "Trails ew_benchmark by >15% over any rolling 6 months, "
                          "or max drawdown exceeds 40%.",
    },
    {
        "id": "template_top10_banded",
        "name": "Template Top 10 (banded)",
        "strategy": "template_top10_banded",
        "cadence": "weekly",
        "params": {"n": 10, "band_rank": 20},
        "description": "Weekly top 10 by RS, equal-weight, with banding: a "
                       "holding is only sold once it falls below RS rank 20.",
        "expectation": "Similar return to top5 with lower turnover and drawdown; "
                       "banding cuts whipsaw churn.",
        "kill_criterion": "Turnover fails to fall below template_top5, or trails "
                          "ew_benchmark by >15% over 6 months.",
    },
    {
        "id": "dual_momentum",
        "name": "Dual Momentum (GEM)",
        "strategy": "dual_momentum",
        "cadence": "monthly",
        "params": {"assets": ["SPY", "EFA"], "cash_proxy": "BIL", "lookback": 252},
        "description": "Classic GEM: monthly, hold the 12-mo winner of SPY vs EFA "
                       "if it beats BIL, else cash. 100% single position.",
        "expectation": "Lower drawdown than buy-and-hold via the cash switch; "
                       "lags in strong bull runs.",
        "kill_criterion": "Underperforms spy_benchmark by >20% over 2 years while "
                          "not delivering a lower max drawdown.",
    },
    {
        "id": "mr_overlay",
        "name": "Mean-Reversion Overlay",
        "strategy": "mr_overlay",
        "cadence": "daily",
        "params": {"rsi_max": 10, "down_closes": 3, "weight": 0.10,
                   "max_concurrent": 5, "time_stop": 10},
        "description": "Daily on passes_template names: enter on RSI(2)<10 and 3 "
                       "down closes, 10% each, max 5 concurrent. Exit on close > "
                       "prior high or a 10-day time stop.",
        "expectation": "Many small quick wins; positive expectancy in trending "
                       "names bought on pullbacks.",
        "kill_criterion": "Expectancy per trade turns negative over 50+ trades, "
                          "or max drawdown exceeds 25%.",
    },
    {
        "id": "template_top5_gated",
        "name": "Template Top 5 (regime-gated)",
        "strategy": "template_top5",
        "cadence": "weekly",
        "params": {"n": 5, "weight": 0.20, "gated": True},
        "description": "template_top5 but no NEW entries while SPY < 200d SMA "
                       "(risk-off). Existing positions exit at rebalance as usual.",
        "expectation": "Same upside as top5 in risk-on, materially lower drawdown "
                       "in bear markets (drifts to cash).",
        "kill_criterion": "Does not reduce max drawdown vs ungated top5 across a "
                          "full risk-off episode.",
    },
    {
        "id": "template_top10_banded_gated",
        "name": "Template Top 10 banded (regime-gated)",
        "strategy": "template_top10_banded",
        "cadence": "weekly",
        "params": {"n": 10, "band_rank": 20, "gated": True},
        "description": "template_top10_banded with the risk-off entry gate.",
        "expectation": "Lowest-drawdown of the template family; modest return give-up.",
        "kill_criterion": "No drawdown improvement vs ungated banded across a "
                          "risk-off episode.",
    },
    {
        "id": "dual_momentum_gated",
        "name": "Dual Momentum (regime-gated)",
        "strategy": "dual_momentum",
        "cadence": "monthly",
        "params": {"assets": ["SPY", "EFA"], "cash_proxy": "BIL", "lookback": 252,
                   "gated": True},
        "description": "Dual momentum; the risk-off gate blocks new risk entries "
                       "(GEM already switches to cash, so the gate rarely binds).",
        "expectation": "Near-identical to ungated GEM; gate is a belt-and-braces "
                       "check.",
        "kill_criterion": "Diverges materially from ungated GEM (would signal a "
                          "gate bug).",
    },
    {
        "id": "mr_overlay_gated",
        "name": "Mean-Reversion Overlay (regime-gated)",
        "strategy": "mr_overlay",
        "cadence": "daily",
        "params": {"rsi_max": 10, "down_closes": 3, "weight": 0.10,
                   "max_concurrent": 5, "time_stop": 10, "gated": True},
        "description": "mr_overlay with no new entries while risk-off; open "
                       "positions still exit on signal / time stop.",
        "expectation": "Fewer trades and lower drawdown than ungated MR; avoids "
                       "catching falling knives in bear tapes.",
        "kill_criterion": "No drawdown/expectancy improvement vs ungated MR.",
    },
    {
        "id": "ew_benchmark",
        "name": "Equal-Weight Benchmark",
        "strategy": "ew_benchmark",
        "cadence": "monthly",
        "params": {"cap": 50},
        "description": "Equal-weight the passes_template set (top 50 by RS), "
                       "rebalanced monthly. The strategy-agnostic yardstick.",
        "expectation": "Captures the screen's breadth; the bar every active "
                       "strategy must clear.",
        "kill_criterion": "Reference benchmark — not killed.",
    },
    {
        "id": "spy_benchmark",
        "name": "SPY Buy & Hold",
        "strategy": "spy_benchmark",
        "cadence": "once",
        "params": {"ticker": "SPY"},
        "description": "Buy SPY once at inception and hold. The market benchmark.",
        "expectation": "Baseline market return; the absolute-return yardstick.",
        "kill_criterion": "Reference benchmark — not killed.",
    },
    {
        "id": "turtle_breakout",
        "name": "Turtle Breakout (ATR-stopped)",
        "strategy": "turtle_breakout",
        "cadence": "daily",
        "params": {"entry_lookback": 55, "atr_period": 20, "stop_mult": 2.5,
                   "trail_mult": 3.0, "risk_frac": 0.0075, "max_positions": 10,
                   "max_weight": 0.15},
        "description": "Daily 55-session close breakout on passes_template names, "
                       "sized to risk 0.75% of equity against a 2.5×ATR(20) stop "
                       "(15% weight cap, max 10 names). Exit on a 3×ATR chandelier "
                       "trail off the post-entry peak close; no entries while "
                       "SPY < 200d SMA.",
        "expectation": "Positive-skew trend capture: roughly a 40% win rate with "
                       "the winners carrying the book, and drawdown well below "
                       "Template Top 5 thanks to ATR sizing and the trail.",
        "kill_criterion": "Max drawdown exceeds 25%, or trails ew_benchmark by "
                          ">15% over any rolling 6 months.",
    },
    {
        "id": "momo_stopped",
        "name": "Momentum Top 10 (stop-managed)",
        "strategy": "momo_stopped",
        "cadence": "daily",
        "params": {"n": 10, "band_rank": 20, "stop_frac": 0.85},
        "description": "template_top10_banded's weekly selection exactly, plus a "
                       "daily stop: sell in full on a close 15% below the last "
                       "weekly-signal close. The A/B isolates the stop.",
        "expectation": "Similar upside to Template Top 10 (banded) with materially "
                       "lower drawdown, the daily stop cutting losers between "
                       "weekly rebalances.",
        "kill_criterion": "Fails to reduce max drawdown vs template_top10_banded "
                          "over 6 months, or trails it by >5% cumulative return "
                          "with no drawdown benefit.",
    },
    {
        "id": "sector_momentum",
        "name": "Sector ETF Rotation",
        "strategy": "sector_momentum",
        "cadence": "monthly",
        "params": {"sectors": ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP",
                               "XLU", "XLB", "XLRE", "XLC"],
                   "n": 3, "lookbacks": [63, 126, 252]},
        "description": "Monthly: score the 11 SPDR sector ETFs by their mean 3/6/"
                       "12-month total return, hold the top 3 equal-weight; a slot "
                       "whose ETF has a non-positive 12-month return sits in cash.",
        "expectation": "Market-like return with lower drawdown — it wins by losing "
                       "less in downturns, not by out-running the index.",
        "kill_criterion": "Trails spy_benchmark by >10% over 12 months without "
                          "delivering a lower max drawdown.",
    },
    {
        "id": "low_vol",
        "name": "Low-Volatility Defensive",
        "strategy": "low_vol",
        "cadence": "monthly",
        "params": {"n": 30, "keep_rank": 60, "sector_cap": 5, "cap_floor": 5e9,
                   "vol_lookback": 252},
        "description": "Monthly: rank $5B+ equities by 252-session realized "
                       "volatility, hold the 30 lowest equal-weight, max 5 per "
                       "sector; a holding is kept while it stays inside the lowest "
                       "60 (buffer against churn).",
        "expectation": "Market-like return at noticeably lower volatility; expect "
                       "it to lag melt-ups and hold up in selloffs.",
        "kill_criterion": "Realized volatility is not below spy_benchmark's over 6 "
                          "months, or max drawdown exceeds SPY's in the same window.",
    },
    {
        "id": "high_52wk",
        "name": "52-Week-High Momentum",
        "strategy": "high_52wk",
        "cadence": "monthly",
        "params": {"n": 25, "min_ratio": 0.85, "keep_ratio": 0.75, "keep_rank": 50},
        "description": "Monthly: hold the 25 non-ETF names closest to their "
                       "52-week high (close ÷ 252-session high ≥ 0.85), equal "
                       "weight; a holding is kept while its ratio stays ≥ 0.75 and "
                       "it remains in the top 50.",
        "expectation": "Momentum-like returns without the long-run reversal that "
                       "dogs raw RS ranking, and lower churn than the RS books.",
        "kill_criterion": "Trails ew_benchmark by >15% over any rolling 6 months, "
                          "or max drawdown exceeds 35%.",
    },
    {
        "id": "pead_ear",
        "name": "PEAD (earnings reaction)",
        "strategy": "pead_ear",
        "cadence": "daily",
        "params": {"min_ear": 0.05, "vol_mult": 2.0, "weight": 0.04,
                   "max_concurrent": 10, "max_hold": 45, "stop_frac": 0.92},
        "description": "Daily: buy names whose earnings-day abnormal return (vs "
                       "SPY) is ≥ 5% on ≥2× the prior 20-day average volume, 4% of "
                       "equity each, max 10 concurrent. Exit after 45 sessions or "
                       "on a close 8% below avg cost.",
        "expectation": "A small, largely uncorrelated event sleeve: many small "
                       "positions and a modest positive expectancy rather than a "
                       "return driver.",
        "kill_criterion": "Expectancy turns negative after 30+ closed trades, or "
                          "max drawdown exceeds 15%.",
    },
    {
        "id": "macro_composite",
        "name": "Macro Composite (all-signals)",
        "strategy": "macro_composite",
        "cadence": "weekly",
        "params": {},
        "description": "Weekly SPY allocation in {0,25,50,75,100}% from four "
                       "pre-registered signal blocks — internal breadth, credit "
                       "(HY OAS / HYG-LQD), VIX term structure, macro "
                       "(claims+NFCI+curve-resteepen) — plus a fear-extremes "
                       "add-back and a leverage/short-interest cap. Signals from "
                       "the point-in-time macro_signals table (engine/signals.py); "
                       "thresholds frozen 2026-07-31 per "
                       "research/market-regime-signals.md.",
        "expectation": "Drawdown reducer, not alpha: lower max DD than "
                       "spy_benchmark across a full risk-off episode at a 2-4pp "
                       "CAGR toll; lags in strong bull years.",
        "kill_criterion": "Fails to reduce max drawdown vs spy_benchmark across a "
                          "full risk-off episode, or trails spy_benchmark by >20% "
                          "over 2 years without a lower max drawdown over the "
                          "same window.",
    },
]


def config_by_id(cid: str) -> dict:
    for c in CONFIGS:
        if c["id"] == cid:
            return c
    raise KeyError(cid)
