# Compatibility shim (2026-09-03): the equity-curve stats moved to farm/stats/equity.py.
# Keep importing `from farm.backtest import stats`; new code should use farm.stats.equity.
from farm.stats.equity import *  # noqa: F401,F403
from farm.stats.equity import _sharpe  # noqa: F401  (tests reach for it)
