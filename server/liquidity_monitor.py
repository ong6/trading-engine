"""Read-only reconciliation of scheduled liquidity-refresh evidence."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import duckdb

from sim import nyse

from .read_model_utils import require_public_nonnegative_integer
from .status_validation import iso_date, iso_timestamp, metadata_timestamp, nonnegative_int

log = logging.getLogger(__name__)

PUBLIC_STATUSES = frozenset(
    {
        "current",
        "failed",
        "interrupted",
        "invalid",
        "issues",
        "missing",
        "not-yet-run",
        "overdue",
        "stale",
        "stale-running",
        "unknown",
        "updating",
    }
)
PUBLIC_REASONS = frozenset(
    {
        "candidate-download-failures",
        "candidate-and-backfill-failures",
        "backfill-failures",
        "driver-not-successful",
        "evidence-ahead-of-store",
        "evidence-missing",
        "evidence-postdates-latest-run",
        "evidence-predates-latest-run",
        "future-evidence",
        "malformed-evidence",
        "market-date-unavailable",
        "no-scheduled-run",
        "projection-error",
        "scheduled-market-date-mismatch",
        "store-count-mismatch",
    }
)


def _public_status(result: dict) -> dict:
    """Assert that producer output stays inside the documented public vocabulary."""
    if result.get("status") not in PUBLIC_STATUSES:
        raise ValueError("undocumented liquidity status")
    reason = result.get("reason")
    if reason is not None and reason not in PUBLIC_REASONS:
        raise ValueError("undocumented liquidity reason")
    return result


def _ticker_lists(raw: dict) -> tuple[list[str], list[str], list[str]]:
    admitted, demoted, kept_held = raw["admitted"], raw["demoted"], raw["kept_held"]
    lists = (admitted, demoted, kept_held)
    if any(
        not isinstance(values, list)
        or any(not isinstance(ticker, str) or not ticker for ticker in values)
        or len(values) != len(set(values))
        for values in lists
    ):
        raise ValueError("liquidity ticker lists are invalid")
    if any(
        set(left) & set(right) for left, right in zip(lists, lists[1:] + lists[:1], strict=True)
    ):
        raise ValueError("liquidity ticker outcomes overlap")
    return admitted, demoted, kept_held


def _validate_backfill(raw: dict) -> dict[str, int]:
    backfill = raw["backfill"]
    if not isinstance(backfill, dict):
        raise ValueError("backfill evidence is invalid")
    processed = nonnegative_int(backfill, "processed")
    failed = nonnegative_int(backfill, "failed")
    if failed > processed:
        raise ValueError("failed backfills exceed processed backfills")
    return {
        "backfill_processed": require_public_nonnegative_integer(processed),
        "backfill_failed": require_public_nonnegative_integer(failed),
    }


def _checked_at(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _liquidity_counts(raw: dict, admitted: list[str], demoted: list[str]) -> dict[str, int]:
    counts = {
        field: require_public_nonnegative_integer(nonnegative_int(raw, field))
        for field in ("liquid_before", "liquid_after", "candidates_pulled", "candidates_failed")
    }
    if raw["dry_run"] is not False:
        raise ValueError("scheduled liquidity evidence must be non-dry-run")
    if counts["liquid_before"] + len(admitted) - len(demoted) != counts["liquid_after"]:
        raise ValueError("liquidity totals do not reconcile")
    if counts["candidates_failed"] > counts["candidates_pulled"]:
        raise ValueError("failed candidates exceed candidates pulled")
    if not isinstance(raw["rule"], str) or not raw["rule"]:
        raise ValueError("liquidity rule is missing")
    counts.update(_validate_backfill(raw))
    return counts


def _evidence(raw: dict, driver: dict, now: datetime | None) -> dict:
    published_at = metadata_timestamp(raw)
    started_at = iso_timestamp(
        driver["started_at"], "driver start must be a canonical ISO timestamp"
    ).astimezone(timezone.utc)
    finished_at = iso_timestamp(
        driver["finished_at"], "driver finish must be a canonical ISO timestamp"
    ).astimezone(timezone.utc)
    if finished_at < started_at:
        raise ValueError("driver finish predates its start")
    checked_at = _checked_at(now)
    as_of = iso_date(raw["as_of"], "liquidity as_of must be YYYY-MM-DD")
    admitted, demoted, kept_held = _ticker_lists(raw)
    counts = _liquidity_counts(raw, admitted, demoted)
    return {
        "published_at": published_at,
        "started_at": started_at,
        "finished_at": finished_at,
        "checked_at": checked_at,
        "as_of": as_of,
        "admitted": admitted,
        "demoted": demoted,
        "kept_held": kept_held,
        **counts,
    }


def _expected_date(started_at: datetime) -> date:
    expected = started_at.date() - timedelta(days=1)
    while not nyse.is_session(expected):
        expected -= timedelta(days=1)
    return expected


def _publication_state(evidence: dict, store_liquid: int) -> dict | None:
    if evidence["published_at"] < evidence["started_at"]:
        return {
            "status": "stale",
            "reason": "evidence-predates-latest-run",
            "published_at": evidence["published_at"].isoformat(),
        }
    if evidence["published_at"] > evidence["checked_at"]:
        return {"status": "invalid", "reason": "future-evidence"}
    # Shell markers have whole-second precision while metadata retains
    # microseconds. A publication in the marker's displayed finish second is
    # coherent; the following second is not part of that run.
    if evidence["published_at"] >= evidence["finished_at"] + timedelta(seconds=1):
        return {
            "status": "invalid",
            "reason": "evidence-postdates-latest-run",
            "published_at": evidence["published_at"].isoformat(),
            "finished_at": evidence["finished_at"].isoformat(),
        }
    if evidence["liquid_after"] != store_liquid:
        return {
            "status": "stale",
            "reason": "store-count-mismatch",
            "published_at": evidence["published_at"].isoformat(),
            "liquid_after": evidence["liquid_after"],
            "store_liquid": store_liquid,
        }
    return None


def _market_date_state(evidence: dict, latest: date | None) -> dict | None:
    if latest is None:
        return {"status": "unknown", "reason": "market-date-unavailable"}
    expected_as_of = _expected_date(evidence["started_at"])
    if evidence["as_of"] != expected_as_of:
        return {
            "status": "stale" if evidence["as_of"] < expected_as_of else "invalid",
            "reason": "scheduled-market-date-mismatch",
            "as_of": evidence["as_of"],
            "expected_as_of": expected_as_of,
            "latest_date": latest,
        }
    if evidence["as_of"] > latest:
        return {
            "status": "invalid",
            "reason": "evidence-ahead-of-store",
            "as_of": evidence["as_of"],
            "latest_date": latest,
        }
    return None


def _evidence_state(
    evidence: dict,
    con: duckdb.DuckDBPyConnection,
    latest: date | None,
) -> dict | None:
    store_liquid = require_public_nonnegative_integer(
        con.execute("SELECT COUNT(*) FROM universe WHERE liquid = TRUE").fetchone()[0]
    )
    return _publication_state(evidence, store_liquid) or _market_date_state(evidence, latest)


def _driver_state(driver: dict | None) -> dict | None:
    if driver is None:
        return {"status": "not-yet-run", "reason": "no-scheduled-run"}
    status = driver.get("status")
    if status == "running":
        return {"status": "updating"}
    if status != "ok":
        return {
            "status": status if isinstance(status, str) else "invalid",
            "reason": "driver-not-successful",
        }
    return None


def _evidence_payload(evidence: dict) -> dict:
    candidate_failures = bool(evidence["candidates_failed"])
    backfill_failures = bool(evidence["backfill_failed"])
    if candidate_failures and backfill_failures:
        reason = "candidate-and-backfill-failures"
    elif candidate_failures:
        reason = "candidate-download-failures"
    elif backfill_failures:
        reason = "backfill-failures"
    else:
        reason = None
    return {
        "status": "issues" if reason is not None else "current",
        "reason": reason,
        "as_of": evidence["as_of"],
        "published_at": evidence["published_at"].isoformat(),
        "admitted": len(evidence["admitted"]),
        "demoted": len(evidence["demoted"]),
        "kept_held": len(evidence["kept_held"]),
        "liquid_before": evidence["liquid_before"],
        "liquid_after": evidence["liquid_after"],
        "candidates_pulled": evidence["candidates_pulled"],
        "candidates_failed": evidence["candidates_failed"],
        "backfill_processed": evidence["backfill_processed"],
        "backfill_failed": evidence["backfill_failed"],
    }


def evidence_status(
    meta: dict,
    driver: dict | None,
    con: duckdb.DuckDBPyConnection,
    latest: date | None,
    *,
    now: datetime | None = None,
) -> dict:
    """Reconcile the weekly wrapper with its published liquidity result."""
    if state := _driver_state(driver):
        return _public_status(state)

    raw = meta.get("liquid_refresh")
    if raw is None:
        return _public_status({"status": "missing", "reason": "evidence-missing"})
    try:
        evidence = _evidence(raw, driver, now)
        if state := _evidence_state(evidence, con, latest):
            return _public_status(state)
    except (KeyError, TypeError, ValueError, duckdb.Error) as exc:
        log.warning("liquidity evidence validation failed", exc_info=exc)
        return _public_status({"status": "invalid", "reason": "malformed-evidence"})

    return _public_status(_evidence_payload(evidence))
