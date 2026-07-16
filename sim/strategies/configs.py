"""Pre-registered strategy configs — the paper league's 10 portfolios.

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
]


def config_by_id(cid: str) -> dict:
    for c in CONFIGS:
        if c["id"] == cid:
            return c
    raise KeyError(cid)
