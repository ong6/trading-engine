"""Read-only startup reconciliation assessment for the inert broker boundary."""

from __future__ import annotations

import math
import re
from dataclasses import asdict
from datetime import datetime, timezone

import duckdb

from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists

from . import (
    broker_ledger,
    broker_reconciliation,
    broker_risk_control,
    broker_risk_snapshot,
)
from .broker_contract import (
    MAX_ACCOUNT_ROWS,
    BrokerAdapter,
    BrokerStateError,
    require_identifier,
)

STARTUP_SCHEMA_VERSION = 2
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RESOLUTION_OUTCOMES = frozenset(
    {
        "observed_open",
        "observed_filled",
        "observed_terminal_partial_fill",
        "not_observed_burned",
    }
)


def _utc(value: object) -> datetime:
    if (
        type(value) is not datetime
        or value.utcoffset() is None
        or value.utcoffset().total_seconds() != 0
    ):
        raise ValueError("startup assessment time must be UTC")
    return value.astimezone(timezone.utc)


def _parse_utc(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} is invalid") from exc
    if parsed.isoformat().replace("+00:00", "Z") != value:
        raise ValueError(f"{label} is not canonical")
    try:
        return _utc(parsed)
    except ValueError as exc:
        raise ValueError(f"{label} is invalid") from exc


def _sha256(value: object, label: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def _identifier_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or value != sorted(set(value)):
        raise ValueError(f"{label} must be a sorted unique list")
    for item in value:
        require_identifier(item, label)
    return value


def verify_assessment(
    assessment: object,
    *,
    account_id: str,
    trusted_assessment_sha256: str,
) -> dict:
    """Verify a complete startup artifact without granting authority."""
    require_identifier(account_id, "account identifier")
    trusted_assessment_sha256 = _sha256(
        trusted_assessment_sha256,
        "trusted startup assessment identity",
    )
    expected_fields = {
        "schema_version",
        "account_id",
        "status",
        "safe_halted",
        "submission_authority",
        "observed_at",
        "account_active",
        "account_snapshot_sha256",
        "reconciliation_key",
        "reconciliation_status",
        "reconciliation_observed_at",
        "reconciliation_age_seconds",
        "max_reconciliation_age_seconds",
        "reconciliation_sha256",
        "operational_control",
        "operational_control_sha256",
        "uncertain_submission_keys",
        "resolved_submissions",
        "resolved_open_submission_keys",
        "uncertain_cancellation_keys",
        "incomplete_emergency_stop_keys",
        "reasons",
        "assessment_sha256",
    }
    if not isinstance(assessment, dict) or set(assessment) != expected_fields:
        raise ValueError("startup assessment shape is invalid")
    for field in (
        "account_snapshot_sha256",
        "reconciliation_sha256",
        "operational_control_sha256",
        "assessment_sha256",
    ):
        _sha256(assessment[field], field.replace("_", " "))
    require_identifier(assessment["account_id"], "startup account identifier")
    require_identifier(
        assessment["reconciliation_key"],
        "startup reconciliation identifier",
    )
    observed_at = _parse_utc(assessment["observed_at"], "startup assessment time")
    reconciliation_at = _parse_utc(
        assessment["reconciliation_observed_at"],
        "startup reconciliation time",
    )
    age = assessment["reconciliation_age_seconds"]
    maximum_age = assessment["max_reconciliation_age_seconds"]
    if (
        isinstance(age, bool)
        or not isinstance(age, (int, float))
        or not math.isfinite(age)
        or isinstance(maximum_age, bool)
        or not isinstance(maximum_age, int)
        or not 1 <= maximum_age <= 300
        or not math.isclose(
            float(age),
            (observed_at - reconciliation_at).total_seconds(),
            rel_tol=0.0,
            abs_tol=1e-9,
        )
    ):
        raise ValueError("startup reconciliation age is invalid")
    if assessment["reconciliation_status"] not in {
        "match",
        "difference",
        "unavailable",
    }:
        raise ValueError("startup reconciliation status is invalid")
    if type(assessment["account_active"]) is not bool:
        raise ValueError("startup account state is invalid")

    control = assessment["operational_control"]
    if not isinstance(control, dict) or set(control) != {
        "schema_version",
        "account_id",
        "halted",
        "reason",
        "event_count",
        "latest_event_sha256",
        "execution_authority",
    }:
        raise ValueError("startup operational control is invalid")
    reason = control["reason"]
    if (
        type(control["schema_version"]) is not int
        or control["schema_version"] != broker_risk_control.CONTROL_SCHEMA_VERSION
        or control["account_id"] != account_id
        or type(control["halted"]) is not bool
        or not isinstance(reason, str)
        or not reason
        or reason != reason.strip()
        or len(reason) > broker_risk_control.MAX_REASON_CHARS
        or not reason.isprintable()
        or isinstance(control["event_count"], bool)
        or not isinstance(control["event_count"], int)
        or control["event_count"] < 0
        or control["execution_authority"] != "none"
        or (
            control["event_count"] == 0
            and control["latest_event_sha256"] is not None
        )
        or (
            control["event_count"] > 0
            and _sha256(
                control["latest_event_sha256"],
                "startup control event identity",
            )
            is None
        )
        or canonical_sha256(control)
        != assessment["operational_control_sha256"]
    ):
        raise ValueError("startup operational control is invalid")

    uncertain = _identifier_list(
        assessment["uncertain_submission_keys"],
        "uncertain submission identifier",
    )
    resolved_open = _identifier_list(
        assessment["resolved_open_submission_keys"],
        "resolved open submission identifier",
    )
    uncertain_cancellations = _identifier_list(
        assessment["uncertain_cancellation_keys"],
        "uncertain cancellation identifier",
    )
    incomplete_stops = _identifier_list(
        assessment["incomplete_emergency_stop_keys"],
        "incomplete emergency-stop identifier",
    )
    resolved = assessment["resolved_submissions"]
    if not isinstance(resolved, list):
        raise ValueError("resolved startup submissions are invalid")
    resolved_keys = []
    expected_open = []
    for item in resolved:
        if not isinstance(item, dict) or set(item) != {
            "idempotency_key",
            "resolution_key",
            "outcome",
            "resolution_sha256",
            "retry_permitted",
        }:
            raise ValueError("resolved startup submission is invalid")
        require_identifier(
            item["idempotency_key"],
            "resolved submission identifier",
        )
        require_identifier(
            item["resolution_key"],
            "submission resolution identifier",
        )
        _sha256(item["resolution_sha256"], "submission resolution identity")
        if (
            item["outcome"] not in _RESOLUTION_OUTCOMES
            or item["retry_permitted"] is not False
        ):
            raise ValueError("resolved startup submission is invalid")
        resolved_keys.append(item["idempotency_key"])
        if item["outcome"] == "observed_open":
            expected_open.append(item["idempotency_key"])
    if (
        resolved_keys != sorted(set(resolved_keys))
        or resolved_open != sorted(expected_open)
        or set(uncertain).intersection(resolved_keys)
    ):
        raise ValueError("startup submission recovery state is inconsistent")

    expected_reasons = []
    if assessment["account_active"] is not True:
        expected_reasons.append("account_inactive")
    if assessment["reconciliation_status"] != "match":
        expected_reasons.append(
            f"reconciliation_{assessment['reconciliation_status']}"
        )
    if not 0 <= float(age) <= maximum_age:
        expected_reasons.append("reconciliation_stale_or_future")
    if uncertain:
        expected_reasons.append("uncertain_submissions")
    if resolved_open:
        expected_reasons.append("resolved_open_submissions")
    if uncertain_cancellations:
        expected_reasons.append("uncertain_cancellations")
    if incomplete_stops:
        expected_reasons.append("incomplete_emergency_stops")
    if control["halted"] is not True:
        expected_reasons.append("control_not_halted")
    ready = not expected_reasons
    body = {
        key: value
        for key, value in assessment.items()
        if key != "assessment_sha256"
    }
    if (
        assessment["schema_version"] != STARTUP_SCHEMA_VERSION
        or assessment["account_id"] != account_id
        or assessment["status"]
        != ("reconciled_halted" if ready else "blocked")
        or assessment["safe_halted"] is not ready
        or assessment["submission_authority"] != "none"
        or assessment["reasons"] != expected_reasons
        or canonical_sha256(body) != assessment["assessment_sha256"]
        or assessment["assessment_sha256"] != trusted_assessment_sha256
    ):
        raise ValueError("startup assessment is invalid")
    return assessment


def _submission_recovery_state(
    con: duckdb.DuckDBPyConnection,
    account_id: str,
) -> tuple[tuple[str, ...], tuple[dict, ...]]:
    if not table_exists(con, "broker_submission_events"):
        return (), ()
    has_intents = table_exists(con, "broker_intents")
    if has_intents:
        query = (
            "SELECT idempotency_key FROM ("
            "SELECT idempotency_key FROM broker_submission_events WHERE account_id = ? "
            "UNION SELECT idempotency_key FROM broker_intents WHERE account_id = ?"
            ") keys ORDER BY idempotency_key LIMIT ?"
        )
        parameters = [account_id, account_id, MAX_ACCOUNT_ROWS + 1]
    else:
        query = (
            "SELECT DISTINCT idempotency_key FROM broker_submission_events "
            "WHERE account_id = ? ORDER BY idempotency_key LIMIT ?"
        )
        parameters = [account_id, MAX_ACCOUNT_ROWS + 1]
    keys = [row[0] for row in con.execute(query, parameters).fetchall()]
    if len(keys) > MAX_ACCOUNT_ROWS:
        raise BrokerStateError("startup submission count exceeds assessment limit")
    uncertain = []
    resolved = []
    for key in keys:
        state = broker_ledger.submission_state(con, key)
        if state == "uncertain":
            resolution = broker_ledger.submission_resolution(con, key)
            if resolution is None:
                uncertain.append(key)
            else:
                resolved.append(
                    {
                        "idempotency_key": key,
                        "resolution_key": resolution["resolution_key"],
                        "outcome": resolution["outcome"],
                        "resolution_sha256": resolution["resolution_sha256"],
                        "retry_permitted": False,
                    }
                )
    return tuple(uncertain), tuple(resolved)


def _uncertain_cancellation_keys(
    con: duckdb.DuckDBPyConnection,
    account_id: str,
) -> tuple[str, ...]:
    if not table_exists(con, "broker_cancellation_events"):
        return ()
    states = broker_ledger.cancellation_states_for_account(con, account_id)
    return tuple(sorted(key for key, state in states.items() if state == "uncertain"))


def _incomplete_emergency_stop_keys(
    con: duckdb.DuckDBPyConnection,
    account_id: str,
) -> tuple[str, ...]:
    if not table_exists(con, "broker_emergency_stop_events"):
        return ()
    states = broker_ledger.emergency_stop_states_for_account(con, account_id)
    return tuple(sorted(key for key, state in states.items() if state == "started"))


def assess(
    con: duckdb.DuckDBPyConnection,
    adapter: BrokerAdapter,
    account_id: str,
    *,
    reconciliation_key: str,
    now: datetime,
    max_reconciliation_age_seconds: int,
) -> dict:
    """Return hash-bound startup state without enabling broker submission."""
    require_identifier(account_id, "account identifier")
    require_identifier(reconciliation_key, "reconciliation key")
    observed_at = _utc(now)
    if (
        isinstance(max_reconciliation_age_seconds, bool)
        or not isinstance(max_reconciliation_age_seconds, int)
        or not 1 <= max_reconciliation_age_seconds <= 300
    ):
        raise ValueError(
            "maximum reconciliation age must be from 1 through 300 seconds"
        )

    initial = broker_reconciliation.capture_snapshot(adapter, account_id)
    snapshot_sha256 = canonical_sha256(initial.comparable_payload())
    reconciliation = broker_risk_snapshot.verified_reconciliation_evidence(
        con,
        reconciliation_key,
        account_id=account_id,
        snapshot_sha256=snapshot_sha256,
    )
    control = broker_risk_control.status(con, account_id)
    uncertain_submissions, resolved_submissions = _submission_recovery_state(
        con,
        account_id,
    )
    resolved_open_submissions = tuple(
        item["idempotency_key"]
        for item in resolved_submissions
        if item["outcome"] == "observed_open"
    )
    uncertain_cancellations = _uncertain_cancellation_keys(con, account_id)
    incomplete_emergency_stops = _incomplete_emergency_stop_keys(con, account_id)
    closing = broker_reconciliation.capture_snapshot(adapter, account_id)
    if closing.retained_payload() != initial.retained_payload():
        raise BrokerStateError(
            "broker state changed during startup reconciliation assessment"
        )

    reconciliation_age_seconds = (
        observed_at - reconciliation.observed_at
    ).total_seconds()
    reasons = []
    if not initial.account.active:
        reasons.append("account_inactive")
    if reconciliation.status != "match":
        reasons.append(f"reconciliation_{reconciliation.status}")
    if not 0 <= reconciliation_age_seconds <= max_reconciliation_age_seconds:
        reasons.append("reconciliation_stale_or_future")
    if uncertain_submissions:
        reasons.append("uncertain_submissions")
    if resolved_open_submissions:
        reasons.append("resolved_open_submissions")
    if uncertain_cancellations:
        reasons.append("uncertain_cancellations")
    if incomplete_emergency_stops:
        reasons.append("incomplete_emergency_stops")
    if not control.halted:
        reasons.append("control_not_halted")
    body = {
        "schema_version": STARTUP_SCHEMA_VERSION,
        "account_id": account_id,
        "status": "reconciled_halted" if not reasons else "blocked",
        "safe_halted": not reasons,
        "submission_authority": "none",
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "account_active": initial.account.active,
        "account_snapshot_sha256": snapshot_sha256,
        "reconciliation_key": reconciliation_key,
        "reconciliation_status": reconciliation.status,
        "reconciliation_observed_at": (
            reconciliation.observed_at.isoformat().replace("+00:00", "Z")
        ),
        "reconciliation_age_seconds": reconciliation_age_seconds,
        "max_reconciliation_age_seconds": max_reconciliation_age_seconds,
        "reconciliation_sha256": reconciliation.evidence_sha256,
        "operational_control": asdict(control),
        "operational_control_sha256": canonical_sha256(asdict(control)),
        "uncertain_submission_keys": list(uncertain_submissions),
        "resolved_submissions": list(resolved_submissions),
        "resolved_open_submission_keys": list(resolved_open_submissions),
        "uncertain_cancellation_keys": list(uncertain_cancellations),
        "incomplete_emergency_stop_keys": list(incomplete_emergency_stops),
        "reasons": reasons,
    }
    return {**body, "assessment_sha256": canonical_sha256(body)}
