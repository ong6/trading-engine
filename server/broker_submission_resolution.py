"""Read-only adjudication for broker submissions left uncertain after a call.

This coordinator observes a twice-stable, complete broker snapshot and stores
one immutable resolution. It has no submit, cancel, retry, activation, or
authority surface. Absence at the venue permanently burns the original
idempotency key; it never makes the request retryable.
"""

from __future__ import annotations

from datetime import datetime, timezone

import duckdb

from engine.lib import db

from . import broker_ledger, broker_reconciliation
from .broker_contract import BrokerAdapter, BrokerStateError, require_identifier


def resolve_uncertain(
    con: duckdb.DuckDBPyConnection,
    adapter: BrokerAdapter,
    idempotency_key: str,
    *,
    resolution_key: str,
    now: datetime,
) -> dict:
    """Persist one stable-snapshot adjudication without granting retry."""
    require_identifier(idempotency_key, "idempotency key")
    require_identifier(resolution_key, "submission resolution key")
    if (
        type(now) is not datetime
        or now.utcoffset() is None
        or now.utcoffset().total_seconds() != 0
    ):
        raise ValueError("submission resolution time must be UTC")
    observed_at = now.astimezone(timezone.utc)
    broker_ledger.init_broker_ledger_schema(con)
    existing = broker_ledger.submission_resolution(con, idempotency_key)
    if existing is not None:
        expected_observed_at = observed_at.isoformat().replace("+00:00", "Z")
        if (
            existing["resolution_key"] != resolution_key
            or existing["observed_at"] != expected_observed_at
        ):
            raise BrokerStateError(
                "stored submission resolution conflicts with replay"
            )
        return existing

    request = broker_ledger.uncertain_submission_request(con, idempotency_key)
    snapshot = broker_reconciliation.capture_snapshot(adapter, request.account_id)
    with db.transaction(con):
        result = broker_ledger.record_submission_resolution(
            con,
            request=request,
            resolution_key=resolution_key,
            account=snapshot.account,
            positions=snapshot.positions,
            open_orders=snapshot.open_orders,
            fills=snapshot.fills,
            now=observed_at,
        )
    if (
        result["retry_permitted"] is not False
        or result["submission_authority"] != "none"
    ):
        raise BrokerStateError("submission resolution created forbidden authority")
    return result
