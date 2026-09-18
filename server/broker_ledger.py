"""Durable internal lifecycle ledger for broker-neutral execution.

The ledger is separate from the existing simulator tables. It records caller
intent, adapter order acknowledgement, observed execution, and reconciliation
without changing strategy, portfolio, fill, or broker state. Submission state
is deliberately three-valued: a started attempt becomes ``acknowledged`` only
after an adapter order is durably linked; otherwise it remains ``uncertain``
and must never be retried blindly.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Literal

import duckdb

from engine.lib.provenance import canonical_sha256

from . import broker_risk_control
from .broker_contract import (
    MAX_ACCOUNT_ROWS,
    BrokerAccount,
    BrokerCancellationUncertain,
    BrokerFill,
    BrokerIdempotencyConflict,
    BrokerOrder,
    BrokerPosition,
    BrokerStateError,
    BrokerSubmissionUncertain,
    SubmitOrderRequest,
    require_identifier,
)
from .broker_risk import verify as verify_risk_decision

INTENT_SCHEMA_VERSION = 1
LEDGER_SCHEMA_VERSION = 1
SUBMISSION_RESOLUTION_SCHEMA_VERSION = 1
SubmissionState = Literal["uncertain", "acknowledged"]
CancellationState = Literal["uncertain", "acknowledged"]
ReconciliationStatus = Literal["match", "difference", "unavailable"]
SubmissionResolutionOutcome = Literal[
    "observed_open",
    "observed_filled",
    "observed_terminal_partial_fill",
    "not_observed_burned",
]
MAX_DETAIL_CHARS = 4_096
MAX_RESOLUTION_FILLS = 10_000
EMERGENCY_STOP_EVENT_TYPES = (
    "emergency_stop_started",
    "emergency_stop_completed",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime | None = None) -> str:
    timestamp = value or _now()
    if (
        type(timestamp) is not datetime
        or timestamp.utcoffset() is None
        or timestamp.utcoffset().total_seconds() != 0
    ):
        raise ValueError("broker ledger timestamp must be UTC")
    return timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _intent_payload(request: SubmitOrderRequest) -> dict:
    return {
        "schema_version": INTENT_SCHEMA_VERSION,
        "idempotency_key": request.idempotency_key,
        "account_id": request.account_id,
        "symbol": request.symbol,
        "side": request.side,
        "quantity": request.quantity,
        "signal_date": request.signal_date.isoformat(),
        "order_type": request.order_type,
        "time_in_force": request.time_in_force,
        "extended_hours": request.extended_hours,
    }


def _order_payload(order: BrokerOrder) -> dict:
    return {
        "broker_order_id": order.broker_order_id,
        "idempotency_key": order.idempotency_key,
        "account_id": order.account_id,
        "symbol": order.symbol,
        "side": order.side,
        "quantity": order.quantity,
        "signal_date": order.signal_date.isoformat(),
        "status": order.status,
        "rejection_reason": order.rejection_reason,
        "filled_quantity": order.filled_quantity,
        "order_type": order.order_type,
        "time_in_force": order.time_in_force,
        "extended_hours": order.extended_hours,
    }


def _fill_payload(fill: BrokerFill) -> dict:
    return {
        "execution_id": fill.execution_id,
        "broker_order_id": fill.broker_order_id,
        "idempotency_key": fill.idempotency_key,
        "account_id": fill.account_id,
        "symbol": fill.symbol,
        "side": fill.side,
        "quantity": fill.quantity,
        "occurred_on": fill.occurred_on.isoformat(),
        "reference_price": fill.reference_price,
        "price": fill.price,
        "total_cost_bps": fill.total_cost_bps,
    }


def _order_from_payload(raw: object) -> BrokerOrder:
    if not isinstance(raw, str):
        raise BrokerStateError("stored broker order payload is invalid")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise BrokerStateError("stored broker order payload is invalid") from exc
    expected_fields = {
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
    if not isinstance(payload, dict) or set(payload) != expected_fields:
        raise BrokerStateError("stored broker order payload is invalid")
    try:
        signal_date = datetime.strptime(payload["signal_date"], "%Y-%m-%d").date()
        return BrokerOrder(
            broker_order_id=payload["broker_order_id"],
            idempotency_key=payload["idempotency_key"],
            account_id=payload["account_id"],
            symbol=payload["symbol"],
            side=payload["side"],
            quantity=payload["quantity"],
            signal_date=signal_date,
            status=payload["status"],
            rejection_reason=payload["rejection_reason"],
            filled_quantity=payload["filled_quantity"],
            order_type=payload["order_type"],
            time_in_force=payload["time_in_force"],
            extended_hours=payload["extended_hours"],
        )
    except (TypeError, ValueError) as exc:
        raise BrokerStateError("stored broker order payload is invalid") from exc


def _request_from_payload(raw: object) -> SubmitOrderRequest:
    if not isinstance(raw, str):
        raise BrokerStateError("stored broker intent payload is invalid")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise BrokerStateError("stored broker intent payload is invalid") from exc
    expected_fields = {
        "schema_version",
        "idempotency_key",
        "account_id",
        "symbol",
        "side",
        "quantity",
        "signal_date",
        "order_type",
        "time_in_force",
        "extended_hours",
    }
    if (
        not isinstance(payload, dict)
        or set(payload) != expected_fields
        or payload["schema_version"] != INTENT_SCHEMA_VERSION
    ):
        raise BrokerStateError("stored broker intent payload is invalid")
    try:
        signal_date = datetime.strptime(payload["signal_date"], "%Y-%m-%d").date()
        return SubmitOrderRequest(
            idempotency_key=payload["idempotency_key"],
            account_id=payload["account_id"],
            symbol=payload["symbol"],
            side=payload["side"],
            quantity=payload["quantity"],
            signal_date=signal_date,
            order_type=payload["order_type"],
            time_in_force=payload["time_in_force"],
            extended_hours=payload["extended_hours"],
        )
    except (TypeError, ValueError) as exc:
        raise BrokerStateError("stored broker intent payload is invalid") from exc


def init_broker_ledger_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create append-only lifecycle evidence tables without adding authority."""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS broker_intents (
            idempotency_key VARCHAR PRIMARY KEY,
            account_id      VARCHAR NOT NULL,
            intent_sha256   VARCHAR NOT NULL,
            intent_payload  VARCHAR NOT NULL,
            created_at      TIMESTAMP NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS broker_risk_decisions (
            idempotency_key VARCHAR PRIMARY KEY,
            account_id      VARCHAR NOT NULL,
            decision_sha256 VARCHAR NOT NULL,
            decision_payload VARCHAR NOT NULL,
            decided_at      TIMESTAMP NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS broker_submission_events (
            idempotency_key VARCHAR NOT NULL,
            event_sequence  INTEGER NOT NULL,
            account_id      VARCHAR NOT NULL,
            intent_sha256   VARCHAR NOT NULL,
            event_type      VARCHAR NOT NULL,
            broker_order_id VARCHAR,
            order_sha256    VARCHAR,
            order_payload   VARCHAR,
            occurred_at     TIMESTAMP NOT NULL,
            PRIMARY KEY (idempotency_key, event_sequence)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS broker_submission_resolutions (
            idempotency_key    VARCHAR PRIMARY KEY,
            resolution_key     VARCHAR NOT NULL UNIQUE,
            account_id         VARCHAR NOT NULL,
            intent_sha256      VARCHAR NOT NULL,
            outcome            VARCHAR NOT NULL,
            control_sha256     VARCHAR NOT NULL,
            evidence_sha256    VARCHAR NOT NULL,
            evidence_payload   VARCHAR NOT NULL,
            resolution_sha256  VARCHAR NOT NULL,
            resolution_payload VARCHAR NOT NULL,
            observed_at        VARCHAR NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS broker_order_observations (
            observation_key VARCHAR PRIMARY KEY,
            account_id      VARCHAR NOT NULL,
            broker_order_id VARCHAR NOT NULL,
            order_sha256    VARCHAR NOT NULL,
            order_payload   VARCHAR NOT NULL,
            observed_at     TIMESTAMP NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS broker_cancellation_events (
            cancellation_key VARCHAR NOT NULL,
            event_sequence   INTEGER NOT NULL,
            account_id       VARCHAR NOT NULL,
            broker_order_id  VARCHAR NOT NULL,
            event_type       VARCHAR NOT NULL,
            order_sha256     VARCHAR,
            order_payload    VARCHAR,
            occurred_at      TIMESTAMP NOT NULL,
            PRIMARY KEY (cancellation_key, event_sequence)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS broker_emergency_stop_events (
            halt_key          VARCHAR NOT NULL,
            event_sequence    INTEGER NOT NULL,
            account_id        VARCHAR NOT NULL,
            event_type        VARCHAR NOT NULL,
            event_sha256      VARCHAR NOT NULL,
            event_payload     VARCHAR NOT NULL,
            occurred_at       VARCHAR NOT NULL,
            PRIMARY KEY (halt_key, event_sequence)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS broker_executions (
            execution_id    VARCHAR PRIMARY KEY,
            account_id      VARCHAR NOT NULL,
            broker_order_id VARCHAR NOT NULL,
            execution_sha256 VARCHAR NOT NULL,
            execution_payload VARCHAR NOT NULL,
            observed_at     TIMESTAMP NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS broker_snapshots (
            snapshot_key       VARCHAR PRIMARY KEY,
            reconciliation_key VARCHAR NOT NULL,
            role               VARCHAR NOT NULL,
            account_id         VARCHAR NOT NULL,
            snapshot_sha256    VARCHAR NOT NULL,
            snapshot_payload   VARCHAR NOT NULL,
            observed_at        TIMESTAMP NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS broker_reconciliations (
            reconciliation_key VARCHAR PRIMARY KEY,
            account_id         VARCHAR NOT NULL,
            status             VARCHAR NOT NULL,
            expected_sha256    VARCHAR,
            observed_sha256    VARCHAR,
            expected_payload   VARCHAR,
            observed_payload   VARCHAR,
            detail             VARCHAR NOT NULL,
            observed_at        TIMESTAMP NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS broker_reconciliation_differences (
            reconciliation_key VARCHAR NOT NULL,
            difference_sequence INTEGER NOT NULL,
            difference_sha256   VARCHAR NOT NULL,
            difference_payload  VARCHAR NOT NULL,
            recorded_at         TIMESTAMP NOT NULL,
            PRIMARY KEY (reconciliation_key, difference_sequence)
        )
        """
    )


def record_risk_decision(
    con: duckdb.DuckDBPyConnection,
    *,
    request: SubmitOrderRequest,
    decision: dict,
    now: datetime | None = None,
) -> str:
    """Append one verified risk decision bound to the immutable intent."""
    verified = verify_risk_decision(decision)
    request_payload = {
        key: value
        for key, value in _intent_payload(request).items()
        if key != "schema_version"
    }
    if (
        verified["request"] != request_payload
        or verified["request_sha256"] != canonical_sha256(request_payload)
    ):
        raise BrokerStateError("risk decision does not match broker intent")
    record_intent(con, request, now=now)
    payload = _canonical(verified)
    decision_sha256 = verified["decision_sha256"]
    row = con.execute(
        "SELECT account_id, decision_sha256, decision_payload "
        "FROM broker_risk_decisions WHERE idempotency_key = ?",
        [request.idempotency_key],
    ).fetchone()
    expected = (request.account_id, decision_sha256, payload)
    if row is None:
        con.execute(
            "INSERT INTO broker_risk_decisions "
            "(idempotency_key, account_id, decision_sha256, decision_payload, decided_at) "
            "VALUES (?, ?, ?, ?, ?)",
            [request.idempotency_key, *expected, now or _now()],
        )
        return decision_sha256
    if row != expected:
        raise BrokerStateError("stored risk decision conflicts with idempotency key")
    return decision_sha256


def record_intent(
    con: duckdb.DuckDBPyConnection,
    request: SubmitOrderRequest,
    *,
    now: datetime | None = None,
) -> str:
    """Insert an immutable intent, or verify an exact idempotent replay."""
    payload = _canonical(_intent_payload(request))
    digest = canonical_sha256(json.loads(payload))
    row = con.execute(
        "SELECT account_id, intent_sha256, intent_payload FROM broker_intents "
        "WHERE idempotency_key = ?",
        [request.idempotency_key],
    ).fetchone()
    if row is None:
        con.execute(
            "INSERT INTO broker_intents "
            "(idempotency_key, account_id, intent_sha256, intent_payload, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            [request.idempotency_key, request.account_id, digest, payload, now or _now()],
        )
        return digest
    if row != (request.account_id, digest, payload):
        raise BrokerIdempotencyConflict(
            "stored broker intent conflicts with idempotency key"
        )
    return digest


def _submission_events(
    con: duckdb.DuckDBPyConnection,
    idempotency_key: str,
) -> tuple[SubmissionState | None, tuple | None]:
    rows = con.execute(
        "SELECT event_sequence, account_id, intent_sha256, event_type, "
        "broker_order_id, order_sha256, order_payload, occurred_at "
        "FROM broker_submission_events WHERE idempotency_key = ? "
        "ORDER BY event_sequence",
        [idempotency_key],
    ).fetchall()
    if not rows:
        return None, None
    started = rows[0]
    if (
        len(rows) > 2
        or started[0] != 1
        or started[3] != "submission_started"
        or any(value is not None for value in started[4:7])
        or started[7] is None
    ):
        raise BrokerStateError("stored broker submission event sequence is invalid")
    intent_row = con.execute(
        "SELECT account_id, intent_sha256, intent_payload FROM broker_intents "
        "WHERE idempotency_key = ?",
        [idempotency_key],
    ).fetchone()
    if intent_row is None:
        raise BrokerStateError("stored broker submission has no intent")
    intent_account, intent_sha256, intent_payload = intent_row
    request = _request_from_payload(intent_payload)
    if (
        request.idempotency_key != idempotency_key
        or request.account_id != intent_account
        or started[1:3] != (intent_account, intent_sha256)
        or canonical_sha256(json.loads(intent_payload)) != intent_sha256
        or _canonical(_intent_payload(request)) != intent_payload
    ):
        raise BrokerStateError("stored broker submission intent is invalid")
    if len(rows) == 1:
        return "uncertain", started
    acknowledged = rows[1]
    if (
        acknowledged[0] != 2
        or acknowledged[1:3] != started[1:3]
        or acknowledged[3] != "submission_acknowledged"
        or any(value is None for value in acknowledged[4:8])
    ):
        raise BrokerStateError("stored broker submission event sequence is invalid")
    return "acknowledged", acknowledged


def begin_submission(
    con: duckdb.DuckDBPyConnection,
    request: SubmitOrderRequest,
    *,
    now: datetime | None = None,
) -> SubmissionState:
    """Persist pre-call uncertainty before any adapter submission is attempted."""
    intent_sha256 = record_intent(con, request, now=now)
    state, event = _submission_events(con, request.idempotency_key)
    if state is None:
        con.execute(
            "INSERT INTO broker_submission_events "
            "(idempotency_key, event_sequence, account_id, intent_sha256, event_type, "
            "broker_order_id, order_sha256, order_payload, occurred_at) "
            "VALUES (?, 1, ?, ?, 'submission_started', NULL, NULL, NULL, ?)",
            [request.idempotency_key, request.account_id, intent_sha256, now or _now()],
        )
        return "uncertain"
    if event is None:
        raise BrokerStateError("stored broker submission event is unavailable")
    _sequence, account_id, stored_intent, _event_type, *_rest = event
    if account_id != request.account_id or stored_intent != intent_sha256:
        raise BrokerStateError("stored broker submission conflicts with intent")
    if state == "uncertain":
        raise BrokerSubmissionUncertain(
            f"submission {request.idempotency_key!r} is uncertain and requires reconciliation"
        )
    if state == "acknowledged":
        return "acknowledged"
    raise BrokerStateError("stored broker submission state is invalid")


def acknowledge_submission(
    con: duckdb.DuckDBPyConnection,
    request: SubmitOrderRequest,
    order: BrokerOrder,
    *,
    now: datetime | None = None,
) -> None:
    """Bind one exact adapter acknowledgement to its durable intent."""
    if (
        order.idempotency_key != request.idempotency_key
        or order.account_id != request.account_id
        or order.symbol != request.symbol
        or order.side != request.side
        or order.quantity != request.quantity
        or order.signal_date != request.signal_date
        or order.order_type != request.order_type
        or order.time_in_force != request.time_in_force
        or order.extended_hours != request.extended_hours
    ):
        raise BrokerStateError("adapter order acknowledgement does not match intent")
    intent_sha256 = record_intent(con, request, now=now)
    state, event = _submission_events(con, request.idempotency_key)
    if state is None or event is None:
        raise BrokerStateError("broker submission was not durably started")
    (
        _sequence,
        account_id,
        stored_intent,
        _event_type,
        stored_order_id,
        stored_order_hash,
        stored_order_payload,
        _occurred_at,
    ) = event
    if account_id != request.account_id or stored_intent != intent_sha256:
        raise BrokerStateError("stored broker submission conflicts with intent")
    payload = _canonical(_order_payload(order))
    digest = canonical_sha256(json.loads(payload))
    if state == "acknowledged":
        if (stored_order_id, stored_order_hash, stored_order_payload) != (
            order.broker_order_id,
            digest,
            payload,
        ):
            raise BrokerStateError("stored broker acknowledgement conflicts with adapter order")
        return
    if state != "uncertain":
        raise BrokerStateError("stored broker submission is inconsistent")
    con.execute(
        "INSERT INTO broker_submission_events "
        "(idempotency_key, event_sequence, account_id, intent_sha256, event_type, "
        "broker_order_id, order_sha256, order_payload, occurred_at) "
        "VALUES (?, 2, ?, ?, 'submission_acknowledged', ?, ?, ?, ?)",
        [
            request.idempotency_key,
            request.account_id,
            intent_sha256,
            order.broker_order_id,
            digest,
            payload,
            now or _now(),
        ],
    )


def _cancellation_events(
    con: duckdb.DuckDBPyConnection,
    cancellation_key: str,
) -> tuple[CancellationState | None, tuple | None]:
    rows = con.execute(
        "SELECT event_sequence, account_id, broker_order_id, event_type, "
        "order_sha256, order_payload, occurred_at "
        "FROM broker_cancellation_events WHERE cancellation_key = ? "
        "ORDER BY event_sequence",
        [cancellation_key],
    ).fetchall()
    if not rows:
        return None, None
    started = rows[0]
    if (
        len(rows) > 2
        or started[0] != 1
        or started[3] != "cancellation_started"
        or any(value is not None for value in started[4:6])
        or started[6] is None
    ):
        raise BrokerStateError("stored broker cancellation event sequence is invalid")
    if len(rows) == 1:
        return "uncertain", started
    acknowledged = rows[1]
    if (
        acknowledged[0] != 2
        or acknowledged[1:3] != started[1:3]
        or acknowledged[3] != "cancellation_acknowledged"
        or any(value is None for value in acknowledged[4:7])
    ):
        raise BrokerStateError("stored broker cancellation event sequence is invalid")
    return "acknowledged", acknowledged


def begin_cancellation(
    con: duckdb.DuckDBPyConnection,
    *,
    cancellation_key: str,
    account_id: str,
    broker_order_id: str,
    now: datetime | None = None,
) -> CancellationState:
    """Persist cancellation uncertainty before invoking an adapter."""
    require_identifier(cancellation_key, "cancellation key")
    require_identifier(account_id, "account identifier")
    require_identifier(broker_order_id, "broker order identifier")
    state, event = _cancellation_events(con, cancellation_key)
    if state is None:
        con.execute(
            "INSERT INTO broker_cancellation_events "
            "(cancellation_key, event_sequence, account_id, broker_order_id, "
            "event_type, order_sha256, order_payload, occurred_at) "
            "VALUES (?, 1, ?, ?, 'cancellation_started', NULL, NULL, ?)",
            [cancellation_key, account_id, broker_order_id, now or _now()],
        )
        return "uncertain"
    if event is None or event[1:3] != (account_id, broker_order_id):
        raise BrokerStateError("stored broker cancellation conflicts with request")
    if state == "uncertain":
        raise BrokerCancellationUncertain(
            f"cancellation {cancellation_key!r} is uncertain and requires reconciliation"
        )
    return "acknowledged"


def acknowledge_cancellation(
    con: duckdb.DuckDBPyConnection,
    *,
    cancellation_key: str,
    account_id: str,
    broker_order_id: str,
    order: BrokerOrder,
    now: datetime | None = None,
) -> None:
    """Bind one exact cancelled-order acknowledgement to a started cancellation."""
    if (
        not isinstance(order, BrokerOrder)
        or order.account_id != account_id
        or order.broker_order_id != broker_order_id
        or order.status != "cancelled"
    ):
        raise BrokerStateError(
            "adapter cancellation acknowledgement does not match request"
        )
    state, event = _cancellation_events(con, cancellation_key)
    if state is None or event is None:
        raise BrokerStateError("broker cancellation was not durably started")
    if event[1:3] != (account_id, broker_order_id):
        raise BrokerStateError("stored broker cancellation conflicts with request")
    payload = _canonical(_order_payload(order))
    digest = canonical_sha256(json.loads(payload))
    if state == "acknowledged":
        if event[4:6] != (digest, payload):
            raise BrokerStateError(
                "stored broker cancellation acknowledgement conflicts with adapter order"
            )
        return
    con.execute(
        "INSERT INTO broker_cancellation_events "
        "(cancellation_key, event_sequence, account_id, broker_order_id, "
        "event_type, order_sha256, order_payload, occurred_at) "
        "VALUES (?, 2, ?, ?, 'cancellation_acknowledged', ?, ?, ?)",
        [
            cancellation_key,
            account_id,
            broker_order_id,
            digest,
            payload,
            now or _now(),
        ],
    )


def cancellation_state(
    con: duckdb.DuckDBPyConnection,
    cancellation_key: str,
) -> CancellationState | None:
    """Return verified cancellation lifecycle state."""
    require_identifier(cancellation_key, "cancellation key")
    state, _event = _cancellation_events(con, cancellation_key)
    return state


def acknowledged_cancellation_order(
    con: duckdb.DuckDBPyConnection,
    cancellation_key: str,
) -> BrokerOrder | None:
    """Return the exact verified cancelled order, if acknowledged."""
    require_identifier(cancellation_key, "cancellation key")
    state, event = _cancellation_events(con, cancellation_key)
    if state is None or state == "uncertain":
        return None
    if state != "acknowledged" or event is None:
        raise BrokerStateError("stored broker cancellation state is invalid")
    order = _order_from_payload(event[5])
    if (
        order.account_id != event[1]
        or order.broker_order_id != event[2]
        or order.status != "cancelled"
        or canonical_sha256(json.loads(event[5])) != event[4]
        or _canonical(_order_payload(order)) != event[5]
    ):
        raise BrokerStateError(
            "stored broker cancellation acknowledgement is invalid"
        )
    return order


def cancellation_states_for_account(
    con: duckdb.DuckDBPyConnection,
    account_id: str,
) -> dict[str, CancellationState]:
    """Return every verified cancellation state for one account."""
    require_identifier(account_id, "account identifier")
    keys = con.execute(
        "SELECT DISTINCT cancellation_key FROM broker_cancellation_events "
        "WHERE account_id = ? ORDER BY cancellation_key",
        [account_id],
    ).fetchall()
    result = {}
    for (cancellation_key,) in keys:
        require_identifier(cancellation_key, "cancellation key")
        state, event = _cancellation_events(con, cancellation_key)
        if (
            state not in {"uncertain", "acknowledged"}
            or event is None
            or event[1] != account_id
        ):
            raise BrokerStateError("stored broker cancellation account state is invalid")
        result[cancellation_key] = state
    return result


def emergency_stop_events(
    con: duckdb.DuckDBPyConnection,
    halt_key: str,
) -> tuple[dict, ...]:
    """Return one verified start event and an optional completion event."""
    require_identifier(halt_key, "halt key")
    rows = con.execute(
        "SELECT event_sequence, account_id, event_type, event_sha256, "
        "event_payload, occurred_at FROM broker_emergency_stop_events "
        "WHERE halt_key = ? ORDER BY event_sequence",
        [halt_key],
    ).fetchall()
    if len(rows) > len(EMERGENCY_STOP_EVENT_TYPES):
        raise BrokerStateError("stored emergency-stop event sequence is invalid")
    events = []
    account_id = None
    prior_occurred_at = None
    for sequence, row in enumerate(rows, 1):
        (
            event_sequence,
            stored_account,
            event_type,
            event_sha256,
            event_payload,
            occurred_at,
        ) = row
        try:
            require_identifier(stored_account, "account identifier")
            payload = json.loads(event_payload)
            parsed_at = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
            canonical_at = _timestamp(parsed_at)
        except (TypeError, ValueError) as exc:
            raise BrokerStateError("stored emergency-stop event is invalid") from exc
        if (
            event_sequence != sequence
            or event_type != EMERGENCY_STOP_EVENT_TYPES[sequence - 1]
            or account_id not in {None, stored_account}
            or occurred_at is None
            or not isinstance(payload, dict)
            or payload.get("halt_key") != halt_key
            or payload.get("account_id") != stored_account
            or canonical_at != occurred_at
            or payload.get("occurred_at") != canonical_at
            or (
                prior_occurred_at is not None
                and parsed_at < prior_occurred_at
            )
            or canonical_sha256(payload) != event_sha256
            or _canonical(payload) != event_payload
        ):
            raise BrokerStateError("stored emergency-stop event is invalid")
        account_id = stored_account
        prior_occurred_at = parsed_at
        events.append(payload)
    return tuple(events)


def emergency_stop_states_for_account(
    con: duckdb.DuckDBPyConnection,
    account_id: str,
) -> dict[str, Literal["started", "completed"]]:
    """Return every verified emergency-stop lifecycle for one account."""
    require_identifier(account_id, "account identifier")
    rows = con.execute(
        "SELECT DISTINCT halt_key FROM broker_emergency_stop_events "
        "WHERE account_id = ? ORDER BY halt_key",
        [account_id],
    ).fetchall()
    result = {}
    for (halt_key,) in rows:
        events = emergency_stop_events(con, halt_key)
        if not events or any(event.get("account_id") != account_id for event in events):
            raise BrokerStateError("stored emergency-stop account state is invalid")
        result[halt_key] = "completed" if len(events) == 2 else "started"
    return result


def record_emergency_stop_event(
    con: duckdb.DuckDBPyConnection,
    *,
    halt_key: str,
    account_id: str,
    event_type: str,
    payload: dict,
    now: datetime | None = None,
) -> str:
    """Append one exact emergency-stop lifecycle event, accepting exact replay."""
    require_identifier(halt_key, "halt key")
    require_identifier(account_id, "account identifier")
    if event_type not in EMERGENCY_STOP_EVENT_TYPES:
        raise ValueError("emergency-stop event type is invalid")
    if (
        not isinstance(payload, dict)
        or payload.get("halt_key") != halt_key
        or payload.get("account_id") != account_id
    ):
        raise ValueError("emergency-stop event payload is invalid")
    occurred_at = _timestamp(now)
    if payload.get("occurred_at") != occurred_at:
        raise ValueError("emergency-stop event timestamp is invalid")
    events = emergency_stop_events(con, halt_key)
    sequence = EMERGENCY_STOP_EVENT_TYPES.index(event_type) + 1
    encoded = _canonical(payload)
    digest = canonical_sha256(payload)
    existing = con.execute(
        "SELECT account_id, event_type, event_sha256, event_payload "
        "FROM broker_emergency_stop_events "
        "WHERE halt_key = ? AND event_sequence = ?",
        [halt_key, sequence],
    ).fetchone()
    expected = (account_id, event_type, digest, encoded)
    if existing is not None:
        if existing != expected:
            raise BrokerStateError("stored emergency-stop event conflicts with request")
        return digest
    if len(events) != sequence - 1:
        raise BrokerStateError("emergency-stop event sequence is invalid")
    if event_type == "emergency_stop_started":
        active = [
            key
            for key, state in emergency_stop_states_for_account(con, account_id).items()
            if state == "started" and key != halt_key
        ]
        if active:
            raise BrokerStateError(
                "another emergency-stop operation is already in progress"
            )
    con.execute(
        "INSERT INTO broker_emergency_stop_events "
        "(halt_key, event_sequence, account_id, event_type, event_sha256, "
        "event_payload, occurred_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [halt_key, sequence, account_id, event_type, digest, encoded, occurred_at],
    )
    return digest


def record_order_observation(
    con: duckdb.DuckDBPyConnection,
    *,
    observation_key: str,
    order: BrokerOrder,
    now: datetime | None = None,
) -> str:
    """Append an immutable adapter-order observation, accepting exact replay."""
    require_identifier(observation_key, "order observation key")
    payload = _canonical(_order_payload(order))
    digest = canonical_sha256(json.loads(payload))
    row = con.execute(
        "SELECT account_id, broker_order_id, order_sha256, order_payload "
        "FROM broker_order_observations WHERE observation_key = ?",
        [observation_key],
    ).fetchone()
    expected = (order.account_id, order.broker_order_id, digest, payload)
    if row is None:
        con.execute(
            "INSERT INTO broker_order_observations "
            "(observation_key, account_id, broker_order_id, order_sha256, "
            "order_payload, observed_at) VALUES (?, ?, ?, ?, ?, ?)",
            [observation_key, *expected, now or _now()],
        )
        return digest
    if row != expected:
        raise BrokerStateError(
            "stored broker order observation conflicts with observation key"
        )
    return digest


def record_execution(
    con: duckdb.DuckDBPyConnection,
    fill: BrokerFill,
    *,
    now: datetime | None = None,
) -> str:
    """Append an immutable execution observation, accepting exact replay."""
    payload = _canonical(_fill_payload(fill))
    digest = canonical_sha256(json.loads(payload))
    row = con.execute(
        "SELECT account_id, broker_order_id, execution_sha256, execution_payload "
        "FROM broker_executions WHERE execution_id = ?",
        [fill.execution_id],
    ).fetchone()
    expected = (fill.account_id, fill.broker_order_id, digest, payload)
    if row is None:
        con.execute(
            "INSERT INTO broker_executions "
            "(execution_id, account_id, broker_order_id, execution_sha256, "
            "execution_payload, observed_at) VALUES (?, ?, ?, ?, ?, ?)",
            [
                fill.execution_id,
                fill.account_id,
                fill.broker_order_id,
                digest,
                payload,
                now or _now(),
            ],
        )
        return digest
    if row != expected:
        raise BrokerStateError("stored broker execution conflicts with execution identifier")
    return digest


def record_snapshot(
    con: duckdb.DuckDBPyConnection,
    *,
    snapshot_key: str,
    reconciliation_key: str,
    role: Literal["expected", "observed"],
    account_id: str,
    snapshot: object,
    now: datetime | None = None,
) -> str:
    """Append one exact adapter snapshot, accepting only exact replay."""
    require_identifier(snapshot_key, "snapshot key")
    require_identifier(reconciliation_key, "reconciliation key")
    require_identifier(account_id, "account identifier")
    if role not in {"expected", "observed"}:
        raise ValueError("snapshot role is invalid")
    payload = _canonical(snapshot)
    digest = canonical_sha256(json.loads(payload))
    row = con.execute(
        "SELECT reconciliation_key, role, account_id, snapshot_sha256, "
        "snapshot_payload FROM broker_snapshots WHERE snapshot_key = ?",
        [snapshot_key],
    ).fetchone()
    expected = (reconciliation_key, role, account_id, digest, payload)
    if row is None:
        con.execute(
            "INSERT INTO broker_snapshots "
            "(snapshot_key, reconciliation_key, role, account_id, snapshot_sha256, "
            "snapshot_payload, observed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [snapshot_key, *expected, now or _now()],
        )
        return digest
    if row != expected:
        raise BrokerStateError("stored broker snapshot conflicts with snapshot key")
    return digest


def record_reconciliation(
    con: duckdb.DuckDBPyConnection,
    *,
    reconciliation_key: str,
    account_id: str,
    status: ReconciliationStatus,
    expected: object | None,
    observed: object | None,
    detail: str,
    now: datetime | None = None,
) -> None:
    """Append one immutable reconciliation result, accepting exact replay."""
    require_identifier(reconciliation_key, "reconciliation key")
    require_identifier(account_id, "account identifier")
    if status not in {"match", "difference", "unavailable"}:
        raise ValueError("reconciliation status is invalid")
    if not isinstance(detail, str) or not detail.strip() or len(detail) > MAX_DETAIL_CHARS:
        raise ValueError("reconciliation detail is invalid")
    expected_payload = None if expected is None else _canonical(expected)
    observed_payload = None if observed is None else _canonical(observed)
    expected_sha256 = (
        None if expected_payload is None else canonical_sha256(json.loads(expected_payload))
    )
    observed_sha256 = (
        None if observed_payload is None else canonical_sha256(json.loads(observed_payload))
    )
    if status == "match" and (
        expected_sha256 is None or expected_sha256 != observed_sha256
    ):
        raise ValueError("matching reconciliation requires equal expected and observed state")
    row = con.execute(
        "SELECT account_id, status, expected_sha256, observed_sha256, "
        "expected_payload, observed_payload, detail "
        "FROM broker_reconciliations WHERE reconciliation_key = ?",
        [reconciliation_key],
    ).fetchone()
    expected_row = (
        account_id,
        status,
        expected_sha256,
        observed_sha256,
        expected_payload,
        observed_payload,
        detail,
    )
    if row is None:
        con.execute(
            "INSERT INTO broker_reconciliations "
            "(reconciliation_key, account_id, status, expected_sha256, "
            "observed_sha256, expected_payload, observed_payload, detail, observed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [reconciliation_key, *expected_row, now or _now()],
        )
        return
    if row != expected_row:
        raise BrokerStateError("stored broker reconciliation conflicts with key")


def record_reconciliation_differences(
    con: duckdb.DuckDBPyConnection,
    *,
    reconciliation_key: str,
    differences: tuple[dict, ...],
    now: datetime | None = None,
) -> None:
    """Append one complete ordered discrepancy set, accepting exact replay."""
    require_identifier(reconciliation_key, "reconciliation key")
    if not isinstance(differences, tuple):
        raise ValueError("reconciliation differences must be a tuple")
    reconciliation = con.execute(
        "SELECT status FROM broker_reconciliations WHERE reconciliation_key = ?",
        [reconciliation_key],
    ).fetchone()
    if reconciliation is None:
        raise BrokerStateError("broker reconciliation result is unavailable")
    if (reconciliation[0] == "match") != (len(differences) == 0):
        raise BrokerStateError(
            "broker reconciliation difference count conflicts with result status"
        )
    expected_rows = []
    for sequence, difference in enumerate(differences, 1):
        if not isinstance(difference, dict):
            raise ValueError("reconciliation difference is invalid")
        payload = _canonical(difference)
        expected_rows.append(
            (
                sequence,
                canonical_sha256(json.loads(payload)),
                payload,
            )
        )
    stored_rows = con.execute(
        "SELECT difference_sequence, difference_sha256, difference_payload "
        "FROM broker_reconciliation_differences WHERE reconciliation_key = ? "
        "ORDER BY difference_sequence",
        [reconciliation_key],
    ).fetchall()
    if stored_rows:
        if stored_rows != expected_rows:
            raise BrokerStateError(
                "stored broker reconciliation differences conflict with key"
            )
        return
    if not expected_rows:
        return
    con.executemany(
        "INSERT INTO broker_reconciliation_differences "
        "(reconciliation_key, difference_sequence, difference_sha256, "
        "difference_payload, recorded_at) VALUES (?, ?, ?, ?, ?)",
        [
            (reconciliation_key, sequence, digest, payload, now or _now())
            for sequence, digest, payload in expected_rows
        ],
    )


def submission_state(
    con: duckdb.DuckDBPyConnection,
    idempotency_key: str,
) -> SubmissionState | None:
    require_identifier(idempotency_key, "idempotency key")
    state, _event = _submission_events(con, idempotency_key)
    return state


def uncertain_submission_request(
    con: duckdb.DuckDBPyConnection,
    idempotency_key: str,
) -> SubmitOrderRequest:
    """Return the verified immutable request for one uncertain submission."""
    require_identifier(idempotency_key, "idempotency key")
    state, event = _submission_events(con, idempotency_key)
    if state != "uncertain" or event is None:
        raise BrokerStateError("broker submission is not uncertain")
    row = con.execute(
        "SELECT account_id, intent_sha256, intent_payload FROM broker_intents "
        "WHERE idempotency_key = ?",
        [idempotency_key],
    ).fetchone()
    if row is None:
        raise BrokerStateError("uncertain broker submission has no intent")
    account_id, intent_sha256, intent_payload = row
    request = _request_from_payload(intent_payload)
    if (
        request.idempotency_key != idempotency_key
        or request.account_id != account_id
        or event[1:3] != (account_id, intent_sha256)
        or canonical_sha256(json.loads(intent_payload)) != intent_sha256
        or _canonical(_intent_payload(request)) != intent_payload
    ):
        raise BrokerStateError("uncertain broker submission intent is invalid")
    return request


def _fill_from_payload(payload: object) -> BrokerFill:
    expected_fields = {
        "execution_id",
        "broker_order_id",
        "idempotency_key",
        "account_id",
        "symbol",
        "side",
        "quantity",
        "occurred_on",
        "reference_price",
        "price",
        "total_cost_bps",
    }
    if not isinstance(payload, dict) or set(payload) != expected_fields:
        raise BrokerStateError("stored submission resolution evidence is invalid")
    try:
        occurred_on = datetime.strptime(payload["occurred_on"], "%Y-%m-%d").date()
        return BrokerFill(
            execution_id=payload["execution_id"],
            broker_order_id=payload["broker_order_id"],
            idempotency_key=payload["idempotency_key"],
            account_id=payload["account_id"],
            symbol=payload["symbol"],
            side=payload["side"],
            quantity=payload["quantity"],
            occurred_on=occurred_on,
            reference_price=payload["reference_price"],
            price=payload["price"],
            total_cost_bps=payload["total_cost_bps"],
        )
    except (TypeError, ValueError) as exc:
        raise BrokerStateError(
            "stored submission resolution evidence is invalid"
        ) from exc


def _resolution_evidence_payload(
    *,
    account: BrokerAccount,
    positions: tuple[BrokerPosition, ...],
    open_orders: tuple[BrokerOrder, ...],
    fills: tuple[BrokerFill, ...],
) -> dict:
    if (
        not isinstance(account, BrokerAccount)
        or not isinstance(positions, tuple)
        or len(positions) > MAX_ACCOUNT_ROWS
        or not all(isinstance(item, BrokerPosition) for item in positions)
        or not isinstance(open_orders, tuple)
        or len(open_orders) > MAX_ACCOUNT_ROWS
        or not all(isinstance(item, BrokerOrder) for item in open_orders)
        or not isinstance(fills, tuple)
        or len(fills) > MAX_RESOLUTION_FILLS
        or not all(isinstance(item, BrokerFill) for item in fills)
    ):
        raise ValueError("submission resolution evidence is invalid")
    scoped = (*positions, *open_orders, *fills)
    if any(item.account_id != account.account_id for item in scoped):
        raise ValueError("submission resolution evidence crosses account scope")
    if any(
        order.status not in {"pending", "partially_filled"}
        for order in open_orders
    ):
        raise ValueError("submission resolution evidence contains a terminal open order")
    if (
        positions != tuple(sorted(positions, key=lambda item: item.symbol))
        or open_orders
        != tuple(sorted(open_orders, key=lambda item: item.idempotency_key))
        or fills
        != tuple(
            sorted(
                fills,
                key=lambda item: (
                    item.idempotency_key,
                    item.occurred_on,
                    item.execution_id,
                ),
            )
        )
    ):
        raise ValueError("submission resolution evidence is not canonically ordered")
    if (
        len({item.symbol for item in positions}) != len(positions)
        or len({item.idempotency_key for item in open_orders}) != len(open_orders)
        or len({item.broker_order_id for item in open_orders}) != len(open_orders)
        or len({item.execution_id for item in fills}) != len(fills)
    ):
        raise ValueError("submission resolution evidence contains duplicate identifiers")
    return {
        "schema_version": SUBMISSION_RESOLUTION_SCHEMA_VERSION,
        "account": asdict(account),
        "positions": [asdict(item) for item in positions],
        "open_orders": [_order_payload(item) for item in open_orders],
        "fills": [_fill_payload(item) for item in fills],
    }


def _resolution_evidence_objects(
    evidence: object,
) -> tuple[
    BrokerAccount,
    tuple[BrokerPosition, ...],
    tuple[BrokerOrder, ...],
    tuple[BrokerFill, ...],
]:
    if (
        not isinstance(evidence, dict)
        or set(evidence)
        != {"schema_version", "account", "positions", "open_orders", "fills"}
        or evidence["schema_version"] != SUBMISSION_RESOLUTION_SCHEMA_VERSION
        or not isinstance(evidence["account"], dict)
        or not isinstance(evidence["positions"], list)
        or not isinstance(evidence["open_orders"], list)
        or not isinstance(evidence["fills"], list)
    ):
        raise BrokerStateError("stored submission resolution evidence is invalid")
    try:
        account = BrokerAccount(**evidence["account"])
        positions = tuple(BrokerPosition(**item) for item in evidence["positions"])
        open_orders = tuple(
            _order_from_payload(_canonical(item)) for item in evidence["open_orders"]
        )
        fills = tuple(_fill_from_payload(item) for item in evidence["fills"])
        rebuilt = _resolution_evidence_payload(
            account=account,
            positions=positions,
            open_orders=open_orders,
            fills=fills,
        )
    except (TypeError, ValueError) as exc:
        raise BrokerStateError(
            "stored submission resolution evidence is invalid"
        ) from exc
    if rebuilt != evidence:
        raise BrokerStateError("stored submission resolution evidence is invalid")
    return account, positions, open_orders, fills


def _resolution_classification(
    request: SubmitOrderRequest,
    *,
    account: BrokerAccount,
    open_orders: tuple[BrokerOrder, ...],
    fills: tuple[BrokerFill, ...],
) -> tuple[SubmissionResolutionOutcome, tuple[str, ...], tuple[str, ...], float]:
    if account.account_id != request.account_id:
        raise BrokerStateError("submission resolution evidence targets another account")
    matching_orders = tuple(
        order for order in open_orders if order.idempotency_key == request.idempotency_key
    )
    matching_fills = tuple(
        fill for fill in fills if fill.idempotency_key == request.idempotency_key
    )
    if len(matching_orders) > 1:
        raise BrokerStateError("submission resolution evidence is ambiguous")
    expected_order_terms = (
        request.account_id,
        request.symbol,
        request.side,
        request.quantity,
        request.signal_date,
        request.order_type,
        request.time_in_force,
        request.extended_hours,
    )
    for order in matching_orders:
        actual = (
            order.account_id,
            order.symbol,
            order.side,
            order.quantity,
            order.signal_date,
            order.order_type,
            order.time_in_force,
            order.extended_hours,
        )
        if actual != expected_order_terms:
            raise BrokerStateError(
                "submission resolution order conflicts with immutable intent"
            )
    for fill in matching_fills:
        if (
            fill.account_id,
            fill.symbol,
            fill.side,
        ) != (
            request.account_id,
            request.symbol,
            request.side,
        ):
            raise BrokerStateError(
                "submission resolution fill conflicts with immutable intent"
            )
    broker_order_ids = {
        *(order.broker_order_id for order in matching_orders),
        *(fill.broker_order_id for fill in matching_fills),
    }
    if len(broker_order_ids) > 1:
        raise BrokerStateError(
            "submission resolution evidence has conflicting broker order identifiers"
        )
    filled_quantity = math.fsum(fill.quantity for fill in matching_fills)
    if (
        not math.isfinite(filled_quantity)
        or filled_quantity < 0
        or filled_quantity > request.quantity
    ):
        raise BrokerStateError("submission resolution evidence exceeds intent quantity")
    if matching_orders:
        order = matching_orders[0]
        if order.filled_quantity != filled_quantity:
            raise BrokerStateError(
                "submission resolution order and fill evidence disagree"
            )
        outcome: SubmissionResolutionOutcome = "observed_open"
    elif filled_quantity == request.quantity:
        outcome = "observed_filled"
    elif filled_quantity > 0:
        outcome = "observed_terminal_partial_fill"
    else:
        outcome = "not_observed_burned"
    return (
        outcome,
        tuple(sorted(order.broker_order_id for order in matching_orders)),
        tuple(sorted(fill.execution_id for fill in matching_fills)),
        filled_quantity,
    )


def _verified_resolution_control(
    con: duckdb.DuckDBPyConnection,
    account_id: str,
    payload: object,
    payload_sha256: object,
    *,
    resolution_at: datetime,
) -> None:
    expected_fields = {
        "schema_version",
        "account_id",
        "halted",
        "reason",
        "event_count",
        "latest_event_sha256",
        "execution_authority",
    }
    if (
        not isinstance(payload, dict)
        or set(payload) != expected_fields
        or payload.get("account_id") != account_id
        or payload.get("halted") is not True
        or payload.get("execution_authority") != "none"
        or isinstance(payload.get("event_count"), bool)
        or not isinstance(payload.get("event_count"), int)
        or payload["event_count"] < 1
        or canonical_sha256(payload) != payload_sha256
    ):
        raise BrokerStateError("stored submission resolution control is invalid")
    current = broker_risk_control.status(con, account_id)
    if current.event_count < payload["event_count"]:
        raise BrokerStateError("stored submission resolution control is invalid")
    row = con.execute(
        "SELECT halt_key, reason, occurred_at, prior_event_sha256, event_sha256 "
        "FROM broker_risk_control_events "
        "WHERE account_id = ? AND event_sequence = ?",
        [account_id, payload["event_count"]],
    ).fetchone()
    if row is None:
        raise BrokerStateError("stored submission resolution control is invalid")
    halt_key, reason, occurred_at, prior_event_sha256, event_sha256 = row
    try:
        halt_at = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise BrokerStateError(
            "stored submission resolution control is invalid"
        ) from exc
    expected = {
        "schema_version": broker_risk_control.CONTROL_SCHEMA_VERSION,
        "account_id": account_id,
        "halted": True,
        "reason": reason,
        "event_count": payload["event_count"],
        "latest_event_sha256": event_sha256,
        "execution_authority": "none",
    }
    halt_body = {
        "schema_version": broker_risk_control.CONTROL_SCHEMA_VERSION,
        "halt_key": halt_key,
        "account_id": account_id,
        "event_sequence": payload["event_count"],
        "event_type": "halt",
        "reason": reason,
        "occurred_at": occurred_at,
        "prior_event_sha256": prior_event_sha256,
        "execution_authority": "none",
    }
    if (
        payload != expected
        or canonical_sha256(halt_body) != event_sha256
        or halt_at > resolution_at
    ):
        raise BrokerStateError("stored submission resolution control is invalid")


def _verified_submission_resolution(
    con: duckdb.DuckDBPyConnection,
    idempotency_key: str,
) -> dict | None:
    if not con.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'broker_submission_resolutions'"
    ).fetchone():
        return None
    row = con.execute(
        "SELECT resolution_key, account_id, intent_sha256, outcome, "
        "control_sha256, evidence_sha256, evidence_payload, resolution_sha256, "
        "resolution_payload, observed_at "
        "FROM broker_submission_resolutions WHERE idempotency_key = ?",
        [idempotency_key],
    ).fetchone()
    if row is None:
        return None
    (
        resolution_key,
        account_id,
        intent_sha256,
        outcome,
        control_sha256,
        evidence_sha256,
        evidence_encoded,
        resolution_sha256,
        encoded,
        observed_at,
    ) = row
    try:
        require_identifier(resolution_key, "submission resolution key")
        require_identifier(account_id, "account identifier")
        payload = json.loads(encoded)
        evidence = json.loads(evidence_encoded)
        parsed_at = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        canonical_at = _timestamp(parsed_at)
    except (TypeError, ValueError) as exc:
        raise BrokerStateError("stored submission resolution is invalid") from exc
    expected_fields = {
        "schema_version",
        "resolution_key",
        "idempotency_key",
        "account_id",
        "intent_sha256",
        "outcome",
        "operational_control",
        "operational_control_sha256",
        "evidence_sha256",
        "observed_at",
        "matching_order_ids",
        "matching_execution_ids",
        "observed_filled_quantity",
        "retry_permitted",
        "submission_authority",
    }
    if (
        not isinstance(payload, dict)
        or set(payload) != expected_fields
        or payload["schema_version"] != SUBMISSION_RESOLUTION_SCHEMA_VERSION
        or payload["resolution_key"] != resolution_key
        or payload["idempotency_key"] != idempotency_key
        or payload["account_id"] != account_id
        or payload["intent_sha256"] != intent_sha256
        or payload["outcome"] != outcome
        or payload["operational_control_sha256"] != control_sha256
        or payload["evidence_sha256"] != evidence_sha256
        or payload["observed_at"] != canonical_at
        or payload["retry_permitted"] is not False
        or payload["submission_authority"] != "none"
        or outcome
        not in {
            "observed_open",
            "observed_filled",
            "observed_terminal_partial_fill",
            "not_observed_burned",
        }
        or _canonical(payload) != encoded
        or canonical_sha256(payload) != resolution_sha256
        or _canonical(evidence) != evidence_encoded
        or canonical_sha256(evidence) != evidence_sha256
    ):
        raise BrokerStateError("stored submission resolution is invalid")
    intent_row = con.execute(
        "SELECT account_id, intent_sha256, intent_payload FROM broker_intents "
        "WHERE idempotency_key = ?",
        [idempotency_key],
    ).fetchone()
    if intent_row is None:
        raise BrokerStateError("stored submission resolution has no intent")
    request = _request_from_payload(intent_row[2])
    if (
        intent_row[:2] != (account_id, intent_sha256)
        or request.idempotency_key != idempotency_key
        or canonical_sha256(json.loads(intent_row[2])) != intent_sha256
    ):
        raise BrokerStateError("stored submission resolution intent is invalid")
    account, _positions, open_orders, fills = _resolution_evidence_objects(evidence)
    (
        derived_outcome,
        matching_order_ids,
        matching_execution_ids,
        observed_filled_quantity,
    ) = _resolution_classification(
        request,
        account=account,
        open_orders=open_orders,
        fills=fills,
    )
    _verified_resolution_control(
        con,
        account_id,
        payload["operational_control"],
        control_sha256,
        resolution_at=parsed_at,
    )
    state, started = _submission_events(con, idempotency_key)
    if state != "uncertain" or started is None:
        raise BrokerStateError("stored submission resolution has no uncertain attempt")
    started_at = started[7]
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    if (
        parsed_at < started_at.astimezone(timezone.utc)
        or derived_outcome != outcome
        or payload["matching_order_ids"] != list(matching_order_ids)
        or payload["matching_execution_ids"] != list(matching_execution_ids)
        or payload["observed_filled_quantity"] != observed_filled_quantity
    ):
        raise BrokerStateError("stored submission resolution is invalid")
    return {**payload, "resolution_sha256": resolution_sha256}


def record_submission_resolution(
    con: duckdb.DuckDBPyConnection,
    *,
    request: SubmitOrderRequest,
    resolution_key: str,
    account: BrokerAccount,
    positions: tuple[BrokerPosition, ...],
    open_orders: tuple[BrokerOrder, ...],
    fills: tuple[BrokerFill, ...],
    now: datetime,
) -> dict:
    """Append terminal reconciliation evidence without permitting a retry."""
    require_identifier(resolution_key, "submission resolution key")
    request_from_ledger = uncertain_submission_request(con, request.idempotency_key)
    if request_from_ledger != request:
        raise BrokerStateError("submission resolution request conflicts with intent")
    evidence = _resolution_evidence_payload(
        account=account,
        positions=positions,
        open_orders=open_orders,
        fills=fills,
    )
    outcome, matching_order_ids, matching_execution_ids, filled_quantity = (
        _resolution_classification(
            request,
            account=account,
            open_orders=open_orders,
            fills=fills,
        )
    )
    control = broker_risk_control.status(con, request.account_id)
    if not control.halted or control.event_count < 1:
        raise BrokerStateError(
            "submission resolution requires durable halted control"
        )
    control_payload = asdict(control)
    control_sha256 = canonical_sha256(control_payload)
    evidence_encoded = _canonical(evidence)
    evidence_sha256 = canonical_sha256(evidence)
    intent_sha256 = canonical_sha256(_intent_payload(request))
    observed_at = _timestamp(now)
    state, started = _submission_events(con, request.idempotency_key)
    if state != "uncertain" or started is None:
        raise BrokerStateError("broker submission is not uncertain")
    started_at = started[7]
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    if now < started_at.astimezone(timezone.utc):
        raise ValueError("submission resolution precedes submission start")
    existing = _verified_submission_resolution(con, request.idempotency_key)
    if existing is not None:
        expected_replay = {
            "resolution_key": resolution_key,
            "idempotency_key": request.idempotency_key,
            "account_id": request.account_id,
            "intent_sha256": intent_sha256,
            "outcome": outcome,
            "evidence_sha256": evidence_sha256,
            "observed_at": observed_at,
            "matching_order_ids": list(matching_order_ids),
            "matching_execution_ids": list(matching_execution_ids),
            "observed_filled_quantity": filled_quantity,
            "retry_permitted": False,
            "submission_authority": "none",
        }
        if any(existing.get(key) != value for key, value in expected_replay.items()):
            raise BrokerStateError(
                "stored submission resolution conflicts with idempotency key"
            )
        return existing
    body = {
        "schema_version": SUBMISSION_RESOLUTION_SCHEMA_VERSION,
        "resolution_key": resolution_key,
        "idempotency_key": request.idempotency_key,
        "account_id": request.account_id,
        "intent_sha256": intent_sha256,
        "outcome": outcome,
        "operational_control": control_payload,
        "operational_control_sha256": control_sha256,
        "evidence_sha256": evidence_sha256,
        "observed_at": observed_at,
        "matching_order_ids": list(matching_order_ids),
        "matching_execution_ids": list(matching_execution_ids),
        "observed_filled_quantity": filled_quantity,
        "retry_permitted": False,
        "submission_authority": "none",
    }
    encoded = _canonical(body)
    digest = canonical_sha256(body)
    conflict = con.execute(
        "SELECT idempotency_key FROM broker_submission_resolutions "
        "WHERE resolution_key = ?",
        [resolution_key],
    ).fetchone()
    if conflict is not None:
        raise BrokerStateError("submission resolution key is already used")
    con.execute(
        "INSERT INTO broker_submission_resolutions "
        "(idempotency_key, resolution_key, account_id, intent_sha256, outcome, "
        "control_sha256, evidence_sha256, evidence_payload, resolution_sha256, "
        "resolution_payload, observed_at) VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            request.idempotency_key,
            resolution_key,
            request.account_id,
            intent_sha256,
            outcome,
            control_sha256,
            evidence_sha256,
            evidence_encoded,
            digest,
            encoded,
            observed_at,
        ],
    )
    return {**body, "resolution_sha256": digest}


def submission_resolution(
    con: duckdb.DuckDBPyConnection,
    idempotency_key: str,
) -> dict | None:
    """Return verified terminal adjudication; it never permits retry."""
    require_identifier(idempotency_key, "idempotency key")
    return _verified_submission_resolution(con, idempotency_key)


def acknowledged_order(
    con: duckdb.DuckDBPyConnection,
    idempotency_key: str,
) -> BrokerOrder | None:
    """Return and verify the immutable acknowledged order, if one exists."""
    require_identifier(idempotency_key, "idempotency key")
    state, event = _submission_events(con, idempotency_key)
    if state is None:
        return None
    if state == "uncertain":
        return None
    if state != "acknowledged" or event is None:
        raise BrokerStateError("stored broker submission state is invalid")
    (
        _sequence,
        _account_id,
        _intent_sha256,
        _event_type,
        broker_order_id,
        order_sha256,
        order_payload,
        _occurred_at,
    ) = event
    order = _order_from_payload(order_payload)
    if (
        order.broker_order_id != broker_order_id
        or canonical_sha256(json.loads(order_payload)) != order_sha256
        or _canonical(_order_payload(order)) != order_payload
    ):
        raise BrokerStateError("stored broker order acknowledgement is invalid")
    return order
