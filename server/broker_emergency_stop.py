"""Halt-first cancellation coordinator for the inert broker boundary.

This module can only add a durable halt and cancel already-open orders through
an explicitly supplied adapter. It cannot clear a halt, enable submissions,
grant authority, discover credentials, or construct an external adapter.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

import duckdb

from engine.lib import db
from engine.lib.provenance import canonical_sha256

from . import broker_ledger, broker_reconciliation, broker_risk_control
from .broker_contract import (
    BrokerAdapter,
    BrokerCancellationUncertain,
    BrokerOrder,
    BrokerStateError,
    require_identifier,
)

EMERGENCY_STOP_SCHEMA_VERSION = 1


def _utc(value: datetime | None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if (
        type(result) is not datetime
        or result.utcoffset() is None
        or result.utcoffset().total_seconds() != 0
    ):
        raise ValueError("emergency-stop time must be UTC")
    return result.astimezone(timezone.utc)


def _cancellation_key(halt_key: str, order: BrokerOrder) -> str:
    digest = canonical_sha256(
        {
            "halt_key": halt_key,
            "account_id": order.account_id,
            "broker_order_id": order.broker_order_id,
            "idempotency_key": order.idempotency_key,
        }
    )
    return f"cancel:{digest}"


def _order_payload(order: BrokerOrder) -> dict:
    return {
        **asdict(order),
        "signal_date": order.signal_date.isoformat(),
    }


def _planned_order(value: object) -> tuple[str, BrokerOrder]:
    expected = {
        "cancellation_key",
        "broker_order_id",
        "idempotency_key",
        "account_id",
        "symbol",
        "side",
        "quantity",
        "signal_date",
        "status",
        "rejection_reason",
        "filled_quantity",
        "order_type",
        "time_in_force",
        "extended_hours",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise BrokerStateError("stored emergency-stop order is invalid")
    cancellation_key = value["cancellation_key"]
    try:
        require_identifier(cancellation_key, "cancellation key")
        order = BrokerOrder(
            **{
                **{key: item for key, item in value.items() if key != "cancellation_key"},
                "signal_date": datetime.strptime(value["signal_date"], "%Y-%m-%d").date(),
            }
        )
    except (TypeError, ValueError) as exc:
        raise BrokerStateError("stored emergency-stop order is invalid") from exc
    if order.status not in {"pending", "partially_filled"}:
        raise BrokerStateError("stored emergency-stop order is invalid")
    return cancellation_key, order


def _same_order(left: BrokerOrder, right: BrokerOrder) -> bool:
    return (
        left.broker_order_id == right.broker_order_id
        and left.idempotency_key == right.idempotency_key
        and left.account_id == right.account_id
        and left.symbol == right.symbol
        and left.side == right.side
        and left.quantity == right.quantity
        and left.signal_date == right.signal_date
        and left.filled_quantity == right.filled_quantity
        and left.order_type == right.order_type
        and left.time_in_force == right.time_in_force
        and left.extended_hours == right.extended_hours
    )


def _validate_acknowledgement(
    acknowledgement: object,
    planned: BrokerOrder,
) -> BrokerOrder:
    if (
        not isinstance(acknowledgement, BrokerOrder)
        or acknowledgement.status != "cancelled"
        or not _same_order(acknowledgement, planned)
    ):
        raise BrokerStateError(
            "adapter cancellation acknowledgement does not match planned order"
        )
    return acknowledgement


def _start_payload(
    *,
    halt_key: str,
    account_id: str,
    reason: str,
    halt_event_sha256: str,
    snapshot: broker_reconciliation.BrokerSnapshot,
    occurred_at: str,
) -> dict:
    orders = []
    for order in snapshot.open_orders:
        orders.append(
            {
                "cancellation_key": _cancellation_key(halt_key, order),
                **_order_payload(order),
            }
        )
    return {
        "schema_version": EMERGENCY_STOP_SCHEMA_VERSION,
        "event_type": "emergency_stop_started",
        "halt_key": halt_key,
        "account_id": account_id,
        "reason": reason,
        "occurred_at": occurred_at,
        "halt_event_sha256": halt_event_sha256,
        "initial_open_orders_sha256": canonical_sha256(orders),
        "orders": orders,
        "submission_authority": "none",
    }


def _validate_start(payload: dict, *, halt_key: str, account_id: str) -> list[tuple[str, BrokerOrder]]:
    expected = {
        "schema_version",
        "event_type",
        "halt_key",
        "account_id",
        "reason",
        "occurred_at",
        "halt_event_sha256",
        "initial_open_orders_sha256",
        "orders",
        "submission_authority",
    }
    if (
        set(payload) != expected
        or payload["schema_version"] != EMERGENCY_STOP_SCHEMA_VERSION
        or payload["event_type"] != "emergency_stop_started"
        or payload["halt_key"] != halt_key
        or payload["account_id"] != account_id
        or not isinstance(payload["reason"], str)
        or not payload["reason"]
        or not isinstance(payload["occurred_at"], str)
        or not payload["occurred_at"].endswith("Z")
        or not isinstance(payload["halt_event_sha256"], str)
        or len(payload["halt_event_sha256"]) != 64
        or not isinstance(payload["initial_open_orders_sha256"], str)
        or len(payload["initial_open_orders_sha256"]) != 64
        or not isinstance(payload["orders"], list)
        or canonical_sha256(payload["orders"])
        != payload["initial_open_orders_sha256"]
        or payload["submission_authority"] != "none"
    ):
        raise BrokerStateError("stored emergency-stop start event is invalid")
    planned = []
    seen_keys = set()
    seen_order_ids = set()
    for value in payload["orders"]:
        cancellation_key, order = _planned_order(value)
        if cancellation_key != _cancellation_key(halt_key, order):
            raise BrokerStateError("stored emergency-stop order is invalid")
        if cancellation_key in seen_keys or order.broker_order_id in seen_order_ids:
            raise BrokerStateError("stored emergency-stop order is duplicated")
        seen_keys.add(cancellation_key)
        seen_order_ids.add(order.broker_order_id)
        planned.append((cancellation_key, order))
    return planned


def _completed_result(
    events: tuple[dict, ...],
    *,
    start: dict,
    planned_order_ids: list[str],
) -> dict | None:
    if len(events) < 2:
        return None
    result = events[1]
    expected = {
        "schema_version",
        "event_type",
        "status",
        "account_id",
        "halt_key",
        "halt_event_sha256",
        "start_event_sha256",
        "occurred_at",
        "cancelled_order_ids",
        "cancelled_count",
        "final_open_orders_sha256",
        "remaining_open_order_count",
        "submission_authority",
    }
    if (
        set(result) != expected
        or result["schema_version"] != EMERGENCY_STOP_SCHEMA_VERSION
        or result["event_type"] != "emergency_stop_completed"
        or result["status"] != "halted_cancelled"
        or result["account_id"] != start["account_id"]
        or result["halt_key"] != start["halt_key"]
        or result["halt_event_sha256"] != start["halt_event_sha256"]
        or result["start_event_sha256"] != canonical_sha256(start)
        or not isinstance(result["occurred_at"], str)
        or not result["occurred_at"].endswith("Z")
        or result["remaining_open_order_count"] != 0
        or result["submission_authority"] != "none"
        or not isinstance(result["cancelled_order_ids"], list)
        or result["cancelled_order_ids"] != sorted(result["cancelled_order_ids"])
        or len(set(result["cancelled_order_ids"])) != len(result["cancelled_order_ids"])
        or result["cancelled_count"] != len(result["cancelled_order_ids"])
        or result["cancelled_order_ids"] != sorted(planned_order_ids)
        or result["final_open_orders_sha256"] != canonical_sha256([])
    ):
        raise BrokerStateError("stored emergency-stop completion event is invalid")
    return {**result, "result_sha256": canonical_sha256(result)}


def _verified_acknowledgements(
    con: duckdb.DuckDBPyConnection,
    *,
    planned: list[tuple[str, BrokerOrder]],
    states: dict[str, broker_ledger.CancellationState],
) -> list[BrokerOrder]:
    acknowledgements = []
    for cancellation_key, order in planned:
        if states.get(cancellation_key) != "acknowledged":
            raise BrokerStateError(
                "completed emergency stop has an unacknowledged cancellation"
            )
        acknowledgement = broker_ledger.acknowledged_cancellation_order(
            con,
            cancellation_key,
        )
        if acknowledgement is None or not _same_order(acknowledgement, order):
            raise BrokerStateError(
                "acknowledged cancellation conflicts with emergency-stop order"
            )
        acknowledgements.append(acknowledgement)
    return acknowledgements


def cancel_all_and_halt(
    con: duckdb.DuckDBPyConnection,
    adapter: BrokerAdapter,
    account_id: str,
    *,
    halt_key: str,
    reason: str,
    now: datetime | None = None,
) -> dict:
    """Persist a halt first, then cancel every stable open order exactly once."""
    require_identifier(account_id, "account identifier")
    require_identifier(halt_key, "halt key")
    stopped_at = _utc(now)
    stopped_at_text = stopped_at.isoformat().replace("+00:00", "Z")
    control = broker_risk_control.record_halt(
        con,
        halt_key=halt_key,
        account_id=account_id,
        reason=reason,
        now=stopped_at,
    )
    if not control.halted:
        raise BrokerStateError("emergency stop did not establish halted state")
    halt_event_sha256 = broker_risk_control.halt_event_sha256(
        con,
        halt_key=halt_key,
        account_id=account_id,
    )

    broker_ledger.init_broker_ledger_schema(con)
    events = broker_ledger.emergency_stop_events(con, halt_key)
    if not events:
        operation_states = broker_ledger.emergency_stop_states_for_account(
            con,
            account_id,
        )
        if any(state == "started" for state in operation_states.values()):
            raise BrokerStateError(
                "another emergency-stop operation is already in progress"
            )
        existing_cancellations = broker_ledger.cancellation_states_for_account(
            con,
            account_id,
        )
        if any(state == "uncertain" for state in existing_cancellations.values()):
            raise BrokerCancellationUncertain(
                f"account {account_id!r} has uncertain cancellation evidence"
            )
        initial = broker_reconciliation.capture_snapshot(adapter, account_id)
        start = _start_payload(
            halt_key=halt_key,
            account_id=account_id,
            reason=reason,
            halt_event_sha256=halt_event_sha256,
            snapshot=initial,
            occurred_at=stopped_at_text,
        )
        with db.transaction(con):
            broker_ledger.record_emergency_stop_event(
                con,
                halt_key=halt_key,
                account_id=account_id,
                event_type="emergency_stop_started",
                payload=start,
                now=stopped_at,
            )
        events = (start,)
    start = events[0]
    planned = _validate_start(start, halt_key=halt_key, account_id=account_id)
    if (
        start["reason"] != reason
        or start["halt_event_sha256"] != halt_event_sha256
    ):
        raise BrokerStateError("stored emergency-stop start conflicts with halt event")
    completed = _completed_result(
        events,
        start=start,
        planned_order_ids=[order.broker_order_id for _key, order in planned],
    )
    states = broker_ledger.cancellation_states_for_account(con, account_id)
    uncertain = sorted(key for key, state in states.items() if state == "uncertain")
    if uncertain:
        raise BrokerCancellationUncertain(
            f"account {account_id!r} has uncertain cancellation evidence"
        )
    if completed is not None:
        if completed["account_id"] != account_id or completed["halt_key"] != halt_key:
            raise BrokerStateError("stored emergency-stop completion conflicts with request")
        _verified_acknowledgements(con, planned=planned, states=states)
        closing = broker_reconciliation.capture_snapshot(adapter, account_id)
        if closing.open_orders:
            raise BrokerStateError("open orders exist after completed emergency stop")
        return completed

    current = broker_reconciliation.capture_snapshot(adapter, account_id)
    current_by_id = {order.broker_order_id: order for order in current.open_orders}
    planned_ids = {order.broker_order_id for _key, order in planned}
    if set(current_by_id) - planned_ids:
        raise BrokerStateError("open-order set changed after emergency stop started")

    cancelled = []
    for cancellation_key, order in planned:
        state = states.get(cancellation_key)
        if state == "acknowledged":
            acknowledgement = broker_ledger.acknowledged_cancellation_order(
                con,
                cancellation_key,
            )
            if (
                acknowledgement is None
                or not _same_order(acknowledgement, order)
                or order.broker_order_id in current_by_id
            ):
                raise BrokerStateError(
                    "acknowledged cancellation conflicts with emergency-stop order"
                )
            cancelled.append(acknowledgement)
            continue
        observed = current_by_id.get(order.broker_order_id)
        if observed is None or not _same_order(observed, order):
            raise BrokerStateError(
                "uncancelled emergency-stop order is not currently open"
            )
        with db.transaction(con):
            broker_ledger.begin_cancellation(
                con,
                cancellation_key=cancellation_key,
                account_id=account_id,
                broker_order_id=order.broker_order_id,
                now=stopped_at,
            )
        acknowledgement = adapter.cancel_order(account_id, order.broker_order_id)
        acknowledgement = _validate_acknowledgement(acknowledgement, order)
        with db.transaction(con):
            broker_ledger.acknowledge_cancellation(
                con,
                cancellation_key=cancellation_key,
                account_id=account_id,
                broker_order_id=order.broker_order_id,
                order=acknowledgement,
                now=stopped_at,
            )
        cancelled.append(acknowledgement)

    closing = broker_reconciliation.capture_snapshot(adapter, account_id)
    if closing.open_orders:
        raise BrokerStateError("open orders remain after emergency cancellation")
    final_states = broker_ledger.cancellation_states_for_account(con, account_id)
    if any(state == "uncertain" for state in final_states.values()):
        raise BrokerCancellationUncertain(
            f"account {account_id!r} has uncertain cancellation evidence"
        )
    retained = _verified_acknowledgements(
        con,
        planned=planned,
        states=final_states,
    )
    if sorted(order.broker_order_id for order in retained) != sorted(
        order.broker_order_id for order in cancelled
    ):
        raise BrokerStateError("emergency-stop cancellation evidence is incomplete")
    body = {
        "schema_version": EMERGENCY_STOP_SCHEMA_VERSION,
        "event_type": "emergency_stop_completed",
        "status": "halted_cancelled",
        "account_id": account_id,
        "halt_key": halt_key,
        "halt_event_sha256": start["halt_event_sha256"],
        "start_event_sha256": canonical_sha256(start),
        "occurred_at": stopped_at_text,
        "cancelled_order_ids": sorted(
            order.broker_order_id for order in cancelled
        ),
        "cancelled_count": len(cancelled),
        "final_open_orders_sha256": canonical_sha256([]),
        "remaining_open_order_count": 0,
        "submission_authority": "none",
    }
    with db.transaction(con):
        result_sha256 = broker_ledger.record_emergency_stop_event(
            con,
            halt_key=halt_key,
            account_id=account_id,
            event_type="emergency_stop_completed",
            payload=body,
            now=stopped_at,
        )
    return {**body, "result_sha256": result_sha256}
