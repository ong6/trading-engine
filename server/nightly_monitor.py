"""Read-only reconciliation of fatal nightly driver and database state."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import duckdb

from engine.lib.settings import DATA_DIR
from engine.lib.util import table_exists
from sim import nyse

from . import nightly_reports
from .status_validation import iso_date, nonnegative_int

log = logging.getLogger(__name__)
P15_PUBLISHER = "p15-scoring"
# Mirrors sim.p15_books.BOOK_IDS and server.p15_scoring_store.POLICY_ID (tests pin both):
# importing them would pull the simulator into the backup tool's recovery closure.
P15_BOOK_IDS = ("p15_ai_ranked", "p15_rule_control", "p15_hybrid_veto")
P15_POLICY_ID = "p15-scoring-v1"
# P15 books are marked by the P15 scoring service, not the nightly: its timer fires at
# 02:30 UTC on the calendar day after each session, and its runner refuses work after
# 12:00 UTC that day, so a session's P15 marks are due by then.
P15_PUBLISH_DEADLINE_UTC = time(12, 0)


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


def _p15_publish_due(latest: date) -> datetime:
    return datetime.combine(latest + timedelta(days=1), P15_PUBLISH_DEADLINE_UTC, timezone.utc)


def _p15_run_finished(con: duckdb.DuckDBPyConnection, latest: date) -> bool:
    if not table_exists(con, "p15_scoring_runs"):
        return False
    row = con.execute(
        "SELECT status FROM p15_scoring_runs WHERE policy_id = ? AND market_date = ?",
        [P15_POLICY_ID, latest],
    ).fetchone()
    return row is not None and row[0] != "running"


def _pending_by_design(
    con: duckdb.DuckDBPyConnection,
    latest: date,
    missing: list[str],
    now: datetime,
) -> bool:
    """True when every missing mark is a P15 book its publisher is not yet due to mark."""
    if not missing or not set(missing) <= set(P15_BOOK_IDS):
        return False
    if now >= _p15_publish_due(latest) or _p15_run_finished(con, latest):
        return False
    # The league renders an unmarked book at its last mark; pending is only the one
    # session the publisher has not reached yet, i.e. marked through the prior session.
    placeholders = ",".join("?" for _ in missing)
    prior = dict(
        con.execute(
            "SELECT portfolio_id, MAX(date) FROM sim_equity "
            f"WHERE portfolio_id IN ({placeholders}) AND date < ? GROUP BY portfolio_id",
            [*missing, latest],
        ).fetchall()
    )
    return all(
        prior.get(portfolio_id) is not None and nyse.next_session(prior[portfolio_id]) == latest
        for portfolio_id in missing
    )


def _active_equity_counts(
    con: duckdb.DuckDBPyConnection, latest: date, now: datetime
) -> tuple[int, int, tuple[str, ...]]:
    rows = con.execute(
        """
        SELECT p.id, e.portfolio_id IS NOT NULL
        FROM portfolios p
        LEFT JOIN sim_equity e ON e.portfolio_id = p.id AND e.date = ?
        WHERE p.active
        ORDER BY p.id
        """,
        [latest],
    ).fetchall()
    active = len(rows)
    with_equity = sum(1 for _, marked in rows if marked)
    if active <= 0:
        raise ValueError("no active portfolios")
    missing = [portfolio_id for portfolio_id, marked in rows if not marked]
    if _pending_by_design(con, latest, missing, now):
        return active, with_equity, tuple(missing)
    if with_equity != active:
        raise _EvidenceResult(
            "incomplete",
            "active-equity-missing",
            active_portfolios=active,
            portfolios_with_equity=with_equity,
        )
    return active, with_equity, ()


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
    equity_counts: tuple[int, int, tuple[str, ...]],
) -> dict:
    screen_count, passing_count, new_count, policy = summary
    active, with_equity, pending = equity_counts
    evidence = {
        "status": "current",
        "as_of": latest,
        "screened": screen_count,
        "passing": passing_count,
        "new_today": new_count,
        "universe_policy": policy,
        "active_portfolios": active,
        "portfolios_with_equity": with_equity,
    }
    if pending:
        evidence.update(
            portfolios_pending_publisher=len(pending),
            pending_publisher=P15_PUBLISHER,
            pending_due_at=_p15_publish_due(latest).isoformat().replace("+00:00", "Z"),
        )
    return evidence


def validate_snapshot(
    meta: dict,
    con: duckdb.DuckDBPyConnection,
    latest: date,
    *,
    data_dir: Path = DATA_DIR,
    now: datetime | None = None,
) -> dict:
    """Reconcile one database snapshot with its generated nightly artifacts."""
    now = now or datetime.now(timezone.utc)
    try:
        summary = _screen_summary(con, latest)
        _validate_screen_metadata(meta, latest, summary)
        equity_counts = _active_equity_counts(con, latest, now)
        nightly_reports.validate(
            meta, latest, summary, con, data_dir, pending=equity_counts[2]
        )
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
    now: datetime | None = None,
) -> dict:
    """Reconcile the fatal nightly core with its database and reports."""
    prerequisite = _prerequisite_status(driver, con, latest)
    if prerequisite is not None:
        return prerequisite
    return validate_snapshot(meta, con, latest, data_dir=data_dir, now=now)
