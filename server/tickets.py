"""Transactional discretionary-ticket mutations.

This is the only server module that creates or cancels paper order intents.
It never fills an order; the nightly simulator remains the sole fill path.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import duckdb

from engine.lib import db as engine_db
from sim.schema import INITIAL_CASH, init_sim_schema

from . import market_read_models, risk, risk_book, ticket_contract, ticket_store
from .read_model_utils import (
    require_public_date,
    require_public_nonempty_string,
    require_public_positive_integer,
)

DISC_ID = risk_book.DISC_ID
_ET = ZoneInfo("America/New_York")
_OPEN_ET = time(9, 30)
PUBLIC_GATE_FIELDS = frozenset({"name", "status", "detail"})
SUBMISSION_RESULT_FIELDS = frozenset(
    {"ticket_id", "allowed", "status", "order_id", "signal_date", "gates", "reasons"}
)
CANCELLATION_RESULT_FIELDS = frozenset({"ticket_id", "order_id", "status"})
REVIEW_RESULT_FIELDS = frozenset({"ok", "kind", "ts", "detail"})
MAX_PUBLIC_GATES = 32
MAX_GATE_NAME_CHARS = 128
MAX_GATE_DETAIL_CHARS = 4_096
MAX_PUBLIC_REASONS = 32
MAX_REASON_CHARS = MAX_GATE_NAME_CHARS + len(" unacknowledged: ") + MAX_GATE_DETAIL_CHARS


def _now() -> datetime:
    return datetime.now(timezone.utc)


def signal_date(as_of: date, now: datetime | None = None) -> date:
    """Choose a signal date that can only fill after the owner submits it."""
    now_et = (now or _now()).astimezone(_ET)
    if now_et.date() > as_of and now_et.time() >= _OPEN_ET:
        return now_et.date()
    return as_of


def _audit(
    con: duckdb.DuckDBPyConnection,
    action: str,
    payload: dict,
    *,
    now: datetime | None = None,
) -> None:
    con.execute(
        "INSERT INTO audit_log (ts, actor, action, payload) VALUES (?, ?, ?, ?)",
        [now or _now(), "user", action, json.dumps(payload, default=str)],
    )


def _validate_public_gate(gate: object) -> None:
    if not isinstance(gate, dict) or set(gate) != PUBLIC_GATE_FIELDS:
        raise ValueError("public ticket gate is invalid")
    name = require_public_nonempty_string(gate.get("name"), "ticket gate name")
    if len(name) > MAX_GATE_NAME_CHARS:
        raise ValueError("public ticket gate name is invalid")
    if gate.get("status") not in {"pass", "fail", "unknown"}:
        raise ValueError("public ticket gate status is invalid")
    detail = gate.get("detail")
    if not isinstance(detail, str) or len(detail) > MAX_GATE_DETAIL_CHARS:
        raise ValueError("public ticket gate detail is invalid")


def _validate_submission_result(result: dict) -> None:
    if not isinstance(result, dict) or set(result) != SUBMISSION_RESULT_FIELDS:
        raise ValueError("public ticket submission shape is invalid")
    require_public_positive_integer(result.get("ticket_id"))
    allowed = result.get("allowed")
    if type(allowed) is not bool:
        raise ValueError("public ticket decision is invalid")
    require_public_date(result.get("signal_date"), "ticket signal date")
    gates = result.get("gates")
    if not isinstance(gates, list) or not gates or len(gates) > MAX_PUBLIC_GATES:
        raise ValueError("public ticket gates are invalid")
    for gate in gates:
        _validate_public_gate(gate)
    reasons = result.get("reasons")
    if (
        not isinstance(reasons, list)
        or len(reasons) > MAX_PUBLIC_REASONS
        or not all(
            isinstance(reason, str) and reason.strip() and len(reason) <= MAX_REASON_CHARS
            for reason in reasons
        )
    ):
        raise ValueError("public ticket reasons are invalid")
    if allowed:
        if (
            result.get("status") != "submitted"
            or not isinstance(result.get("order_id"), int)
            or isinstance(result.get("order_id"), bool)
            or reasons
        ):
            raise ValueError("public submitted ticket result is invalid")
        require_public_positive_integer(result["order_id"])
    elif result.get("status") != "rejected" or result.get("order_id") is not None or not reasons:
        raise ValueError("public rejected ticket result is invalid")


def _validate_cancellation_result(result: dict, expected_ticket_id: int) -> None:
    if not isinstance(result, dict) or set(result) != CANCELLATION_RESULT_FIELDS:
        raise ValueError("public ticket cancellation shape is invalid")
    ticket_id = require_public_positive_integer(result.get("ticket_id"))
    require_public_positive_integer(result.get("order_id"))
    if ticket_id != expected_ticket_id or result.get("status") != "cancelled":
        raise ValueError("public ticket cancellation result is invalid")


def _validate_review_result(result: dict) -> None:
    if not isinstance(result, dict) or set(result) != REVIEW_RESULT_FIELDS:
        raise ValueError("public review result shape is invalid")
    if result.get("ok") is not True or result.get("kind") != "circuit_breaker":
        raise ValueError("public review result is invalid")
    timestamp = result.get("ts")
    if type(timestamp) is not datetime or timestamp.utcoffset() is None:
        raise ValueError("public review timestamp is invalid")
    offset_seconds = timestamp.utcoffset().total_seconds()
    if offset_seconds % 60 != 0 or abs(offset_seconds) > 14 * 60 * 60:
        raise ValueError("public review timestamp is invalid")
    require_public_nonempty_string(result.get("detail"), "review detail")


def _ensure_discretionary_portfolio(con: duckdb.DuckDBPyConnection, as_of: date) -> None:
    exists, active = ticket_store.portfolio_active(con, DISC_ID)
    if exists:
        if not active:
            raise ticket_contract.TicketError(409, "discretionary portfolio is inactive")
        return
    ticket_store.insert_portfolio(
        con,
        as_of,
        discretionary_id=DISC_ID,
        initial_cash=INITIAL_CASH,
    )


def _available_to_sell(con: duckdb.DuckDBPyConnection, ticker: str) -> float:
    return ticket_store.available_to_sell(con, ticker, discretionary_id=DISC_ID)


def _ticket_decision(
    con: duckdb.DuckDBPyConnection,
    ticket: dict,
    submitted_at: datetime,
) -> tuple[list[dict], bool, list[str], ticket_contract.TicketError | None]:
    if ticket["side"] != "sell":
        gates = risk.evaluate_gates(con, ticket, now=submitted_at)
        allowed, reasons = risk.is_allowed(gates, ticket)
        return gates, allowed, reasons, None

    gates = [
        {
            "name": "closing_order",
            "status": "pass",
            "detail": "sell closes available long position",
        }
    ]
    available = _available_to_sell(con, ticket["ticker"])
    if ticket["qty"] <= available:
        return gates, True, [], None
    _audit(
        con,
        "ticket_reject_short",
        {**ticket, "available_to_sell": max(available, 0.0)},
        now=submitted_at,
    )
    rejection = ticket_contract.TicketError(
        400,
        "shorts unsupported v1; sell quantity exceeds the open position after pending exits",
    )
    return gates, True, [], rejection


def _record_submission(
    con: duckdb.DuckDBPyConnection,
    ticket: dict,
    gates: list[dict],
    allowed: bool,
    reasons: list[str],
    as_of: date,
    submitted_at: datetime,
) -> dict:
    actual_signal_date = signal_date(as_of, submitted_at)
    status = "submitted" if allowed else "rejected"
    order_id = (
        ticket_store.insert_pending_order(
            con,
            ticket,
            actual_signal_date,
            discretionary_id=DISC_ID,
        )
        if allowed
        else None
    )
    ticket_id = ticket_store.insert_ticket(
        con,
        ticket,
        gates,
        status,
        order_id,
        submitted_at,
    )
    _audit(
        con,
        "ticket_submit",
        {
            "ticket_id": ticket_id,
            "status": status,
            "order_id": order_id,
            "allowed": allowed,
            "ticket": ticket,
        },
        now=submitted_at,
    )
    return {
        "ticket_id": ticket_id,
        "allowed": allowed,
        "status": status,
        "order_id": order_id,
        "signal_date": actual_signal_date,
        "gates": gates,
        "reasons": reasons,
    }


def create(
    con: duckdb.DuckDBPyConnection,
    body: dict,
    *,
    now: datetime | None = None,
) -> dict:
    """Validate and record one paper ticket and optional pending order atomically."""
    ticket = ticket_contract.normalize(body)
    init_sim_schema(con)
    as_of = market_read_models.latest_prices_date(con)
    if as_of is None:
        raise ticket_contract.TicketError(503, "no price data")
    submitted_at = now or _now()
    rejection: ticket_contract.TicketError | None = None
    result = None
    try:
        with engine_db.transaction(con):
            _ensure_discretionary_portfolio(con, as_of)
            gates, allowed, reasons, rejection = _ticket_decision(con, ticket, submitted_at)
            if rejection is None:
                result = _record_submission(
                    con,
                    ticket,
                    gates,
                    allowed,
                    reasons,
                    as_of,
                    submitted_at,
                )
                _validate_submission_result(result)
    except ticket_store.IdentifierSpaceExhausted as exc:
        raise ticket_contract.TicketError(503, "paper identifier space exhausted") from exc
    if rejection is not None:
        raise rejection
    return result


def cancel(con: duckdb.DuckDBPyConnection, ticket_id: int) -> dict:
    try:
        ticket_id = require_public_positive_integer(ticket_id)
    except ValueError as exc:
        raise ticket_contract.TicketError(422, "ticket identifier is invalid") from exc
    with engine_db.transaction(con):
        exists, order_id = ticket_store.ticket_order_id(con, ticket_id)
        if not exists:
            raise ticket_contract.TicketError(404, f"no ticket {ticket_id}")
        if order_id is None:
            raise ticket_contract.TicketError(
                409, f"ticket {ticket_id} has no order (was rejected)"
            )
        try:
            order_id = require_public_positive_integer(order_id)
        except ValueError as exc:
            raise ticket_contract.TicketError(
                409, f"ticket {ticket_id} has an invalid linked order identifier"
            ) from exc
        order_exists, state = ticket_store.order_status(con, order_id)
        if state != "pending":
            state_detail = state if order_exists else "missing"
            raise ticket_contract.TicketError(
                409,
                f"order {order_id} not pending (status {state_detail}) — cannot cancel",
            )
        ticket_store.cancel_pending_order(con, ticket_id, order_id)
        _audit(con, "ticket_cancel", {"ticket_id": ticket_id, "order_id": order_id})
        result = {"ticket_id": ticket_id, "order_id": order_id, "status": "cancelled"}
        _validate_cancellation_result(result, ticket_id)
    return result


def mark_review_done(con: duckdb.DuckDBPyConnection) -> dict:
    init_sim_schema(con)
    timestamp = _now()
    with engine_db.transaction(con):
        ticket_store.insert_review_marker(con, timestamp)
        _audit(
            con,
            "review_done",
            {"kind": "circuit_breaker", "ts": str(timestamp)},
            now=timestamp,
        )
        result = {
            "ok": True,
            "kind": "circuit_breaker",
            "ts": timestamp,
            "detail": "circuit breaker cleared",
        }
        _validate_review_result(result)
    return result
