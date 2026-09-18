#!/usr/bin/env python3
"""Initialize one inactive isolated agent paper book after backup verification.

This operator-only command consumes the exact plan produced by
``server.agent_paper_book_plan``. It inserts one inactive portfolio, one
book-attribution contract, and one cash-only opening equity row in a single
transaction. It does not activate the portfolio, create an order, add a
schedule or route, or grant execution authority.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256
from engine.lib.settings import DEFAULT_DB, REPO_ROOT
from server import (
    agent_paper_attribution,
    agent_paper_book_plan,
    agent_paper_book_preflight,
    agent_policy,
)
from tools import backup_database

SCHEMA_VERSION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
INSERTED_TABLES = (
    "portfolios",
    agent_paper_attribution.BOOK_ATTRIBUTION_TABLE,
    "sim_equity",
)


class PaperBookInitializationError(RuntimeError):
    """The guarded inactive-book initialization could not be applied."""


def _database_location(repo_root: Path, database: Path) -> dict:
    try:
        relative = database.resolve(strict=True).relative_to(
            repo_root.resolve(strict=True)
        )
    except (OSError, ValueError) as exc:
        raise PaperBookInitializationError(
            "initialization database must be an existing repository-relative file"
        ) from exc
    return {"kind": "repository-relative", "path": relative.as_posix()}


def _current_snapshot(con: duckdb.DuckDBPyConnection) -> dict:
    database_name = con.execute("SELECT current_database()").fetchone()[0]
    return backup_database.database_snapshot(con, database_name)


def _catalog(con: duckdb.DuckDBPyConnection) -> dict:
    database_name = con.execute("SELECT current_database()").fetchone()[0]
    return backup_database._catalog_rows(con, database_name)


def _timestamp(value: datetime) -> str:
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    if aware.utcoffset() is None or aware.utcoffset().total_seconds() != 0:
        raise PaperBookInitializationError(
            "persisted paper book timestamp is invalid"
        )
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _expected_records(plan: dict) -> dict[str, dict]:
    records = plan["expected_records"]
    if (
        not isinstance(records, list)
        or len(records) != len(INSERTED_TABLES)
        or tuple(record.get("table") for record in records) != INSERTED_TABLES
        or any(record.get("operation") != "insert_only" for record in records)
    ):
        raise PaperBookInitializationError(
            "paper book plan insert scope is invalid"
        )
    return {record["table"]: record["values"] for record in records}


def _insert_records(con: duckdb.DuckDBPyConnection, plan: dict) -> None:
    records = _expected_records(plan)
    portfolio = records["portfolios"]
    con.execute(
        "INSERT INTO portfolios "
        "(id, name, strategy, config, created, active, cash, initial_cash, "
        "execution_profile) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            portfolio["id"],
            portfolio["name"],
            portfolio["strategy"],
            portfolio["config"],
            portfolio["created"],
            portfolio["active"],
            portfolio["cash"],
            portfolio["initial_cash"],
            portfolio["execution_profile"],
        ],
    )
    attribution = records[agent_paper_attribution.BOOK_ATTRIBUTION_TABLE]
    con.execute(
        "INSERT INTO agent_paper_book_attribution "
        "(portfolio_id, policy_id, policy_registration_sha256, mode, "
        "contract_payload, contract_sha256, recorded_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            attribution["portfolio_id"],
            attribution["policy_id"],
            attribution["policy_registration_sha256"],
            attribution["mode"],
            attribution["contract_payload"],
            attribution["contract_sha256"],
            attribution["recorded_at"],
        ],
    )
    equity = records["sim_equity"]
    con.execute(
        "INSERT INTO sim_equity "
        "(portfolio_id, date, equity, cash, n_positions) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            equity["portfolio_id"],
            equity["date"],
            equity["equity"],
            equity["cash"],
            equity["n_positions"],
        ],
    )


def _persisted_records(
    con: duckdb.DuckDBPyConnection,
    plan: dict,
) -> dict[str, dict]:
    portfolio_id = plan["portfolio_id"]
    portfolio_rows = con.execute(
        "SELECT id, name, strategy, config, created, active, cash, initial_cash, "
        "execution_profile FROM portfolios WHERE id = ?",
        [portfolio_id],
    ).fetchall()
    attribution_rows = con.execute(
        "SELECT portfolio_id, policy_id, policy_registration_sha256, mode, "
        "contract_payload, contract_sha256, recorded_at "
        "FROM agent_paper_book_attribution WHERE portfolio_id = ?",
        [portfolio_id],
    ).fetchall()
    equity_rows = con.execute(
        "SELECT portfolio_id, date, equity, cash, n_positions "
        "FROM sim_equity WHERE portfolio_id = ?",
        [portfolio_id],
    ).fetchall()
    if not (
        len(portfolio_rows) == len(attribution_rows) == len(equity_rows) == 1
    ):
        raise PaperBookInitializationError(
            "paper book initialization did not create exactly one record per target"
        )
    portfolio = portfolio_rows[0]
    attribution = attribution_rows[0]
    equity = equity_rows[0]
    if type(portfolio[4]) is not date or type(equity[1]) is not date:
        raise PaperBookInitializationError(
            "persisted paper book dates are invalid"
        )
    if type(attribution[6]) is not datetime:
        raise PaperBookInitializationError(
            "persisted paper book timestamp is invalid"
        )
    return {
        "portfolios": {
            "id": portfolio[0],
            "name": portfolio[1],
            "strategy": portfolio[2],
            "config": portfolio[3],
            "created": portfolio[4].isoformat(),
            "active": portfolio[5],
            "cash": float(portfolio[6]),
            "initial_cash": float(portfolio[7]),
            "execution_profile": portfolio[8],
        },
        agent_paper_attribution.BOOK_ATTRIBUTION_TABLE: {
            "portfolio_id": attribution[0],
            "policy_id": attribution[1],
            "policy_registration_sha256": attribution[2],
            "mode": attribution[3],
            "contract_payload": attribution[4],
            "contract_sha256": attribution[5],
            "recorded_at": _timestamp(attribution[6]),
        },
        "sim_equity": {
            "portfolio_id": equity[0],
            "date": equity[1].isoformat(),
            "equity": float(equity[2]),
            "cash": float(equity[3]),
            "n_positions": equity[4],
        },
    }


def _require_scoped_change(
    before: dict,
    after: dict,
    *,
    before_catalog: dict,
    after_catalog: dict,
    before_capture: dict,
    after_capture: dict,
    plan: dict,
    policy: dict,
    con: duckdb.DuckDBPyConnection,
) -> dict:
    expected_counts = dict(before["row_counts"])
    for table in INSERTED_TABLES:
        key = f"main.{table}"
        expected_counts[key] += 1
    unchanged_fields = (
        "schema_sha256",
        "table_count",
        "view_count",
        "index_count",
        "latest_price_date",
        "job_states",
        "active_portfolio_count",
        "active_portfolios_sha256",
    )
    expected_reserved_counts = {
        "portfolios": 1,
        agent_paper_attribution.BOOK_ATTRIBUTION_TABLE: 1,
        agent_paper_attribution.ORDER_ATTRIBUTION_TABLE: 0,
        "sim_orders": 0,
        "sim_fills": 0,
        "sim_positions": 0,
        "sim_dividends": 0,
        "sim_equity": 1,
    }
    expected_records = _expected_records(plan)
    persisted_records = _persisted_records(con, plan)
    if (
        after["row_counts"] != expected_counts
        or any(after[field] != before[field] for field in unchanged_fields)
        or after_catalog != before_catalog
        or after_capture["reserved_row_counts"] != expected_reserved_counts
        or after_capture["schemas"] != before_capture["schemas"]
        or after_capture["controls"] != before_capture["controls"]
        or after_capture["protected_portfolio_snapshot_sha256"]
        != before_capture["protected_portfolio_snapshot_sha256"]
        or persisted_records != expected_records
    ):
        raise PaperBookInitializationError(
            "paper book initialization changed state outside its exact plan"
        )
    attribution = agent_paper_attribution.assess_policy(
        con,
        policy,
        decision_records=[],
    )
    if (
        attribution["status"] != agent_paper_attribution.STATUS_AVAILABLE
        or attribution["portfolio_id"] != plan["portfolio_id"]
        or attribution["book_contract_sha256"]
        != plan["book_contract_sha256"]
        or attribution["attribution_start_date"].isoformat()
        != plan["attribution_start_date"]
        or attribution["order_count"] != 0
        or attribution["attributed_order_count"] != 0
        or attribution["fill_count"] != 0
        or attribution["position_count"] != 0
        or attribution["dividend_count"] != 0
        or attribution["equity_observation_count"] != 1
        or attribution["execution_authority"] != "none"
    ):
        raise PaperBookInitializationError(
            "paper book initialization failed attribution verification"
        )
    return attribution


def _require_policy_stable(policy: dict, policy_id: str) -> None:
    try:
        current = agent_policy.get(policy_id)
    except agent_policy.PolicyError as exc:
        raise PaperBookInitializationError(
            "agent policy registration changed during initialization"
        ) from exc
    if current != policy:
        raise PaperBookInitializationError(
            "agent policy registration changed during initialization"
        )


def initialize(
    database: Path,
    backup_bundle: Path,
    expected_manifest_sha256: str,
    policy_id: str,
    attribution_start_date: date,
    *,
    repo_root: Path = REPO_ROOT,
    planned_at: datetime | None = None,
) -> dict:
    """Create one exact inactive book after backup, preflight, and scope proofs."""
    if (
        not isinstance(expected_manifest_sha256, str)
        or _SHA256.fullmatch(expected_manifest_sha256) is None
    ):
        raise PaperBookInitializationError(
            "expected backup manifest SHA-256 is invalid"
        )
    if type(attribution_start_date) is not date:
        raise PaperBookInitializationError(
            "paper book attribution start must be a date"
        )
    planning_time = planned_at or datetime.now(timezone.utc)
    if (
        type(planning_time) is not datetime
        or planning_time.utcoffset() is None
        or planning_time.utcoffset().total_seconds() != 0
    ):
        raise PaperBookInitializationError(
            "paper book planning time must be UTC"
        )
    database = database.resolve(strict=True)
    expected_location = _database_location(repo_root, database)
    try:
        verified_backup = backup_database.verify_backup(backup_bundle)
    except (backup_database.BackupError, OSError) as exc:
        raise PaperBookInitializationError(str(exc)) from exc
    if verified_backup["manifest_sha256"] != expected_manifest_sha256:
        raise PaperBookInitializationError(
            "verified backup manifest identity does not match"
        )
    if verified_backup["source_database"] != expected_location:
        raise PaperBookInitializationError(
            "verified backup names a different source database"
        )
    try:
        policy = agent_policy.get(policy_id)
        plan = agent_paper_book_plan.plan(
            policy,
            attribution_start_date,
            planned_at=planning_time,
        )
    except (
        agent_policy.PolicyError,
        agent_paper_book_plan.PaperBookPlanError,
    ) as exc:
        raise PaperBookInitializationError(str(exc)) from exc

    try:
        con = engine_db.connect(database, wait_s=0)
    except (duckdb.Error, OSError) as exc:
        raise PaperBookInitializationError(
            "paper book initialization database is unavailable"
        ) from exc
    try:
        before = _current_snapshot(con)
        before_catalog = _catalog(con)
        if canonical_sha256(before) != verified_backup["database_snapshot_sha256"]:
            raise PaperBookInitializationError(
                "verified backup does not match the current database snapshot"
            )
        try:
            preflight = agent_paper_book_preflight.assess(con, plan, policy)
        except agent_paper_book_preflight.PaperBookPreflightError as exc:
            raise PaperBookInitializationError(str(exc)) from exc
        if not preflight["preconditions_passed"]:
            raise PaperBookInitializationError(
                "paper book initialization preflight is blocked: "
                + ", ".join(preflight["blockers"])
            )
        before_capture = agent_paper_book_preflight._capture(con, plan)
        try:
            with engine_db.transaction(con):
                _insert_records(con, plan)
                after = _current_snapshot(con)
                after_catalog = _catalog(con)
                after_capture = agent_paper_book_preflight._capture(con, plan)
                attribution = _require_scoped_change(
                    before,
                    after,
                    before_catalog=before_catalog,
                    after_catalog=after_catalog,
                    before_capture=before_capture,
                    after_capture=after_capture,
                    plan=plan,
                    policy=policy,
                    con=con,
                )
                _require_policy_stable(policy, policy_id)
        except (
            duckdb.Error,
            agent_paper_attribution.PaperAttributionError,
            agent_paper_book_preflight.PaperBookPreflightError,
        ) as exc:
            raise PaperBookInitializationError(
                "paper book initialization transaction failed"
            ) from exc
    finally:
        con.close()

    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "inactive_agent_paper_book_initialized",
        "database": expected_location,
        "backup_manifest_sha256": expected_manifest_sha256,
        "before_snapshot_sha256": canonical_sha256(before),
        "after_snapshot_sha256": canonical_sha256(after),
        "policy_id": policy["id"],
        "policy_registration_sha256": policy["registration_sha256"],
        "mode": policy["mode"],
        "portfolio_id": plan["portfolio_id"],
        "portfolio_active": False,
        "attribution_start_date": plan["attribution_start_date"],
        "plan_sha256": plan["plan_sha256"],
        "preflight_sha256": preflight["preflight_sha256"],
        "book_contract_sha256": attribution["book_contract_sha256"],
        "inserted_tables": list(INSERTED_TABLES),
        "inserted_record_count": len(INSERTED_TABLES),
        "order_count": 0,
        "fill_count": 0,
        "position_count": 0,
        "scheduler_integration_implemented": False,
        "order_route_implemented": False,
        "initialization_performed": True,
        "execution_authority": "none",
    }
    return {**body, "initialization_sha256": canonical_sha256(body)}


def _date_arg(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("must be a canonical ISO date")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("policy_id")
    parser.add_argument("attribution_start_date", type=_date_arg)
    parser.add_argument("backup_bundle", type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    try:
        result = initialize(
            args.database,
            args.backup_bundle,
            args.manifest_sha256,
            args.policy_id,
            args.attribution_start_date,
            repo_root=args.repo_root,
        )
    except (PaperBookInitializationError, OSError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
