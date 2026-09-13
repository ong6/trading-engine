"""Read-only reconciliation of scheduled miner jobs and published evidence."""

from __future__ import annotations

from datetime import timezone

import duckdb

from engine.lib.util import table_exists
from server.json_utils import loads_object

from .read_model_utils import (
    require_public_nonnegative_integer,
    require_public_positive_integer,
)
from .status_validation import metadata_timestamp, nonnegative_int

_MINER_META_KEYS = {
    "intraday": "intraday",
    "signals": "signals_incremental",
    "earnings": "earnings",
    "fundamentals": "fundamentals",
}
_SCHEDULED_MINER_PARAMS = {
    "intraday": {},
    "signals": {"mode": "incremental"},
    "earnings": {},
    "fundamentals": {},
}
JOB_SCAN_BATCH_SIZE = 256


def _intraday_has_issues(raw: dict) -> bool:
    requested = require_public_nonnegative_integer(nonnegative_int(raw, "tickers_requested"))
    with_data = require_public_nonnegative_integer(nonnegative_int(raw, "tickers_with_data"))
    failed = require_public_nonnegative_integer(nonnegative_int(raw, "failed_tickers"))
    failed_batches = require_public_nonnegative_integer(nonnegative_int(raw, "failed_batches"))
    if with_data + failed != requested:
        raise ValueError("intraday ticker accounting is inconsistent")
    return bool(failed or failed_batches)


def _earnings_has_issues(raw: dict) -> bool:
    pulled = require_public_nonnegative_integer(nonnegative_int(raw, "pulled_this_run"))
    with_date = require_public_nonnegative_integer(nonnegative_int(raw, "with_upcoming_date"))
    no_date = require_public_nonnegative_integer(nonnegative_int(raw, "no_upcoming_date"))
    failed = require_public_nonnegative_integer(nonnegative_int(raw, "failed_tickers"))
    if with_date + no_date + failed != pulled:
        raise ValueError("earnings ticker accounting is inconsistent")
    return bool(failed)


def _fundamentals_has_issues(raw: dict) -> bool:
    pulled = require_public_nonnegative_integer(nonnegative_int(raw, "pulled_this_run"))
    with_data = require_public_nonnegative_integer(nonnegative_int(raw, "with_data"))
    with_market_cap = require_public_nonnegative_integer(nonnegative_int(raw, "with_market_cap"))
    failed = require_public_nonnegative_integer(nonnegative_int(raw, "failed_tickers"))
    if with_data + failed != pulled or with_market_cap > with_data:
        raise ValueError("fundamentals ticker accounting is inconsistent")
    return bool(failed)


def _signals_has_issues(raw: dict) -> bool:
    sources = raw.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise ValueError("signals sources are missing")
    warnings = raw.get("warnings")
    if not isinstance(warnings, list):
        raise ValueError("signals warnings are invalid")
    require_public_nonnegative_integer(nonnegative_int(raw, "rows_inserted"))
    has_issue = bool(warnings)
    for result in sources.values():
        if not isinstance(result, dict):
            raise ValueError("signals source result is invalid")
        require_public_nonnegative_integer(nonnegative_int(result, "rows_fetched"))
        require_public_nonnegative_integer(nonnegative_int(result, "rows_inserted"))
        has_issue = has_issue or result.get("status") != "ok"
    return has_issue


_ISSUE_CHECKS = {
    "intraday": _intraday_has_issues,
    "signals": _signals_has_issues,
    "earnings": _earnings_has_issues,
    "fundamentals": _fundamentals_has_issues,
}


def _latest_scheduled_jobs(con: duckdb.DuckDBPyConnection) -> dict[str, tuple]:
    cursor = con.execute(
        "SELECT kind, id, params, state, progress, created_at, updated_at, last_error "
        "FROM jobs WHERE kind IN ('intraday', 'signals', 'earnings', 'fundamentals') "
        "ORDER BY id DESC"
    )
    latest_jobs = {}
    while batch := cursor.fetchmany(JOB_SCAN_BATCH_SIZE):
        for row in batch:
            try:
                params = loads_object(row[2])
            except (TypeError, ValueError):
                continue
            if params == _SCHEDULED_MINER_PARAMS[row[0]]:
                latest_jobs.setdefault(row[0], row)
        if latest_jobs.keys() >= _SCHEDULED_MINER_PARAMS.keys():
            break
    return latest_jobs


def _unfinished_job_status(result: dict, progress: object, last_error: object) -> dict:
    result["reason"] = "latest-job-not-done"
    if progress is not None:
        result["progress"] = progress
    if last_error is not None:
        result["last_error"] = last_error
    return result


def _reconcile_evidence(kind: str, raw: dict, created_at: object, result: dict) -> None:
    evidence_at = metadata_timestamp(raw)
    if created_at is None:
        raise ValueError("job creation time is missing")
    job_started = (
        created_at.replace(tzinfo=timezone.utc)
        if created_at.tzinfo is None
        else created_at.astimezone(timezone.utc)
    )
    if evidence_at < job_started:
        result.update(status="stale", reason="evidence-predates-latest-job")
    elif _ISSUE_CHECKS[kind](raw):
        result.update(status="issues", reason="miner-reported-failures")
    else:
        result["status"] = "current"
    result["evidence_at"] = evidence_at.isoformat()


def _job_status(kind: str, meta_key: str, row: tuple, meta: dict) -> dict:
    _kind, job_id, _params, state, progress, created_at, updated_at, last_error = row
    require_public_positive_integer(job_id)
    result = {
        "status": state,
        "job_id": job_id,
        "job_state": state,
        "job_updated_at": None if updated_at is None else updated_at.isoformat(),
    }
    if state != "done":
        return _unfinished_job_status(result, progress, last_error)
    if progress != "complete" or last_error is not None:
        result.update(status="invalid", reason="incoherent-done-job")
        return result

    raw = meta.get(meta_key)
    if raw is None:
        result.update(status="missing", reason="evidence-missing")
        return result
    try:
        _reconcile_evidence(kind, raw, created_at, result)
    except (KeyError, TypeError, ValueError):
        result.update(status="invalid", reason="evidence-invalid")
    return result


def _overall_status(miners: dict[str, dict]) -> str:
    statuses = {item["status"] for item in miners.values()}
    if statuses == {"current"}:
        return "current"
    for status in ("invalid", "failed"):
        if status in statuses:
            return status
    if statuses & {"pending", "queued", "running"}:
        return "updating"
    for status in ("issues", "stale"):
        if status in statuses:
            return status
    return "incomplete"


def evidence_status(meta: dict, con: duckdb.DuckDBPyConnection) -> dict:
    """Reconcile each scheduled miner's latest queue outcome with its evidence."""
    miners: dict[str, dict] = {}
    if not table_exists(con, "jobs"):
        return {
            "status": "unknown",
            "current": 0,
            "expected": len(_MINER_META_KEYS),
            "miners": {
                kind: {"status": "unknown", "reason": "jobs-table-missing"}
                for kind in _MINER_META_KEYS
            },
        }

    latest_jobs = _latest_scheduled_jobs(con)

    for kind, meta_key in _MINER_META_KEYS.items():
        row = latest_jobs.get(kind)
        if row is None:
            miners[kind] = {"status": "missing", "reason": "job-missing"}
            continue
        miners[kind] = _job_status(kind, meta_key, row, meta)

    current = sum(item["status"] == "current" for item in miners.values())
    return {
        "status": _overall_status(miners),
        "current": current,
        "expected": len(miners),
        "miners": miners,
    }
