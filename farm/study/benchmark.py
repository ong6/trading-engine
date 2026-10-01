"""Gross study comparators and the explicitly separate allocation mode."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import numpy as np

from .data import MarketData, PriceSource
from .universe import Universe


@dataclass(frozen=True)
class Benchmark:
    kind: str
    ticker: str | None = None
    mode: str = "gross"

    def __post_init__(self) -> None:
        if self.kind not in {"equal_weight", "ticker", "cash"}:
            raise ValueError("unknown benchmark kind")
        if (self.kind == "ticker") != bool(self.ticker):
            raise ValueError("only a ticker benchmark takes a ticker")
        if self.mode not in {"gross", "allocation"}:
            raise ValueError("benchmark mode must be gross or allocation")


def _close(source: PriceSource, ticker: str, session: date) -> float:
    bar = source.get(ticker, session)
    if bar is None or bar.close is None or bar.close < 0:
        raise ValueError(f"benchmark close unavailable for {ticker} on {session}")
    return float(bar.close)


def gross_returns(benchmark: Benchmark, data: MarketData, sessions: list[date], *,
                  universe: Universe | None = None) -> np.ndarray:
    if sessions != sorted(set(sessions)) or len(sessions) < 2:
        raise ValueError("benchmark needs at least two sorted unique sessions")
    if benchmark.kind == "cash":
        return np.zeros(len(sessions) - 1)
    if benchmark.kind == "ticker":
        closes = [_close(data.primary, benchmark.ticker or "", day) for day in sessions]
        return np.asarray(closes[1:]) / np.asarray(closes[:-1]) - 1
    if universe is None:
        raise ValueError("equal-weight benchmark needs a universe")
    output = []
    for previous, current in zip(sessions[:-1], sessions[1:], strict=True):
        view = data.view(previous, "at_close", previous)
        eligible = universe.eligible(view, previous)
        if not eligible:
            raise ValueError(f"equal-weight benchmark is empty on {previous}")
        returns = []
        for ticker in eligible:
            start = _close(data.primary, ticker, previous)
            bar = data.primary.get(ticker, current)
            if bar is not None and bar.close is not None and bar.close >= 0:
                end = float(bar.close)
            else:
                outcome = universe.delisting_exit(
                    ticker, held_on=previous, entry_price=start)
                if outcome is None:
                    raise ValueError(f"unresolved benchmark price for {ticker} on {current}")
                end = outcome.exit_price
            returns.append(end / start - 1)
        output.append(float(np.mean(returns)))
    return np.asarray(output)


@dataclass(frozen=True)
class Comparison:
    mode: str
    strategy_net_return: float
    benchmark_return: float
    excess_return: float
    absolute_net_positive: bool


def compare(strategy_net: np.ndarray, benchmark_gross: np.ndarray, benchmark: Benchmark, *,
            allocation_cost_returns: np.ndarray | None = None) -> Comparison:
    strategy, comparator = map(lambda values: np.asarray(values, dtype=float),
                               (strategy_net, benchmark_gross))
    if strategy.ndim != 1 or strategy.shape != comparator.shape or not np.all(
            np.isfinite(strategy)) or not np.all(np.isfinite(comparator)):
        raise ValueError("strategy and benchmark series must be finite and aligned")
    if benchmark.mode == "gross" and allocation_cost_returns is not None:
        raise ValueError("gross benchmark cannot pay costs")
    if benchmark.mode == "allocation":
        costs = np.asarray(allocation_cost_returns, dtype=float)
        if costs.shape != comparator.shape or np.any(costs < 0) or not np.all(np.isfinite(costs)):
            raise ValueError("allocation mode needs aligned non-negative comparator costs")
        comparator = comparator - costs
    strategy_total = math.prod(1 + strategy) - 1
    benchmark_total = math.prod(1 + comparator) - 1
    return Comparison(benchmark.mode, strategy_total, benchmark_total,
                      strategy_total - benchmark_total, strategy_total > 0)
