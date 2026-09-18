"""Crash-safe coordinator for broker-neutral order submission.

No current API, agent, strategy, or schedule calls this coordinator. It exists
to prove the internal lifecycle boundary before any paper authority is wired.
"""

from __future__ import annotations

from datetime import datetime, timezone

import duckdb

from engine.lib import db

from . import broker_ledger
from .broker_contract import (
    BrokerAdapter,
    BrokerOrder,
    BrokerRiskRejected,
    BrokerStateError,
    BrokerSubmissionUncertain,
    SubmitOrderRequest,
)


def submit_once(
    con: duckdb.DuckDBPyConnection,
    adapter: BrokerAdapter,
    request: SubmitOrderRequest,
    *,
    risk_decision: dict,
    now: datetime | None = None,
) -> BrokerOrder:
    """Submit once, with durable uncertainty spanning the external call.

    The first transaction commits an ``uncertain`` marker before the adapter is
    called. If the call raises or the process exits afterward, subsequent calls
    fail with ``BrokerSubmissionUncertain``. They do not invoke the adapter.
    Reconciliation must establish whether the venue accepted the order.
    """
    broker_ledger.init_broker_ledger_schema(con)
    submitted_at = now or datetime.now(timezone.utc)
    if (
        type(submitted_at) is not datetime
        or submitted_at.utcoffset() is None
        or submitted_at.utcoffset().total_seconds() != 0
    ):
        raise ValueError("submission time must be UTC")
    with db.transaction(con):
        broker_ledger.record_risk_decision(
            con,
            request=request,
            decision=risk_decision,
        )
    with db.transaction(con):
        state = broker_ledger.submission_state(con, request.idempotency_key)
        if state == "acknowledged":
            order = broker_ledger.acknowledged_order(con, request.idempotency_key)
            if order is None:
                raise BrokerStateError("acknowledged broker order is unavailable")
            expected = (
                request.idempotency_key,
                request.account_id,
                request.symbol,
                request.side,
                request.quantity,
                request.signal_date,
                request.order_type,
                request.time_in_force,
                request.extended_hours,
            )
            actual = (
                order.idempotency_key,
                order.account_id,
                order.symbol,
                order.side,
                order.quantity,
                order.signal_date,
                order.order_type,
                order.time_in_force,
                order.extended_hours,
            )
            if actual != expected:
                raise BrokerStateError(
                    "acknowledged broker order conflicts with requested intent"
                )
            return order
        if state == "uncertain":
            raise BrokerSubmissionUncertain(
                f"submission {request.idempotency_key!r} is uncertain "
                "and requires reconciliation"
            )
        if risk_decision["status"] != "pass":
            raise BrokerRiskRejected(
                "independent pre-trade risk rejected the broker intent"
            )
        try:
            expires_at = datetime.fromisoformat(risk_decision["expires_at"])
        except (TypeError, ValueError) as exc:
            raise BrokerStateError("risk decision expiry is invalid") from exc
        if submitted_at >= expires_at:
            raise BrokerRiskRejected("independent pre-trade risk decision expired")
        broker_ledger.begin_submission(con, request)

    order = adapter.submit_order(request)
    if not isinstance(order, BrokerOrder):
        raise BrokerStateError("adapter returned an invalid order acknowledgement")

    with db.transaction(con):
        broker_ledger.acknowledge_submission(con, request, order)
    return order
