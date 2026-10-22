"""Columnar builders for `farm.study` price sources, without per-bar objects.

`PriceSource.from_duckdb` materializes one `Bar` per row and writes it into the
panel one structured-array element at a time: about 126 seconds for a
3,000-ticker, 15-year panel. These builders read the same columns as numpy
arrays and scatter them into the same dense panel in a few vectorized passes.

The result is the same object graph `PriceSource(declaration, bars)` builds:
identical tickers, sessions, field arrays byte for byte, presence mask,
availability clocks, read-only flags and duplicate/empty-ticker errors
(`tests/test_study_columnar.py`, `tools/sim_bench.py --check`). The P18 core
files are left untouched because live research pins them; this module only
assembles their public `Panel`/`PriceSource` types.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, time
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from engine.lib import db
from farm.study.data import DataDeclaration, PriceSource, prices_query
from farm.study.panel import _MISSING_TIME, FIELDS, Panel, PanelBars, _timestamp

BAR_COLUMNS = ("open", "high", "low", "close", "volume")


def _float_column(values) -> np.ndarray:
    """NULL -> NaN, everything else `float(value)`, as `Panel._number` does."""
    if isinstance(values, np.ma.MaskedArray):
        mask = np.ma.getmaskarray(values)
        data = np.asarray(values.data)
        if data.dtype == object:
            data = np.where(mask, 0.0, data)
        out = data.astype(np.float64)
        out[mask] = np.nan
        return out
    array = np.asarray(values)
    if array.dtype == object:
        return np.asarray([np.nan if value is None else float(value) for value in array],
                          dtype=np.float64)
    return array.astype(np.float64)


def _session_days(values) -> np.ndarray:
    array = np.asarray(values)
    if np.issubdtype(array.dtype, np.datetime64):
        days = array.astype("datetime64[D]")
        if np.any(days.astype(array.dtype) != array):
            raise ValueError("session values must be whole dates")
        return days
    if any(type(value) is not date for value in array):
        raise ValueError("sessions must be dates")
    return np.asarray(list(array), dtype="datetime64[D]")


def _sorted_codes(values: np.ndarray) -> tuple[np.ndarray, tuple]:
    """Codes into the sorted distinct values; hashing first keeps it O(n)."""
    codes, uniques = pd.factorize(values, sort=False)
    distinct = list(uniques)
    order = sorted(range(len(distinct)), key=distinct.__getitem__)
    remap = np.empty(len(distinct), dtype=np.int64)
    remap[order] = np.arange(len(distinct))
    sorted_codes = np.where(codes < 0, -1, remap[np.maximum(codes, 0)]) if len(distinct) else codes
    return sorted_codes, tuple(distinct[index] for index in order)


def panel_from_columns(declaration: DataDeclaration, tickers, sessions,
                       columns: Mapping[str, object]) -> Panel:
    """Build the dense panel `Panel(bars, declaration)` would build.

    `columns` holds any of `FIELDS`; absent fields are all-missing, exactly as
    `Bar` defaults leave them. Rows may arrive in any order.
    """
    if isinstance(tickers, np.ma.MaskedArray) and np.ma.getmaskarray(tickers).any():
        raise ValueError("bar ticker is required")
    unknown = set(columns) - set(FIELDS)
    if unknown:
        raise ValueError(f"unknown panel columns: {sorted(unknown)}")
    ti, ticker_tuple = _sorted_codes(np.asarray(tickers, dtype=object))
    if any(not name for name in ticker_tuple) or (len(ti) and ti.min() < 0):
        raise ValueError("bar ticker is required")
    si, session_days = _sorted_codes(_session_days(sessions).view(np.int64))
    if len(si) != len(ti):
        raise ValueError("ticker and session columns differ in length")
    session_tuple = tuple(np.asarray(session_days, dtype=np.int64).view("datetime64[D]")
                          .astype(object))
    if any(type(value) is not date for value in session_tuple):
        raise ValueError("sessions must be dates")
    shape = len(ticker_tuple), len(session_tuple)
    present = np.zeros(shape, dtype=np.bool_)
    present[ti, si] = True
    if int(present.sum()) != len(ti):
        raise ValueError("duplicate ticker/session bar")
    fields = {}
    for name in FIELDS:
        array = np.full(shape, np.nan, dtype=np.float64)
        if name in columns:
            values = _float_column(columns[name])
            if len(values) != len(ti):
                raise ValueError(f"column {name} differs in length")
            array[ti, si] = values
        fields[name] = array
    funding_at = np.full(shape, _MISSING_TIME, dtype=np.int64)
    zone = ZoneInfo(declaration.timezone)
    open_hour, open_minute = map(int, declaration.session_open.split(":"))
    close_hour, close_minute = map(int, declaration.session_close.split(":"))
    open_at = np.asarray([_timestamp(datetime.combine(day, time(open_hour, open_minute), zone))
                          for day in session_tuple], dtype=np.int64)
    daily_at = np.asarray([_timestamp(datetime.combine(day, time(close_hour, close_minute), zone)
                                      + declaration.daily_bar_lag) for day in session_tuple],
                          dtype=np.int64)
    for array in (*fields.values(), funding_at, present, open_at, daily_at):
        array.flags.writeable = False
    panel = Panel.__new__(Panel)
    panel.tickers, panel.sessions, panel.bar_count = ticker_tuple, session_tuple, len(ti)
    panel.ticker_index = MappingProxyType({value: i for i, value in enumerate(ticker_tuple)})
    panel.session_index = MappingProxyType({value: i for i, value in enumerate(session_tuple)})
    panel.fields, panel.intraday = MappingProxyType(fields), MappingProxyType({})
    panel.funding_at, panel.present = funding_at, present
    panel.open_available_at, panel.daily_available_at = open_at, daily_at
    panel.session_days = np.asarray(session_tuple, dtype="datetime64[D]")
    panel.session_days.flags.writeable = False
    panel.bars = PanelBars(panel)
    return panel


def price_source_from_columns(declaration: DataDeclaration, tickers, sessions,
                              columns: Mapping[str, object]) -> PriceSource:
    """A dividend-free `PriceSource` over columnar bars."""
    panel = panel_from_columns(declaration, tickers, sessions, columns)
    source = PriceSource.__new__(PriceSource)
    source.declaration, source.panel, source.bars = declaration, panel, panel.bars
    source.dividends, source._dividends = (), MappingProxyType({})
    return source


def price_source_from_duckdb(path: str | Path, declaration: DataDeclaration, *,
                             start: date | None = None, end: date | None = None,
                             tickers: Iterable[str] | None = None) -> PriceSource:
    """Columnar equivalent of `PriceSource.from_duckdb` (same query, same result)."""
    con = db.connect(Path(path), read_only=True, wait_s=0)
    try:
        sql, params = prices_query(con, start=start, end=end, tickers=tickers)
        rows = con.execute(sql, params).fetchnumpy()
    finally:
        con.close()
    return price_source_from_columns(
        declaration, rows["ticker"], rows["date"],
        {name: rows[name] for name in BAR_COLUMNS})


def panel_digest(source) -> str:
    """SHA-256 over every array byte, dtype, shape and label of a study panel."""
    panel, digest = source.panel, hashlib.sha256()
    digest.update(repr((panel.tickers, panel.sessions, panel.bar_count, sorted(panel.intraday),
                        source.dividends, sorted(panel.ticker_index.items()),
                        sorted(panel.session_index.items()))).encode())
    arrays = [*sorted(panel.fields.items()), *sorted(panel.intraday.items()),
              ("present", panel.present), ("funding_at", panel.funding_at),
              ("open_available_at", panel.open_available_at),
              ("daily_available_at", panel.daily_available_at),
              ("session_days", panel.session_days)]
    for name, array in arrays:
        digest.update(f"{name}:{array.dtype.str}:{array.shape}:{array.flags.writeable}".encode())
        digest.update(np.ascontiguousarray(array).tobytes())
    return digest.hexdigest()
