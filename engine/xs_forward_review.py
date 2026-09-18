#!/usr/bin/env python
"""Prospective paper review of raw 12-1 momentum versus the screen benchmark.

The two books are already active, but ``xs_momentum_12_1`` has not yet emitted
its first monthly signal.  This monitor therefore waits for the close after the
2026-09-30 signal's next-open fills and freezes that shared close as the return
baseline.  It never backfills performance, changes a portfolio, or promotes a
strategy.

A positive verdict is impossible before five calendar years and 48 complete
paired months.  At maturity it requires positive absolute and excess return,
plus a predeclared 90% stationary-bootstrap interval on mean monthly excess
wholly above zero.  A 55% live drawdown requests human review early.  Every
status is paper-only and has no automatic action.
"""

from __future__ import annotations

import argparse
import calendar as month_calendar
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import numpy as np

from engine.lib import db, resources
from engine.lib.provenance import canonical_sha256
from engine.lib.settings import DATA_DIR, REPO_ROOT
from farm.stats.equity import max_drawdown
from farm.walkforward.monthly import block_bootstrap_ci
from sim import nyse
from sim.execution import resolve_profile
from sim.portfolio import FILL_MODEL_VERSION
from sim.strategies import REGISTRY
from sim.strategies.base import PortfolioView, passing_ranked
from sim.strategies.ew_benchmark import EwBenchmark
from sim.strategies.xs_common import has_table, window_returns
from sim.strategies.xs_momentum_12_1 import XsMomentum121

CANDIDATE_ID = "xs_momentum_12_1"
CONTROL_ID = "ew_benchmark"
SIGNAL_DATE = date(2026, 9, 30)
OBSERVATION_START = date(2026, 10, 1)
WINDOW_MONTHS = 60
MIN_PAIRED_MONTHS = 48
MAX_DRAWDOWN = -0.55
BOOTSTRAP_CONF = 0.90
BOOTSTRAP_DRAWS = 10_000
BOOTSTRAP_MEAN_BLOCK = 4
BOOTSTRAP_SEED = 20260907
EXPECTED_INITIAL_CASH = 39_000.0
EXPECTED_EXECUTION_PROFILE = "baseline_v1"
EXPECTED_FILL_MODEL_VERSION = "v4"
EXPECTED_PROFILE_SHA256 = "6340e47066716dbc6d3d221007033fb67069faf9cc9ec04aa95c89ec4de574db"
EXPECTED_CONFIG_SHA256 = {
    CANDIDATE_ID: "fb5a0f0e3472f14ed9b0a5d5bac05a081ec0284f200db91663b11d5d47ab9214",
    CONTROL_ID: "692d49494298d2e840c98ab78cb8e4a4829516b6049d7d24253eb3e28fe1318e",
}
EXPECTED_STRATEGY_TYPES = {
    CANDIDATE_ID: XsMomentum121,
    CONTROL_ID: EwBenchmark,
}
RUNTIME_CONTRACT_FILES = (
    "engine/xs_forward_review.py",
    "engine/actions.py",
    "engine/collect.py",
    "engine/lib/data_quality.py",
    "engine/lib/db.py",
    "engine/lib/resources.py",
    "engine/lib/util.py",
    "engine/screen.py",
    "engine/universe.py",
    "farm/walkforward/monthly.py",
    "sim/calendar.py",
    "sim/execution.py",
    "sim/fills.py",
    "sim/league.py",
    "sim/nyse.py",
    "sim/portfolio.py",
    "sim/schema.py",
    "sim/settle.py",
    "sim/strategies/base.py",
    "sim/strategies/ew_benchmark.py",
    "sim/strategies/xs_common.py",
    "sim/strategies/xs_momentum_12_1.py",
)
RUNTIME_CONTRACT_VERSION = 21
SUPERSEDED_RUNTIME_CONTRACT_SHA256 = (
    "8bdfdf2ce028964de6c49d10a95132ac66d66e5a900b4173109355e1945d781e"
)
RUNTIME_CONTRACT_MIGRATION = (
    "2026-09-18 isolated agent-paper lifecycle after interruption-safe transaction cleanup and "
    "before the first signal: attributed agent orders "
    "survive same-date reruns and the no-op agent book uses the ordinary simulator lifecycle; "
    "XS strategy, signal, execution economics, and statistical rules are unchanged"
)
# Filled after the file list was frozen; tests verify this against current bytes.
EXPECTED_RUNTIME_CONTRACT_SHA256 = (
    "f7a8a048eb79643f244f08a40dbd328e299644452c03ef95907b6cf5db6c7fac"
)

PRIOR_RUNTIME_CONTRACT_VERSION = 20
PRIOR_RUNTIME_CONTRACT_SHA256 = SUPERSEDED_RUNTIME_CONTRACT_SHA256
PRIOR_SUPERSEDED_RUNTIME_CONTRACT_SHA256 = (
    "7f4085fca17872a9ef1125c64ed03f58b2191abe68286e9720441df74f8f06f3"
)
PRIOR_RUNTIME_CONTRACT_MIGRATION = (
    "2026-09-13 interruption-safe transaction cleanup before the first signal: every explicit "
    "DuckDB transaction now rolls back process-level interruptions, preserves the original "
    "failure if cleanup also fails, and leaves borrowed connections reusable; strategy, signal, "
    "execution economics, and statistical rules are unchanged"
)
PRIOR_RUNTIME_CONTRACT_FILES = RUNTIME_CONTRACT_FILES


@dataclass(frozen=True)
class BookRegistration:
    portfolio_id: str
    strategy: str
    initial_cash: float
    execution_profile: str
    config: dict
    config_sha256: str


def _runtime_contract_sha256(repo_root: Path = REPO_ROOT) -> str:
    digest = hashlib.sha256()
    for relative in sorted(RUNTIME_CONTRACT_FILES):
        path = repo_root / relative
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"XS forward runtime contract file unavailable: {relative}") from exc
        if relative == "engine/xs_forward_review.py":
            # Break the otherwise circular dependency between this digest and
            # the expected digest literal stored in this file. Every other byte
            # of the monitor, including its verdict logic, remains covered.
            content = content.replace(
                EXPECTED_RUNTIME_CONTRACT_SHA256.encode(), b"<EXPECTED_SELF_HASH>"
            )
        encoded = relative.encode()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _registration(con, portfolio_id: str) -> BookRegistration:
    row = con.execute(
        "SELECT strategy, initial_cash, execution_profile, config "
        "FROM portfolios WHERE id = ? AND active",
        [portfolio_id],
    ).fetchone()
    if row is None:
        raise ValueError(f"active portfolio {portfolio_id!r} not found")
    try:
        config = json.loads(row[3])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"portfolio {portfolio_id!r} has invalid config JSON") from exc
    if not isinstance(config, dict):
        raise ValueError(f"portfolio {portfolio_id!r} config must be an object")
    return BookRegistration(
        portfolio_id=portfolio_id,
        strategy=row[0],
        initial_cash=float(row[1]),
        execution_profile=row[2],
        config=config,
        config_sha256=canonical_sha256(config),
    )


def _validate_runtime(candidate: BookRegistration, control: BookRegistration) -> None:
    if FILL_MODEL_VERSION != EXPECTED_FILL_MODEL_VERSION:
        raise ValueError("XS forward fill model changed")
    if (
        canonical_sha256(resolve_profile(EXPECTED_EXECUTION_PROFILE).as_dict())
        != EXPECTED_PROFILE_SHA256
    ):
        raise ValueError("XS forward execution profile changed")
    if _runtime_contract_sha256() != EXPECTED_RUNTIME_CONTRACT_SHA256:
        raise ValueError("XS forward strategy/execution source changed")
    for strategy_id, expected_type in EXPECTED_STRATEGY_TYPES.items():
        if REGISTRY.get(strategy_id) is not expected_type:
            raise ValueError(f"XS forward registry mapping changed for {strategy_id!r}")
    for book in (candidate, control):
        if book.strategy != book.portfolio_id:
            raise ValueError(f"{book.portfolio_id} strategy registration changed")
        if book.config_sha256 != EXPECTED_CONFIG_SHA256[book.portfolio_id]:
            raise ValueError(f"{book.portfolio_id} config changed")
        if book.initial_cash != EXPECTED_INITIAL_CASH:
            raise ValueError(f"{book.portfolio_id} initial capital changed")
        if book.execution_profile != EXPECTED_EXECUTION_PROFILE:
            raise ValueError(f"{book.portfolio_id} execution profile changed")


def _plus_months(value: date, months: int) -> date:
    total = value.year * 12 + value.month - 1 + months
    year, month_zero = divmod(total, 12)
    month = month_zero + 1
    return date(year, month, min(value.day, month_calendar.monthrange(year, month)[1]))


def _equity_payload(rows: list[tuple[date, float, float]]) -> list[list]:
    return [[d.isoformat(), float(candidate), float(control)] for d, candidate, control in rows]


def _metrics(rows: list[tuple[date, float, float]], column: int) -> dict:
    values = np.asarray([float(row[column]) for row in rows], dtype=float)
    if not np.all(np.isfinite(values)) or np.any(values <= 0):
        raise ValueError("XS forward equity must contain finite positive values")
    return {
        "start_equity": float(values[0]),
        "end_equity": float(values[-1]),
        "total_return": float(values[-1] / values[0] - 1.0),
        "max_drawdown": max_drawdown(values),
    }


def _completed_monthly_excess(rows: list[tuple[date, float, float]]) -> list[list]:
    """Monthly candidate-minus-control returns, excluding the open current month.

    A month counts only when its scheduled final NYSE session is present.  This
    prevents a data gap from turning a multi-month move into one mislabeled
    monthly observation.  The October 1 baseline is a return anchor, not an
    October month-end point.
    """
    as_of = rows[-1][0]
    month_end: dict[tuple[int, int], tuple[float, float]] = {}
    for d, candidate, control in rows:
        if nyse.is_last_session_of_month(d) and (
            (d.year, d.month) < (as_of.year, as_of.month) or d == as_of
        ):
            month_end[(d.year, d.month)] = (float(candidate), float(control))

    expected_months = []
    cursor = date(rows[0][0].year, rows[0][0].month, 1)
    current_month = date(as_of.year, as_of.month, 1)
    while cursor < current_month:
        expected_months.append((cursor.year, cursor.month))
        cursor = _plus_months(cursor, 1)
    if nyse.is_last_session_of_month(as_of):
        expected_months.append((as_of.year, as_of.month))
    if sorted(month_end) != expected_months:
        missing = [
            f"{year:04d}-{month:02d}"
            for year, month in expected_months
            if (year, month) not in month_end
        ]
        raise ValueError(
            "XS forward complete-month equity is missing scheduled month-end(s): "
            + ", ".join(missing)
        )

    points = [(float(rows[0][1]), float(rows[0][2]))]
    points.extend(month_end[key] for key in expected_months)
    out = []
    labels = [f"{year:04d}-{month:02d}" for year, month in expected_months]
    for i, label in enumerate(labels, start=1):
        prior_candidate, prior_control = points[i - 1]
        candidate, control = points[i]
        out.append(
            [
                label,
                candidate / prior_candidate - 1.0,
                control / prior_control - 1.0,
                (candidate / prior_candidate) - (control / prior_control),
            ]
        )
    return out


def _execution_audit(con, as_of: date) -> dict:
    out = {}
    for portfolio_id in (CANDIDATE_ID, CONTROL_ID):
        rows = con.execute(
            "SELECT status, COUNT(*) FROM sim_orders WHERE portfolio_id = ? "
            "AND signal_date >= ? GROUP BY status",
            [portfolio_id, SIGNAL_DATE],
        ).fetchall()
        counts = {status: int(count) for status, count in rows}
        stale_pending = con.execute(
            "SELECT COUNT(*) FROM sim_orders WHERE portfolio_id = ? "
            "AND signal_date >= ? AND signal_date < ? AND status = 'pending'",
            [portfolio_id, SIGNAL_DATE, as_of],
        ).fetchone()[0]
        out[portfolio_id] = {
            "filled": counts.get("filled", 0),
            "rejected": counts.get("rejected", 0),
            "pending": counts.get("pending", 0),
            "stale_pending": int(stale_pending),
        }
    return out


def _stored_signal_input_hashes(con) -> tuple[dict[str, str], list[str]]:
    universe = con.execute(
        "SELECT ticker, name, exchange, etf, member, active, liquid "
        "FROM universe_snapshot WHERE snapshot_date = ? ORDER BY ticker",
        [SIGNAL_DATE],
    ).fetchall()
    screen = con.execute(
        "SELECT ticker, close, rs_rank, template_score, passes_template, "
        "dist_50d, dist_200d, off_52w_low, off_52w_high, base_tight, vol_dryup, "
        "new_today, universe_policy FROM screen_results WHERE run_date = ? "
        "ORDER BY ticker",
        [SIGNAL_DATE],
    ).fetchall()
    if not universe or not screen:
        raise ValueError("frozen XS signal inputs are missing")
    snapshot_eligible = sorted(
        row[0] for row in universe if row[3] is False and row[5] is True and row[6] is True
    )
    return (
        {
            "universe_snapshot_sha256": canonical_sha256(universe),
            "screen_results_sha256": canonical_sha256(screen),
            "candidate_universe_sha256": canonical_sha256(snapshot_eligible),
        },
        snapshot_eligible,
    )


def _signal_input_hashes(
    con,
    candidate: BookRegistration,
    control: BookRegistration,
) -> dict[str, str]:
    hashes, snapshot_eligible = _stored_signal_input_hashes(con)
    live_eligible = [
        row[0]
        for row in con.execute(
            "SELECT ticker FROM universe WHERE active AND liquid AND NOT etf ORDER BY ticker"
        ).fetchall()
    ]
    if snapshot_eligible != live_eligible:
        raise ValueError("frozen XS universe snapshot does not match the signal universe")
    params = candidate.config.get("params", {})
    lookback = int(params.get("lookback", 252))
    skip = int(params.get("skip", 21))
    min_bars = int(params.get("min_bars", lookback + 1))
    min_price = float(params.get("min_price", 5.0))
    signal_rows = window_returns(
        con,
        SIGNAL_DATE,
        start_offset=lookback + 1,
        end_offset=skip + 1,
        min_bars=min_bars,
        min_price=min_price,
        universe_snapshot_date=SIGNAL_DATE,
    )
    cap = int(control.config.get("params", {}).get("cap", 50))
    control_targets = passing_ranked(con, SIGNAL_DATE)[:cap]
    if not signal_rows or not control_targets:
        raise ValueError("frozen XS derived signal rows are missing")
    return {
        **hashes,
        "candidate_signal_rows_sha256": canonical_sha256(signal_rows),
        "control_target_rows_sha256": canonical_sha256(control_targets),
    }


def _signal_state(con) -> dict:
    out = {}
    for portfolio_id in (CANDIDATE_ID, CONTROL_ID):
        row = con.execute(
            "SELECT p.cash, e.equity, e.cash, e.n_positions FROM portfolios p "
            "JOIN sim_equity e ON e.portfolio_id = p.id "
            "WHERE p.id = ? AND e.date = ?",
            [portfolio_id, SIGNAL_DATE],
        ).fetchone()
        if row is None:
            raise ValueError(f"{portfolio_id} signal-date state is missing")
        if not np.isclose(float(row[0]), float(row[2]), atol=1e-8, rtol=1e-10):
            raise ValueError(f"{portfolio_id} signal-date cash is inconsistent")
        out[portfolio_id] = _current_state_snapshot(
            con,
            portfolio_id,
            SIGNAL_DATE,
            equity=float(row[1]),
            cash=float(row[0]),
            n_positions=int(row[3]),
            label="signal-date",
        )
    return out


def _current_state_snapshot(
    con,
    portfolio_id: str,
    as_of: date,
    *,
    equity: float,
    cash: float,
    n_positions: int,
    label: str,
) -> dict:
    """Capture current holdings only when they represent ``as_of`` exactly."""
    if (
        not np.isfinite(equity)
        or equity <= 0
        or not np.isfinite(cash)
        or cash < -1e-6
        or n_positions < 0
    ):
        raise ValueError(f"{portfolio_id} {label} account state is invalid")
    positions = con.execute(
        "SELECT ticker, qty, avg_cost FROM sim_positions "
        "WHERE portfolio_id = ? AND qty != 0 ORDER BY ticker",
        [portfolio_id],
    ).fetchall()
    if n_positions != len(positions):
        raise ValueError(f"{portfolio_id} {label} position count is inconsistent")
    market_value = 0.0
    normalized_positions = []
    for ticker, qty, avg_cost in positions:
        qty = float(qty)
        avg_cost = float(avg_cost)
        if not np.isfinite(qty) or qty <= 0 or not np.isfinite(avg_cost) or avg_cost <= 0:
            raise ValueError(f"{portfolio_id} {label} position state is invalid")
        close_row = con.execute(
            "SELECT close FROM prices WHERE ticker = ? AND date <= ? "
            "AND close IS NOT NULL ORDER BY date DESC LIMIT 1",
            [ticker, as_of],
        ).fetchone()
        if close_row is None or not np.isfinite(float(close_row[0])):
            raise ValueError(f"{portfolio_id} {label} position has no usable close")
        market_value += qty * float(close_row[0])
        normalized_positions.append([ticker, qty, avg_cost])
    if not np.isclose(equity, cash + market_value, atol=1e-6, rtol=1e-10):
        raise ValueError(f"{portfolio_id} {label} equity is inconsistent")
    return {
        "cash": cash,
        "equity": equity,
        "n_positions": n_positions,
        "positions": normalized_positions,
    }


def _expected_signal_orders_from_state(
    con,
    registration: BookRegistration,
    state: dict,
) -> list[list]:
    view = PortfolioView(
        id=registration.portfolio_id,
        params=registration.config.get("params", {}),
        cash=state["cash"],
        positions={ticker: qty for ticker, qty, _avg_cost in state["positions"]},
        equity=state["equity"],
    )
    strategy = EXPECTED_STRATEGY_TYPES[registration.portfolio_id]()
    orders = strategy.generate_orders(con, view, SIGNAL_DATE)
    return [[order.ticker, order.side, float(order.qty)] for order in orders]


def _initial_orders_sha256(con, *, allow_control_noop: bool) -> str:
    payload = []
    for portfolio_id in (CANDIDATE_ID, CONTROL_ID):
        rows = con.execute(
            "SELECT id, ticker, side, qty, signal_date FROM sim_orders "
            "WHERE portfolio_id = ? AND signal_date = ? ORDER BY id",
            [portfolio_id, SIGNAL_DATE],
        ).fetchall()
        if not rows and portfolio_id == CANDIDATE_ID:
            raise ValueError(f"{portfolio_id} emitted no orders on the frozen signal")
        if not rows and not allow_control_noop:
            raise ValueError("ew_benchmark no-order signal was not prospectively validated")
        payload.extend(
            [portfolio_id, row[0], row[1], row[2], float(row[3]), row[4].isoformat()]
            for row in rows
        )
        if not rows:
            payload.append([portfolio_id, "NO_REBALANCE_ORDERS"])
    return canonical_sha256(payload)


def _freeze_signal_boundary(
    con,
    candidate: BookRegistration,
    control: BookRegistration,
) -> dict:
    signal_input_hashes = _signal_input_hashes(con, candidate, control)
    state = _signal_state(con)
    if state[CANDIDATE_ID]["positions"]:
        raise ValueError("XS forward candidate was already invested before its first signal")
    for registration in (candidate, control):
        expected = _expected_signal_orders_from_state(
            con, registration, state[registration.portfolio_id]
        )
        actual = con.execute(
            "SELECT ticker, side, qty, status FROM sim_orders WHERE portfolio_id = ? "
            "AND signal_date = ? ORDER BY ticker, side, id",
            [registration.portfolio_id, SIGNAL_DATE],
        ).fetchall()
        if any(status != "pending" for *_order, status in actual):
            raise ValueError(f"{registration.portfolio_id} frozen signal orders were not pending")
        actual = [[ticker, side, float(qty)] for ticker, side, qty, _status in actual]
        expected.sort(key=lambda row: (row[0], row[1], row[2]))
        if len(actual) != len(expected) or any(
            a[:2] != e[:2] or not np.isclose(a[2], e[2], atol=1e-10, rtol=1e-10)
            for a, e in zip(actual, expected, strict=True)
        ):
            raise ValueError(
                f"{registration.portfolio_id} frozen signal orders do not match its rule"
            )
    control_noop = not _expected_signal_orders_from_state(con, control, state[CONTROL_ID])
    return {
        "protocol_contract": {
            "candidate_config_sha256": candidate.config_sha256,
            "control_config_sha256": control.config_sha256,
            "execution_profile_sha256": EXPECTED_PROFILE_SHA256,
            "fill_model": EXPECTED_FILL_MODEL_VERSION,
            "runtime_contract_sha256": EXPECTED_RUNTIME_CONTRACT_SHA256,
            "criterion_sha256": canonical_sha256(_criterion()),
        },
        "signal_input_hashes": signal_input_hashes,
        "initial_orders_sha256": _initial_orders_sha256(con, allow_control_noop=control_noop),
        "signal_ledger_sha256": _ledger_sha256(con, SIGNAL_DATE),
        "signal_state": state,
        "signal_state_sha256": canonical_sha256(state),
        "control_signal_noop": control_noop,
    }


def _validate_signal_boundary(
    con,
    boundary: dict,
    *,
    validate_live_state: bool = False,
) -> None:
    try:
        protocol_contract = boundary["protocol_contract"]
        state = boundary["signal_state"]
        expected_state_hash = boundary["signal_state_sha256"]
        expected_inputs = boundary["signal_input_hashes"]
        expected_orders_hash = boundary["initial_orders_sha256"]
        expected_ledger_hash = boundary["signal_ledger_sha256"]
        control_noop = bool(boundary["control_signal_noop"])
    except (KeyError, TypeError) as exc:
        raise ValueError("frozen XS signal boundary is incomplete") from exc
    required_input_hashes = {
        "universe_snapshot_sha256",
        "screen_results_sha256",
        "candidate_universe_sha256",
        "candidate_signal_rows_sha256",
        "control_target_rows_sha256",
    }
    if set(expected_inputs) != required_input_hashes or not all(
        isinstance(value, str) and len(value) == 64 for value in expected_inputs.values()
    ):
        raise ValueError("frozen XS signal boundary is incomplete")
    if canonical_sha256(state) != expected_state_hash:
        raise ValueError("frozen XS signal state changed")
    if validate_live_state and canonical_sha256(_signal_state(con)) != expected_state_hash:
        raise ValueError("frozen XS signal state changed")
    expected_contract = {
        "candidate_config_sha256": EXPECTED_CONFIG_SHA256[CANDIDATE_ID],
        "control_config_sha256": EXPECTED_CONFIG_SHA256[CONTROL_ID],
        "execution_profile_sha256": EXPECTED_PROFILE_SHA256,
        "fill_model": EXPECTED_FILL_MODEL_VERSION,
        "runtime_contract_sha256": EXPECTED_RUNTIME_CONTRACT_SHA256,
        "criterion_sha256": canonical_sha256(_criterion()),
    }
    if protocol_contract != expected_contract:
        raise ValueError("frozen XS protocol contract changed")
    current_stored, _eligible = _stored_signal_input_hashes(con)
    if any(expected_inputs.get(key) != value for key, value in current_stored.items()):
        raise ValueError("frozen XS signal inputs changed")
    if _ledger_sha256(con, SIGNAL_DATE) != expected_ledger_hash:
        raise ValueError("frozen XS signal ledger changed")
    if _initial_orders_sha256(con, allow_control_noop=control_noop) != expected_orders_hash:
        raise ValueError("frozen XS signal order hash changed")


def _ledger_sha256(con, through: date) -> str:
    """Hash immutable executions and settlements through a date.

    Cash dividends are deliberately excluded: the live reconciler can discover
    and credit them several sessions after their ex-date. Boundary state records
    the cash known at the time; a later credit is then part of forward return,
    not a retroactive mutation of the checkpoint.
    """
    payload = {
        "fills": con.execute(
            "SELECT order_id, portfolio_id, ticker, side, qty, fill_date, open_px, "
            "fill_px, slippage_bps, cost_bps FROM sim_fills "
            "WHERE portfolio_id IN (?, ?) AND fill_date <= ? "
            "ORDER BY fill_date, portfolio_id, order_id",
            [CANDIDATE_ID, CONTROL_ID, through],
        ).fetchall(),
        "settlements": [],
    }
    if has_table(con, "sim_settlements"):
        payload["settlements"] = con.execute(
            "SELECT portfolio_id, ticker, kind, qty, price, into_ticker, ratio, effective "
            "FROM sim_settlements WHERE portfolio_id IN (?, ?) AND effective <= ? "
            "ORDER BY effective, portfolio_id, ticker",
            [CANDIDATE_ID, CONTROL_ID, through],
        ).fetchall()
    normalized = {
        key: [
            [value.isoformat() if isinstance(value, date) else value for value in row]
            for row in rows
        ]
        for key, rows in payload.items()
    }
    return canonical_sha256(normalized)


def _baseline_state(con) -> dict:
    out = {}
    for portfolio_id in (CANDIDATE_ID, CONTROL_ID):
        row = con.execute(
            "SELECT e.equity, e.cash, e.n_positions, p.cash FROM sim_equity e "
            "JOIN portfolios p ON p.id = e.portfolio_id "
            "WHERE e.portfolio_id = ? AND e.date = ?",
            [portfolio_id, OBSERVATION_START],
        ).fetchone()
        if row is None:
            raise ValueError(f"{portfolio_id} frozen baseline state is missing")
        if not np.isclose(float(row[1]), float(row[3]), atol=1e-8, rtol=1e-10):
            raise ValueError(f"{portfolio_id} baseline cash is inconsistent")
        out[portfolio_id] = _current_state_snapshot(
            con,
            portfolio_id,
            OBSERVATION_START,
            equity=float(row[0]),
            cash=float(row[1]),
            n_positions=int(row[2]),
            label="baseline",
        )
    return out


def _validate_frozen_baseline_state(con, expected: dict, expected_hash: str) -> None:
    if canonical_sha256(expected) != expected_hash:
        raise ValueError("previously published XS forward baseline state changed")
    if set(expected) != {CANDIDATE_ID, CONTROL_ID}:
        raise ValueError("previously published XS forward baseline state changed")
    for portfolio_id in (CANDIDATE_ID, CONTROL_ID):
        state = expected.get(portfolio_id)
        if not isinstance(state, dict) or set(state) != {
            "cash",
            "equity",
            "n_positions",
            "positions",
        }:
            raise ValueError("previously published XS forward baseline state changed")
        positions = state["positions"]
        if not isinstance(positions, list) or int(state["n_positions"]) != len(positions):
            raise ValueError("previously published XS forward baseline state changed")
        row = con.execute(
            "SELECT equity, cash, n_positions FROM sim_equity WHERE portfolio_id = ? AND date = ?",
            [portfolio_id, OBSERVATION_START],
        ).fetchone()
        if (
            row is None
            or int(row[2]) != int(state["n_positions"])
            or not np.isclose(float(row[0]), float(state["equity"]), atol=1e-8)
            or not np.isclose(float(row[1]), float(state["cash"]), atol=1e-8)
        ):
            raise ValueError("previously published XS forward baseline state changed")


def _validate_initial_transition(con) -> str:
    """Require the candidate signal and hash each book's post-signal transition.

    The already-invested EW control may legitimately need no rebalance order if
    its holdings are exactly on target.  That no-op is explicit in the hash;
    the candidate must trade because this is its first signal.
    """
    transition = []
    for portfolio_id in (CANDIDATE_ID, CONTROL_ID):
        rows = con.execute(
            "SELECT o.id, o.ticker, o.side, o.qty, o.status, o.reject_reason, "
            "f.fill_date, f.open_px, f.fill_px, f.slippage_bps, f.cost_bps "
            "FROM sim_orders o LEFT JOIN sim_fills f ON f.order_id = o.id "
            "WHERE o.portfolio_id = ? AND o.signal_date = ? ORDER BY o.id",
            [portfolio_id, SIGNAL_DATE],
        ).fetchall()
        if not rows and portfolio_id == CANDIDATE_ID:
            raise ValueError(f"{portfolio_id} emitted no orders on the frozen signal")
        baseline_fills = con.execute(
            "SELECT COUNT(*) FROM sim_fills WHERE portfolio_id = ? AND fill_date = ?",
            [portfolio_id, OBSERVATION_START],
        ).fetchone()[0]
        if baseline_fills != len(rows):
            raise ValueError(
                f"{portfolio_id} baseline fills do not exactly match the frozen signal"
            )
        if not rows:
            transition.append([portfolio_id, "NO_REBALANCE_ORDERS"])
            continue
        for row in rows:
            if row[4] != "filled" or row[6] != OBSERVATION_START:
                raise ValueError(
                    f"{portfolio_id} baseline orders do not exactly match the frozen signal"
                )
            transition.append(
                [
                    portfolio_id,
                    *row[:6],
                    row[6].isoformat(),
                    *row[7:],
                ]
            )
    return canonical_sha256(transition)


def _signal_boundary_from_prior(prior_result: dict | None) -> dict:
    try:
        boundary = prior_result["frozen_runtime"]["signal_boundary"]
    except (KeyError, TypeError) as exc:
        raise ValueError(
            "prospective XS signal boundary was not published before execution"
        ) from exc
    if not isinstance(boundary, dict):
        raise ValueError("prospective XS signal boundary was not published before execution")
    return boundary


def _last_valid_result(prior_result: dict | None) -> dict | None:
    if not isinstance(prior_result, dict):
        return None
    if prior_result.get("status") == "INVALID":
        preserved = prior_result.get("last_valid_result")
        return preserved if isinstance(preserved, dict) else None
    return prior_result


def _validate_published_runtime(prior_result: dict | None) -> None:
    """Reject silent runtime-contract replacement on an ordinary monitor run."""
    if prior_result is None:
        return
    try:
        frozen = prior_result["frozen_runtime"]
        actual = (
            frozen["runtime_contract_version"],
            frozen["runtime_contract_sha256"],
            frozen["superseded_runtime_contract_sha256"],
            frozen["runtime_contract_migration"],
            frozen["runtime_contract_files"],
        )
    except (KeyError, TypeError) as exc:
        raise ValueError("prior XS forward report has invalid runtime metadata") from exc
    expected = (
        RUNTIME_CONTRACT_VERSION,
        EXPECTED_RUNTIME_CONTRACT_SHA256,
        SUPERSEDED_RUNTIME_CONTRACT_SHA256,
        RUNTIME_CONTRACT_MIGRATION,
        list(RUNTIME_CONTRACT_FILES),
    )
    if actual != expected:
        raise ValueError("published XS runtime contract requires explicit migration")


def migrate_runtime_contract(con, prior_result: dict | None) -> dict:
    """Move the waiting XS record from v19 to v20 before any signal boundary exists."""
    prior_result = _last_valid_result(prior_result)
    if prior_result is None:
        raise ValueError("published XS forward report is required for migration")
    candidate = _registration(con, CANDIDATE_ID)
    control = _registration(con, CONTROL_ID)
    _validate_runtime(candidate, control)
    try:
        frozen = prior_result["frozen_runtime"]
        observation = prior_result["observation"]
    except (KeyError, TypeError) as exc:
        raise ValueError("prior XS forward report has invalid migration metadata") from exc
    if (
        prior_result.get("schema_version") != 2
        or prior_result.get("status") != "WAITING"
        or prior_result.get("paper_only") is not True
        or prior_result.get("automatic_action") != "none"
        or prior_result.get("candidate") != asdict(candidate)
        or prior_result.get("control") != asdict(control)
        or prior_result.get("criterion") != _criterion()
        or frozen.get("signal_date") != SIGNAL_DATE.isoformat()
        or frozen.get("observation_start") != OBSERVATION_START.isoformat()
        or frozen.get("fill_model") != EXPECTED_FILL_MODEL_VERSION
        or frozen.get("execution_profile_sha256") != EXPECTED_PROFILE_SHA256
        or frozen.get("runtime_contract_version") != PRIOR_RUNTIME_CONTRACT_VERSION
        or frozen.get("runtime_contract_sha256") != PRIOR_RUNTIME_CONTRACT_SHA256
        or frozen.get("superseded_runtime_contract_sha256")
        != PRIOR_SUPERSEDED_RUNTIME_CONTRACT_SHA256
        or frozen.get("runtime_contract_migration") != PRIOR_RUNTIME_CONTRACT_MIGRATION
        or frozen.get("runtime_contract_files") != list(PRIOR_RUNTIME_CONTRACT_FILES)
        or any(
            frozen.get(key) is not None
            for key in (
                "baseline_equity",
                "baseline_state",
                "baseline_state_sha256",
                "signal_boundary",
                "initial_transition_sha256",
                "baseline_ledger_sha256",
            )
        )
        or observation
        != {
            "signal_date": SIGNAL_DATE.isoformat(),
            "observation_start": OBSERVATION_START.isoformat(),
            "eligible_after": _plus_months(OBSERVATION_START, WINDOW_MONTHS).isoformat(),
            "shared_sessions": 0,
            "paired_complete_months": 0,
            "mature": False,
            "signal_boundary_frozen": False,
        }
    ):
        raise ValueError("published XS v19 record is not the exact pre-signal checkpoint")

    latest = con.execute(
        "SELECT MAX(date) FROM sim_equity WHERE portfolio_id IN (?, ?)",
        [CANDIDATE_ID, CONTROL_ID],
    ).fetchone()[0]
    future_orders = con.execute(
        "SELECT COUNT(*) FROM sim_orders WHERE portfolio_id IN (?, ?) AND signal_date >= ?",
        [CANDIDATE_ID, CONTROL_ID, SIGNAL_DATE],
    ).fetchone()[0]
    future_fills = con.execute(
        "SELECT COUNT(*) FROM sim_fills WHERE portfolio_id IN (?, ?) AND fill_date >= ?",
        [CANDIDATE_ID, CONTROL_ID, OBSERVATION_START],
    ).fetchone()[0]
    if latest is None or latest >= SIGNAL_DATE or future_orders or future_fills:
        raise ValueError("XS runtime migration is permitted only before its first signal")
    return _waiting_result(candidate, control)


def _validate_prior(
    con,
    rows: list[tuple[date, float, float]],
    prior_result: dict | None,
    candidate: BookRegistration,
    control: BookRegistration,
) -> dict:
    boundary = _signal_boundary_from_prior(prior_result)
    _validate_signal_boundary(con, boundary)
    if prior_result.get("status") not in {
        "ACCUMULATING",
        "PASS-FORWARD",
        "INCONCLUSIVE",
        "REVIEW-KILL",
    }:
        return boundary
    try:
        observation = prior_result["observation"]
        prior_as_of = date.fromisoformat(observation["as_of"])
        expected_count = int(observation["shared_sessions"])
        expected_hash = observation["equity_sha256"]
        frozen = prior_result["frozen_runtime"]
        expected_baseline = frozen["baseline_equity"]
        expected_transition = frozen["initial_transition_sha256"]
        expected_ledger = frozen["baseline_ledger_sha256"]
        expected_baseline_state = frozen["baseline_state"]
        expected_baseline_state_hash = frozen["baseline_state_sha256"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("prior XS forward report has invalid continuity metadata") from exc
    prefix = [row for row in rows if row[0] <= prior_as_of]
    if (
        len(prefix) != expected_count
        or not prefix
        or prefix[-1][0] != prior_as_of
        or canonical_sha256(_equity_payload(prefix)) != expected_hash
        or not np.isclose(float(rows[0][1]), expected_baseline[CANDIDATE_ID], atol=1e-8)
        or not np.isclose(float(rows[0][2]), expected_baseline[CONTROL_ID], atol=1e-8)
        or _validate_initial_transition(con) != expected_transition
        or _ledger_sha256(con, OBSERVATION_START) != expected_ledger
    ):
        raise ValueError("previously published XS forward equity window changed")
    _validate_frozen_baseline_state(con, expected_baseline_state, expected_baseline_state_hash)
    return boundary


def _waiting_result(
    candidate: BookRegistration,
    control: BookRegistration,
    signal_boundary: dict | None = None,
) -> dict:
    return {
        "schema_version": 2,
        "status": "WAITING",
        "paper_only": True,
        "automatic_action": "none",
        "candidate": asdict(candidate),
        "control": asdict(control),
        "criterion": _criterion(),
        "frozen_runtime": _frozen_runtime(None, signal_boundary=signal_boundary),
        "observation": {
            "signal_date": SIGNAL_DATE.isoformat(),
            "observation_start": OBSERVATION_START.isoformat(),
            "eligible_after": _plus_months(OBSERVATION_START, WINDOW_MONTHS).isoformat(),
            "shared_sessions": 0,
            "paired_complete_months": 0,
            "mature": False,
            "signal_boundary_frozen": signal_boundary is not None,
        },
    }


def _criterion() -> dict:
    return {
        "window_months": WINDOW_MONTHS,
        "minimum_paired_months": MIN_PAIRED_MONTHS,
        "maximum_candidate_drawdown": MAX_DRAWDOWN,
        "success": (
            "positive candidate return and cumulative excess, with the 90% stationary-"
            "bootstrap CI on mean paired monthly excess wholly above zero"
        ),
        "early_kill": "candidate max drawdown reaches or exceeds 55%",
    }


def _frozen_runtime(
    baseline: dict[str, float] | None,
    *,
    signal_boundary: dict | None = None,
    initial_transition_sha256: str | None = None,
    baseline_ledger_sha256: str | None = None,
    baseline_state: dict | None = None,
) -> dict:
    return {
        "signal_date": SIGNAL_DATE.isoformat(),
        "observation_start": OBSERVATION_START.isoformat(),
        "fill_model": EXPECTED_FILL_MODEL_VERSION,
        "execution_profile_sha256": EXPECTED_PROFILE_SHA256,
        "runtime_contract_version": RUNTIME_CONTRACT_VERSION,
        "runtime_contract_sha256": EXPECTED_RUNTIME_CONTRACT_SHA256,
        "superseded_runtime_contract_sha256": SUPERSEDED_RUNTIME_CONTRACT_SHA256,
        "runtime_contract_migration": RUNTIME_CONTRACT_MIGRATION,
        "runtime_contract_files": list(RUNTIME_CONTRACT_FILES),
        "baseline_equity": baseline,
        "baseline_state": baseline_state,
        "baseline_state_sha256": (
            canonical_sha256(baseline_state) if baseline_state is not None else None
        ),
        "signal_boundary": signal_boundary,
        "initial_transition_sha256": initial_transition_sha256,
        "baseline_ledger_sha256": baseline_ledger_sha256,
        "baseline_note": (
            "The first shared close after the frozen 2026-09-30 signal and next-open "
            "execution is the baseline. This excludes legacy EW performance and the "
            "initial transition; later monthly rebalances retain their realized costs."
        ),
    }


def evaluate(con, prior_result: dict | None = None) -> dict:
    prior_result = _last_valid_result(prior_result)
    candidate = _registration(con, CANDIDATE_ID)
    control = _registration(con, CONTROL_ID)
    _validate_runtime(candidate, control)
    _validate_published_runtime(prior_result)
    shared = con.execute(
        "SELECT candidate.date, candidate.equity, control.equity "
        "FROM sim_equity candidate JOIN sim_equity control ON control.date = candidate.date "
        "WHERE candidate.portfolio_id = ? AND control.portfolio_id = ? "
        "AND candidate.date >= ? ORDER BY candidate.date",
        [CANDIDATE_ID, CONTROL_ID, OBSERVATION_START],
    ).fetchall()
    if not shared:
        latest = con.execute(
            "SELECT MAX(date) FROM sim_equity WHERE portfolio_id IN (?, ?)",
            [CANDIDATE_ID, CONTROL_ID],
        ).fetchone()[0]
        if latest is None or latest < SIGNAL_DATE:
            return _waiting_result(candidate, control)
        if latest == SIGNAL_DATE:
            frozen = (prior_result or {}).get("frozen_runtime") or {}
            boundary = frozen.get("signal_boundary")
            if boundary is None:
                boundary = _freeze_signal_boundary(con, candidate, control)
            else:
                _validate_signal_boundary(con, boundary, validate_live_state=True)
            return _waiting_result(candidate, control, boundary)
        if latest < OBSERVATION_START:
            boundary = _signal_boundary_from_prior(prior_result)
            _validate_signal_boundary(con, boundary, validate_live_state=True)
            return _waiting_result(candidate, control, boundary)
        raise ValueError("missing frozen XS forward baseline")
    if shared[0][0] != OBSERVATION_START:
        raise ValueError("missing exact frozen XS forward baseline")
    if any(row[0] == SIGNAL_DATE for row in shared):
        raise ValueError("pre-execution signal close leaked into XS forward window")
    signal_boundary = _validate_prior(con, shared, prior_result, candidate, control)
    transition_sha256 = _validate_initial_transition(con)
    baseline_ledger_sha256 = _ledger_sha256(con, OBSERVATION_START)
    if prior_result and prior_result.get("status") in {
        "ACCUMULATING",
        "PASS-FORWARD",
        "INCONCLUSIVE",
        "REVIEW-KILL",
    }:
        baseline_state = prior_result["frozen_runtime"]["baseline_state"]
    else:
        baseline_state = _baseline_state(con)
    if any(int(baseline_state[book]["n_positions"]) <= 0 for book in (CANDIDATE_ID, CONTROL_ID)):
        raise ValueError("XS forward baseline was not invested after the frozen signal")
    execution = _execution_audit(con, shared[-1][0])
    if execution[CANDIDATE_ID]["filled"] == 0:
        raise ValueError("XS forward candidate has no fills from the frozen signal")
    candidate_metrics = _metrics(shared, 1)
    control_metrics = _metrics(shared, 2)
    monthly = _completed_monthly_excess(shared)
    excess = [row[3] for row in monthly]
    mean_ci = block_bootstrap_ci(
        excess,
        stat="mean",
        conf=BOOTSTRAP_CONF,
        n_boot=BOOTSTRAP_DRAWS,
        mean_block=BOOTSTRAP_MEAN_BLOCK,
        seed=BOOTSTRAP_SEED,
    )
    cumulative_excess = candidate_metrics["total_return"] - control_metrics["total_return"]
    eligible_after = _plus_months(OBSERVATION_START, WINDOW_MONTHS)
    mature = shared[-1][0] >= eligible_after and len(monthly) >= MIN_PAIRED_MONTHS
    execution_clean = all(
        values["rejected"] == 0 and values["stale_pending"] == 0 for values in execution.values()
    )
    drawdown_kill = candidate_metrics["max_drawdown"] <= MAX_DRAWDOWN
    passed = bool(
        mature
        and execution_clean
        and candidate_metrics["total_return"] > 0
        and cumulative_excess > 0
        and mean_ci
        and mean_ci["lo"] > 0
    )
    if drawdown_kill or not execution_clean:
        status = "REVIEW-KILL"
    elif not mature:
        status = "ACCUMULATING"
    else:
        status = "PASS-FORWARD" if passed else "INCONCLUSIVE"
    baseline = {CANDIDATE_ID: float(shared[0][1]), CONTROL_ID: float(shared[0][2])}
    return {
        "schema_version": 2,
        "status": status,
        "paper_only": True,
        "automatic_action": "none",
        "candidate": asdict(candidate),
        "control": asdict(control),
        "criterion": _criterion(),
        "frozen_runtime": _frozen_runtime(
            baseline,
            signal_boundary=signal_boundary,
            initial_transition_sha256=transition_sha256,
            baseline_ledger_sha256=baseline_ledger_sha256,
            baseline_state=baseline_state,
        ),
        "observation": {
            "signal_date": SIGNAL_DATE.isoformat(),
            "observation_start": OBSERVATION_START.isoformat(),
            "as_of": shared[-1][0].isoformat(),
            "eligible_after": eligible_after.isoformat(),
            "shared_sessions": len(shared),
            "paired_complete_months": len(monthly),
            "mature": mature,
            "equity_sha256": canonical_sha256(_equity_payload(shared)),
        },
        "metrics": {
            CANDIDATE_ID: candidate_metrics,
            CONTROL_ID: control_metrics,
            "cumulative_excess": cumulative_excess,
            "mean_monthly_excess": float(np.mean(excess)) if excess else None,
            "mean_monthly_excess_ci": mean_ci,
        },
        "execution": execution,
        "checks": {
            "candidate_profitable": candidate_metrics["total_return"] > 0,
            "cumulative_excess_positive": cumulative_excess > 0,
            "mean_excess_ci_above_zero": bool(mean_ci and mean_ci["lo"] > 0),
            "drawdown_kill_triggered": drawdown_kill,
            "execution_clean": execution_clean,
        },
    }


def _pct(value: float | None) -> str:
    return "·" if value is None else f"{value:+.2%}"


def render(result: dict) -> str:
    status = result["status"]
    if status == "INVALID":
        return (
            "# XS momentum 12-1 — prospective paper review\n\n"
            "_Status **INVALID** · paper only · no automatic action._\n\n"
            "The monitor failed closed. Inspect the nightly log; portfolio state was not changed.\n"
        )
    obs = result["observation"]
    if status == "WAITING":
        waiting_note = (
            "The 2026-09-30 signal inputs, pre-trade state, and pending intents have been "
            "captured. The monitor is waiting for next-open execution and the shared "
            "2026-10-01 closing baseline."
            if obs["signal_boundary_frozen"]
            else "The protocol is frozen before the first trade. The monitor will capture "
            "the 2026-09-30 signal inputs, pre-trade state, and pending intents before "
            "opening the shared 2026-10-01 post-fill baseline."
        )
        return "\n".join(
            [
                "# XS momentum 12-1 — prospective paper review",
                "",
                "_Status **WAITING** · paper only · no automatic action._",
                "",
                waiting_note,
                "",
                result["frozen_runtime"]["baseline_note"],
                "",
            ]
        )
    metrics = result["metrics"]
    candidate = metrics[CANDIDATE_ID]
    control = metrics[CONTROL_ID]
    ci = metrics["mean_monthly_excess_ci"]
    ci_text = "·" if ci is None else f"[{_pct(ci['lo'])}, {_pct(ci['hi'])}]"
    return "\n".join(
        [
            "# XS momentum 12-1 — prospective paper review",
            "",
            f"_Status **{status}** · through {obs['as_of']} · paper only · no automatic action._",
            "",
            result["frozen_runtime"]["baseline_note"],
            "",
            f"The test cannot mature before **{obs['eligible_after']}** and requires at least "
            f"**{MIN_PAIRED_MONTHS}** complete paired months. It currently has "
            f"**{obs['paired_complete_months']}**.",
            "",
            "| Measure | `xs_momentum_12_1` | `ew_benchmark` | Difference |",
            "|---|---:|---:|---:|",
            f"| Return | {_pct(candidate['total_return'])} | {_pct(control['total_return'])} | "
            f"{_pct(metrics['cumulative_excess'])} |",
            f"| Max drawdown | {_pct(candidate['max_drawdown'])} | "
            f"{_pct(control['max_drawdown'])} | "
            f"{_pct(candidate['max_drawdown'] - control['max_drawdown'])} |",
            f"| Mean monthly excess | {_pct(metrics['mean_monthly_excess'])} | · | {ci_text} (90% CI) |",
            "",
            "A positive verdict is evidence for continued paper observation only. It cannot "
            "authorize live capital or automatic promotion.",
            "",
        ]
    )


def write_report(result: dict, data_dir: Path = DATA_DIR) -> tuple[Path, Path]:
    report_dir = data_dir / "reports" / "forward"
    report_dir.mkdir(parents=True, exist_ok=True)
    md_path = report_dir / f"{CANDIDATE_ID}.md"
    json_path = report_dir / f"{CANDIDATE_ID}.json"
    resources.write_text_atomic(
        json_path, json.dumps(result, indent=2, sort_keys=True, default=str) + "\n"
    )
    resources.write_text_atomic(md_path, render(result))
    return md_path, json_path


def _invalid_result(exc: Exception, prior_result: dict | None = None) -> dict:
    result = {
        "schema_version": 2,
        "status": "INVALID",
        "paper_only": True,
        "automatic_action": "none",
        "error": {"type": type(exc).__name__, "message": "XS forward review failed closed"},
    }
    last_valid = _last_valid_result(prior_result)
    if last_valid is not None and last_valid.get("status") in {
        "WAITING",
        "ACCUMULATING",
        "PASS-FORWARD",
        "INCONCLUSIVE",
        "REVIEW-KILL",
    }:
        result["last_valid_result"] = last_valid
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument(
        "--migrate-runtime-contract",
        action="store_true",
        help="explicitly migrate the exact pre-signal v19 checkpoint to runtime contract v20",
    )
    args = parser.parse_args()
    prior = None
    prior_path = args.data_dir / "reports" / "forward" / f"{CANDIDATE_ID}.json"
    if prior_path.exists():
        try:
            loaded = json.loads(prior_path.read_text())
            prior = loaded if isinstance(loaded, dict) else None
        except (OSError, json.JSONDecodeError):
            prior = None
    if args.migrate_runtime_contract:
        try:
            con = db.connect(args.db or db.DEFAULT_DB, read_only=True)
            try:
                result = migrate_runtime_contract(con, prior)
            finally:
                con.close()
            md_path, json_path = write_report(result, args.data_dir)
        except Exception as exc:  # noqa: BLE001 - migration never replaces evidence on failure
            print(
                f"[xs-forward-review] migration refused: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return 1
        print(
            f"[xs-forward-review] migrated runtime contract to v{RUNTIME_CONTRACT_VERSION}: "
            f"wrote {md_path} and {json_path}"
        )
        return 0
    try:
        con = db.connect(args.db or db.DEFAULT_DB, read_only=True)
        try:
            result = evaluate(con, prior_result=prior)
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001 - every failure replaces stale status
        result = _invalid_result(exc, prior)
        md_path, json_path = write_report(result, args.data_dir)
        print(
            f"[xs-forward-review] INVALID: wrote {md_path} and {json_path}: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    md_path, json_path = write_report(result, args.data_dir)
    print(f"[xs-forward-review] {result['status']}: wrote {md_path} and {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
