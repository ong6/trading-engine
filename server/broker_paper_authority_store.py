"""Internal transactional writer for automatic-paper activation evidence.

This module can append one already planned ``activation_recorded`` event to an
exact preinstalled retention table. It does not create schema, issue a lease,
load trust, expose a route, schedule work, consume authority, or call an
adapter. Persisted activation evidence remains non-submittable.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import duckdb

from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256

from . import (
    broker_paper_activation_plan,
    broker_paper_authority_transcript,
    broker_paper_startup_store,
)
from .broker_paper_lease import PaperAuthorityLease

STORE_RESULT_SCHEMA_VERSION = 1


class PaperAuthorityStoreError(ValueError):
    """An activation cannot be safely retained in the authority store."""


def _utc(value: object, label: str) -> datetime:
    if (
        type(value) is not datetime
        or value.utcoffset() is None
        or value.utcoffset().total_seconds() != 0
    ):
        raise PaperAuthorityStoreError(f"{label} must be UTC")
    return value.astimezone(timezone.utc)


def _parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PaperAuthorityStoreError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PaperAuthorityStoreError(f"{label} is invalid") from exc
    if parsed.isoformat().replace("+00:00", "Z") != value:
        raise PaperAuthorityStoreError(f"{label} is not canonical")
    return _utc(parsed, label)


def _canonical_json(value: dict) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _verified_rows(
    con: duckdb.DuckDBPyConnection,
    *,
    account_id: str,
) -> tuple[tuple[object, ...], ...]:
    schema = broker_paper_startup_store._table_schema(con)
    if schema != broker_paper_startup_store.RETENTION_SCHEMA:
        raise PaperAuthorityStoreError(
            "paper authority retention table is not preinstalled with exact schema"
        )
    rows = broker_paper_startup_store._capture_rows(con)
    if rows is None:  # pragma: no cover - exact schema check owns this case
        raise PaperAuthorityStoreError(
            "paper authority retention table is not preinstalled with exact schema"
        )
    broker_paper_startup_store._epochs(rows, account_id=account_id)
    return rows


def _row_values(
    lease: PaperAuthorityLease,
    plan: dict,
    *,
    global_sequence: int,
    prior_global_row_sha256: str | None,
) -> dict:
    event = {
        **plan["expected_activation_event"],
        "event_sha256": plan["expected_activation_event_sha256"],
    }
    values = {
        "global_sequence": global_sequence,
        "account_id": lease.account_id,
        "mode": lease.mode,
        "lease_id": lease.lease_id,
        "lease_sha256": lease.sha256(),
        "lease_payload": _canonical_json(lease.payload()),
        "event_sequence": 1,
        "event_type": "activation_recorded",
        "event_payload": _canonical_json(event),
        "event_sha256": event["event_sha256"],
        "trusted_activation_event_sha256": event["event_sha256"],
        "candidate_assessment_sha256": plan["candidate_assessment_sha256"],
        "startup_assessment_sha256": plan["startup_assessment_sha256"],
        "activation_runtime_epoch_sha256": plan["runtime_epoch_sha256"],
        "prior_global_row_sha256": prior_global_row_sha256,
    }
    body = broker_paper_startup_store._retained_row_body(
        **{
            **values,
            "lease_payload": lease.payload(),
            "event_payload": event,
        }
    )
    return {**values, "row_sha256": canonical_sha256(body)}


def _verify_lease_binding(lease: PaperAuthorityLease, plan: object) -> dict:
    if not isinstance(lease, PaperAuthorityLease):
        raise TypeError("lease must be a PaperAuthorityLease")
    try:
        verified = broker_paper_activation_plan.verify_plan(plan)
    except (TypeError, ValueError) as exc:
        raise PaperAuthorityStoreError(
            "paper activation plan verification failed"
        ) from exc
    lease_expiry = lease.expires_at.isoformat().replace("+00:00", "Z")
    event = {
        **verified["expected_activation_event"],
        "event_sha256": verified["expected_activation_event_sha256"],
    }
    if (
        verified["lease_id"] != lease.lease_id
        or verified["lease_sha256"] != lease.sha256()
        or verified["account_id"] != lease.account_id
        or verified["mode"] != lease.mode
        or verified["lease_expires_at"] != lease_expiry
    ):
        raise PaperAuthorityStoreError(
            "paper activation plan does not match the supplied lease"
        )
    try:
        transcript = broker_paper_authority_transcript.verify_transcript(
            lease,
            (event,),
            trusted_activation_event_sha256=event["event_sha256"],
            candidate_assessment_sha256=verified[
                "candidate_assessment_sha256"
            ],
            startup_assessment_sha256=verified["startup_assessment_sha256"],
            activation_runtime_epoch_sha256=verified[
                "runtime_epoch_sha256"
            ],
            current_runtime_epoch_sha256=verified["runtime_epoch_sha256"],
            current_control=broker_paper_authority_transcript.ControlAnchor(
                event_count=verified["control_event_count"],
                latest_event_sha256=verified["control_event_sha256"],
            ),
            now=_parse_timestamp(
                verified["planned_at"],
                "paper activation plan time",
            ),
        )
    except (TypeError, ValueError) as exc:
        raise PaperAuthorityStoreError(
            "paper activation event does not match the supplied lease"
        ) from exc
    if transcript["state"] != "activation_window_open_design_only":
        raise PaperAuthorityStoreError(
            "paper activation event is not an open design-only activation"
        )
    return verified


def _insert_row(
    con: duckdb.DuckDBPyConnection,
    row: dict,
) -> None:
    columns = broker_paper_startup_store._COLUMN_NAMES
    con.execute(
        f"INSERT INTO {broker_paper_startup_store.RETENTION_TABLE} "
        f"({', '.join(columns)}) VALUES "
        f"({', '.join('?' for _ in columns)})",
        [row[name] for name in columns],
    )


def _result(lease: PaperAuthorityLease, plan: dict, row: dict) -> dict:
    body = {
        "schema_version": STORE_RESULT_SCHEMA_VERSION,
        "status": "activation_persisted_for_test_harness",
        "lease_id": lease.lease_id,
        "lease_sha256": lease.sha256(),
        "account_id": lease.account_id,
        "mode": lease.mode,
        "activation_bundle_sha256": plan["activation_bundle_sha256"],
        "activation_event_sha256": plan[
            "expected_activation_event_sha256"
        ],
        "activation_global_sequence": row["global_sequence"],
        "activation_row_sha256": row["row_sha256"],
        "persistence_implemented": True,
        "runtime_activation_implemented": False,
        "consumption_implemented": False,
        "adapter_integration_implemented": False,
        "http_route": "absent",
        "scheduler": "absent",
        "paper_order_route": "absent",
        "submission_authority": "none",
    }
    return {**body, "activation_record_sha256": canonical_sha256(body)}


def record_activation_for_test_harness(
    con: duckdb.DuckDBPyConnection,
    lease: PaperAuthorityLease,
    plan: object,
    *,
    now: datetime,
) -> dict:
    """Append exactly one activation row or return its exact retained replay."""
    verified_plan = _verify_lease_binding(lease, plan)
    observed_at = _utc(now, "paper activation persistence time")
    planned_at = _parse_timestamp(
        verified_plan["planned_at"],
        "paper activation plan time",
    )
    expected_prior_count = verified_plan["expected_prior_global_row_count"]
    expected_prior_head = verified_plan["expected_prior_global_row_sha256"]
    candidate = _row_values(
        lease,
        verified_plan,
        global_sequence=expected_prior_count + 1,
        prior_global_row_sha256=expected_prior_head,
    )
    columns = broker_paper_startup_store._COLUMN_NAMES
    expected_tuple = tuple(candidate[name] for name in columns)

    try:
        with engine_db.transaction(con):
            rows = _verified_rows(con, account_id=lease.account_id)
            if (
                len(rows) >= candidate["global_sequence"]
                and rows[candidate["global_sequence"] - 1] == expected_tuple
            ):
                return _result(lease, verified_plan, candidate)

            identities = {
                "lease_id": lease.lease_id,
                "lease_sha256": lease.sha256(),
                "event_sha256": candidate["event_sha256"],
                "trusted_activation_event_sha256": candidate[
                    "trusted_activation_event_sha256"
                ],
            }
            indexes = {
                name: columns.index(name)
                for name in identities
            }
            if any(
                any(row[indexes[name]] == value for name, value in identities.items())
                for row in rows
            ):
                raise PaperAuthorityStoreError(
                    "paper activation lease or event identity conflicts with retained history"
                )
            actual_head = (
                None
                if not rows
                else rows[-1][columns.index("row_sha256")]
            )
            if (
                len(rows) != expected_prior_count
                or actual_head != expected_prior_head
            ):
                raise PaperAuthorityStoreError(
                    "paper authority retention table does not match the activation plan head"
                )
            if (
                observed_at < planned_at
                or observed_at >= lease.expires_at
                or (
                    observed_at - planned_at
                ).total_seconds()
                > broker_paper_activation_plan.MAX_ACTIVATION_EVIDENCE_AGE_SECONDS
            ):
                raise PaperAuthorityStoreError(
                    "paper activation plan is stale at persistence time"
                )

            _insert_row(con, candidate)
            resulting_rows = _verified_rows(con, account_id=lease.account_id)
            if (
                len(resulting_rows) != len(rows) + 1
                or resulting_rows[:-1] != rows
                or resulting_rows[-1] != expected_tuple
            ):
                raise PaperAuthorityStoreError(
                    "paper activation append failed complete-chain verification"
                )
            return _result(lease, verified_plan, candidate)
    except broker_paper_startup_store.PaperAuthorityStartupStoreError as exc:
        raise PaperAuthorityStoreError(
            "paper authority retention history verification failed"
        ) from exc
    except duckdb.Error as exc:
        raise PaperAuthorityStoreError(
            "paper activation persistence transaction failed"
        ) from exc
