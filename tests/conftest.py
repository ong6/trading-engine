"""Shared fixtures — every DB is in-memory. store/ is never opened."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sim.schema import INITIAL_CASH, init_sim_schema  # noqa: E402

PRICES_DDL = """
CREATE TABLE IF NOT EXISTS prices (
    ticker VARCHAR NOT NULL, date DATE NOT NULL,
    open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT,
    source VARCHAR DEFAULT 'yfinance', fetched_at TIMESTAMP,
    PRIMARY KEY (ticker, date)
)
"""

# A fixed session calendar: weekdays from 2024-06-03 through 2024-07-31 with
# 2024-06-19 (Juneteenth) and 2024-07-04 (Independence Day) removed.
HOLIDAYS = {date(2024, 6, 19), date(2024, 7, 4)}


def sessions(start=date(2024, 6, 3), end=date(2024, 7, 31)) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5 and d not in HOLIDAYS:
            out.append(d)
        d += timedelta(days=1)
    return out


SESSIONS = sessions()


def insert_bars(con, ticker, dates, *, open_=100.0, close=100.0, volume=1_000_000,
                high=None, low=None):
    """Insert flat bars for `ticker` on `dates`. Scalars or per-date lists."""
    n = len(dates)

    def seq(v):
        return list(v) if isinstance(v, (list, tuple)) else [v] * n

    rows = list(zip([ticker] * n, dates, seq(open_),
                    seq(high if high is not None else (open_ if not isinstance(open_, (list, tuple)) else open_)),
                    seq(low if low is not None else close), seq(close), seq(volume)))
    con.executemany(
        "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)", rows)


@pytest.fixture
def con():
    """In-memory DuckDB with the prices table + the sim schema."""
    c = duckdb.connect()
    c.execute(PRICES_DDL)
    init_sim_schema(c)
    yield c
    c.close()


@pytest.fixture
def book(con):
    """A funded portfolio 'test' with INITIAL_CASH and no positions."""
    con.execute(
        "INSERT INTO portfolios (id, name, strategy, config, created, active, cash) "
        "VALUES ('test', 'test', 'none', '{}', ?, TRUE, ?)",
        [SESSIONS[0], INITIAL_CASH])
    return "test"
