"""Pure account-risk calculations used by admission and nightly halts."""
from __future__ import annotations

import math

DRAWDOWN_LIMIT = -0.20
DAILY_LOSS_LIMIT = -0.05
MAX_GROSS_FRACTION = 1.5


def _finite(value: float, field: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{field} must be finite")
    return value


def drawdown(equity: float, peak_equity: float) -> float:
    equity, peak_equity = _finite(equity, "equity"), _finite(peak_equity, "peak equity")
    if peak_equity <= 0:
        raise ValueError("peak equity must be positive")
    return equity / peak_equity - 1.0


def daily_return(equity: float, prior_close_equity: float | None) -> float | None:
    if prior_close_equity is None:
        return None
    equity = _finite(equity, "equity")
    prior_close_equity = _finite(prior_close_equity, "prior close equity")
    if prior_close_equity <= 0:
        return None
    return equity / prior_close_equity - 1.0


def gross_exposure(positions: dict[str, dict], marks: dict[str, float]) -> float:
    missing = sorted(set(positions) - set(marks))
    if missing:
        raise ValueError(f"missing marks: {','.join(missing)}")
    return sum(abs(float(row["qty"]) * _finite(marks[ticker], "mark"))
               for ticker, row in positions.items())


def margin_excess(equity: float, long_market_value: float,
                  short_market_value: float) -> float:
    requirement = 0.25 * max(0.0, long_market_value) + 0.30 * abs(short_market_value)
    return _finite(equity, "equity") - requirement
