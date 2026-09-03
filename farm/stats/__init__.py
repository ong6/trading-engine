"""farm.stats — statistics package.

  inference.py  per-trade RETURN series: Sharpe, PSR/DSR, t-stat, bootstrap CI
  equity.py     daily EQUITY curves: CAGR, vol, Sharpe (raw/ex-BIL), drawdown, worst month

Everything the old flat `farm/stats.py` exported is re-exported here, so
`from farm import stats as fstats` keeps working. The one behavioural change:
`max_drawdown` now takes an EQUITY curve (the farm.stats.equity definition);
the old returns-based call is `max_drawdown_from_returns`.
"""
from farm.stats.equity import (
    TRADING_DAYS,
    bil_daily_returns,
    equity_stats,
    max_drawdown,
    worst_month,
)
from farm.stats.inference import (
    BOOTSTRAP_CONF,
    BOOTSTRAP_DRAWS,
    BOOTSTRAP_SEED,
    MIN_BOOTSTRAP_N,
    SeriesStats,
    bootstrap_ci,
    ci_verdict,
    compute,
    deflated_sharpe,
    expected_max_sharpe,
    max_drawdown_from_returns,
    probabilistic_sharpe,
)

__all__ = [
    "BOOTSTRAP_CONF", "BOOTSTRAP_DRAWS", "BOOTSTRAP_SEED", "MIN_BOOTSTRAP_N",
    "SeriesStats", "TRADING_DAYS", "bil_daily_returns", "bootstrap_ci", "ci_verdict",
    "compute", "deflated_sharpe", "equity_stats", "expected_max_sharpe", "max_drawdown",
    "max_drawdown_from_returns", "probabilistic_sharpe", "worst_month",
]
