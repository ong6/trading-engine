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

    rows = list(zip(
        [ticker] * n,
        dates,
        seq(open_),
        seq(high if high is not None else (open_ if not isinstance(open_, (list, tuple)) else open_)),
        seq(low if low is not None else close),
        seq(close),
        seq(volume),
        strict=True,
    ))
    con.executemany(
        "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)", rows)


def record_p16_calibration(con, registration, recorded_at, *, cost=0.0005):
    """Retain a compact valid synthetic calibration for construction unit tests."""
    from engine.lib.provenance import canonical_sha256
    from farm.p16_calibration import DEFAULT_LAMBDA_GRID
    from server import p16_book_store

    selected = float(DEFAULT_LAMBDA_GRID[7])
    curve = []
    for value in DEFAULT_LAMBDA_GRID:
        risk_aversion = float(value)
        eligible = risk_aversion == selected
        curve.append({
            "risk_aversion": risk_aversion, "status": "converged",
            "eligible": eligible,
            "median_tracking_error": {
                "p16_construct_ai": 0.05 if eligible else 0.03,
                "p16_construct_rule": 0.05 if eligible else 0.03,
            },
            "distance": 0.0 if eligible else 0.02, "failures": [],
            "solve_timings": [
                {"case_index": 0, "book_id": "p16_construct_ai", "solve_seconds": 0.01},
                {"case_index": 1, "book_id": "p16_construct_rule", "solve_seconds": 0.01},
            ],
            "solve_seconds_total": 0.02,
        })
    body = {
        "schema_version": 1, "status": "calibrated", "selected_lambda": selected,
        "selected_at_grid_endpoint": False, "grid_bounds": [0.1, 1000.0],
        "curve": curve, "books": [
            {"book_id": "p16_construct_ai", "status": "calibrated",
             "snapshot_count": 1, "median_tracking_error": 0.05},
            {"book_id": "p16_construct_rule", "status": "calibrated",
             "snapshot_count": 1, "median_tracking_error": 0.05},
        ],
        "snapshot_dates": [recorded_at.date().isoformat()],
        "risk_snapshot_sha256s": ["b" * 64], "score_snapshot_sha256s": ["c" * 64],
        "cost_per_turnover": cost, "ic_source": "registered_assumption",
        "assumed_ic": 0.03, "execution_authority": "none",
    }
    payload = {**body, "calibration_sha256": canonical_sha256(body)}
    return p16_book_store.record_calibration(
        con, registration_sha256=registration, payload=payload, recorded_at=recorded_at,
    )


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
