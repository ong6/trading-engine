"""Read-only reconciliation of walk-forward queue cohorts and driver state."""

from __future__ import annotations

from datetime import datetime, timezone

import duckdb

from engine.lib.util import table_exists
from farm.walkforward import protocol as walkforward_protocol
from server.json_utils import loads_object
from server.status_validation import iso_timestamp

JOB_SCAN_BATCH_SIZE = 256


def eligible_walkforward_ids(con: duckdb.DuckDBPyConnection) -> set[str]:
    if not table_exists(con, "portfolios"):
        return set()
    return {
        portfolio_id
        for portfolio_id, strategy in con.execute(
            "SELECT id, strategy FROM portfolios WHERE active ORDER BY id"
        ).fetchall()
        if walkforward_protocol.excluded_reason(portfolio_id, strategy) is None
    }


def _driver_boundary(status: dict) -> datetime | None:
    boundary_key = "started_at" if status.get("status") == "running" else "recovered_at"
    boundary_raw = status.get(boundary_key) or status.get("finished_at")
    if boundary_raw is None:
        return None
    boundary = iso_timestamp(
        boundary_raw,
        "driver boundary must be a canonical ISO timestamp",
        require_timezone=False,
    )
    if boundary.tzinfo is not None:
        boundary = boundary.astimezone(timezone.utc).replace(tzinfo=None)
    return boundary


def _is_exact_batch(batch: list[tuple], expected: set[str]) -> bool:
    try:
        ids = [loads_object(row[1])["config_id"] for row in batch]
    except (KeyError, TypeError, ValueError):
        return False
    return len(batch) == len(expected) and len(ids) == len(set(ids)) and set(ids) == expected


def _newest_exact_batch(
    con: duckdb.DuckDBPyConnection,
    boundary: datetime,
    expected: set[str],
) -> list[tuple] | None:
    """Scan newest-first while retaining at most one possible exact cohort."""
    cursor = con.execute(
        "SELECT id, params, state, progress, last_error, created_at, updated_at "
        "FROM jobs WHERE kind = 'walkforward' AND created_at > ? "
        "ORDER BY created_at DESC, id DESC",
        [boundary],
    )
    batch: list[tuple] = []
    oversized = False
    previous_created_at = None
    while rows := cursor.fetchmany(JOB_SCAN_BATCH_SIZE):
        for row in rows:
            created_at = row[5]
            if (
                previous_created_at is not None
                and (previous_created_at - created_at).total_seconds() > 5
            ):
                if not oversized and _is_exact_batch(batch, expected):
                    return batch
                batch = []
                oversized = False
            if not oversized:
                batch.append(row)
                if len(batch) > len(expected):
                    batch = []
                    oversized = True
            previous_created_at = created_at
    if not oversized and _is_exact_batch(batch, expected):
        return batch
    return None


def _base_batch_projection(status: dict, batch: list[tuple]) -> dict:
    counts: dict[str, int] = {}
    for row in batch:
        counts[row[2]] = counts.get(row[2], 0) + 1
    projected = {
        **status,
        "previous_status": status.get("status"),
        "refresh_job_count": len(batch),
        "refresh_job_counts": counts,
    }
    if status.get("status") == "failed":
        projected.update(recovery_job_count=len(batch), recovery_job_counts=counts)
    return projected


def _completed_batch(batch: list[tuple]) -> bool:
    return all(row[2] == "done" and row[3] == "complete" and row[4] is None for row in batch)


def _healthy_batch(batch: list[tuple]) -> bool:
    return all(
        row[2] in {"pending", "running", "done"}
        and (row[2] != "done" or (row[3] == "complete" and row[4] is None))
        for row in batch
    )


def _project_batch(status: dict, batch: list[tuple]) -> dict:
    projected = _base_batch_projection(status, batch)
    if _completed_batch(batch):
        refreshed_at = max(row[6] for row in batch).isoformat()
        projected["refreshed_at"] = refreshed_at
        if status.get("status") == "failed":
            projected.update(status="recovered", recovered_at=refreshed_at)
        return projected
    if _healthy_batch(batch):
        refresh_started_at = min(row[5] for row in batch).isoformat()
        projected.update(status="updating", refresh_started_at=refresh_started_at)
        if status.get("status") == "failed":
            projected["recovery_started_at"] = refresh_started_at
    return projected


def reconcile_driver_status(
    status: dict | None,
    con: duckdb.DuckDBPyConnection,
) -> dict | None:
    """Project the newest exact queue cohort over scheduled-driver state.

    The newest exact eligible cohort wins: it is ``updating`` while healthy jobs
    remain pending/running. A failed driver becomes ``recovered`` only after every
    job completes; successful/running drivers retain their terminal/base status.
    """
    if (
        status is None
        or status.get("status") in {"invalid", "stale-running"}
        or not table_exists(con, "jobs")
    ):
        return status
    try:
        boundary = _driver_boundary(status)
        if boundary is None:
            return status
        expected = eligible_walkforward_ids(con)
        if not expected:
            return status
        batch = _newest_exact_batch(con, boundary, expected)
        if batch is not None:
            return _project_batch(status, batch)
    except (KeyError, TypeError, ValueError, duckdb.Error):
        return status
    return status
