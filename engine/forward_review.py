#!/usr/bin/env python
"""Maturity-aware forward-paper review for the selected strategy candidate.

This is deliberately not a backtest and not an optimizer. It reads the live,
persisted ``sim_equity`` paths for the already-registered sector-momentum
book and its SPY control, writes a deterministic report, and never changes a
portfolio. Until a full twelve-calendar-month shared record exists, the only
valid verdict is ``ACCUMULATING``.

Once mature, the monitor applies the frozen kill criterion literally: request
a human retirement review if sector momentum trails SPY by more than ten
percentage points over the trailing twelve months without a smaller drawdown.
A ``CONTINUE`` result means only that this kill condition did not fire; it is
not evidence of positive alpha and is not permission to trade live capital.
"""

from __future__ import annotations

import argparse
import calendar
import copy
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
from engine.lib.util import table_exists
from farm.stats.equity import max_drawdown
from farm.walkforward.protocol import minus_months
from sim.execution import resolve_profile
from sim.portfolio import FILL_MODEL_VERSION
from sim.strategies import REGISTRY
from sim.strategies.sector_momentum import SectorMomentum
from sim.strategies.spy_benchmark import SpyBenchmark

CANDIDATE_ID = "sector_momentum"
CONTROL_ID = "spy_benchmark"
WINDOW_MONTHS = 12
MIN_SHARED_SESSIONS = 200
MAX_TRAIL = 0.10
# The live books began before execution model v4 existed. Their 2026-09-04
# closing marks are therefore the prospective baseline, not evidence attributed
# to v4. Performance before this date remains visible in the league but is not
# part of this frozen observation.
OBSERVATION_START = date(2026, 9, 4)
EXPECTED_INITIAL_CASH = 39_000.0
EXPECTED_EXECUTION_PROFILE = "baseline_v1"
EXPECTED_FILL_MODEL_VERSION = "v4"
EXPECTED_PROFILE_SHA256 = "6340e47066716dbc6d3d221007033fb67069faf9cc9ec04aa95c89ec4de574db"
EXPECTED_BASELINE_EQUITY = {
    CANDIDATE_ID: 41_742.09372396311,
    CONTROL_ID: 40_163.91313403321,
}
EXPECTED_BASELINE_STATE = {
    CANDIDATE_ID: {
        "cash": 35.138662886144374,
        "equity": 41_742.09372396311,
        "n_positions": 3,
        "positions": [
            ["XLE", 216.7514552594882, 58.74868862533569, 64.05999755859375],
            ["XLK", 74.13743682635298, 174.18400450134274, 187.27999877929688],
            ["XLV", 81.29133004417835, 163.93930986015226, 171.4499969482422],
        ],
    },
    CONTROL_ID: {
        "cash": 114.03300708008464,
        "equity": 40_163.91313403321,
        "n_positions": 1,
        "positions": [["SPY", 52.0, 747.8070575561522, 770.1900024414062]],
    },
}
EXPECTED_BASELINE_STATE_SHA256 = (
    "6009bf5f765b8f28e41636d60666af5d9319c121aa0668f214ba7a647cc0a902"
)
EXPECTED_LEGACY_BASELINE_EQUITY_SHA256 = (
    "1fb07940da9d3a310b9d63ccf3829184edd68175a81cac30b78344f3913a88cb"
)
RUNTIME_CONTRACT_VERSION = 10
SUPERSEDED_RUNTIME_CONTRACT_SHA256 = (
    "c430b451ee510c858705ba4235f81b68f9d7443745a60b4716035acb32741788"
)
RUNTIME_CONTRACT_MIGRATION = (
    "2026-09-18 isolated agent-paper lifecycle after interruption-safe transaction cleanup: "
    "attributed agent orders survive same-date "
    "reruns and the no-op agent book uses the ordinary simulator lifecycle; sector strategy, "
    "execution economics, baseline, and evidence-continuity rules are unchanged"
)
EXPECTED_RUNTIME_CONTRACT_SHA256 = (
    "8a91b71295afd533c1d508645daad2b62e9dc80deab506f2b422b095b1b8a2ce"
)
RUNTIME_CONTRACT_FILES = (
    "engine/forward_review.py",
    "engine/actions.py",
    "engine/lib/data_quality.py",
    "engine/lib/db.py",
    "engine/lib/util.py",
    "sim/calendar.py",
    "sim/execution.py",
    "sim/fills.py",
    "sim/league.py",
    "sim/nyse.py",
    "sim/portfolio.py",
    "sim/schema.py",
    "sim/settle.py",
    "sim/strategies/base.py",
    "sim/strategies/sector_momentum.py",
    "sim/strategies/spy_benchmark.py",
)
PRIOR_RUNTIME_CONTRACT_VERSION = 9
PRIOR_RUNTIME_CONTRACT_SHA256 = SUPERSEDED_RUNTIME_CONTRACT_SHA256
PRIOR_SUPERSEDED_RUNTIME_CONTRACT_SHA256 = (
    "c0788167bf63f734c6c9b3428b425a0054f1cead1754048aa00a6cc48eb5662f"
)
PRIOR_RUNTIME_CONTRACT_MIGRATION = (
    "2026-09-13 interruption-safe transaction cleanup: every explicit DuckDB transaction now "
    "rolls back process-level interruptions, preserves the original failure if cleanup also "
    "fails, and leaves borrowed connections reusable; strategy, execution economics, baseline, "
    "and evidence-continuity rules are unchanged"
)
PRIOR_RUNTIME_CONTRACT_FILES = RUNTIME_CONTRACT_FILES
EXPECTED_STRATEGY_TYPES = {
    CANDIDATE_ID: SectorMomentum,
    CONTROL_ID: SpyBenchmark,
}
EXPECTED_CONFIG_SHA256 = {
    CANDIDATE_ID: "c72300f5e438958572985c2257f7bcdf800dfe2cfe89c73f55c471850cc6e67a",
    CONTROL_ID: "277c8f3c71e7fe220af0b0cd80ff41400ccacebd6be90495ad3433fc5b040e1e",
}
EXPECTED_KILL_CRITERION = (
    "Trails spy_benchmark by >10% over 12 months without delivering a lower max drawdown."
)


@dataclass(frozen=True)
class BookRegistration:
    portfolio_id: str
    name: str
    strategy: str
    created: date
    initial_cash: float
    execution_profile: str
    config: dict
    config_sha256: str


def _runtime_contract_sha256(repo_root: Path = REPO_ROOT) -> str:
    """Hash the exact source files that govern this forward comparison."""
    digest = hashlib.sha256()
    for relative in sorted(RUNTIME_CONTRACT_FILES):
        path = repo_root / relative
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"forward runtime contract file unavailable: {relative}") from exc
        if relative == "engine/forward_review.py":
            # Normalize the expected digest literal to break the otherwise
            # circular self-hash while keeping every other monitor byte covered.
            content = content.replace(
                EXPECTED_RUNTIME_CONTRACT_SHA256.encode(), b"<EXPECTED_SELF_HASH>"
            )
        encoded_path = relative.encode()
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _validate_strategy_registry() -> None:
    """Pin the monitored mappings without freezing unrelated registrations."""
    for strategy_id, expected_type in EXPECTED_STRATEGY_TYPES.items():
        if REGISTRY.get(strategy_id) is not expected_type:
            raise ValueError(
                f"forward strategy registry mapping changed for {strategy_id!r}; "
                "start a newly dated forward observation"
            )


def _registration(con, portfolio_id: str) -> BookRegistration:
    row = con.execute(
        "SELECT name, strategy, created, initial_cash, execution_profile, config "
        "FROM portfolios WHERE id = ? AND active",
        [portfolio_id],
    ).fetchone()
    if row is None:
        raise ValueError(f"active portfolio {portfolio_id!r} not found")
    try:
        config = json.loads(row[5])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"portfolio {portfolio_id!r} has invalid config JSON") from exc
    if not isinstance(config, dict):
        raise ValueError(f"portfolio {portfolio_id!r} config must be an object")
    return BookRegistration(
        portfolio_id=portfolio_id,
        name=row[0],
        strategy=row[1],
        created=row[2],
        initial_cash=float(row[3]),
        execution_profile=row[4],
        config=config,
        config_sha256=canonical_sha256(config),
    )


def _validate_registration(candidate: BookRegistration, control: BookRegistration) -> None:
    if FILL_MODEL_VERSION != EXPECTED_FILL_MODEL_VERSION:
        raise ValueError(
            f"fill model changed from {EXPECTED_FILL_MODEL_VERSION!r} to {FILL_MODEL_VERSION!r}; "
            "start a newly dated forward observation"
        )
    profile_sha256 = canonical_sha256(resolve_profile(EXPECTED_EXECUTION_PROFILE).as_dict())
    if profile_sha256 != EXPECTED_PROFILE_SHA256:
        raise ValueError(
            f"execution profile {EXPECTED_EXECUTION_PROFILE!r} changed; "
            "start a newly dated forward observation"
        )
    contract_sha256 = _runtime_contract_sha256()
    if contract_sha256 != EXPECTED_RUNTIME_CONTRACT_SHA256:
        raise ValueError(
            "forward strategy/execution source changed; start a newly dated forward observation"
        )
    _validate_strategy_registry()
    if candidate.strategy != CANDIDATE_ID:
        raise ValueError(
            f"{CANDIDATE_ID!r} runs strategy {candidate.strategy!r}, expected {CANDIDATE_ID!r}"
        )
    criterion = candidate.config.get("kill_criterion")
    if criterion != EXPECTED_KILL_CRITERION:
        raise ValueError(
            "sector_momentum kill criterion changed; update the forward monitor only through "
            "a new, explicitly dated registration"
        )
    if control.strategy != CONTROL_ID:
        raise ValueError(
            f"{CONTROL_ID!r} runs strategy {control.strategy!r}, expected {CONTROL_ID!r}"
        )
    for book in (candidate, control):
        if book.config_sha256 != EXPECTED_CONFIG_SHA256[book.portfolio_id]:
            raise ValueError(
                f"{book.portfolio_id} config changed; this monitor is pinned to "
                f"{EXPECTED_CONFIG_SHA256[book.portfolio_id]}"
            )
        if book.initial_cash != EXPECTED_INITIAL_CASH:
            raise ValueError(
                f"{book.portfolio_id} capital changed from ${EXPECTED_INITIAL_CASH:,.0f}"
            )
        if book.execution_profile != EXPECTED_EXECUTION_PROFILE:
            raise ValueError(
                f"{book.portfolio_id} execution profile changed from {EXPECTED_EXECUTION_PROFILE!r}"
            )


def _book_metrics(rows: list[tuple[date, float, float]], column: int) -> dict:
    equity = np.asarray([float(row[column]) for row in rows], dtype=float)
    if not np.all(np.isfinite(equity)) or np.any(equity <= 0):
        raise ValueError("forward equity must contain finite positive values")
    return {
        "start_equity": float(equity[0]),
        "end_equity": float(equity[-1]),
        "total_return": float(equity[-1] / equity[0] - 1.0),
        "max_drawdown": max_drawdown(equity),
    }


def _equity_payload(rows: list[tuple[date, float, float]]) -> list[list]:
    return [[row[0].isoformat(), float(row[1]), float(row[2])] for row in rows]


def _validate_baseline_state(con) -> dict:
    """Validate the exact inherited positions and their boundary marks."""
    if canonical_sha256(EXPECTED_BASELINE_STATE) != EXPECTED_BASELINE_STATE_SHA256:
        raise ValueError("frozen forward baseline state constant changed")
    for portfolio_id in (CANDIDATE_ID, CONTROL_ID):
        expected = EXPECTED_BASELINE_STATE[portfolio_id]
        row = con.execute(
            "SELECT equity, cash, n_positions FROM sim_equity "
            "WHERE portfolio_id = ? AND date = ?",
            [portfolio_id, OBSERVATION_START],
        ).fetchone()
        if row is None:
            raise ValueError(f"frozen {portfolio_id} baseline account state is missing")
        equity, cash, n_positions = float(row[0]), float(row[1]), int(row[2])
        if (
            not np.isfinite(equity)
            or equity <= 0
            or not np.isfinite(cash)
            or cash < -1e-6
            or n_positions < 0
            or not np.isclose(equity, float(expected["equity"]), atol=1e-8, rtol=0.0)
            or not np.isclose(cash, float(expected["cash"]), atol=1e-8, rtol=0.0)
            or n_positions != int(expected["n_positions"])
        ):
            raise ValueError(f"frozen {portfolio_id} baseline account state changed")
        positions = expected["positions"]
        if n_positions != len(positions):
            raise ValueError(f"frozen {portfolio_id} baseline position count changed")
        market_value = 0.0
        seen = set()
        for item in positions:
            if not isinstance(item, list) or len(item) != 4:
                raise ValueError(f"frozen {portfolio_id} baseline position state changed")
            ticker, quantity, average_cost, expected_close = item
            quantity = float(quantity)
            average_cost = float(average_cost)
            expected_close = float(expected_close)
            if (
                not isinstance(ticker, str)
                or not ticker
                or ticker in seen
                or not np.isfinite(quantity)
                or quantity <= 0
                or not np.isfinite(average_cost)
                or average_cost <= 0
                or not np.isfinite(expected_close)
                or expected_close <= 0
            ):
                raise ValueError(f"frozen {portfolio_id} baseline position state changed")
            seen.add(ticker)
            close = con.execute(
                "SELECT close FROM prices WHERE ticker = ? AND date <= ? "
                "AND close IS NOT NULL ORDER BY date DESC LIMIT 1",
                [ticker, OBSERVATION_START],
            ).fetchone()
            if (
                close is None
                or not np.isfinite(float(close[0]))
                or float(close[0]) <= 0
                or not np.isclose(float(close[0]), expected_close, atol=1e-8, rtol=0.0)
            ):
                raise ValueError(f"frozen {portfolio_id} baseline mark is unavailable")
            market_value += quantity * float(close[0])
        if not np.isclose(equity, cash + market_value, atol=1e-6, rtol=1e-10):
            raise ValueError(f"frozen {portfolio_id} baseline equity does not reconcile")

    latest = con.execute(
        "SELECT MAX(date) FROM sim_equity WHERE portfolio_id IN (?, ?)",
        [CANDIDATE_ID, CONTROL_ID],
    ).fetchone()[0]
    if latest == OBSERVATION_START:
        # One-time migration proof: while the boundary remains the live state,
        # require its mutable account rows to equal the constants being frozen.
        for portfolio_id in (CANDIDATE_ID, CONTROL_ID):
            expected = EXPECTED_BASELINE_STATE[portfolio_id]
            cash = con.execute(
                "SELECT cash FROM portfolios WHERE id = ?", [portfolio_id]
            ).fetchone()
            positions = con.execute(
                "SELECT ticker, qty, avg_cost FROM sim_positions "
                "WHERE portfolio_id = ? AND qty != 0 ORDER BY ticker",
                [portfolio_id],
            ).fetchall()
            normalized = [
                [ticker, float(qty), float(cost), expected["positions"][index][3]]
                for index, (ticker, qty, cost) in enumerate(positions)
            ]
            if (
                cash is None
                or not np.isclose(float(cash[0]), float(expected["cash"]), atol=1e-8)
                or normalized != expected["positions"]
            ):
                raise ValueError(f"frozen {portfolio_id} live baseline state changed")
    return EXPECTED_BASELINE_STATE


def _normal(value):
    return value.isoformat() if isinstance(value, date) else value


def _forward_ledger(con, through: date, *, validate_terminal: bool = True) -> dict:
    """Validate and return all monitored post-boundary execution events."""
    if through < OBSERVATION_START:
        raise ValueError("forward ledger ends before its frozen boundary")
    ids = (CANDIDATE_ID, CONTROL_ID)
    orders = con.execute(
        "SELECT id, portfolio_id, ticker, side, qty, signal_date, status, reject_reason "
        "FROM sim_orders WHERE portfolio_id IN (?, ?) AND signal_date >= ? "
        "AND signal_date <= ? ORDER BY signal_date, portfolio_id, id",
        [*ids, OBSERVATION_START, through],
    ).fetchall()
    fills = con.execute(
        "SELECT order_id, portfolio_id, ticker, side, qty, fill_date, open_px, fill_px, "
        "slippage_bps, cost_bps FROM sim_fills WHERE portfolio_id IN (?, ?) "
        "AND fill_date >= ? AND fill_date <= ? ORDER BY fill_date, portfolio_id, order_id",
        [*ids, OBSERVATION_START, through],
    ).fetchall()
    costs = con.execute(
        "SELECT c.order_id, c.execution_profile, c.participation, c.market_bps, "
        "c.impact_bps, c.fee_bps, c.total_bps FROM sim_fill_costs c "
        "JOIN sim_fills f ON f.order_id = c.order_id WHERE f.portfolio_id IN (?, ?) "
        "AND f.fill_date >= ? AND f.fill_date <= ? ORDER BY c.order_id",
        [*ids, OBSERVATION_START, through],
    ).fetchall()
    attempts = con.execute(
        "SELECT a.order_id, a.attempt_date, a.execution_profile, a.raw_notional, "
        "a.median_dollar_vol, a.participation, a.outcome, a.reject_reason "
        "FROM sim_execution_attempts a JOIN sim_orders o ON o.id = a.order_id "
        "WHERE o.portfolio_id IN (?, ?) AND a.attempt_date >= ? AND a.attempt_date <= ? "
        "ORDER BY a.attempt_date, a.order_id",
        [*ids, OBSERVATION_START, through],
    ).fetchall()
    settlements = []
    if table_exists(con, "sim_settlements"):
        settlements = con.execute(
            "SELECT portfolio_id, ticker, kind, qty, price, into_ticker, ratio, effective "
            "FROM sim_settlements WHERE portfolio_id IN (?, ?) AND effective >= ? "
            "AND effective <= ? ORDER BY effective, portfolio_id, ticker",
            [*ids, OBSERVATION_START, through],
        ).fetchall()

    allowed_statuses = {"pending", "filled", "rejected", "cancelled"}
    order_by_id = {}
    for row in orders:
        order_id, portfolio_id, ticker, side, qty, signal_date, status, reason = row
        qty = float(qty)
        if (
            order_id in order_by_id
            or portfolio_id not in ids
            or not isinstance(ticker, str)
            or not ticker
            or side not in {"buy", "sell"}
            or not np.isfinite(qty)
            or qty <= 0
            or signal_date < OBSERVATION_START
            or signal_date > through
            or status not in allowed_statuses
            or (status == "rejected" and not reason)
            or (status in {"pending", "filled"} and reason is not None)
        ):
            raise ValueError("forward order ledger is invalid")
        order_by_id[order_id] = row

    fill_by_order = {}
    for row in fills:
        order_id, portfolio_id, ticker, side, qty, fill_date, open_px, fill_px, slip, cost = row
        order = order_by_id.get(order_id)
        values = [qty, open_px, fill_px, slip, cost]
        if (
            order is None
            or order_id in fill_by_order
            or order[1:4] != (portfolio_id, ticker, side)
            or (validate_terminal and order[6] != "filled")
            or fill_date <= order[5]
            or fill_date > through
            or any(not np.isfinite(float(value)) for value in values)
            or float(qty) <= 0
            or float(qty) > float(order[4]) + 1e-8
            or float(open_px) <= 0
            or float(fill_px) <= 0
            or float(slip) < 0
            or float(cost) < 0
        ):
            raise ValueError("forward fill ledger is invalid")
        expected_fill = float(open_px) * (
            1.0 + float(cost) / 1e4 if side == "buy" else 1.0 - float(cost) / 1e4
        )
        if not np.isclose(float(fill_px), expected_fill, atol=1e-8, rtol=1e-10):
            raise ValueError("forward fill price is inconsistent with its recorded cost")
        fill_by_order[order_id] = row
    if validate_terminal and any(
        (row[6] == "filled") != (row[0] in fill_by_order) for row in orders
    ):
        raise ValueError("forward order and fill ledgers do not reconcile")

    cost_by_order = {}
    for row in costs:
        order_id, profile, participation, market, impact, fee, total = row
        values = [participation, market, impact, fee, total]
        if (
            order_id not in fill_by_order
            or order_id in cost_by_order
            or profile != EXPECTED_EXECUTION_PROFILE
            or any(value is None or not np.isfinite(float(value)) for value in values)
            or any(float(value) < 0 for value in values)
            or not np.isclose(float(market) + float(fee), float(total), atol=1e-10)
            or not np.isclose(float(market), float(fill_by_order[order_id][8]), atol=1e-10)
            or not np.isclose(float(total), float(fill_by_order[order_id][9]), atol=1e-10)
        ):
            raise ValueError("forward fill-cost ledger is invalid")
        cost_by_order[order_id] = row
    if set(cost_by_order) != set(fill_by_order):
        raise ValueError("forward fill-cost ledger is incomplete")

    attempts_by_order = {}
    for row in attempts:
        order_id, attempt_date, profile, raw, median_dv, participation, outcome, _reason = row
        order = order_by_id.get(order_id)
        optional_values = [raw, median_dv, participation]
        if (
            order is None
            or attempt_date <= order[5]
            or attempt_date > through
            or profile != EXPECTED_EXECUTION_PROFILE
            or outcome not in {"pending", "filled", "rejected"}
            or any(value is not None and (
                not np.isfinite(float(value)) or float(value) < 0
            ) for value in optional_values)
            or (outcome == "filled" and (
                order_id not in fill_by_order or fill_by_order[order_id][5] != attempt_date
            ))
        ):
            raise ValueError("forward execution-attempt ledger is invalid")
        attempts_by_order.setdefault(order_id, []).append(row)
    if any(
        not any(attempt[6] == "filled" for attempt in attempts_by_order.get(order_id, []))
        for order_id in fill_by_order
    ):
        raise ValueError("forward filled order has no matching execution attempt")

    for portfolio_id, ticker, kind, qty, price, into_ticker, ratio, _effective in settlements:
        qty = float(qty)
        price = float(price)
        stock_terms = (
            kind == "stock"
            and isinstance(into_ticker, str)
            and bool(into_ticker)
            and ratio is not None
            and np.isfinite(float(ratio))
            and float(ratio) > 0
        )
        cash_terms = kind in {"cash", "worthless"} and into_ticker is None and ratio is None
        if (
            portfolio_id not in ids
            or not isinstance(ticker, str)
            or not ticker
            or not np.isfinite(qty)
            or qty <= 0
            or not np.isfinite(price)
            or price < 0
            or (kind == "worthless" and price != 0)
            or not (stock_terms or cash_terms)
        ):
            raise ValueError("forward settlement ledger is invalid")

    payload = {
        "orders": orders,
        "fills": fills,
        "fill_costs": costs,
        "execution_attempts": attempts,
        "settlements": settlements,
    }
    return {
        key: [[_normal(value) for value in row] for row in rows]
        for key, rows in payload.items()
    }


def _execution_audit(ledger: dict) -> dict:
    out = {}
    for portfolio_id in (CANDIDATE_ID, CONTROL_ID):
        orders = [row for row in ledger["orders"] if row[1] == portfolio_id]
        counts = {status: sum(row[6] == status for row in orders) for status in (
            "filled", "rejected", "pending", "cancelled"
        )}
        out[portfolio_id] = counts
    return out


def _ledger_checkpoint(ledger: dict) -> dict:
    """Immutable projection suitable for prefix continuity checks.

    Order status/reject_reason are excluded because they legitimately mutate
    after a signal date. Their terminal state remains validated against the
    append-only attempts/fills in the current complete ledger.
    """
    return {
        "orders": [row[:6] for row in ledger["orders"]],
        "fills": ledger["fills"],
        "fill_costs": ledger["fill_costs"],
        "execution_attempts": ledger["execution_attempts"],
        "settlements": ledger["settlements"],
    }


def _validate_prior_equity(
    con, shared: list[tuple[date, float, float]], prior_result: dict | None
) -> None:
    """Reject rewrites of the window already published by the prior report."""
    if not prior_result or prior_result.get("status") not in {
        "ACCUMULATING",
        "CONTINUE",
        "REVIEW-KILL",
    }:
        return
    frozen = prior_result.get("frozen_runtime", {})
    if frozen.get("observation_start") != OBSERVATION_START.isoformat():
        return  # pre-v4 report from the superseded observation boundary
    try:
        observation = prior_result["observation"]
        prior_as_of = date.fromisoformat(observation["as_of"])
        expected_hash = observation["equity_sha256"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("prior forward report has invalid continuity metadata") from exc
    if prior_result.get("schema_version") == 1:
        prior_start = date.fromisoformat(observation["window_start"])
        expected_count = int(observation["shared_sessions_in_window"])
        if not (
            prior_start == OBSERVATION_START
            and prior_as_of == OBSERVATION_START
            and expected_count == 1
            and expected_hash == EXPECTED_LEGACY_BASELINE_EQUITY_SHA256
            and shared[-1][0] == OBSERVATION_START
        ):
            raise ValueError("legacy forward report is not the frozen migration checkpoint")
    elif prior_result.get("schema_version") == 2:
        prior_start = date.fromisoformat(observation["first_shared_date"])
        expected_count = int(observation["shared_sessions_available"])
    else:
        raise ValueError("prior forward report has unsupported schema")
    prior_rows = [row for row in shared if prior_start <= row[0] <= prior_as_of]
    if (
        len(prior_rows) != expected_count
        or not prior_rows
        or prior_rows[0][0] != prior_start
        or prior_rows[-1][0] != prior_as_of
        or canonical_sha256(_equity_payload(prior_rows)) != expected_hash
    ):
        raise ValueError("previously published forward equity window changed")
    if prior_result.get("schema_version") == 2:
        try:
            expected_state = frozen["baseline_state"]
            expected_state_hash = frozen["baseline_state_sha256"]
            expected_ledger_hash = observation["forward_ledger_sha256"]
        except (KeyError, TypeError) as exc:
            raise ValueError("prior forward report has invalid continuity metadata") from exc
        if (
            expected_state != EXPECTED_BASELINE_STATE
            or expected_state_hash != EXPECTED_BASELINE_STATE_SHA256
            or canonical_sha256(
                _ledger_checkpoint(
                    _forward_ledger(con, prior_as_of, validate_terminal=False)
                )
            ) != expected_ledger_hash
        ):
            raise ValueError("previously published forward execution ledger changed")


def _plus_months(value: date, months: int) -> date:
    """Shift a date forward by whole calendar months, clamping month-end."""
    total = value.year * 12 + value.month - 1 + months
    year, month_zero = divmod(total, 12)
    month = month_zero + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _runtime_metadata() -> dict:
    return {
        "runtime_contract_version": RUNTIME_CONTRACT_VERSION,
        "runtime_contract_sha256": EXPECTED_RUNTIME_CONTRACT_SHA256,
        "superseded_runtime_contract_sha256": SUPERSEDED_RUNTIME_CONTRACT_SHA256,
        "runtime_contract_migration": RUNTIME_CONTRACT_MIGRATION,
        "runtime_contract_files": list(RUNTIME_CONTRACT_FILES),
    }


def _validate_published_runtime(prior_result: dict | None) -> None:
    """Reject an old contract on an ordinary monitor run."""
    if prior_result is None:
        return
    try:
        frozen = prior_result["frozen_runtime"]
        actual = {key: frozen[key] for key in _runtime_metadata()}
    except (KeyError, TypeError) as exc:
        raise ValueError("prior sector forward report has invalid runtime metadata") from exc
    if actual != _runtime_metadata():
        raise ValueError("published sector runtime contract requires explicit migration")


def migrate_runtime_contract(con, prior_result: dict | None) -> dict:
    """Replace only the exact prior sector contract metadata."""
    prior_result = _last_valid_result(prior_result)
    if prior_result is None:
        raise ValueError("published sector forward report is required for migration")

    current = evaluate(con)
    expected_prior = copy.deepcopy(current)
    expected_prior["frozen_runtime"].update(
        {
            "runtime_contract_version": PRIOR_RUNTIME_CONTRACT_VERSION,
            "runtime_contract_sha256": PRIOR_RUNTIME_CONTRACT_SHA256,
            "superseded_runtime_contract_sha256": PRIOR_SUPERSEDED_RUNTIME_CONTRACT_SHA256,
            "runtime_contract_migration": PRIOR_RUNTIME_CONTRACT_MIGRATION,
            "runtime_contract_files": list(PRIOR_RUNTIME_CONTRACT_FILES),
        }
    )
    prior_json = json.loads(json.dumps(prior_result, default=str))
    expected_json = json.loads(json.dumps(expected_prior, default=str))
    if prior_json != expected_json:
        raise ValueError("published sector v8 report is not the exact migration checkpoint")
    return current


def evaluate(con, prior_result: dict | None = None) -> dict:
    """Evaluate the frozen candidate/control pair from their shared paper path."""
    candidate = _registration(con, CANDIDATE_ID)
    control = _registration(con, CONTROL_ID)
    _validate_registration(candidate, control)
    _validate_published_runtime(prior_result)

    shared = con.execute(
        "SELECT candidate.date, candidate.equity, control.equity "
        "FROM sim_equity candidate "
        "JOIN sim_equity control ON control.date = candidate.date "
        "WHERE candidate.portfolio_id = ? AND control.portfolio_id = ? "
        "AND candidate.date >= ? "
        "ORDER BY candidate.date",
        [CANDIDATE_ID, CONTROL_ID, OBSERVATION_START],
    ).fetchall()
    if not shared:
        raise ValueError(
            f"candidate and control have no shared paper-equity observations on or after "
            f"{OBSERVATION_START}"
        )

    first_date = shared[0][0]
    if first_date != OBSERVATION_START:
        raise ValueError(
            f"missing frozen forward baseline on {OBSERVATION_START}; first shared date is "
            f"{first_date}"
        )
    baseline = shared[0]
    for portfolio_id, value in (
        (CANDIDATE_ID, float(baseline[1])),
        (CONTROL_ID, float(baseline[2])),
    ):
        if not np.isclose(value, EXPECTED_BASELINE_EQUITY[portfolio_id], rtol=0.0, atol=1e-8):
            raise ValueError(f"frozen {portfolio_id} baseline equity changed")
    baseline_state = _validate_baseline_state(con)
    _validate_prior_equity(con, shared, prior_result)
    as_of = shared[-1][0]
    forward_ledger = _forward_ledger(con, as_of)
    forward_ledger_sha256 = canonical_sha256(_ledger_checkpoint(forward_ledger))
    cutoff = minus_months(as_of, WINDOW_MONTHS)
    full_calendar_window = first_date <= cutoff
    if full_calendar_window:
        start_index = max(i for i, row in enumerate(shared) if row[0] <= cutoff)
    else:
        start_index = 0
    window = shared[start_index:]

    candidate_metrics = _book_metrics(window, 1)
    control_metrics = _book_metrics(window, 2)
    excess = candidate_metrics["total_return"] - control_metrics["total_return"]
    drawdown_improvement = candidate_metrics["max_drawdown"] - control_metrics["max_drawdown"]
    enough_sessions = len(window) >= MIN_SHARED_SESSIONS
    mature = full_calendar_window and enough_sessions
    trails_beyond_limit = excess < -MAX_TRAIL
    has_lower_drawdown = drawdown_improvement > 0.0
    kill_triggered = mature and trails_beyond_limit and not has_lower_drawdown
    status = "REVIEW-KILL" if kill_triggered else ("CONTINUE" if mature else "ACCUMULATING")

    equity_payload = _equity_payload(shared)
    return {
        "schema_version": 2,
        "status": status,
        "paper_only": True,
        "automatic_action": "none",
        "candidate": asdict(candidate),
        "control": asdict(control),
        "criterion": {
            "text": EXPECTED_KILL_CRITERION,
            "window_months": WINDOW_MONTHS,
            "max_trailing_excess_loss": -MAX_TRAIL,
            "requires_no_drawdown_improvement": True,
        },
        "frozen_runtime": {
            "observation_start": OBSERVATION_START.isoformat(),
            "fill_model": EXPECTED_FILL_MODEL_VERSION,
            "execution_profile_sha256": EXPECTED_PROFILE_SHA256,
            "baseline_equity": EXPECTED_BASELINE_EQUITY,
            "baseline_state": baseline_state,
            "baseline_state_sha256": EXPECTED_BASELINE_STATE_SHA256,
            **_runtime_metadata(),
            "baseline_note": (
                "The 2026-09-04 closing marks are the prospective baseline. Existing holdings "
                "were inherited from the pre-v4 paper path; no pre-baseline return is credited "
                "to this observation."
            ),
        },
        "observation": {
            "first_shared_date": first_date.isoformat(),
            "window_start": window[0][0].isoformat(),
            "as_of": as_of.isoformat(),
            "calendar_days_available": (as_of - first_date).days,
            "shared_sessions_available": len(shared),
            "shared_sessions_in_window": len(window),
            "minimum_shared_sessions": MIN_SHARED_SESSIONS,
            "eligible_after": _plus_months(first_date, WINDOW_MONTHS).isoformat(),
            "mature": mature,
            "equity_sha256": canonical_sha256(equity_payload),
            "forward_ledger_sha256": forward_ledger_sha256,
        },
        "metrics": {
            CANDIDATE_ID: candidate_metrics,
            CONTROL_ID: control_metrics,
            "excess_return": excess,
            "drawdown_improvement": drawdown_improvement,
        },
        "checks": {
            "trails_control_by_more_than_10pp": trails_beyond_limit,
            "has_lower_drawdown": has_lower_drawdown,
            "kill_triggered": kill_triggered,
        },
        "execution": _execution_audit(forward_ledger),
    }


def _pct(value: float) -> str:
    return f"{value:+.2%}"


def render(result: dict) -> str:
    if result["status"] == "INVALID":
        error = result["error"]
        return "\n".join(
            [
                "# Sector momentum — forward paper review",
                "",
                "_Status **INVALID** · paper only · no automatic action._",
                "",
                "The forward review could not validate or evaluate its frozen inputs. "
                "The previous report has been replaced so stale evidence cannot appear current.",
                "",
                f"Error: `{error['type']}` — {error['message']}",
                "",
                "Portfolio state was not changed. Inspect the nightly log and repair the input "
                "or registration mismatch before interpreting this monitor.",
                "",
            ]
        )

    obs = result["observation"]
    metrics = result["metrics"]
    candidate = metrics[CANDIDATE_ID]
    control = metrics[CONTROL_ID]
    mature_note = (
        "The registered 12-month test is mature."
        if obs["mature"]
        else f"The registered test is not mature before {obs['eligible_after']} and "
        f"requires at least {obs['minimum_shared_sessions']} shared sessions."
    )
    interpretation = {
        "ACCUMULATING": "No decision is permitted from this partial forward window.",
        "CONTINUE": "The kill condition did not fire; this does not establish positive alpha.",
        "REVIEW-KILL": "The frozen kill condition fired; a human should review retirement.",
    }[result["status"]]
    return "\n".join(
        [
            "# Sector momentum — forward paper review",
            "",
            f"_Status **{result['status']}** · through {obs['as_of']} · paper only · no automatic action._",
            "",
            "This report uses only the shared persisted paper equity paths of "
            "`sector_momentum` and `spy_benchmark`. It does not reuse walk-forward folds or "
            "search parameters.",
            "",
            f"**Frozen kill criterion:** {result['criterion']['text']}",
            "",
            f"**Frozen observation boundary:** {result['frozen_runtime']['observation_start']} · "
            f"fill model `{result['frozen_runtime']['fill_model']}` · execution profile "
            f"`{result['candidate']['execution_profile']}`.",
            "",
            result["frozen_runtime"]["baseline_note"],
            "",
            f"{mature_note} {interpretation}",
            "",
            "| Measure | `sector_momentum` | `spy_benchmark` | Difference |",
            "|---|---:|---:|---:|",
            f"| Return ({obs['window_start']} → {obs['as_of']}) | "
            f"{_pct(candidate['total_return'])} | {_pct(control['total_return'])} | "
            f"{_pct(metrics['excess_return'])} |",
            f"| Max drawdown | {_pct(candidate['max_drawdown'])} | "
            f"{_pct(control['max_drawdown'])} | "
            f"{_pct(metrics['drawdown_improvement'])} |",
            "",
            f"Shared observations: **{obs['shared_sessions_available']}**; sessions in displayed "
            f"window: **{obs['shared_sessions_in_window']}**; first shared date: "
            f"**{obs['first_shared_date']}**.",
            "",
            f"Candidate config SHA-256: `{result['candidate']['config_sha256']}`. "
            f"Execution profile: `{result['candidate']['execution_profile']}`. "
            f"Profile SHA-256: `{result['frozen_runtime']['execution_profile_sha256']}`. "
            f"Runtime-contract SHA-256: `{result['frozen_runtime']['runtime_contract_sha256']}`. "
            f"Baseline-state SHA-256: `{result['frozen_runtime']['baseline_state_sha256']}`. "
            f"Equity-prefix SHA-256: `{obs['equity_sha256']}`. "
            f"Forward-ledger SHA-256: `{obs['forward_ledger_sha256']}`.",
            "",
            "A `CONTINUE` verdict only means the downside kill rule was not met. Promotion or "
            "live deployment requires separate positive-edge evidence and explicit approval.",
            "",
        ]
    )


def write_report(result: dict, data_dir: Path = DATA_DIR) -> tuple[Path, Path]:
    report_dir = data_dir / "reports" / "forward"
    report_dir.mkdir(parents=True, exist_ok=True)
    md_path = report_dir / f"{CANDIDATE_ID}.md"
    json_path = report_dir / f"{CANDIDATE_ID}.json"
    # The API/UI consumes JSON. Publish it first so a later Markdown write
    # failure cannot leave yesterday's machine-readable status in place.
    resources.write_text_atomic(
        json_path, json.dumps(result, indent=2, sort_keys=True, default=str) + "\n"
    )
    resources.write_text_atomic(md_path, render(result))
    return md_path, json_path


def _invalid_result(exc: Exception) -> dict:
    """Safe status artifact written when validation/evaluation fails closed."""
    return {
        "schema_version": 2,
        "status": "INVALID",
        "paper_only": True,
        "automatic_action": "none",
        "error": {
            "type": type(exc).__name__,
            "message": "Forward review failed closed; inspect the local nightly log.",
        },
    }


def _last_valid_result(prior_result: dict | None) -> dict | None:
    if not isinstance(prior_result, dict):
        return None
    if prior_result.get("status") == "INVALID":
        preserved = prior_result.get("last_valid_result")
        return preserved if isinstance(preserved, dict) else None
    return prior_result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument(
        "--migrate-runtime-contract",
        action="store_true",
        help="explicitly migrate the exact sector v8 report to runtime contract v9",
    )
    args = parser.parse_args()
    prior_result = None
    prior_path = args.data_dir / "reports" / "forward" / f"{CANDIDATE_ID}.json"
    if prior_path.exists():
        try:
            loaded = json.loads(prior_path.read_text())
            prior_result = loaded if isinstance(loaded, dict) else None
        except (OSError, json.JSONDecodeError):
            prior_result = None
    prior_result = _last_valid_result(prior_result)
    if args.migrate_runtime_contract:
        try:
            con = db.connect(args.db or db.DEFAULT_DB, read_only=True)
            try:
                result = migrate_runtime_contract(con, prior_result)
            finally:
                con.close()
            md_path, json_path = write_report(result, args.data_dir)
        except Exception as exc:  # noqa: BLE001 - never replace evidence on migration failure
            print(
                f"[forward-review] migration refused: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return 1
        print(
            f"[forward-review] migrated runtime contract to v{RUNTIME_CONTRACT_VERSION}: "
            f"wrote {md_path} and {json_path}"
        )
        return 0
    try:
        con = db.connect(args.db or db.DEFAULT_DB, read_only=True)
        try:
            result = evaluate(con, prior_result=prior_result)
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001 - every monitor failure must invalidate stale output
        result = _invalid_result(exc)
        if prior_result is not None:
            result["last_valid_result"] = prior_result
        md_path, json_path = write_report(result, args.data_dir)
        print(
            f"[forward-review] INVALID: wrote {md_path} and {json_path}: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    md_path, json_path = write_report(result, args.data_dir)
    print(f"[forward-review] {result['status']}: wrote {md_path} and {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
