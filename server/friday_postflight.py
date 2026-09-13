"""Schedule-aware projection of the read-only Friday postflight receipt."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from .json_utils import load_object
from .read_model_utils import require_public_positive_integer
from .status_validation import iso_date, iso_timestamp

SCHEMA_VERSION = 1
MAX_FAILURE_REASON_LENGTH = 1_000
SCHEDULE_WEEKDAY = 5  # Saturday, matching datetime.weekday().
SCHEDULE_TIME = time(5, 15, tzinfo=timezone.utc)
COMPLETION_GRACE = timedelta(minutes=15)
FIRST_EXPECTED_AT = datetime(2026, 9, 12, 5, 15, tzinfo=timezone.utc)
EXPECTED_MINERS = frozenset({"intraday", "signals", "earnings", "fundamentals"})
PUBLIC_STATUSES = frozenset(
    {"current", "failed", "invalid", "not-yet-run", "overdue", "stale", "updating"}
)
PUBLIC_INVALID_REASONS = frozenset(
    {
        "projection-error",
        "receipt-before-first-schedule",
        "receipt-from-future-slot",
        "receipt-invalid",
    }
)
RECEIPT_COMMON_FIELDS = frozenset(
    {"schema_version", "checked_at", "status", "expected_date"}
)
CURRENT_RECEIPT_FIELDS = RECEIPT_COMMON_FIELDS | {
    "market_date",
    "nightly_started_at",
    "nightly_finished_at",
    "miner_job_ids",
    "miner_evidence_at",
}
FAILED_RECEIPT_FIELDS = RECEIPT_COMMON_FIELDS | {"reason"}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("observation time must be timezone-aware")
    return value.astimezone(timezone.utc)


def _latest_slot(now: datetime, grace: timedelta) -> datetime | None:
    for days_ago in range(8):
        candidate_date = now.date() - timedelta(days=days_ago)
        if candidate_date.weekday() != SCHEDULE_WEEKDAY:
            continue
        candidate = datetime.combine(candidate_date, SCHEDULE_TIME)
        if candidate >= FIRST_EXPECTED_AT and candidate + grace <= now:
            return candidate
    return None


def _expected_date(slot: datetime) -> date:
    return slot.date() - timedelta(days=1)


def _receipt_slot(expected_date: date) -> datetime:
    if expected_date.weekday() != 4:
        raise ValueError("postflight expected_date is not a Friday")
    return datetime.combine(expected_date + timedelta(days=1), SCHEDULE_TIME)


def _positive_job_ids(value: Any) -> dict[str, int]:
    if not isinstance(value, dict) or set(value) != EXPECTED_MINERS:
        raise ValueError("postflight miner_job_ids are invalid")
    try:
        for item in value.values():
            require_public_positive_integer(item)
    except ValueError:
        raise ValueError("postflight miner_job_ids are invalid") from None
    if len(set(value.values())) != len(value):
        raise ValueError("postflight miner_job_ids are not unique")
    return value


def _evidence_timestamps(value: Any, started_at: datetime, finished_at: datetime) -> dict:
    if not isinstance(value, dict) or set(value) != EXPECTED_MINERS:
        raise ValueError("postflight miner_evidence_at is invalid")
    parsed = {
        kind: iso_timestamp(
            timestamp, f"postflight {kind} evidence timestamp is invalid"
        ).astimezone(timezone.utc)
        for kind, timestamp in value.items()
    }
    if any(not started_at <= timestamp <= finished_at for timestamp in parsed.values()):
        raise ValueError("postflight miner evidence falls outside the nightly window")
    return value


def _receipt_header(payload: dict[str, Any], now: datetime) -> tuple[str, date, datetime, datetime]:
    schema_version = payload.get("schema_version")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != SCHEMA_VERSION
    ):
        raise ValueError("postflight receipt schema is invalid")
    status = payload.get("status")
    if status not in {"current", "failed"}:
        raise ValueError("postflight receipt status is invalid")
    expected_date = iso_date(payload.get("expected_date"), "postflight expected_date is invalid")
    slot = _receipt_slot(expected_date)
    checked_at = iso_timestamp(
        payload.get("checked_at"), "postflight checked_at is invalid"
    ).astimezone(timezone.utc)
    if checked_at < slot or checked_at > now:
        raise ValueError("postflight checked_at is outside its observation window")
    return status, expected_date, slot, checked_at


def _validate_current_receipt(
    payload: dict[str, Any], expected_date: date, checked_at: datetime
) -> None:
    market_date = iso_date(payload.get("market_date"), "postflight market_date is invalid")
    if market_date > expected_date:
        raise ValueError("postflight market_date is after expected Friday")
    started_at = iso_timestamp(
        payload.get("nightly_started_at"), "postflight nightly start is invalid"
    ).astimezone(timezone.utc)
    finished_at = iso_timestamp(
        payload.get("nightly_finished_at"), "postflight nightly finish is invalid"
    ).astimezone(timezone.utc)
    if started_at.date() != expected_date or finished_at < started_at or finished_at > checked_at:
        raise ValueError("postflight nightly window is invalid")
    _positive_job_ids(payload.get("miner_job_ids"))
    _evidence_timestamps(payload.get("miner_evidence_at"), started_at, finished_at)


def _validate_receipt(payload: dict[str, Any], now: datetime) -> tuple[dict, datetime]:
    status, expected_date, slot, checked_at = _receipt_header(payload, now)
    expected_fields = FAILED_RECEIPT_FIELDS if status == "failed" else CURRENT_RECEIPT_FIELDS
    if set(payload) != expected_fields:
        raise ValueError("postflight receipt has unexpected or missing fields")
    if status == "failed":
        reason = payload.get("reason")
        if (
            not isinstance(reason, str)
            or not reason.strip()
            or len(reason) > MAX_FAILURE_REASON_LENGTH
        ):
            raise ValueError("postflight failure reason is invalid")
    else:
        _validate_current_receipt(payload, expected_date, checked_at)
    return payload, slot


def _scheduled_state(status: str, slot: datetime) -> dict:
    return {
        "status": status,
        "expected_date": _expected_date(slot).isoformat(),
        "expected_at": slot.isoformat(),
    }


def _missing_receipt_state(
    started_slot: datetime | None,
    due_slot: datetime | None,
) -> dict:
    if started_slot is not None and started_slot != due_slot:
        return _scheduled_state("updating", started_slot)
    if due_slot is not None:
        return _scheduled_state("overdue", due_slot)
    return {"status": "not-yet-run", "next_expected_at": FIRST_EXPECTED_AT.isoformat()}


def _load_receipt(path: Path, now: datetime) -> tuple[dict, datetime]:
    return _validate_receipt(load_object(path, allow_symlinked_parents=False), now)


def invalid_status(reason: str) -> dict:
    """Return a public fail-closed state with a documented reason."""
    if reason not in PUBLIC_INVALID_REASONS:
        raise ValueError(f"unknown postflight invalid reason: {reason}")
    return {"status": "invalid", "reason": reason}


def status(path: Path, *, now: datetime | None = None) -> dict:
    """Project the newest receipt against the current Saturday schedule."""
    checked_at = _as_utc(now or datetime.now(timezone.utc))
    started_slot = _latest_slot(checked_at, timedelta())
    due_slot = _latest_slot(checked_at, COMPLETION_GRACE)

    try:
        payload, receipt_slot = _load_receipt(path, checked_at)
    except FileNotFoundError:
        return _missing_receipt_state(started_slot, due_slot)
    except (OSError, KeyError, TypeError, ValueError):
        return invalid_status("receipt-invalid")

    if started_slot is not None and started_slot != due_slot:
        if receipt_slot == started_slot:
            return payload
        if receipt_slot < started_slot:
            result = _scheduled_state("updating", started_slot)
            result["previous_status"] = payload["status"]
            return result
        return invalid_status("receipt-from-future-slot")
    if due_slot is None:
        return invalid_status("receipt-before-first-schedule")
    if receipt_slot < due_slot:
        result = _scheduled_state("stale", due_slot)
        result.update(
            observed_expected_date=payload["expected_date"],
            checked_at=payload["checked_at"],
        )
        return result
    if receipt_slot > due_slot:
        return invalid_status("receipt-from-future-slot")
    return payload
