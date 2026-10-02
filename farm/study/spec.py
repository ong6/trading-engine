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
    predicate: Callable[[Any, Any], bool] | None = None
    decision_time: str | None = None
    first_check: str = "next_session"

    def __post_init__(self) -> None:
        if self.kind == "same_session_close":
            if (any(value is not None for value in (
                    self.sessions, self.fill, self.predicate, self.decision_time))
                    or self.first_check != "next_session"):
                raise ValueError("same_session_close takes no arguments")
        elif self.kind == "after_n_sessions":
            if (not isinstance(self.sessions, int) or self.sessions < 1 or self.fill is None
                    or self.predicate is not None or self.decision_time is not None
                    or self.first_check != "next_session"):
                raise ValueError("after_n_sessions needs n >= 1 and a fill point")
        elif self.kind == "at_time":
            if (self.sessions is not None or self.fill is None or self.fill.kind != "bar_close"
                    or self.predicate is not None or self.decision_time is not None
                    or self.first_check != "next_session"):
                raise ValueError("at_time needs an intraday bar close")
        elif self.kind == "first_condition":
            if (not isinstance(self.sessions, int) or self.sessions < 1 or self.fill is None
                    or self.predicate is None or self.decision_time is None):
                raise ValueError("first_condition needs a predicate, max_sessions and fallback")
            _pure_function(self.predicate)
            validate_decision_time(self.decision_time)
            if self.first_check not in {"next_session", "entry_session"}:
                raise ValueError("first_check must be next_session or entry_session")
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

    @classmethod
    def first_condition(cls, predicate: Callable[[Any, Any], bool], max_sessions: int, *,
                        at: str = "close", fallback: str = "close",
                        first_check: str = "next_session") -> ExitRule:
        decision = {"open": "at_open", "close": "at_close"}.get(at, at)
        fill = (FillPoint.open_auction() if fallback == "open" else
                FillPoint.close_auction() if fallback == "close" else
                FillPoint.bar_close(fallback))
        return cls("first_condition", max_sessions, fill, predicate, decision, first_check)


@dataclass(frozen=True)
class Order:
    ticker: str
    side: str
    entry: FillPoint
    exit: ExitRule
    notional: float
    priority: float | None = None
    signal: Mapping[str, float] | None = None

    def __post_init__(self) -> None:
        if not self.ticker or self.side not in {"long", "short"}:
            raise ValueError("order needs a ticker and side long or short")
        if not math.isfinite(self.notional) or self.notional <= 0:
            raise ValueError("order notional must be positive and finite")
        if self.priority is not None:
            if (isinstance(self.priority, bool)
                    or not isinstance(self.priority, (int, float))
                    or not math.isfinite(self.priority)):
                raise ValueError("order priority must be finite")
            object.__setattr__(self, "priority", float(self.priority))
        if self.signal is not None:
            if not isinstance(self.signal, Mapping):
                raise ValueError("order signal must be a mapping")
            values = dict(self.signal)
            if any(not isinstance(key, str) or not key or isinstance(value, bool)
                   or not isinstance(value, (int, float)) or not math.isfinite(value)
                   for key, value in values.items()):
                raise ValueError("order signal must map names to finite numbers")
            object.__setattr__(self, "signal", MappingProxyType(
                {key: float(values[key]) for key in sorted(values)}))
        if self.exit.kind == "first_condition" and self.exit.first_check == "entry_session":
            decision = {"at_open": 570, "at_close": 960}.get(self.exit.decision_time)
            if decision is None:
                decision = sum(value * scale for value, scale in zip(
                    parse_clock(self.exit.decision_time or ""), (60, 1), strict=True))
            entry = ({"open_auction": 570, "next_open": 570, "close_auction": 960}.get(
                self.entry.kind) if self.entry.kind != "bar_close" else sum(
                    value * scale for value, scale in zip(
                        parse_clock(self.entry.at or ""), (60, 1), strict=True)))
            if entry is None or entry >= decision:
                raise ValueError("entry fill must precede the exit decision for entry_session")


@dataclass(frozen=True)
class EventStrategy:
    name: str
    decision_time: str
    order_function: Callable[[Any, date], list[Order]]
    max_concurrent_slots: int
    slot_notional: float
    parameters: Mapping[str, Any] = field(default_factory=dict)
    max_new_per_session: int | None = None
    order_sort_key: tuple[str, ...] = ("ticker", "side")
    open_as_indication: bool = False
    close_as_indication: bool = False
    exit_cost_basis: str = "market_value"
    already_held: str = "reject"
    dividend_withholding: float = 0.0

    def __post_init__(self) -> None:
        validate_decision_time(self.decision_time)
        _pure_function(self.order_function)
        if self.max_concurrent_slots < 1 or self.slot_notional <= 0:
            raise ValueError("event capital needs positive slots and slot notional")
        if self.max_new_per_session is None:
            object.__setattr__(self, "max_new_per_session", self.max_concurrent_slots)
        if self.max_new_per_session < 1:
            raise ValueError("max_new_per_session must be positive")
        keys = tuple(self.order_sort_key)
        allowed = {"ticker", "side", "notional", "entry", "priority", "signal"}
        if (not keys or "ticker" not in {key.lstrip("-") for key in keys}
                or any(key.lstrip("-") not in allowed
                       and not key.lstrip("-").startswith("signal.") for key in keys)):
            raise ValueError("order_sort_key must be declared fields including ticker")
        if self.exit_cost_basis not in {"market_value", "entry_notional"}:
            raise ValueError("exit_cost_basis must be market_value or entry_notional")
        if self.already_held not in {"reject", "allow"}:
            raise ValueError("already_held must be reject or allow")
        if not 0 <= self.dividend_withholding <= 1:
            raise ValueError("dividend_withholding must be between zero and one")
        object.__setattr__(self, "order_sort_key", keys)
        object.__setattr__(self, "parameters", _parameters(self.parameters))

    @property
    def max_concurrent(self) -> int:
        return self.max_concurrent_slots

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
    initial_capital: float = 100_000.0
    open_as_indication: bool = False
    close_as_indication: bool = False
    dividend_withholding: float = 0.0

    def __post_init__(self) -> None:
        validate_decision_time(self.decision_time)
        _pure_function(self.weight_function)
        if not (self.rebalance_schedule in {"daily", "weekly", "monthly"}
                if isinstance(self.rebalance_schedule, str)
                else all(isinstance(day, date) for day in self.rebalance_schedule)):
            raise ValueError("invalid rebalance schedule")
        if not math.isfinite(self.initial_capital) or self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive and finite")
        if not 0 <= self.dividend_withholding <= 1:
            raise ValueError("dividend_withholding must be between zero and one")
        object.__setattr__(self, "parameters", _parameters(self.parameters))

    def target_weights(self, view: Any, rebalance_session: date) -> dict[str, float]:
        result = dict(self.weight_function(view, rebalance_session))
        if any(not ticker or not math.isfinite(weight) for ticker, weight in result.items()):
            raise ValueError("target weights must have tickers and finite weights")
        return result
