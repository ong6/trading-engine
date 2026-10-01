"""Declarative study strategies and their validated order/fill vocabulary."""
from __future__ import annotations

import inspect
import json
import math
from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType
from typing import Any, Callable, Mapping

_DECISIONS = frozenset({"pre_open", "at_open", "at_close"})
_FILL_KINDS = frozenset({"open_auction", "close_auction", "next_open", "bar_close"})


def parse_clock(value: str) -> tuple[int, int]:
    """Parse an exact 24-hour HH:MM value."""
    parts = value.split(":")
    if len(parts) != 2 or not all(part.isdigit() and len(part) == 2 for part in parts):
        raise ValueError(f"invalid time {value!r}; expected HH:MM")
    hour, minute = map(int, parts)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError(f"invalid time {value!r}; expected HH:MM")
    return hour, minute


def validate_decision_time(value: str) -> str:
    if value not in _DECISIONS:
        parse_clock(value)
    return value


def _parameters(value: Mapping[str, Any]) -> Mapping[str, Any]:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("parameters must be canonical JSON values") from exc
    parsed = json.loads(encoded)
    if not isinstance(parsed, dict):
        raise ValueError("parameters must be a mapping")
    return MappingProxyType(parsed)


def _pure_function(fn: Callable[..., Any]) -> None:
    if not inspect.isfunction(fn) or fn.__closure__:
        raise ValueError("strategy callback must be an importable function without a closure")


@dataclass(frozen=True)
class FillPoint:
    kind: str
    at: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in _FILL_KINDS:
            raise ValueError(f"unknown fill point {self.kind!r}")
        if self.kind == "bar_close":
            if self.at is None:
                raise ValueError("bar_close needs HH:MM")
            parse_clock(self.at)
        elif self.at is not None:
            raise ValueError(f"{self.kind} does not accept a time")

    @classmethod
    def open_auction(cls) -> FillPoint:
        return cls("open_auction")

    @classmethod
    def close_auction(cls) -> FillPoint:
        return cls("close_auction")

    @classmethod
    def next_open(cls) -> FillPoint:
        return cls("next_open")

    @classmethod
    def bar_close(cls, at: str) -> FillPoint:
        return cls("bar_close", at)

    @property
    def field(self) -> str:
        return f"bar_close@{self.at}" if self.kind == "bar_close" else {
            "open_auction": "open", "next_open": "open", "close_auction": "close"
        }[self.kind]


@dataclass(frozen=True)
class ExitRule:
    kind: str
    sessions: int | None = None
    fill: FillPoint | None = None

    def __post_init__(self) -> None:
        if self.kind == "same_session_close":
            if self.sessions is not None or self.fill is not None:
                raise ValueError("same_session_close takes no arguments")
        elif self.kind == "after_n_sessions":
            if not isinstance(self.sessions, int) or self.sessions < 1 or self.fill is None:
                raise ValueError("after_n_sessions needs n >= 1 and a fill point")
        elif self.kind == "at_time":
            if self.sessions is not None or self.fill is None or self.fill.kind != "bar_close":
                raise ValueError("at_time needs an intraday bar close")
        else:
            raise ValueError(f"unknown exit rule {self.kind!r}")

    @classmethod
    def same_session_close(cls) -> ExitRule:
        return cls("same_session_close")

    @classmethod
    def after_n_sessions(cls, n: int, *, at: FillPoint) -> ExitRule:
        return cls("after_n_sessions", n, at)

    @classmethod
    def at_time(cls, at: str) -> ExitRule:
        return cls("at_time", fill=FillPoint.bar_close(at))


@dataclass(frozen=True)
class Order:
    ticker: str
    side: str
    entry: FillPoint
    exit: ExitRule
    notional: float

    def __post_init__(self) -> None:
        if not self.ticker or self.side not in {"long", "short"}:
            raise ValueError("order needs a ticker and side long or short")
        if not math.isfinite(self.notional) or self.notional <= 0:
            raise ValueError("order notional must be positive and finite")


@dataclass(frozen=True)
class EventStrategy:
    name: str
    decision_time: str
    order_function: Callable[[Any, date], list[Order]]
    max_concurrent_slots: int
    slot_notional: float
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_decision_time(self.decision_time)
        _pure_function(self.order_function)
        if self.max_concurrent_slots < 1 or self.slot_notional <= 0:
            raise ValueError("event capital needs positive slots and slot notional")
        object.__setattr__(self, "parameters", _parameters(self.parameters))

    def orders(self, view: Any, session: date) -> list[Order]:
        result = self.order_function(view, session)
        if not isinstance(result, list) or not all(isinstance(item, Order) for item in result):
            raise TypeError("orders() must return list[Order]")
        return result


@dataclass(frozen=True)
class PortfolioStrategy:
    name: str
    decision_time: str
    weight_function: Callable[[Any, date], Mapping[str, float]]
    rebalance_schedule: str | tuple[date, ...]
    fill: FillPoint
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_decision_time(self.decision_time)
        _pure_function(self.weight_function)
        if not (self.rebalance_schedule in {"daily", "weekly", "monthly"}
                if isinstance(self.rebalance_schedule, str)
                else all(isinstance(day, date) for day in self.rebalance_schedule)):
            raise ValueError("invalid rebalance schedule")
        object.__setattr__(self, "parameters", _parameters(self.parameters))

    def target_weights(self, view: Any, rebalance_session: date) -> dict[str, float]:
        result = dict(self.weight_function(view, rebalance_session))
        if any(not ticker or not math.isfinite(weight) for ticker, weight in result.items()):
            raise ValueError("target weights must have tickers and finite weights")
        return result
