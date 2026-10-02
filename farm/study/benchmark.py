"""Gross study comparators and the explicitly separate allocation mode."""
from __future__ import annotations

import inspect
import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

import numpy as np

from .data import DerivedInput, MarketData, PointInTimeView, PriceSource
from .universe import Universe


@dataclass(frozen=True)
class Benchmark:
    kind: str
    ticker: str | None = None
    mode: str = "gross"
    eligible: DerivedInput | Callable[[PointInTimeView, tuple[date, date]], set[str]] | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"equal_weight", "ew", "ew_eligible", "ticker", "cash"}:
            raise ValueError("unknown benchmark kind")
        if (self.kind == "ticker") != bool(self.ticker):
            raise ValueError("only a ticker benchmark takes a ticker")
        if self.mode not in {"gross", "allocation"}:
            raise ValueError("benchmark mode must be gross or allocation")
        if self.eligible is not None and self.kind != "ew_eligible":
            raise ValueError("eligible is accepted only by ew_eligible")
        if isinstance(self.eligible, DerivedInput):
            if not self.eligible.keyed_by_ticker or any(
                    "eligible" not in row for row in self.eligible.records):
                raise ValueError("eligible input must be keyed by session/ticker with a flag")
        elif self.eligible is not None and (not inspect.isfunction(self.eligible)
                                            or self.eligible.__closure__):
            raise ValueError("eligible must be an importable function without a closure")

    def as_dict(self) -> dict:
        eligible = self.eligible
        if isinstance(eligible, DerivedInput):
            identity: Any = {"derived_input": eligible.name,
                             "declaration": dict(eligible.declaration)}
        elif eligible is not None:
            identity = f"{eligible.__module__}.{eligible.__qualname__}"
        else:
            identity = None
        result = {"kind": self.kind, "ticker": self.ticker, "mode": self.mode}
        if identity is not None:
            result["eligible"] = identity
        return result


def _close(source: PriceSource, ticker: str, session: date) -> float:
    bar = source.get(ticker, session)
    if bar is None or bar.close is None or bar.close < 0:
        raise ValueError(f"benchmark close unavailable for {ticker} on {session}")
    return float(bar.close)


def eligible_names(benchmark: Benchmark, data: MarketData, universe: Universe,
                   view: PointInTimeView, window: tuple[date, date]) -> list[str]:
    if benchmark.kind != "ew_eligible" or benchmark.eligible is None:
        return universe.eligible(view, window[0])
    if isinstance(benchmark.eligible, DerivedInput):
        rows = [row for row in benchmark.eligible.records if row["session"] == view.session]
        if any(row[benchmark.eligible.available_at_column] > view.decision_at for row in rows):
            from .data import LookAheadError
            raise LookAheadError("eligible input is not known at decision time")
        names = {str(row["ticker"]) for row in rows if bool(row["eligible"])}
    else:
        result = benchmark.eligible(view, window)
        if type(result) is not set or any(not isinstance(name, str) or not name for name in result):
            raise TypeError("eligible function must return set[str]")
        names = result
    return sorted(name for name in names if universe.is_listed(name, window[0]))


def dividend_per_share(data: MarketData, ticker: str, after: date, through: date,
                       withholding: float, *, view: PointInTimeView) -> float:
    return sum(row.cash_amount for row in view.dividend_rows(
        ticker, after=after, through=through)) * (1 - withholding)


def gross_returns(benchmark: Benchmark, data: MarketData, sessions: list[date], *,
                  universe: Universe | None = None,
                  dividend_withholding: float = 0.0) -> np.ndarray:
    if sessions != sorted(set(sessions)) or len(sessions) < 2:
        raise ValueError("benchmark needs at least two sorted unique sessions")
    if benchmark.kind == "cash":
        return np.zeros(len(sessions) - 1)
    if benchmark.kind == "ticker":
        closes = [_close(data.primary, benchmark.ticker or "", day) for day in sessions]
        output = []
        for index, (previous, current) in enumerate(zip(
                sessions[:-1], sessions[1:], strict=True)):
            view = data.view(current, "at_close", current)
            dividend = dividend_per_share(data, benchmark.ticker or "", previous, current,
                                          dividend_withholding, view=view)
            output.append((closes[index + 1] + dividend) / closes[index] - 1)
        return np.asarray(output)
    if universe is None:
        raise ValueError("equal-weight benchmark needs a universe")
    output = []
    for previous, current in zip(sessions[:-1], sessions[1:], strict=True):
        view = data.view(previous, "at_close", previous)
        eligible = eligible_names(benchmark, data, universe, view, (previous, current))
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
            dividend_view = data.view(current, "at_close", current)
            dividend = dividend_per_share(data, ticker, previous, current,
                                          dividend_withholding, view=dividend_view)
            returns.append((end + dividend) / start - 1)
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
    strategy_total = float(math.prod(1 + strategy) - 1)
    benchmark_total = float(math.prod(1 + comparator) - 1)
    return Comparison(benchmark.mode, strategy_total, benchmark_total,
                      strategy_total - benchmark_total, bool(strategy_total > 0))
