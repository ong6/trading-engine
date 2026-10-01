"""Immutable point-in-time price sources and decision-bounded views."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

from engine.lib import db

from .spec import parse_clock, validate_decision_time

DAILY_FIELDS = frozenset({"high", "low", "close", "volume", "auction_volume"})


class LookAheadError(ValueError):
    """Raised when a view asks for information outside its decision boundary."""


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

    def __init__(self, declaration: DataDeclaration, bars: Iterable[Bar]):
        ordered = tuple(sorted(bars, key=lambda bar: (bar.session, bar.ticker)))
        index = {(bar.ticker, bar.session): bar for bar in ordered}
        if len(index) != len(ordered):
            raise ValueError("duplicate ticker/session bar")
        self.declaration = declaration
        self.bars = ordered
        self._index = MappingProxyType(index)

    @classmethod
    def declared(cls, *, source: str, bars: Iterable[Bar], point_in_time: bool = True,
                 survivor_status: str = "point_in_time", **kwargs) -> PriceSource:
        material = tuple(bars)
        payload = json.dumps([bar.canonical() for bar in sorted(
            material, key=lambda bar: (bar.session, bar.ticker))],
            sort_keys=True, separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        declaration = DataDeclaration(source, digest, point_in_time, survivor_status, **kwargs)
        return cls(declaration, material)

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
        return self._index.get((ticker, session))

    @property
    def sessions(self) -> tuple[date, ...]:
        return tuple(sorted({bar.session for bar in self.bars}))


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

    def __post_init__(self) -> None:
        if self.session > self.hard_max_date:
            raise LookAheadError("decision session exceeds the view hard maximum")
        validate_decision_time(self.decision_time)

    @property
    def decision_at(self) -> datetime:
        return _decision_moment(self.session, self.decision_time, self.source.declaration)

    def value(self, ticker: str, field: str, session: date | None = None) -> float | None:
        target = session or self.session
        if target > self.hard_max_date or target > self.session:
            raise LookAheadError(f"{ticker} {target} is beyond the view boundary")
        bar = self.source.get(ticker, target)
        if bar is None:
            raise KeyError((ticker, target))
        declaration = self.source.declaration
        if field == "open":
            available = _local_moment(target, declaration.session_open, declaration)
            if (target == self.session and self.decision_time == "at_open"
                    and not self.open_as_indication):
                raise LookAheadError("official open at at_open requires open_as_indication=True")
            value = bar.open
        elif field in DAILY_FIELDS:
            available = (_local_moment(target, declaration.session_close, declaration)
                         + declaration.daily_bar_lag)
            value = getattr(bar, field)
        elif field == "funding":
            available = bar.funding_at or (
                _local_moment(target, declaration.session_close, declaration)
                + declaration.daily_bar_lag)
            value = bar.funding
        elif field.startswith("bar_close@"):
            clock = field.split("@", 1)[1]
            available = _local_moment(target, clock, declaration)
            value = bar.intraday_closes.get(clock)
        else:
            raise KeyError(field)
        if available > self.decision_at:
            raise LookAheadError(f"{ticker} {field} for {target} is not known at decision time")
        return value

    def history(self, ticker: str, fields: tuple[str, ...], *, before: date | None = None,
                limit: int | None = None) -> list[dict]:
        cutoff = before or (self.session + timedelta(days=1))
        sessions = [day for day in self.source.sessions if day < cutoff and day <= self.session]
        if limit is not None:
            sessions = sessions[-limit:]
        return [{"session": day, **{field: self.value(ticker, field, day) for field in fields}}
                for day in sessions if self.source.get(ticker, day) is not None]


@dataclass(frozen=True)
class FillPricePair:
    primary: float
    secondary: float | None


class MarketData:
    def __init__(self, primary: PriceSource, secondary: PriceSource | None = None):
        self.primary = primary
        self.secondary = secondary

    def view(self, session: date, decision_time: str, hard_max_date: date, *,
             open_as_indication: bool = False, source: str = "primary") -> PointInTimeView:
        selected = self.primary if source == "primary" else self.secondary
        if selected is None or source not in {"primary", "secondary"}:
            raise ValueError(f"unavailable price source {source!r}")
        return PointInTimeView(selected, session, decision_time, hard_max_date, open_as_indication)

    @staticmethod
    def _fill_value(source: PriceSource, ticker: str, session: date, field: str) -> float | None:
        bar = source.get(ticker, session)
        if bar is None:
            return None
        if field.startswith("bar_close@"):
            return bar.intraday_closes.get(field.split("@", 1)[1])
        if field not in {"open", "close"}:
            raise ValueError(f"unsupported fill field {field!r}")
        return getattr(bar, field)

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
