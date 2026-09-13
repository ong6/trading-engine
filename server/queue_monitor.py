"""Read-only job-queue status and failure classification."""

from __future__ import annotations

from datetime import datetime, timezone

import duckdb

from engine.lib.util import table_exists

from . import sweep_monitor
from .read_model_utils import (
    require_public_nonempty_string,
    require_public_nonnegative_integer,
    require_public_positive_integer,
)
from .status_validation import iso_timestamp

FAILURE_DETAIL_LIMIT = 100
FAILURE_KIND_MAX_CHARS = 64
QUEUE_STATES = frozenset({"done", "failed", "pending", "queued", "running", "superseded"})
RESEARCH_JOB_KINDS = frozenset({"walkforward", "sweep", "backtest"})
FAILURE_FIELDS = frozenset({"id", "kind", "updated_at"})
HISTORICAL_FAILURE_FIELDS = FAILURE_FIELDS | {"classification"}
QUEUE_FIELDS = frozenset(
    {
        "counts",
        "actionable_failure_count",
        "actionable_failures",
        "actionable_failures_limit",
        "actionable_failures_truncated",
        "historical_failure_count",
        "historical_failures",
        "historical_failures_limit",
        "historical_failures_truncated",
        "latest_research_job",
    }
)
LATEST_RESEARCH_JOB_FIELDS = frozenset({"id", "kind", "state", "updated_at"})
HISTORICAL_CLASSIFICATION = "recurring sweep charter is closed"


def _utc_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    if type(value) is not datetime:
        raise ValueError("public queue timestamp is invalid")
    aware = (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )
    return aware.isoformat()


def _public_failure(row: dict) -> dict:
    """Project failure identity after full values have served classification."""
    kind = require_public_nonempty_string(row["kind"], "queue job kind")
    return {
        "id": require_public_positive_integer(row["id"]),
        "kind": kind[:FAILURE_KIND_MAX_CHARS],
        "updated_at": row["updated_at"],
    }


def _failure_rows(con: duckdb.DuckDBPyConnection):
    """Yield failed jobs newest-first without materializing the full history."""
    cursor = con.execute(
        "SELECT id, kind, params, updated_at FROM jobs "
        "WHERE state = 'failed' ORDER BY updated_at DESC NULLS LAST, id DESC"
    )
    columns = [column[0] for column in cursor.description]
    while batch := cursor.fetchmany(256):
        for row in batch:
            failure = dict(zip(columns, row, strict=True))
            failure["updated_at"] = _utc_timestamp(failure["updated_at"])
            yield failure


def _sweep_context(con: duckdb.DuckDBPyConnection) -> tuple[set | None, set, set]:
    active_params = con.execute(
        "SELECT params FROM jobs WHERE kind = 'sweep' AND state IN ('queued', 'pending', 'running')"
    ).fetchall()
    active_identities = {
        identity
        for (raw,) in active_params
        if (identity := sweep_monitor.sweep_identity(raw)) is not None
    }
    try:
        open_sweeps = set(sweep_monitor.recurring_charters())
    except ValueError:
        # A broken allowlist is an operational fault, so fail closed: none of
        # its failed jobs may be silently classified as history.
        return None, active_identities, set()
    open_names = {name for name, _version in open_sweeps}
    return open_sweeps, active_identities, open_names


def _historical_reason(
    failure: dict,
    open_sweeps: set | None,
    active_identities: set,
    open_names: set,
) -> str | None:
    if failure["kind"] != "sweep" or open_sweeps is None:
        return None
    identity = sweep_monitor.sweep_identity(failure["params"])
    charter_is_closed = identity is not None and (
        identity not in open_sweeps and (identity[1] is not None or identity[0] not in open_names)
    )
    if charter_is_closed and identity not in active_identities:
        return HISTORICAL_CLASSIFICATION
    return None


def _failure_summary(con: duckdb.DuckDBPyConnection) -> dict:
    open_sweeps, active_identities, open_names = _sweep_context(con)
    result = {
        "actionable_failure_count": 0,
        "actionable_failures": [],
        "historical_failure_count": 0,
        "historical_failures": [],
    }
    for failure in _failure_rows(con):
        reason = _historical_reason(failure, open_sweeps, active_identities, open_names)
        if reason is None:
            result["actionable_failure_count"] += 1
            if len(result["actionable_failures"]) < FAILURE_DETAIL_LIMIT:
                result["actionable_failures"].append(_public_failure(failure))
        else:
            result["historical_failure_count"] += 1
            if len(result["historical_failures"]) < FAILURE_DETAIL_LIMIT:
                result["historical_failures"].append(
                    {**_public_failure(failure), "classification": reason}
                )
    return result


def _latest_research_job(con: duckdb.DuckDBPyConnection) -> dict | None:
    fields = ("id", "kind", "state", "updated_at")
    row = con.execute(
        f"SELECT {', '.join(fields)} FROM jobs "
        "WHERE kind IN ('walkforward', 'sweep', 'backtest') "
        "ORDER BY updated_at DESC NULLS LAST, id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    latest = dict(zip(fields, row, strict=True))
    require_public_positive_integer(latest["id"])
    latest["updated_at"] = _utc_timestamp(latest["updated_at"])
    return latest


def _queue_timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    parsed = iso_timestamp(value, "public queue timestamp is invalid")
    if not value.endswith("+00:00"):
        raise ValueError("public queue timestamp is invalid")
    return parsed


def _failure_is_out_of_order(
    previous: tuple[datetime | None, int],
    current: tuple[datetime | None, int],
) -> bool:
    previous_timestamp, previous_id = previous
    current_timestamp, current_id = current
    if previous_timestamp is None:
        return current_timestamp is not None or current_id >= previous_id
    if current_timestamp is None:
        return False
    return current_timestamp > previous_timestamp or (
        current_timestamp == previous_timestamp and current_id >= previous_id
    )


def _validate_failure_rows(rows: object, *, historical: bool) -> set[int]:
    if not isinstance(rows, list):
        raise ValueError("public queue failures are invalid")
    expected_fields = HISTORICAL_FAILURE_FIELDS if historical else FAILURE_FIELDS
    seen_ids: set[int] = set()
    previous: tuple[datetime | None, int] | None = None
    for row in rows:
        if not isinstance(row, dict) or set(row) != expected_fields:
            raise ValueError("public queue failure shape is invalid")
        job_id = require_public_positive_integer(row["id"])
        if job_id in seen_ids:
            raise ValueError("public queue failure identifier is duplicated")
        seen_ids.add(job_id)
        kind = require_public_nonempty_string(row["kind"], "queue job kind")
        if len(kind) > FAILURE_KIND_MAX_CHARS:
            raise ValueError("public queue job kind is invalid")
        updated_at = _queue_timestamp(row["updated_at"])
        if historical and row["classification"] != HISTORICAL_CLASSIFICATION:
            raise ValueError("public queue failure classification is invalid")
        if previous is not None and _failure_is_out_of_order(previous, (updated_at, job_id)):
            raise ValueError("public queue failures are not ordered")
        previous = (updated_at, job_id)
    return seen_ids


def _validate_queue_status(payload: dict) -> None:
    if not isinstance(payload, dict) or set(payload) != QUEUE_FIELDS:
        raise ValueError("public queue projection shape is invalid")
    counts = payload["counts"]
    if not isinstance(counts, dict) or any(state not in QUEUE_STATES for state in counts):
        raise ValueError("public queue counts are invalid")
    validated_counts = {
        state: require_public_nonnegative_integer(count) for state, count in counts.items()
    }
    all_failure_ids: set[int] = set()
    for prefix, historical in (("actionable", False), ("historical", True)):
        count = require_public_nonnegative_integer(payload[f"{prefix}_failure_count"])
        limit = require_public_positive_integer(payload[f"{prefix}_failures_limit"])
        rows = payload[f"{prefix}_failures"]
        truncated = payload[f"{prefix}_failures_truncated"]
        if (
            limit != FAILURE_DETAIL_LIMIT
            or not isinstance(rows, list)
            or len(rows) != min(count, limit)
            or type(truncated) is not bool
            or truncated != (count > len(rows))
        ):
            raise ValueError("public queue failure collection is inconsistent")
        ids = _validate_failure_rows(rows, historical=historical)
        if all_failure_ids & ids:
            raise ValueError("public queue failure identifier is duplicated")
        all_failure_ids.update(ids)
    if validated_counts.get("failed", 0) != (
        payload["actionable_failure_count"] + payload["historical_failure_count"]
    ):
        raise ValueError("public queue failure counts are inconsistent")
    latest = payload["latest_research_job"]
    if latest is None:
        return
    if not isinstance(latest, dict) or set(latest) != LATEST_RESEARCH_JOB_FIELDS:
        raise ValueError("public latest research job shape is invalid")
    require_public_positive_integer(latest["id"])
    if latest["kind"] not in RESEARCH_JOB_KINDS or latest["state"] not in QUEUE_STATES:
        raise ValueError("public latest research job is invalid")
    _queue_timestamp(latest["updated_at"])


def status(con: duckdb.DuckDBPyConnection) -> dict:
    if not table_exists(con, "jobs"):
        payload = {
            "counts": {},
            "actionable_failure_count": 0,
            "actionable_failures": [],
            "actionable_failures_limit": FAILURE_DETAIL_LIMIT,
            "actionable_failures_truncated": False,
            "historical_failure_count": 0,
            "historical_failures": [],
            "historical_failures_limit": FAILURE_DETAIL_LIMIT,
            "historical_failures_truncated": False,
            "latest_research_job": None,
        }
        _validate_queue_status(payload)
        return payload
    counts = {
        state: require_public_nonnegative_integer(count)
        for state, count in con.execute(
            "SELECT state, COUNT(*) FROM jobs GROUP BY state ORDER BY state"
        ).fetchall()
    }
    failures = _failure_summary(con)
    actionable_count = require_public_nonnegative_integer(failures["actionable_failure_count"])
    historical_count = require_public_nonnegative_integer(failures["historical_failure_count"])
    payload = {
        "counts": counts,
        "actionable_failure_count": actionable_count,
        "actionable_failures": failures["actionable_failures"],
        "actionable_failures_limit": FAILURE_DETAIL_LIMIT,
        "actionable_failures_truncated": actionable_count > FAILURE_DETAIL_LIMIT,
        "historical_failure_count": historical_count,
        "historical_failures": failures["historical_failures"],
        "historical_failures_limit": FAILURE_DETAIL_LIMIT,
        "historical_failures_truncated": historical_count > FAILURE_DETAIL_LIMIT,
        "latest_research_job": _latest_research_job(con),
    }
    _validate_queue_status(payload)
    return payload
