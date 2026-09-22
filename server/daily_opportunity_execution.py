"""Deterministic simulator-only consumption of P8 swing assessments."""
from __future__ import annotations

import json
from datetime import date, datetime

import duckdb

from engine.lib.data_quality import quarantine_reason
from engine.lib.provenance import canonical_sha256
from sim.execution import DEFAULT_PROFILE_ID

from .daily_opportunity_store import PORTFOLIO_ID
from .json_utils import loads_object

INITIAL_CASH = 10_000.0
POSITION_FRACTION = 0.10
MAX_POSITIONS = 3
MIN_CONFIDENCE = 0.65
BOOK_CONFIG = {
    "schema_version": 1, "policy_id": "daily-opportunity-v1",
    "strategy": "agent_only_policy", "cadence": "daily",
    "initial_cash": INITIAL_CASH, "position_fraction": POSITION_FRACTION,
    "max_positions": MAX_POSITIONS, "minimum_confidence": MIN_CONFIDENCE,
    "execution_profile": DEFAULT_PROFILE_ID, "simulator_only": True,
}


class ExecutionError(RuntimeError):
    """P8 paper execution state is absent or inconsistent."""


def initialize_book(con: duckdb.DuckDBPyConnection, start: date, *, active: bool) -> dict:
    encoded = json.dumps(BOOK_CONFIG, sort_keys=True, separators=(",", ":"))
    row = con.execute(
        "SELECT config, created, active, cash, initial_cash, execution_profile "
        "FROM portfolios WHERE id = ?", [PORTFOLIO_ID]
    ).fetchone()
    if row is None:
        con.execute(
            "INSERT INTO portfolios VALUES (?, 'Daily Opportunity Agent', 'agent_only_policy', "
            "?, ?, ?, ?, ?, ?)",
            [PORTFOLIO_ID, encoded, start, active, INITIAL_CASH, INITIAL_CASH, DEFAULT_PROFILE_ID],
        )
        con.execute(
            "INSERT INTO sim_equity VALUES (?, ?, ?, ?, 0)",
            [PORTFOLIO_ID, start, INITIAL_CASH, INITIAL_CASH],
        )
        row = (encoded, start, active, INITIAL_CASH, INITIAL_CASH, DEFAULT_PROFILE_ID)
    expected = (encoded, start, active, INITIAL_CASH, INITIAL_CASH, DEFAULT_PROFILE_ID)
    if row != expected:
        raise ExecutionError("daily opportunity book differs from its frozen contract")
    return {"portfolio_id": PORTFOLIO_ID, "active": active, "book_sha256": canonical_sha256(BOOK_CONFIG)}


def _candidate(bundle: dict, ticker: str) -> dict:
    matches = [item for item in bundle["candidates"] if item["ticker"] == ticker]
    if len(matches) != 1:
        raise ExecutionError("assessment candidate is unavailable")
    return matches[0]


def _eligible_buy(con: duckdb.DuckDBPyConnection, candidate: dict, confidence: float, market_date: date) -> bool:
    earnings = candidate["earnings"].get("next_date")
    earnings_near = earnings is not None and 0 <= (date.fromisoformat(earnings) - market_date).days <= 5
    held = con.execute(
        "SELECT COUNT(*) FROM sim_positions WHERE portfolio_id = ? AND qty > 0", [PORTFOLIO_ID]
    ).fetchone()[0]
    duplicate = con.execute(
        "SELECT 1 FROM sim_orders WHERE portfolio_id = ? AND ticker = ? AND status = 'pending'",
        [PORTFOLIO_ID, candidate["ticker"]],
    ).fetchone()
    return (confidence >= MIN_CONFIDENCE and candidate["passes_template"] is True
            and not earnings_near and held < MAX_POSITIONS and duplicate is None
            and quarantine_reason(con, candidate["ticker"]) is None)


def consume_run(con: duckdb.DuckDBPyConnection, run_id: int, *, now: datetime) -> list[int]:
    run = con.execute(
        "SELECT market_date, bundle_payload, status FROM daily_opportunity_runs WHERE id = ?",
        [run_id],
    ).fetchone()
    if run is None or run[2] != "completed":
        raise ExecutionError("daily opportunity run is not complete")
    book = con.execute(
        "SELECT active, config, cash FROM portfolios WHERE id = ?", [PORTFOLIO_ID]
    ).fetchone()
    if book is None or book[0] is not True or loads_object(book[1]) != BOOK_CONFIG:
        return []
    market_date, bundle = run[0], loads_object(run[1])
    orders = []
    rows = con.execute(
        "SELECT id, ticker, action, confidence, assessment_sha256 "
        "FROM daily_opportunity_assessments WHERE run_id = ? AND decision = 'swing' ORDER BY id",
        [run_id],
    ).fetchall()
    for assessment_id, ticker, side, confidence, assessment_sha256 in rows:
        if con.execute(
            "SELECT 1 FROM daily_opportunity_order_attribution WHERE assessment_id = ?",
            [assessment_id],
        ).fetchone():
            continue
        candidate = _candidate(bundle, ticker)
        if side == "buy":
            if bundle["market"]["regime"] != "risk_on" or not _eligible_buy(
                con, candidate, float(confidence), market_date
            ):
                continue
            quantity = min(float(book[2]) * POSITION_FRACTION, INITIAL_CASH * POSITION_FRACTION) / candidate["close"]
        elif side == "sell":
            position = con.execute(
                "SELECT qty FROM sim_positions WHERE portfolio_id = ? AND ticker = ? AND qty > 0",
                [PORTFOLIO_ID, ticker],
            ).fetchone()
            if position is None:
                continue
            quantity = float(position[0])
        else:
            continue
        order_id = int(con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM sim_orders").fetchone()[0])
        con.execute(
            "INSERT INTO sim_orders VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL)",
            [order_id, PORTFOLIO_ID, ticker, side, quantity, market_date],
        )
        attribution = {
            "order_id": order_id, "assessment_id": assessment_id, "run_id": run_id,
            "portfolio_id": PORTFOLIO_ID, "ticker": ticker, "side": side,
            "quantity": quantity, "signal_date": market_date.isoformat(),
            "assessment_sha256": assessment_sha256, "recorded_at": now.isoformat(),
        }
        con.execute(
            "INSERT INTO daily_opportunity_order_attribution VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [order_id, assessment_id, run_id, PORTFOLIO_ID, ticker, side, quantity, market_date,
             assessment_sha256, canonical_sha256(attribution), now],
        )
        orders.append(order_id)
    return orders
