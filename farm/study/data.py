"""Immutable point-in-time price sources and decision-bounded views."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from engine.lib import db

from .panel import Panel
from .spec import parse_clock, validate_decision_time

DAILY_FIELDS = frozenset({"high", "low", "close", "volume", "auction_volume"})


class LookAheadError(ValueError):
    """Raised when a view asks for information outside its decision boundary."""


@dataclass(frozen=True)
class DerivedInput:
    """Study-owned records gated by their per-row availability timestamp."""

    name: str
    frame: Any = field(repr=False)
    available_at_column: str = "available_at"
    declaration: Mapping[str, Any] = field(default_factory=dict)
    records: tuple[Mapping[str, Any], ...] = field(init=False, repr=False)
    keyed_by_ticker: bool = field(init=False)
    _index: Mapping[tuple[str | None, date], Mapping[str, Any]] = field(
        init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.name or not self.available_at_column:
            raise ValueError("derived input needs a name and availability column")
        raw = (self.frame.to_dict("records") if hasattr(self.frame, "to_dict")
               else list(self.frame))
        rows, seen, keyed = [], set(), None
        for item in raw:
            row = dict(item)
            session, available = row.get("session"), row.get(self.available_at_column)
            has_ticker = "ticker" in row
            if (not isinstance(session, date) or isinstance(session, datetime)
                    or not isinstance(available, datetime) or available.tzinfo is None):
                raise ValueError("derived rows need a session date and aware availability timestamp")
            if keyed is None:
                keyed = has_ticker
            if keyed != has_ticker or (has_ticker and not row["ticker"]):
                raise ValueError("derived rows must use one session or ticker/session schema")
            key = (row.get("ticker"), session)
            if key in seen:
                raise ValueError("duplicate derived input key")
            seen.add(key)
            rows.append(MappingProxyType(row))
        try:
            declaration = json.loads(json.dumps(
                dict(self.declaration), sort_keys=True, separators=(",", ":"), allow_nan=False))
        except (TypeError, ValueError) as exc:
            raise ValueError("derived declaration must contain canonical JSON values") from exc
        object.__setattr__(self, "declaration", MappingProxyType(declaration))
        object.__setattr__(self, "records", tuple(sorted(
            rows, key=lambda row: (row["session"], str(row.get("ticker", ""))))))
        object.__setattr__(self, "keyed_by_ticker", bool(keyed))
        object.__setattr__(self, "_index", MappingProxyType({
            (row.get("ticker"), row["session"]): row for row in rows}))

    def get(self, session: date, ticker: str | None = None) -> Mapping[str, Any] | None:
        if self.keyed_by_ticker and not ticker:
            raise ValueError(f"derived input {self.name!r} is keyed by ticker")
        key = ticker if self.keyed_by_ticker else None
        return self._index.get((key, session))


@dataclass(frozen=True)
class DataDeclaration:
    source: str
    snapshot_sha256: str
    point_in_time: bool
    survivor_status: str
    timezone: str = "America/New_York"
    session_open: str = "09:30"
    session_close: str = "16:00"
    daily_bar_lag: timedelta = timedelta(0)

    def __post_init__(self) -> None:
        if not self.source or len(self.snapshot_sha256) != 64:
            raise ValueError("data declaration needs source and 64-character snapshot hash")
        int(self.snapshot_sha256, 16)
        if self.survivor_status not in {"point_in_time", "current_listings_only", "unknown"}:
            raise ValueError("invalid survivor status")
        parse_clock(self.session_open)
        parse_clock(self.session_close)
        ZoneInfo(self.timezone)
        if self.daily_bar_lag < timedelta(0):
            raise ValueError("daily bar lag cannot be negative")


@dataclass(frozen=True)
class Dividend:
    ticker: str
    ex_date: date
    cash_amount: float
    available_at: datetime | None

    def __post_init__(self) -> None:
        if not self.ticker or not isinstance(self.ex_date, date):
            raise ValueError("dividend needs a ticker and ex-date")
        if not isinstance(self.available_at, datetime) or self.available_at.tzinfo is None:
            raise ValueError("dividend needs an aware availability timestamp")
        if (isinstance(self.cash_amount, bool) or not isinstance(self.cash_amount, (int, float))
                or not math.isfinite(self.cash_amount) or self.cash_amount < 0):
            raise ValueError("dividend cash amount must be non-negative")

    def canonical(self) -> dict:
        return {"ticker": self.ticker, "ex_date": self.ex_date.isoformat(),
                "cash_amount": float(self.cash_amount),
                "available_at": self.available_at.isoformat()}  # type: ignore[union-attr]


@dataclass(frozen=True)
class Bar:
    ticker: str
    session: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    auction_volume: float | None = None
    funding: float | None = None
    funding_at: datetime | None = None
    intraday_closes: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.ticker:
            raise ValueError("bar ticker is required")
        closes = dict(self.intraday_closes)
        for at in closes:
            parse_clock(at)
        object.__setattr__(self, "intraday_closes", MappingProxyType(closes))

    def canonical(self) -> dict:
        return {
            "ticker": self.ticker, "session": self.session.isoformat(), "open": self.open,
            "high": self.high, "low": self.low, "close": self.close, "volume": self.volume,
            "auction_volume": self.auction_volume, "funding": self.funding,
            "funding_at": self.funding_at.isoformat() if self.funding_at else None,
            "intraday_closes": dict(self.intraday_closes),
        }


class PriceSource:
    """One declared, immutable set of normalized bars."""

    def __init__(self, declaration: DataDeclaration, bars: Iterable[Bar],
                 dividends: Iterable[Dividend] = ()):
        panel = Panel(bars, declaration)
        actions = tuple(sorted(dividends, key=lambda row: (row.ex_date, row.ticker)))
        if len({(row.ticker, row.ex_date) for row in actions}) != len(actions):
            raise ValueError("duplicate ticker/ex-date dividend")
        self.declaration = declaration
        self.panel = panel
        self.bars = panel.bars
        self.dividends = actions
        self._dividends = MappingProxyType({ticker: tuple(
            row for row in actions if row.ticker == ticker)
            for ticker in {row.ticker for row in actions}})

    @classmethod
    def declared(cls, *, source: str, bars: Iterable[Bar], point_in_time: bool = True,
                 survivor_status: str = "point_in_time",
                 dividends: Iterable[Dividend] = (), **kwargs) -> PriceSource:
        material, actions = tuple(bars), tuple(dividends)
        canonical_bars = [bar.canonical() for bar in sorted(
            material, key=lambda bar: (bar.session, bar.ticker))]
        snapshot = (canonical_bars if not actions else
                    {"bars": canonical_bars, "dividends": [row.canonical() for row in sorted(
                        actions, key=lambda row: (row.ex_date, row.ticker))]})
        payload = json.dumps(snapshot,
            sort_keys=True, separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        declaration = DataDeclaration(source, digest, point_in_time, survivor_status, **kwargs)
        return cls(declaration, material, actions)

    @classmethod
    def from_duckdb(cls, path: str | Path, declaration: DataDeclaration, *,
                    start: date | None = None, end: date | None = None,
                    tickers: Iterable[str] | None = None) -> PriceSource:
        clauses, params = [], []
        if start is not None:
            clauses.append("date >= ?")
            params.append(start)
        if end is not None:
            clauses.append("date <= ?")
            params.append(end)
        names = sorted(set(tickers or ()))
        if names:
            clauses.append(f"ticker IN ({','.join('?' for _ in names)})")
            params.extend(names)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        con = db.connect(Path(path), read_only=True, wait_s=0)
        try:
            rows = con.execute(
                "SELECT ticker, date, open, high, low, close, volume FROM prices"
                f"{where} ORDER BY date, ticker", params).fetchall()
        finally:
            con.close()
        return cls(declaration, (Bar(*row) for row in rows))

    def get(self, ticker: str, session: date) -> Bar | None:
        return self.panel.get(ticker, session)

    def value(self, ticker: str, session: date, field: str) -> float | None:
        return self.panel.value(ticker, session, field)

    def history(self, ticker: str, fields: tuple[str, ...], *, before: date,
                through: date, limit: int | None) -> list[dict]:
        return self.panel.history(ticker, fields, before=before, through=through, limit=limit)

    def mdv60(self, ticker: str, session: date) -> float | None:
        return self.panel.mdv60(ticker, session)

    @property
    def tickers(self) -> tuple[str, ...]:
        return self.panel.tickers

    @property
    def sessions(self) -> tuple[date, ...]:
        return self.panel.sessions


def _local_moment(session: date, clock: str, declaration: DataDeclaration) -> datetime:
    hour, minute = parse_clock(clock)
    return datetime.combine(session, time(hour, minute), ZoneInfo(declaration.timezone))


def _decision_moment(session: date, decision_time: str,
                     declaration: DataDeclaration) -> datetime:
    validate_decision_time(decision_time)
    if decision_time == "pre_open":
        return _local_moment(session, declaration.session_open, declaration) - timedelta(microseconds=1)
    if decision_time == "at_open":
        return _local_moment(session, declaration.session_open, declaration)
    if decision_time == "at_close":
        return _local_moment(session, declaration.session_close, declaration)
    return _local_moment(session, decision_time, declaration)


@dataclass(frozen=True)
class PointInTimeView:
    source: PriceSource
    session: date
    decision_time: str
    hard_max_date: date
    open_as_indication: bool = False
    close_as_indication: bool = False
    derived_inputs: tuple[DerivedInput, ...] = ()
    _decision_at: datetime = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.session > self.hard_max_date:
            raise LookAheadError("decision session exceeds the view hard maximum")
        validate_decision_time(self.decision_time)
        object.__setattr__(self, "_decision_at", _decision_moment(
            self.session, self.decision_time, self.source.declaration))

    @property
    def decision_at(self) -> datetime:
        return self._decision_at

    def value(self, ticker: str, field: str, session: date | None = None) -> Any:
        target = session or self.session
        if target > self.hard_max_date or target > self.session:
            raise LookAheadError(f"{ticker} {target} is beyond the view boundary")
        if "." in field:
            name, column = field.split(".", 1)
            return self.derived(name, column, session=target, ticker=ticker)
        coordinates = self.source.panel.coordinates(ticker, target)
        if coordinates is None:
            raise KeyError((ticker, target))
        declaration = self.source.declaration
        if field == "open":
            available = _local_moment(target, declaration.session_open, declaration)
            if (target == self.session and self.decision_time == "at_open"
                    and not self.open_as_indication):
                raise LookAheadError("official open at at_open requires open_as_indication=True")
            value = self.source.value(ticker, target, field)
        elif field in DAILY_FIELDS:
            available = (_local_moment(target, declaration.session_close, declaration)
                         + declaration.daily_bar_lag)
            value = self.source.value(ticker, target, field)
        elif field == "funding":
            bar = self.source.get(ticker, target)
            assert bar is not None
            available = bar.funding_at or (
                _local_moment(target, declaration.session_close, declaration)
                + declaration.daily_bar_lag)
            value = bar.funding
        elif field.startswith("bar_close@"):
            clock = field.split("@", 1)[1]
            available = _local_moment(target, clock, declaration)
            value = self.source.value(ticker, target, field)
        else:
            raise KeyError(field)
        if available > self.decision_at:
            raise LookAheadError(f"{ticker} {field} for {target} is not known at decision time")
        return value

    def history(self, ticker: str, fields: tuple[str, ...], *, before: date | None = None,
                limit: int | None = None) -> list[dict]:
        cutoff = before or (self.session + timedelta(days=1))
        if any("." in field for field in fields):
            sessions = [day for day in self.source.sessions
                        if day < cutoff and day <= self.session]
            if limit is not None:
                sessions = sessions[-limit:]
            return [{"session": day, **{
                field: self.value(ticker, field, day) for field in fields}}
                for day in sessions if self.source.panel.coordinates(ticker, day) is not None]
        rows = self.source.history(ticker, fields, before=cutoff, through=self.session, limit=limit)
        for row in rows:
            for column in fields:
                self.value(ticker, column, row["session"])
        return rows

    def derived(self, name: str, field: str, *, session: date | None = None,
                ticker: str | None = None) -> Any:
        target = session or self.session
        if target > self.hard_max_date or target > self.session:
            raise LookAheadError(f"derived input {name} {target} is beyond the view boundary")
        selected = next((item for item in self.derived_inputs if item.name == name), None)
        if selected is None:
            raise KeyError(name)
        row = selected.get(target, ticker)
        if row is None:
            raise KeyError((name, ticker, target))
        if row[selected.available_at_column] > self.decision_at:
            raise LookAheadError(f"derived input {name} for {target} is not known at decision time")
        if field in {"session", "ticker", selected.available_at_column}:
            raise KeyError(field)
        try:
            return row[field]
        except KeyError as exc:
            raise KeyError((name, field)) from exc

    def dividend_rows(self, ticker: str, *, after: date, through: date) -> tuple[Dividend, ...]:
        if through > self.hard_max_date or through > self.session:
            raise LookAheadError(f"dividends through {through} are beyond the view boundary")
        rows = tuple(row for row in self.source._dividends.get(ticker, ())
                     if after < row.ex_date <= through)
        if any(row.available_at > self.decision_at for row in rows):  # type: ignore[operator]
            raise LookAheadError(f"dividend for {ticker} is not known at decision time")
        return rows


@dataclass(frozen=True)
class FillPricePair:
    primary: float
    secondary: float | None


class MarketData:
    def __init__(self, primary: PriceSource, secondary: PriceSource | None = None,
                 derived_inputs: Iterable[DerivedInput] = ()):
        self.primary = primary
        self.secondary = secondary
        self.derived_inputs = tuple(derived_inputs)
        if len({item.name for item in self.derived_inputs}) != len(self.derived_inputs):
            raise ValueError("derived input names must be unique")

    def view(self, session: date, decision_time: str, hard_max_date: date, *,
             open_as_indication: bool = False, close_as_indication: bool = False,
             source: str = "primary") -> PointInTimeView:
        selected = self.primary if source == "primary" else self.secondary
        if selected is None or source not in {"primary", "secondary"}:
            raise ValueError(f"unavailable price source {source!r}")
        return PointInTimeView(selected, session, decision_time, hard_max_date,
                               open_as_indication, close_as_indication, self.derived_inputs)

    @staticmethod
    def _fill_value(source: PriceSource, ticker: str, session: date, field: str) -> float | None:
        if source.panel.coordinates(ticker, session) is None:
            return None
        if field.startswith("bar_close@"):
            return source.value(ticker, session, field)
        if field not in {"open", "close"}:
            raise ValueError(f"unsupported fill field {field!r}")
        return source.value(ticker, session, field)

    def fill_prices(self, ticker: str, session: date, field: str, *,
                    hard_max_date: date) -> FillPricePair:
        if session > hard_max_date:
            raise LookAheadError("fill session exceeds the run hard maximum")
        primary = self._fill_value(self.primary, ticker, session, field)
        if primary is None:
            raise KeyError((ticker, session, field, "primary"))
        secondary = None if self.secondary is None else self._fill_value(
            self.secondary, ticker, session, field)
        return FillPricePair(float(primary), None if secondary is None else float(secondary))
