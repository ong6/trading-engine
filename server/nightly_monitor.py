"""Read-only reconciliation of fatal nightly driver and database state."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import duckdb

from engine.lib.settings import DATA_DIR
from engine.lib.util import table_exists

from . import nightly_reports
from .status_validation import iso_date, nonnegative_int

log = logging.getLogger(__name__)


class _EvidenceResult(Exception):
    """Internal control flow for an expected non-current evidence state."""

    def __init__(self, status: str, reason: str, **details: object) -> None:
        self.payload = {"status": status, "reason": reason, **details}
        super().__init__(reason)


def _screen_summary(con: duckdb.DuckDBPyConnection, latest: date) -> tuple[int, int, int, str]:
    latest_screen = con.execute("SELECT MAX(run_date) FROM screen_results").fetchone()[0]
    row = con.execute(
        """
        SELECT COUNT(*),
               SUM(CASE WHEN passes_template THEN 1 ELSE 0 END),
               SUM(CASE WHEN new_today THEN 1 ELSE 0 END),
               COUNT(DISTINCT COALESCE(universe_policy, 'all')),
               MIN(COALESCE(universe_policy, 'all'))
        FROM screen_results WHERE run_date = ?
        """,
        [latest],
    ).fetchone()
    screen_count = int(row[0])
    passing_count = int(row[1] or 0)
    new_count = int(row[2] or 0)
    if latest_screen != latest or screen_count <= 0:
        raise _EvidenceResult("stale", "screen-date-behind")
    if int(row[3]) != 1:
        raise ValueError("screen rows contain mixed universe policies")
    return screen_count, passing_count, new_count, row[4]


def _validate_screen_metadata(
    meta: dict,
    latest: date,
    summary: tuple[int, int, int, str],
) -> None:
    screen_count, passing_count, new_count, policy = summary
    screen_date = iso_date(meta["screen_date"], "screen_date must be YYYY-MM-DD")
    if screen_date != latest:
        raise _EvidenceResult("stale", "screen-metadata-behind")
    published = {
        "screened": nonnegative_int(meta, "screened"),
        "passing": nonnegative_int(meta, "passing_count"),
        "new": nonnegative_int(meta, "new_today_count"),
    }
    expected = {"screened": screen_count, "passing": passing_count, "new": new_count}
    if published != expected or meta.get("universe_policy") != policy:
        raise ValueError("screen metadata does not match stored rows")


def _active_equity_counts(con: duckdb.DuckDBPyConnection, latest: date) -> tuple[int, int]:
    active, with_equity = con.execute(
        """
        SELECT COUNT(*), COUNT(e.portfolio_id)
        FROM portfolios p
        LEFT JOIN sim_equity e ON e.portfolio_id = p.id AND e.date = ?
        WHERE p.active
        """,
        [latest],
    ).fetchone()
    if active <= 0:
        raise ValueError("no active portfolios")
    if with_equity != active:
        raise _EvidenceResult(
            "incomplete",
            "active-equity-missing",
            active_portfolios=active,
            portfolios_with_equity=with_equity,
        )
    return active, with_equity


def _prerequisite_status(
    driver: dict | None,
    con: duckdb.DuckDBPyConnection,
    latest: date | None,
) -> dict | None:
    if driver is None:
        return {"status": "missing", "reason": "driver-missing"}
    driver_status = driver.get("status")
    if driver_status == "running":
        return {"status": "updating"}
    if driver_status != "ok":
        return {
            "status": driver_status if isinstance(driver_status, str) else "invalid",
            "reason": "driver-not-successful",
        }
    if latest is None:
        return {"status": "unknown", "reason": "market-date-unavailable"}
    if not table_exists(con, "screen_results") or not table_exists(con, "sim_equity"):
        return {"status": "invalid", "reason": "required-table-missing"}
    return None


def _current_evidence(
    latest: date,
    summary: tuple[int, int, int, str],
    equity_counts: tuple[int, int],
) -> dict:
    screen_count, passing_count, new_count, policy = summary
    active, with_equity = equity_counts
    return {
        "status": "current",
        "as_of": latest,
        "screened": screen_count,
        "passing": passing_count,
        "new_today": new_count,
        "universe_policy": policy,
        "active_portfolios": active,
        "portfolios_with_equity": with_equity,
    }


def validate_snapshot(
    meta: dict,
    con: duckdb.DuckDBPyConnection,
    latest: date,
    *,
    data_dir: Path = DATA_DIR,
) -> dict:
    """Reconcile one database snapshot with its generated nightly artifacts."""
    try:
        summary = _screen_summary(con, latest)
        _validate_screen_metadata(meta, latest, summary)
        equity_counts = _active_equity_counts(con, latest)
        nightly_reports.validate(meta, latest, summary, con, data_dir)
    except (_EvidenceResult, nightly_reports.EvidenceState) as result:
        return result.payload
    except (OSError, IndexError, KeyError, TypeError, ValueError, duckdb.Error) as exc:
        log.warning("nightly evidence validation failed", exc_info=exc)
        return {"status": "invalid", "reason": "evidence-invalid"}
    return _current_evidence(latest, summary, equity_counts)


def evidence_status(
    meta: dict,
    driver: dict | None,
    con: duckdb.DuckDBPyConnection,
    latest: date | None,
    *,
    data_dir: Path = DATA_DIR,
) -> dict:
    """Reconcile the fatal nightly core with its database and reports."""
    prerequisite = _prerequisite_status(driver, con, latest)
    if prerequisite is not None:
        return prerequisite
    return validate_snapshot(meta, con, latest, data_dir=data_dir)
