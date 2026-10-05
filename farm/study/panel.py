"""Immutable dense columnar storage for point-in-time study prices."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Iterator, Sequence
from datetime import date, datetime, time, timezone
from types import MappingProxyType
from zoneinfo import ZoneInfo

import numpy as np

FIELDS = ("open", "high", "low", "close", "volume", "auction_volume", "funding")
_CHUNK = 262_144
_ROW_DTYPE = np.dtype([("ticker", "i4"), ("session", "i4"),
                       *((field, "f8") for field in FIELDS), ("funding_at", "i8")])
_MISSING_TIME = np.iinfo(np.int64).min


def _number(value) -> float:
    return np.nan if value is None else float(value)


def _timestamp(value: datetime | None) -> int:
    if value is None:
        return _MISSING_TIME
    return int(value.astimezone(timezone.utc).timestamp() * 1_000_000_000)


class PanelBars(Sequence):
    """Lazy compatibility sequence; the panel remains the only bar storage."""

    def __init__(self, panel: "Panel"):
        self._panel = panel

    def __len__(self) -> int:
        return self._panel.bar_count

    def __iter__(self) -> Iterator:
        for session_index in range(len(self._panel.sessions)):
            for ticker_index in np.flatnonzero(self._panel.present[:, session_index]):
                yield self._panel.bar_at(int(ticker_index), session_index)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return tuple(self)[index]
        if index < 0:
            index += len(self)
        for offset, bar in enumerate(self):
            if offset == index:
                return bar
        raise IndexError(index)


class Panel:
    """Ticker × session arrays with stable O(1) coordinates and read-only storage."""

    def __init__(self, bars, declaration):
        ticker_ids, session_ids, chunks, intraday, count = {}, {}, [], [], 0
        chunk, offset = np.empty(_CHUNK, dtype=_ROW_DTYPE), 0
        for bar in bars:
            if offset == _CHUNK:
                chunks.append(chunk)
                chunk, offset = np.empty(_CHUNK, dtype=_ROW_DTYPE), 0
            ticker_id = ticker_ids.setdefault(bar.ticker, len(ticker_ids))
            session_id = session_ids.setdefault(bar.session, len(session_ids))
            chunk[offset]["ticker"], chunk[offset]["session"] = ticker_id, session_id
            for field in FIELDS:
                chunk[offset][field] = _number(getattr(bar, field))
            chunk[offset]["funding_at"] = _timestamp(bar.funding_at)
            intraday.extend((ticker_id, session_id, at, float(value))
                            for at, value in bar.intraday_closes.items())
            offset, count = offset + 1, count + 1
        if offset:
            chunks.append(chunk[:offset].copy())
        tickers, sessions = tuple(sorted(ticker_ids)), tuple(sorted(session_ids))
        ticker_remap = np.empty(len(tickers), dtype=np.int32)
        session_remap = np.empty(len(sessions), dtype=np.int32)
        for index, value in enumerate(tickers):
            ticker_remap[ticker_ids[value]] = index
        for index, value in enumerate(sessions):
            session_remap[session_ids[value]] = index
        shape = len(tickers), len(sessions)
        fields = {name: np.full(shape, np.nan, dtype=np.float64) for name in FIELDS}
        funding_at = np.full(shape, _MISSING_TIME, dtype=np.int64)
        present = np.zeros(shape, dtype=np.bool_)
        for rows in chunks:
            ti, si = ticker_remap[rows["ticker"]], session_remap[rows["session"]]
            flat = ti.astype(np.int64) * len(sessions) + si
            if np.unique(flat).size != len(rows) or np.any(present[ti, si]):
                raise ValueError("duplicate ticker/session bar")
            present[ti, si] = True
            for field in FIELDS:
                fields[field][ti, si] = rows[field]
            funding_at[ti, si] = rows["funding_at"]
        clocks = {}
        for old_ticker, old_session, at, value in intraday:
            array = clocks.setdefault(at, np.full(shape, np.nan, dtype=np.float64))
            array[ticker_remap[old_ticker], session_remap[old_session]] = value
        zone = ZoneInfo(declaration.timezone)
        open_hour, open_minute = map(int, declaration.session_open.split(":"))
        close_hour, close_minute = map(int, declaration.session_close.split(":"))
        open_at = np.asarray([_timestamp(datetime.combine(day, time(open_hour, open_minute), zone))
                              for day in sessions], dtype=np.int64)
        daily_at = np.asarray([_timestamp(datetime.combine(day, time(close_hour, close_minute), zone)
                                          + declaration.daily_bar_lag) for day in sessions],
                              dtype=np.int64)
        for array in (*fields.values(), *clocks.values(), funding_at, present, open_at, daily_at):
            array.flags.writeable = False
        self.tickers, self.sessions, self.bar_count = tickers, sessions, count
        self.ticker_index = MappingProxyType({value: i for i, value in enumerate(tickers)})
        self.session_index = MappingProxyType({value: i for i, value in enumerate(sessions)})
        self.fields, self.intraday = MappingProxyType(fields), MappingProxyType(clocks)
        self.funding_at, self.present = funding_at, present
        self.open_available_at, self.daily_available_at = open_at, daily_at
        self.session_days = np.asarray(sessions, dtype="datetime64[D]")
        self.session_days.flags.writeable = False
        self.bars = PanelBars(self)

    @staticmethod
    def _optional(value: float):
        return None if np.isnan(value) else float(value)

    def coordinates(self, ticker: str, session: date) -> tuple[int, int] | None:
        ti, si = self.ticker_index.get(ticker), self.session_index.get(session)
        return None if ti is None or si is None or not self.present[ti, si] else (ti, si)

    def value(self, ticker: str, session: date, field: str):
        coordinates = self.coordinates(ticker, session)
        if coordinates is None:
            return None
        ti, si = coordinates
        array = (self.intraday.get(field.split("@", 1)[1])
                 if field.startswith("bar_close@") else self.fields.get(field))
        if array is None:
            raise KeyError(field)
        return self._optional(array[ti, si])

    def bar_at(self, ticker_index: int, session_index: int):
        from .data import Bar
        funding_ns = self.funding_at[ticker_index, session_index]
        intraday = {at: float(values[ticker_index, session_index])
                    for at, values in self.intraday.items()
                    if not np.isnan(values[ticker_index, session_index])}
        values = [self._optional(self.fields[field][ticker_index, session_index])
                  for field in FIELDS]
        return Bar(self.tickers[ticker_index], self.sessions[session_index], *values[:5],
                   auction_volume=values[5], funding=values[6],
                   funding_at=None if funding_ns == _MISSING_TIME else datetime.fromtimestamp(
                       funding_ns / 1_000_000_000, timezone.utc), intraday_closes=intraday)

    def get(self, ticker: str, session: date):
        coordinates = self.coordinates(ticker, session)
        return None if coordinates is None else self.bar_at(*coordinates)

    def history(self, ticker: str, fields: tuple[str, ...], *, before: date,
                through: date, limit: int | None) -> list[dict]:
        ti = self.ticker_index.get(ticker)
        if ti is None:
            return []
        stop = min(bisect_left(self.sessions, before), bisect_right(self.sessions, through))
        start = 0 if limit is None else max(0, stop - limit)
        indexes = range(start, stop)
        return [{"session": self.sessions[si], **{
            field: self.value(ticker, self.sessions[si], field) for field in fields}}
            for si in indexes if self.present[ti, si]]

    def mdv60(self, ticker: str, session: date) -> float | None:
        ti = self.ticker_index.get(ticker)
        if ti is None:
            return None
        valid = ((self.session_days < np.datetime64(session))
                 & self.present[ti] & (self.fields["close"][ti] > 0)
                 & ~np.isnan(self.fields["volume"][ti]))
        indexes = np.flatnonzero(valid)[-60:]
        return (float(np.median(self.fields["close"][ti, indexes]
                                * self.fields["volume"][ti, indexes]))
                if indexes.size else None)

    def last_close(self, ticker: str, start: date, end: date) -> tuple[date, float] | None:
        ti = self.ticker_index.get(ticker)
        if ti is None:
            return None
        close = self.fields["close"][ti]
        valid = ((self.session_days >= np.datetime64(start))
                 & (self.session_days <= np.datetime64(end)) & self.present[ti]
                 & ~np.isnan(close) & (close >= 0))
        indexes = np.flatnonzero(valid)
        return None if not indexes.size else (self.sessions[indexes[-1]], float(close[indexes[-1]]))
