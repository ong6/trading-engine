"""Native event and target-weight simulation over point-in-time study data."""
from __future__ import annotations

import math
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Mapping

import numpy as np

from .benchmark import Benchmark, dividend_per_share, eligible_names, gross_returns
from .costs import CostSelection, calculate, resolve
from .data import MarketData, PriceSource
from .spec import EventStrategy, FillPoint, Order, PortfolioStrategy, parse_clock
from .stats import TradeObservation, calendar_day_series
from .universe import Universe


def _sessions(data: MarketData, window: Iterable[date] | tuple[date, date] | object) -> tuple[date, ...]:
    available = data.primary.sessions
    if hasattr(window, "split_date") and hasattr(window, "validate_end"):
        days = [day for day in available if window.split_date < day <= window.validate_end]
    elif isinstance(window, tuple) and len(window) == 2 and all(isinstance(day, date) for day in window):
        days = [day for day in available if window[0] <= day <= window[1]]
    else:
        requested = set(window)  # type: ignore[arg-type]
        days = [day for day in available if day in requested]
    if not days:
        raise ValueError("simulation window contains no source sessions")
    return tuple(days)


def _fill_day(days: tuple[date, ...], base_index: int, fill: FillPoint) -> date | None:
    index = base_index + (fill.kind == "next_open")
    return days[index] if index < len(days) else None


def _price(source: PriceSource, ticker: str, session: date, field: str) -> float | None:
    value = source.value(ticker, session, field)
    return None if value is None else float(value)


def _mdv60(source: PriceSource, ticker: str, session: date) -> float | None:
    return source.mdv60(ticker, session)


def _ordered(orders: list[Order], keys: tuple[str, ...]) -> list[Order]:
    result = sorted(orders, key=lambda order: (
        order.ticker, order.side, order.notional, order.entry.field, order.exit.kind,
        order.priority or 0.0, tuple((order.signal or {}).items())))
    for declared in reversed(keys):
        key, reverse = declared.lstrip("-"), declared.startswith("-")
        result.sort(key=lambda order, name=key: _order_value(order, name), reverse=reverse)
    return result


def _order_value(order: Order, key: str) -> Any:
    if key == "entry":
        return order.entry.field
    if key == "signal":
        return tuple((order.signal or {}).items())
    if key.startswith("signal."):
        return (order.signal or {}).get(key.split(".", 1)[1], 0.0)
    value = getattr(order, key)
    return 0.0 if value is None else value


def _valid_entry_time(strategy: EventStrategy | PortfolioStrategy, fill: FillPoint,
                      data: MarketData) -> bool:
    if fill.kind == "next_open":
        return True
    open_hour, open_minute = parse_clock(data.primary.declaration.session_open)
    close_hour, close_minute = parse_clock(data.primary.declaration.session_close)
    open_time, close_time = open_hour * 60 + open_minute, close_hour * 60 + close_minute
    decision = {"pre_open": open_time - 1, "at_open": open_time,
                "at_close": close_time}.get(strategy.decision_time)
    if decision is None:
        hour, minute = parse_clock(strategy.decision_time)
        decision = hour * 60 + minute
    if fill.kind == "open_auction":
        fill_time, indication = open_time, strategy.open_as_indication
    elif fill.kind == "close_auction":
        fill_time, indication = close_time, strategy.close_as_indication
    else:
        hour, minute = parse_clock(fill.at or "")
        fill_time, indication = hour * 60 + minute, False
    return fill_time > decision or (fill_time == decision and indication)


@dataclass(frozen=True)
class OpenPosition:
    ticker: str
    side: str
    entry_session: date
    entry_price: float
    shares: float
    notional: float
    order: Order


@dataclass(frozen=True)
class OrderOutcome:
    session: date
    ticker: str
    reason: str

    def as_dict(self) -> dict:
        return {"session": self.session.isoformat(), "ticker": self.ticker,
                "reason": self.reason}


@dataclass(frozen=True)
class Trade:
    entry_session: date
    exit_session: date
    ticker: str
    side: str
    entry_field: str
    exit_field: str
    entry_price: float
    exit_price: float
    shares: float
    notional: float
    mdv60: float | None
    auction_volume: float | None
    costs_by_profile: Mapping[str, Mapping[str, float]]
    gross_return: float
    net_return: float
    net_returns_by_profile: Mapping[str, float]
    benchmark_return: float
    excess_return: float
    absolute_net_positive: bool
    exit_reason: str
    flags: tuple[str, ...] = ()
    priority: float | None = None
    signal: Mapping[str, float] | None = None
    gross_dividend_cash: float = 0.0
    dividend_cash: float = 0.0

    def as_dict(self) -> dict:
        result = {"entry_session": self.entry_session.isoformat(),
                "exit_session": self.exit_session.isoformat(), "ticker": self.ticker,
                "side": self.side, "entry_field": self.entry_field,
                "exit_field": self.exit_field, "entry_price": self.entry_price,
                "exit_price": self.exit_price, "shares": self.shares,
                "notional": self.notional, "mdv60": self.mdv60,
                "auction_volume": self.auction_volume,
                "costs_by_profile": {name: dict(values)
                                     for name, values in sorted(self.costs_by_profile.items())},
                "gross_return": self.gross_return, "net_return": self.net_return,
                "net_returns_by_profile": dict(sorted(self.net_returns_by_profile.items())),
                "benchmark_return": self.benchmark_return, "excess_return": self.excess_return,
                "absolute_net_positive": self.absolute_net_positive,
                "exit_reason": self.exit_reason, "flags": list(self.flags)}
        if self.priority is not None:
            result["priority"] = self.priority
        if self.signal is not None:
            result["signal"] = dict(self.signal)
        if self.gross_dividend_cash or self.dividend_cash:
            result.update(gross_dividend_cash=self.gross_dividend_cash,
                          dividend_cash=self.dividend_cash)
        return result


@dataclass(frozen=True)
class TradeLedger:
    sessions: tuple[date, ...]
    primary_cost: str
    capital: float
    open_as_indication: bool
    close_as_indication: bool
    trades: tuple[Trade, ...]
    rejected_orders: tuple[OrderOutcome, ...]
    unfilled_orders: tuple[OrderOutcome, ...]
    open_positions: tuple[OpenPosition, ...] = ()
    exit_cost_basis: str = "market_value"
    dividend_withholding: float = 0.0

    @property
    def rejected_counts(self) -> dict[str, int]:
        return dict(sorted(Counter(item.reason for item in self.rejected_orders).items()))

    @property
    def unfilled_counts(self) -> dict[str, int]:
        return dict(sorted(Counter(item.reason for item in self.unfilled_orders).items()))

    @property
    def exit_reason_counts(self) -> dict[str, int]:
        return dict(sorted(Counter(item.exit_reason for item in self.trades).items()))

    @property
    def cross_check_trades(self) -> tuple[Any, ...]:
        from .report import CrossCheckTrade
        return tuple(CrossCheckTrade(
            row.ticker, row.side, row.entry_session, row.entry_field,
            row.exit_session, row.exit_field) for row in self.trades)

    def trade_observations(self) -> tuple[TradeObservation, ...]:
        return tuple(TradeObservation(row.entry_session, row.net_return, row.notional,
                                      row.mdv60, row.auction_volume)
                     for row in self.trades)

    def calendar_returns(self) -> np.ndarray:
        pnl = {day: 0.0 for day in self.sessions}
        for row in self.trades:
            pnl[row.exit_session] += row.net_return * row.notional
        return calendar_day_series(self.sessions, pnl, capital=self.capital)

    def as_dict(self) -> dict:
        result = {"schema_version": 1, "kind": "event", "primary_cost": self.primary_cost,
                "capital": self.capital,
                "open_as_indication": self.open_as_indication,
                "close_as_indication": self.close_as_indication,
                "sessions": [day.isoformat() for day in self.sessions],
                "trades": [row.as_dict() for row in self.trades],
                "rejected_orders": [row.as_dict() for row in self.rejected_orders],
                "unfilled_orders": [row.as_dict() for row in self.unfilled_orders],
                "rejected_counts": self.rejected_counts, "unfilled_counts": self.unfilled_counts,
                "exit_reason_counts": self.exit_reason_counts,
                "open_positions": [{"ticker": row.ticker, "side": row.side,
                                    "entry_session": row.entry_session.isoformat()}
                                   for row in self.open_positions]}
        if self.exit_cost_basis != "market_value":
            result["exit_cost_basis"] = self.exit_cost_basis
        if self.dividend_withholding or any(row.dividend_cash for row in self.trades):
            result["dividend_withholding"] = self.dividend_withholding
        return result


def _benchmark_return(benchmark: Benchmark, data: MarketData, universe: Universe,
                      decision_view: Any, exit_view: Any, entry: date, exit_: date,
                      entry_field: str, exit_field: str, withholding: float) -> float:
    if benchmark.kind == "cash":
        return 0.0
    if benchmark.kind == "ticker":
        names = [benchmark.ticker]
    elif benchmark.kind == "ew_eligible" and benchmark.eligible is not None:
        names = eligible_names(benchmark, data, universe, decision_view, (entry, exit_))
    else:
        names = [ticker for ticker in data.primary.tickers if universe.is_listed(ticker, entry)]
    values = []
    for ticker in names:
        start, end = _price(data.primary, ticker or "", entry, entry_field), _price(
            data.primary, ticker or "", exit_, exit_field)
        if start is None or start <= 0:
            continue
        if end is None:
            outcome = universe.delisting_exit(ticker or "", held_on=entry, entry_price=start)
            if outcome is None:
                continue
            end = outcome.exit_price
        dividend = dividend_per_share(data, ticker or "", entry, exit_, withholding,
                                      view=exit_view)
        values.append((end + dividend) / start - 1)
    if not values:
        raise ValueError("benchmark has no exact-window prices")
    return float(np.mean(values))


def _exit(strategy: EventStrategy, data: MarketData, universe: Universe,
          days: tuple[date, ...], position: OpenPosition, entry_index: int,
          hard_max: date, day_indexes: Mapping[date, int]
          ) -> tuple[date, str, float, str, tuple[str, ...]] | None:
    rule, flags = position.order.exit, []
    if rule.kind == "same_session_close":
        target_index, fill, reason = entry_index, FillPoint.close_auction(), rule.kind
    elif rule.kind == "at_time":
        target_index, fill, reason = entry_index, rule.fill, rule.kind
    elif rule.kind == "after_n_sessions":
        target_index, fill, reason = entry_index + (rule.sessions or 0), rule.fill, rule.kind
    else:
        if rule.decision_time == "at_close" and not strategy.close_as_indication:
            raise ValueError("first_condition at close requires close_as_indication=True")
        limit = min(entry_index + (rule.sessions or 0), len(days) - 1)
        target_index, fill, reason = limit, rule.fill, "first_condition_fallback"
        first = entry_index if rule.first_check == "entry_session" else entry_index + 1
        for index in range(first, limit + 1):
            view = data.view(days[index], rule.decision_time or "at_close", hard_max,
                             open_as_indication=strategy.open_as_indication,
                             close_as_indication=strategy.close_as_indication)
            outcome = rule.predicate(view, position)  # type: ignore[misc]
            if type(outcome) is not bool:
                raise TypeError("first_condition predicate must return bool")
            if outcome:
                target_index, reason = index, "first_condition"
                fill = (FillPoint.open_auction() if rule.decision_time == "at_open" else
                        FillPoint.close_auction() if rule.decision_time == "at_close" else
                        FillPoint.bar_close(rule.decision_time or ""))
                break
    if fill is None:
        raise AssertionError("validated exit rule has no fill")
    actual = _fill_day(days, target_index, fill)
    if actual is None:
        return None
    interval = universe.listing_interval(position.ticker)
    if interval is not None and interval.listed_through is not None and interval.listed_through < actual:
        delist = universe.delisting_exit(
            position.ticker, held_on=position.entry_session, entry_price=position.entry_price)
        if delist is None:
            return None
        return (delist.session, "close", delist.exit_price,
                "delisting_fallback" if delist.used_fallback else "delisting",
                ("delisting_return",) if delist.used_fallback else ())
    field, start = fill.field, day_indexes[actual]
    value = _price(data.primary, position.ticker, actual, field)
    if value is None:
        flags.append("missing_exit_bar")
        for later in days[start + 1:]:
            interval = universe.listing_interval(position.ticker)
            if interval is not None and interval.listed_through is not None and later > interval.listed_through:
                break
            value = _price(data.primary, position.ticker, later, field)
            if value is not None:
                actual = later
                break
    if value is None:
        delist = universe.delisting_exit(
            position.ticker, held_on=position.entry_session, entry_price=position.entry_price)
        if delist is None:
            return None
        return (delist.session, "close", delist.exit_price,
                "delisting_fallback" if delist.used_fallback else "delisting",
                tuple(flags + (["delisting_return"] if delist.used_fallback else [])))
    return actual, field, value, reason, tuple(flags)


def simulate_events(strategy: EventStrategy, data: MarketData, universe: Universe,
                    window: Iterable[date] | tuple[date, date] | object,
                    costs: CostSelection, benchmark: Benchmark,
                    secondary: PriceSource | None = None) -> TradeLedger:
    """Turn event orders into deterministic fills and a documented trade ledger."""
    if secondary is not None:
        data = MarketData(data.primary, secondary, data.derived_inputs)
    days, trades, rejected, unfilled, positions = _sessions(data, window), [], [], [], []
    day_indexes, active_by_day, held_through = ({day: index for index, day in enumerate(days)},
                                                np.zeros(len(days), dtype=np.int32), {})
    hard_max = days[-1]
    profiles = (costs.primary, *costs.sensitivities)
    for decision_index, session in enumerate(days):
        view = data.view(session, strategy.decision_time, hard_max,
                         open_as_indication=strategy.open_as_indication,
                         close_as_indication=strategy.close_as_indication)
        orders = _ordered(strategy.orders(view, session), strategy.order_sort_key)
        accepted = 0
        for order in orders:
            if not universe.is_listed(order.ticker, session):
                rejected.append(OrderOutcome(session, order.ticker, "not_in_universe"))
                continue
            if not math.isfinite(order.notional) or order.notional <= 0:
                rejected.append(OrderOutcome(session, order.ticker, "non_positive_notional"))
                continue
            if not _valid_entry_time(strategy, order.entry, data):
                rejected.append(OrderOutcome(session, order.ticker, "invalid_fill_timing"))
                continue
            entry_session = _fill_day(days, decision_index, order.entry)
            if entry_session is None:
                unfilled.append(OrderOutcome(session, order.ticker, "entry_outside_window"))
                continue
            entry_index = day_indexes[entry_session]
            held = held_through.get(order.ticker, -1) >= entry_index
            if strategy.already_held == "reject" and held:
                rejected.append(OrderOutcome(session, order.ticker, "already_held"))
                continue
            entry_price = _price(data.primary, order.ticker, entry_session, order.entry.field)
            if entry_price is None or entry_price <= 0:
                unfilled.append(OrderOutcome(session, order.ticker, "missing_entry_bar"))
                continue
            if accepted >= (strategy.max_new_per_session or 0):
                rejected.append(OrderOutcome(session, order.ticker, "max_new_per_session"))
                continue
            active = int(active_by_day[entry_index])
            if active >= strategy.max_concurrent:
                rejected.append(OrderOutcome(session, order.ticker, "max_concurrent"))
                continue
            position = OpenPosition(order.ticker, order.side, entry_session, entry_price,
                                    order.notional / entry_price, order.notional, order)
            result = _exit(strategy, data, universe, days, position, entry_index, hard_max,
                           day_indexes)
            if result is None:
                positions.append(position)
                unfilled.append(OrderOutcome(session, order.ticker, "missing_exit_bar"))
                active_by_day[entry_index:] += 1
                held_through[order.ticker] = len(days)
                accepted += 1
                continue
            exit_session, exit_field, exit_price, exit_reason, flags = result
            exit_index = day_indexes.get(exit_session, bisect_right(days, exit_session) - 1)
            active_by_day[entry_index:exit_index + 1] += 1
            held_through[order.ticker] = max(held_through.get(order.ticker, -1), exit_index)
            direction = 1 if order.side == "long" else -1
            exit_decision = ({"open": "at_open", "close": "at_close"}[exit_field]
                             if exit_field in {"open", "close"}
                             else exit_field.split("@", 1)[1])
            dividend_view = data.view(exit_session, exit_decision, hard_max,
                                      open_as_indication=True, close_as_indication=True)
            gross_dividend = direction * position.shares * dividend_per_share(
                data, order.ticker, entry_session, exit_session, 0.0, view=dividend_view)
            dividend = gross_dividend * (1 - strategy.dividend_withholding)
            gross = direction * (exit_price / entry_price - 1) + dividend / order.notional
            mdv = _mdv60(data.primary, order.ticker, entry_session)
            profile_costs, profile_returns = {}, {}
            for profile in profiles:
                entry_side, exit_side = (("buy", "sell") if order.side == "long"
                                         else ("sell", "buy"))
                entry_cost = calculate(profile, side=entry_side, notional=order.notional,
                                       fill_price=entry_price, mdv60=mdv).total
                exit_value = (order.notional if strategy.exit_cost_basis == "entry_notional"
                              else position.shares * exit_price)
                exit_cost = (calculate(profile, side=exit_side, notional=exit_value,
                                       fill_price=exit_price, mdv60=mdv).total
                             if exit_value > 0 else 0.0)
                funding = 0.0
                if resolve(profile).funding_from_data:
                    held = [day for day in days if entry_session <= day <= exit_session]
                    funding = order.notional * direction * sum(
                        data.primary.value(order.ticker, day, "funding") or 0.0 for day in held)
                total = entry_cost + exit_cost + funding
                profile_costs[profile] = {"entry": entry_cost, "exit": exit_cost,
                                          "funding": funding, "total": total}
                profile_returns[profile] = gross - total / order.notional
            net = profile_returns[costs.primary]
            bench = _benchmark_return(benchmark, data, universe, view, dividend_view, entry_session,
                                      exit_session, order.entry.field, exit_field,
                                      strategy.dividend_withholding)
            trades.append(Trade(entry_session, exit_session, order.ticker, order.side,
                                order.entry.field, exit_field, entry_price, exit_price,
                                position.shares, order.notional, mdv,
                                data.primary.value(order.ticker, entry_session, "auction_volume"),
                                profile_costs, gross, net,
                                profile_returns, bench, net - bench, net > 0, exit_reason, flags,
                                order.priority, order.signal, gross_dividend, dividend))
            accepted += 1
    trades.sort(key=lambda row: (row.entry_session, row.ticker, row.side, row.exit_session))
    return TradeLedger(days, costs.primary,
                       strategy.max_concurrent_slots * strategy.slot_notional,
                       strategy.open_as_indication, strategy.close_as_indication,
                       tuple(trades), tuple(rejected), tuple(unfilled), tuple(positions),
                       strategy.exit_cost_basis, strategy.dividend_withholding)


@dataclass(frozen=True)
class PortfolioDay:
    session: date
    net_return: float
    benchmark_return: float
    nav: float
    gross_exposure: float
    turnover: float
    costs_by_profile: Mapping[str, float]
    returns_by_profile: Mapping[str, float]
    flags: tuple[str, ...] = ()
    dividend_cash: float = 0.0
    gross_dividend_cash: float = 0.0

    def as_dict(self) -> dict:
        result = {"session": self.session.isoformat(), "net_return": self.net_return,
                "benchmark_return": self.benchmark_return, "nav": self.nav,
                "gross_exposure": self.gross_exposure, "turnover": self.turnover,
                "costs_by_profile": dict(sorted(self.costs_by_profile.items())),
                "returns_by_profile": dict(sorted(self.returns_by_profile.items())),
                "flags": list(self.flags)}
        if self.dividend_cash:
            result.update(dividend_cash=self.dividend_cash,
                          gross_dividend_cash=self.gross_dividend_cash)
        return result


@dataclass(frozen=True)
class PortfolioLedger:
    sessions: tuple[date, ...]
    primary_cost: str
    initial_capital: float
    open_as_indication: bool
    close_as_indication: bool
    days: tuple[PortfolioDay, ...]
    dividend_withholding: float = 0.0

    @property
    def returns(self) -> np.ndarray:
        return np.asarray([row.net_return for row in self.days])

    @property
    def missing_bar_count(self) -> int:
        return sum("missing_bar" in row.flags for row in self.days)

    def as_dict(self) -> dict:
        result = {"schema_version": 1, "kind": "portfolio", "primary_cost": self.primary_cost,
                "initial_capital": self.initial_capital,
                "open_as_indication": self.open_as_indication,
                "close_as_indication": self.close_as_indication,
                "sessions": [day.isoformat() for day in self.sessions],
                "days": [row.as_dict() for row in self.days],
                "missing_bar_count": self.missing_bar_count}
        if self.dividend_withholding or any(row.dividend_cash for row in self.days):
            result["dividend_withholding"] = self.dividend_withholding
        return result


def _rebalance_day(strategy: PortfolioStrategy, days: tuple[date, ...], index: int) -> bool:
    schedule, day = strategy.rebalance_schedule, days[index]
    if not isinstance(schedule, str):
        return day in schedule
    if schedule == "daily":
        return True
    previous = days[index - 1] if index else None
    return (previous is None or (schedule == "weekly" and previous.isocalendar()[:2]
                                 != day.isocalendar()[:2])
            or (schedule == "monthly" and (previous.year, previous.month) != (day.year, day.month)))


def simulate_portfolio(strategy: PortfolioStrategy, data: MarketData, universe: Universe,
                       window: Iterable[date] | tuple[date, date] | object,
                       costs: CostSelection, benchmark: Benchmark) -> PortfolioLedger:
    """Rebalance target weights, charge actual turnover, and mark every session."""
    if not _valid_entry_time(strategy, strategy.fill, data):
        raise ValueError("portfolio fill must follow its decision time")
    days, profiles = _sessions(data, window), (costs.primary, *costs.sensitivities)
    cash, holdings, marks = strategy.initial_capital, {}, {}
    pending: dict[date, tuple[Mapping[str, float], FillPoint]] = {}
    rows, previous_nav = [], strategy.initial_capital
    benchmark_values = (np.concatenate(([0.0], gross_returns(
        benchmark, data, list(days), universe=universe,
        dividend_withholding=strategy.dividend_withholding)))
        if len(days) > 1 else np.asarray([0.0]))

    def apply_target(target: Mapping[str, float], fill: FillPoint, session: date,
                     day_costs: dict[str, float], flags: list[str]) -> float:
        nonlocal cash
        names = sorted(set(holdings) | set(target))
        prices = {name: _price(data.primary, name, session, fill.field) for name in names}
        equity = cash + sum(quantity * (prices[name] if prices[name] is not None else marks.get(name, 0))
                            for name, quantity in holdings.items())
        turnover = 0.0
        for name in names:
            price = prices[name]
            if price is None or price <= 0:
                flags.append("missing_bar")
                continue
            desired = target.get(name, 0.0) * equity / price
            delta = desired - holdings.get(name, 0.0)
            if math.isclose(delta, 0.0, abs_tol=1e-15):
                continue
            notional, side = abs(delta) * price, "buy" if delta > 0 else "sell"
            mdv = _mdv60(data.primary, name, session)
            for profile in profiles:
                day_costs[profile] += calculate(
                    profile, side=side, notional=notional, fill_price=price, mdv60=mdv).total
            cash -= delta * price
            holdings[name], marks[name], turnover = desired, price, turnover + notional
        return turnover

    # apply_target updates cash for trades; deduct costs once per day outside it.
    for index, session in enumerate(days):
        flags, day_costs, turnover = [], {profile: 0.0 for profile in profiles}, 0.0
        previous = days[index - 1] if index else session
        dividend_view = data.view(session, "at_close", session)
        gross_dividend_cash = sum(quantity * dividend_per_share(
            data, name, previous, session, 0.0,
            view=dividend_view) for name, quantity in holdings.items())
        dividend_cash = gross_dividend_cash * (1 - strategy.dividend_withholding)
        cash += dividend_cash
        if session in pending:
            target, fill = pending.pop(session)
            turnover += apply_target(target, fill, session, day_costs, flags)
        if _rebalance_day(strategy, days, index):
            view = data.view(session, strategy.decision_time, days[-1],
                             open_as_indication=strategy.open_as_indication,
                             close_as_indication=strategy.close_as_indication)
            target = strategy.target_weights(view, session)
            if any(not universe.is_listed(name, session) for name in target):
                raise ValueError("portfolio target contains a name outside the point-in-time universe")
            fill_session = _fill_day(days, index, strategy.fill)
            if fill_session is not None:
                if fill_session == session:
                    turnover += apply_target(target, strategy.fill, session, day_costs, flags)
                else:
                    pending[fill_session] = (target, strategy.fill)
        if day_costs[costs.primary]:
            cash -= day_costs[costs.primary]
        for name, quantity in holdings.items():
            bar = data.primary.get(name, session)
            if bar is None or bar.close is None:
                flags.append("missing_bar")
                continue
            marks[name] = float(bar.close)
            if resolve(costs.primary).funding_from_data:
                if bar.funding is None:
                    flags.append("missing_funding")
                else:
                    funding = quantity * marks[name] * bar.funding
                    cash -= funding
                    day_costs[costs.primary] += funding
            for profile in profiles:
                if profile != costs.primary and resolve(profile).funding_from_data and bar.funding is not None:
                    day_costs[profile] += quantity * marks[name] * bar.funding
        nav = cash + sum(quantity * marks.get(name, 0.0) for name, quantity in holdings.items())
        gross_exposure = sum(abs(quantity * marks.get(name, 0.0))
                             for name, quantity in holdings.items())
        base_return = nav / previous_nav - 1
        returns = {profile: base_return - (day_costs[profile] - day_costs[costs.primary])
                   / previous_nav for profile in profiles}
        rows.append(PortfolioDay(session, base_return, float(benchmark_values[index]), nav,
                                 gross_exposure, turnover, day_costs, returns,
                                 tuple(sorted(set(flags))), dividend_cash, gross_dividend_cash))
        previous_nav = nav
    return PortfolioLedger(days, costs.primary, strategy.initial_capital,
                           strategy.open_as_indication, strategy.close_as_indication, tuple(rows),
                           strategy.dividend_withholding)
