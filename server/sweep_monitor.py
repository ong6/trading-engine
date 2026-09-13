"""Read-only recurring-sweep job and published-ranking evidence projection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb

from engine.lib.settings import DATA_DIR
from engine.lib.util import table_exists
from farm.sweep import sweep as sweep_registry
from server.json_utils import load_object, loads_object
from server.read_model_utils import require_public_positive_integer

JOB_SCAN_BATCH_SIZE = 256


def recurring_charters() -> list[tuple[str, str]]:
    """Return the validated recurring sweep identities from the research registry."""
    return sweep_registry.recurring_grids()


def sweep_identity(raw: str) -> tuple[str, str | None] | None:
    """Parse the canonical sweep identity from serialized queue parameters."""
    try:
        params = loads_object(raw)
    except (TypeError, ValueError):
        return None
    if (
        params.keys() - {"grid", "charter_version"}
        or not isinstance(params.get("grid"), str)
        or not params["grid"]
    ):
        return None
    version = params.get("charter_version")
    if version is not None and not isinstance(version, str):
        return None
    return params["grid"], version


def _missing_charter(name: str, version: str | None) -> dict:
    return {
        "grid": name,
        "charter_version": version,
        "status": "missing",
        "reason": "job-missing",
    }


def _latest_jobs(
    con: duckdb.DuckDBPyConnection,
    open_charters: list[tuple[str, str]],
) -> dict[tuple[str, str | None], tuple]:
    wanted = set(open_charters)
    cursor = con.execute(
        "SELECT id, params, state, progress, created_at, updated_at, last_error "
        "FROM jobs WHERE kind = 'sweep' ORDER BY id DESC"
    )
    latest_jobs = {}
    while batch := cursor.fetchmany(JOB_SCAN_BATCH_SIZE):
        for row in batch:
            identity = sweep_identity(row[1])
            if identity in wanted:
                latest_jobs.setdefault(identity, row)
        if latest_jobs.keys() >= wanted:
            break
    return latest_jobs


def _ranking_payload(path: Path, name: str, version: str) -> tuple[dict, datetime]:
    payload = load_object(path)
    generated_at = datetime.strptime(payload["generated"], "%Y-%m-%d %H:%M UTC").replace(
        tzinfo=timezone.utc
    )
    if payload.get("sweep") != name or payload.get("charter_version") != version:
        raise ValueError("ranking identity mismatch")
    return payload, generated_at


def _ranking_trial_count(name: str, payload: dict) -> int:
    expected_trials = len(sweep_registry.expand(name))
    n_trials = payload.get("n_trials")
    rows = payload.get("rows")
    excluded = payload.get("excluded")
    if (
        isinstance(n_trials, bool)
        or n_trials != expected_trials
        or not isinstance(rows, list)
        or not isinstance(excluded, list)
        or len(rows) + len(excluded) != expected_trials
    ):
        raise ValueError("ranking trial accounting mismatch")
    return expected_trials


def _ranking_status(
    name: str,
    version: str,
    created_at: datetime | None,
    root: Path,
) -> dict:
    ranking_path = root / name / "charters" / version / "ranking.json"
    payload, generated_at = _ranking_payload(ranking_path, name, version)
    expected_trials = _ranking_trial_count(name, payload)
    if created_at is None:
        raise ValueError("job creation time is missing")
    job_started = (
        created_at.replace(tzinfo=timezone.utc)
        if created_at.tzinfo is None
        else created_at.astimezone(timezone.utc)
    )
    result = {
        "status": "current",
        "generated_at": generated_at.isoformat(),
        "n_trials": expected_trials,
    }
    # Ranking timestamps are minute-resolution, so tolerate the seconds lost
    # when checking that publication belongs to this queue run.
    if generated_at + timedelta(minutes=1) < job_started:
        result.update(status="stale", reason="ranking-predates-latest-job")
    return result


def _charter_status(
    identity: tuple[str, str],
    row: tuple | None,
    root: Path,
) -> dict:
    name, version = identity
    if row is None:
        return _missing_charter(name, version)
    job_id, _params, state, progress, created_at, updated_at, last_error = row
    require_public_positive_integer(job_id)
    result = {
        "grid": name,
        "charter_version": version,
        "status": state,
        "job_id": job_id,
        "job_state": state,
        "job_updated_at": None if updated_at is None else updated_at.isoformat(),
    }
    if state != "done":
        result["reason"] = "latest-job-not-done"
        return result
    if progress != "complete" or last_error is not None:
        result.update(status="invalid", reason="incoherent-done-job")
        return result
    try:
        result.update(_ranking_status(name, version, created_at, root))
    except (OSError, KeyError, TypeError, ValueError):
        result.update(status="invalid", reason="ranking-invalid")
    return result


def _overall_status(charters: list[dict]) -> str:
    statuses = {item["status"] for item in charters}
    if statuses == {"current"}:
        return "current"
    for status in ("invalid", "failed"):
        if status in statuses:
            return status
    if statuses & {"pending", "queued", "running"}:
        return "updating"
    if "stale" in statuses:
        return "stale"
    return "incomplete"


def _empty_evidence_status(status: str, reason: str) -> dict:
    return {
        "status": status,
        "reason": reason,
        "open_charters": 0,
        "current_charters": 0,
        "charters": [],
    }


def _missing_jobs_status(open_charters: list[tuple[str, str]]) -> dict:
    return {
        "status": "incomplete",
        "reason": "jobs-table-missing",
        "open_charters": len(open_charters),
        "current_charters": 0,
        "charters": [_missing_charter(name, version) for name, version in open_charters],
    }


def _evidence_payload(charters: list[dict]) -> dict:
    return {
        "status": _overall_status(charters),
        "open_charters": len(charters),
        "current_charters": sum(item["status"] == "current" for item in charters),
        "charters": charters,
    }


def evidence_status(
    con: duckdb.DuckDBPyConnection,
    results_dir: Path | None = None,
) -> dict:
    """Distinguish an intentional empty sweep schedule from published evidence."""
    try:
        open_charters = recurring_charters()
    except ValueError:
        return _empty_evidence_status("invalid", "recurring-allowlist-invalid")
    if not open_charters:
        return _empty_evidence_status("idle", "no-open-recurring-charters")

    root = results_dir or DATA_DIR / "reports" / "sweeps"
    if not table_exists(con, "jobs"):
        return _missing_jobs_status(open_charters)

    latest_jobs = _latest_jobs(con, open_charters)
    charters = [
        _charter_status(identity, latest_jobs.get(identity), root) for identity in open_charters
    ]
    return _evidence_payload(charters)
