"""Shared fixtures — every DB is in-memory. store/ is never opened."""
from __future__ import annotations

import json
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
_P16_CALIBRATION_PAYLOADS = {}


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
    import numpy as np

    from engine.lib.provenance import canonical_sha256
    from engine.p16_features import session_dates
    from farm import p16_calibration
    from server import p16_book_store
    from sim import execution, nyse

    del cost
    cache_key = recorded_at.isoformat()
    if cache_key in _P16_CALIBRATION_PAYLOADS:
        return p16_book_store.record_calibration(
            con, registration_sha256=registration,
            payload=json.loads(_P16_CALIBRATION_PAYLOADS[cache_key]),
            recorded_at=recorded_at,
        )
    latest = recorded_at.date()
    while not nyse.is_session(latest):
        latest -= timedelta(days=1)
    dates = [value.isoformat() for value in session_dates(latest, 2)]
    from farm import p16_risk

    tickers = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
    sectors = ["a", "b", "c", "d", "e", "f"]
    scores = {"champion": [6.0, 5.0, 4.0, 3.0, 2.0, 1.0],
              "rule": [6.0, 5.0, 4.0, 3.0, 2.0, 1.0]}
    rng = np.random.default_rng(23)
    spy_returns = rng.normal(0, 0.01, 120)
    stock_returns = spy_returns[:, None] + rng.normal(0, 0.08, (120, len(tickers)))
    derived = {
        policy: p16_risk.calibration_risk_and_alpha(
            stock_returns, spy_returns, policy_scores,
        ) for policy, policy_scores in scores.items()
    }
    solver_inputs = {policy: {
        "alpha_h5": values["alpha_h5"].tolist(),
        "covariance_h5": values["covariance_h5"].tolist(),
        "beta": values["beta"].tolist(),
    } for policy, values in derived.items()}
    snapshots = []
    for market_date in dates:
        end = date.fromisoformat(market_date)
        session_values = [value.isoformat() for value in session_dates(end, 121)]
        risk_sha = canonical_sha256({
            "market_date": market_date, "tickers": tickers, "sessions": session_values,
            "covariance_h5": solver_inputs["champion"]["covariance_h5"],
            "beta": solver_inputs["champion"]["beta"], "sectors": sectors,
        })
        score_sha = canonical_sha256({**scores, "tickers": tickers})
        cost_rows = []
        for ticker in [*tickers, "SPY"]:
            notional = 10_000.0 if ticker == "SPY" else 1_000.0
            for side in ("buy", "sell"):
                components = execution.cost_components(
                    "baseline_v1", side=side, qty=notional / 100, open_px=100,
                    median_dollar_volume=100_000_000,
                )
                cost_rows.append({
                    "market_date": market_date, "ticker": ticker,
                    "role": "core_financing" if ticker == "SPY" else "stock",
                    "side": side, "reference_notional": notional,
                    "qty": notional / 100, "open_px": 100.0,
                    "median_dollar_volume": 100_000_000.0,
                    "execution_profile": "baseline_v1", **components,
                })
        snapshot_body = {
            "market_date": market_date,
            "scoring_information_cutoff_at": recorded_at.isoformat(),
            "sessions": session_values, "tickers": tickers, "sectors": sectors,
            "stock_returns": stock_returns.tolist(), "spy_returns": spy_returns.tolist(),
            "scores": scores, "solver_inputs": solver_inputs,
            "risk_snapshot_sha256": risk_sha, "score_snapshot_sha256": score_sha,
            "previous_weights": [*([0.0] * len(tickers)), 1.0],
            "previous_weight_source": "initial_all_spy", "cost_rows": cost_rows,
        }
        snapshots.append({
            **snapshot_body, "snapshot_sha256": canonical_sha256(snapshot_body),
        })
    frozen_cost = max(
        row["total_bps"] / 10_000
        for snapshot in snapshots for row in snapshot["cost_rows"]
    )
    cases = []
    for snapshot in snapshots:
        for book_id, policy in zip(
            p16_book_store.LOGICAL_BOOK_IDS, ("champion", "rule"), strict=True,
        ):
            values = solver_inputs[policy]
            cases.append({
                "book_id": book_id, "alpha": values["alpha_h5"],
                "covariance": values["covariance_h5"], "beta": values["beta"],
                "sectors": sectors, "previous": [*([0.0] * len(tickers)), 1.0],
                "cost": frozen_cost, "band": 0.005, "horizon_sessions": 5,
                "snapshot_sha256": snapshot["snapshot_sha256"],
                "snapshot_date": snapshot["market_date"],
                "risk_snapshot_sha256": snapshot["risk_snapshot_sha256"],
                "score_snapshot_sha256": snapshot["score_snapshot_sha256"],
            })
    calibrated = p16_calibration.calibrate_lambda(cases)
    selected = calibrated["selected_lambda"]
    selected_row = next(
        row for row in calibrated["curve"] if row["risk_aversion"] == selected
    )
    body = {
        "schema_version": 1, **calibrated, "books": [
            {"book_id": "p16_construct_ai", "status": "calibrated",
             "snapshot_count": 2,
             "median_tracking_error": selected_row["median_tracking_error"][
                 "p16_construct_ai"
             ]},
            {"book_id": "p16_construct_rule", "status": "calibrated",
             "snapshot_count": 2,
             "median_tracking_error": selected_row["median_tracking_error"][
                 "p16_construct_rule"
             ]},
        ],
        "snapshot_dates": dates,
        "risk_snapshot_sha256s": [row["risk_snapshot_sha256"] for row in snapshots],
        "score_snapshot_sha256s": [row["score_snapshot_sha256"] for row in snapshots],
        "snapshots": snapshots, "cost_per_turnover": frozen_cost,
        "ic_source": "registered_assumption", "assumed_ic": 0.03,
        "observed_ic_count": 0,
        "solver_failure_policy": "drop_lambda_on_any_case_failure",
        "execution_authority": "none",
    }
    payload = {**body, "calibration_sha256": canonical_sha256(body)}
    _P16_CALIBRATION_PAYLOADS[cache_key] = json.dumps(payload)
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
