"""Read-only preflight for a future isolated paper-book initialization.

The preflight verifies one exact :mod:`agent_paper_book_plan` against current
DuckDB schema and state. It performs no DDL, inserts, updates, scheduling, or
order routing and cannot grant initialization or execution authority.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256
from engine.lib.settings import DEFAULT_DB

from . import agent_paper_attribution, agent_paper_book_plan, agent_policy
from .json_utils import loads_object

PREFLIGHT_SCHEMA_VERSION = 1
EXPECTED_TABLE_SCHEMAS = {
    "portfolios": (
        ("id", "VARCHAR"),
        ("name", "VARCHAR"),
        ("strategy", "VARCHAR"),
        ("config", "VARCHAR"),
        ("created", "DATE"),
        ("active", "BOOLEAN"),
        ("cash", "DOUBLE"),
        ("initial_cash", "DOUBLE"),
        ("execution_profile", "VARCHAR"),
    ),
    agent_paper_attribution.BOOK_ATTRIBUTION_TABLE: (
        agent_paper_attribution.BOOK_ATTRIBUTION_SCHEMA
    ),
    agent_paper_attribution.ORDER_ATTRIBUTION_TABLE: (
        agent_paper_attribution.ORDER_ATTRIBUTION_SCHEMA
    ),
    "sim_orders": (
        ("id", "BIGINT"),
        ("portfolio_id", "VARCHAR"),
        ("ticker", "VARCHAR"),
        ("side", "VARCHAR"),
        ("qty", "DOUBLE"),
        ("signal_date", "DATE"),
        ("status", "VARCHAR"),
        ("reject_reason", "VARCHAR"),
    ),
    "sim_fills": (
        ("order_id", "BIGINT"),
        ("portfolio_id", "VARCHAR"),
        ("ticker", "VARCHAR"),
        ("side", "VARCHAR"),
        ("qty", "DOUBLE"),
        ("fill_date", "DATE"),
        ("open_px", "DOUBLE"),
        ("fill_px", "DOUBLE"),
        ("slippage_bps", "DOUBLE"),
        ("cost_bps", "DOUBLE"),
    ),
    "sim_positions": (
        ("portfolio_id", "VARCHAR"),
        ("ticker", "VARCHAR"),
        ("qty", "DOUBLE"),
        ("avg_cost", "DOUBLE"),
    ),
    "sim_dividends": (
        ("portfolio_id", "VARCHAR"),
        ("ticker", "VARCHAR"),
        ("ex_date", "DATE"),
        ("qty", "DOUBLE"),
        ("dps", "DOUBLE"),
        ("amount", "DOUBLE"),
    ),
    "sim_equity": (
        ("portfolio_id", "VARCHAR"),
        ("date", "DATE"),
        ("equity", "DOUBLE"),
        ("cash", "DOUBLE"),
        ("n_positions", "INTEGER"),
    ),
}
EXPECTED_TABLE_KEYS = {
    "portfolios": {
        ("PRIMARY KEY", ("id",)),
    },
    agent_paper_attribution.BOOK_ATTRIBUTION_TABLE: {
        ("PRIMARY KEY", agent_paper_attribution.BOOK_ATTRIBUTION_PRIMARY_KEY),
        ("UNIQUE", agent_paper_attribution.BOOK_ATTRIBUTION_UNIQUE_KEYS[0]),
    },
    agent_paper_attribution.ORDER_ATTRIBUTION_TABLE: {
        ("PRIMARY KEY", agent_paper_attribution.ORDER_ATTRIBUTION_PRIMARY_KEY),
        ("UNIQUE", agent_paper_attribution.ORDER_ATTRIBUTION_UNIQUE_KEYS[0]),
    },
    "sim_orders": {
        ("PRIMARY KEY", ("id",)),
    },
    "sim_fills": set(),
    "sim_positions": {
        ("PRIMARY KEY", ("portfolio_id", "ticker")),
    },
    "sim_dividends": {
        ("PRIMARY KEY", ("portfolio_id", "ticker", "ex_date")),
    },
    "sim_equity": {
        ("PRIMARY KEY", ("portfolio_id", "date")),
    },
}


class PaperBookPreflightError(ValueError):
    """The plan or readable store cannot support a trustworthy preflight."""


def _finite(value: object) -> float | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        return None
    return float(value)


def _schema(con: duckdb.DuckDBPyConnection, table: str) -> dict:
    table_rows = con.execute(
        "SELECT table_type FROM information_schema.tables "
        "WHERE table_catalog = current_catalog() "
        "AND table_schema = current_schema() AND table_name = ?",
        [table],
    ).fetchall()
    if not table_rows:
        return {
            "table": table,
            "status": "missing",
            "table_type": None,
            "expected_columns": [list(item) for item in EXPECTED_TABLE_SCHEMAS[table]],
            "actual_columns": [],
            "expected_keys": [
                [kind, list(columns)]
                for kind, columns in sorted(EXPECTED_TABLE_KEYS[table])
            ],
            "actual_keys": [],
            "required_nonnullable_columns": (
                [name for name, _kind in EXPECTED_TABLE_SCHEMAS[table]]
                if table
                in {
                    agent_paper_attribution.BOOK_ATTRIBUTION_TABLE,
                    agent_paper_attribution.ORDER_ATTRIBUTION_TABLE,
                }
                else []
            ),
            "actual_nullable_columns": [],
        }
    column_rows = con.execute(
        "SELECT column_name, data_type, is_nullable "
        "FROM information_schema.columns "
        "WHERE table_catalog = current_catalog() "
        "AND table_schema = current_schema() AND table_name = ? "
        "ORDER BY ordinal_position",
        [table],
    ).fetchall()
    expected = EXPECTED_TABLE_SCHEMAS[table]
    actual = tuple((str(name), str(kind)) for name, kind, _nullable in column_rows)
    nullable = sorted(
        str(name) for name, _kind, is_nullable in column_rows if is_nullable != "NO"
    )
    key_rows = con.execute(
        "SELECT tc.constraint_type, tc.constraint_name, kcu.column_name, "
        "kcu.ordinal_position FROM information_schema.table_constraints tc "
        "JOIN information_schema.key_column_usage kcu "
        "USING (constraint_catalog, constraint_schema, constraint_name) "
        "WHERE tc.table_catalog = current_catalog() "
        "AND tc.table_schema = current_schema() AND tc.table_name = ? "
        "AND tc.constraint_type IN ('PRIMARY KEY', 'UNIQUE') "
        "ORDER BY tc.constraint_type, tc.constraint_name, kcu.ordinal_position",
        [table],
    ).fetchall()
    grouped_keys: dict[tuple[str, str], list[str]] = {}
    for kind, name, column, _position in key_rows:
        grouped_keys.setdefault((str(kind), str(name)), []).append(str(column))
    actual_keys = {
        (kind, tuple(columns))
        for (kind, _name), columns in grouped_keys.items()
    }
    expected_keys = EXPECTED_TABLE_KEYS[table]
    required_nonnullable = (
        {name for name, _kind in expected}
        if table
        in {
            agent_paper_attribution.BOOK_ATTRIBUTION_TABLE,
            agent_paper_attribution.ORDER_ATTRIBUTION_TABLE,
        }
        else set()
    )
    valid = (
        table_rows == [("BASE TABLE",)]
        and actual == expected
        and actual_keys == expected_keys
        and not (required_nonnullable & set(nullable))
    )
    return {
        "table": table,
        "status": "pass" if valid else "invalid",
        "table_type": table_rows[0][0] if len(table_rows) == 1 else "ambiguous",
        "expected_columns": [list(item) for item in expected],
        "actual_columns": [list(item) for item in actual],
        "expected_keys": [
            [kind, list(columns)] for kind, columns in sorted(expected_keys)
        ],
        "actual_keys": [
            [kind, list(columns)] for kind, columns in sorted(actual_keys)
        ],
        "required_nonnullable_columns": sorted(required_nonnullable),
        "actual_nullable_columns": nullable,
    }


def _reserved_counts(
    con: duckdb.DuckDBPyConnection,
    plan: dict,
    schemas: dict[str, dict],
) -> dict[str, int | None]:
    portfolio_id = plan["portfolio_id"]
    policy_id = plan["policy_id"]
    queries = {
        "portfolios": (
            "SELECT COUNT(*) FROM portfolios WHERE id = ?",
            [portfolio_id],
        ),
        agent_paper_attribution.BOOK_ATTRIBUTION_TABLE: (
            "SELECT COUNT(*) FROM agent_paper_book_attribution "
            "WHERE portfolio_id = ? OR policy_id = ?",
            [portfolio_id, policy_id],
        ),
        agent_paper_attribution.ORDER_ATTRIBUTION_TABLE: (
            "SELECT COUNT(*) FROM agent_paper_order_attribution "
            "WHERE portfolio_id = ? OR policy_id = ?",
            [portfolio_id, policy_id],
        ),
        "sim_orders": (
            "SELECT COUNT(*) FROM sim_orders WHERE portfolio_id = ?",
            [portfolio_id],
        ),
        "sim_fills": (
            "SELECT COUNT(*) FROM sim_fills WHERE portfolio_id = ?",
            [portfolio_id],
        ),
        "sim_positions": (
            "SELECT COUNT(*) FROM sim_positions WHERE portfolio_id = ?",
            [portfolio_id],
        ),
        "sim_dividends": (
            "SELECT COUNT(*) FROM sim_dividends WHERE portfolio_id = ?",
            [portfolio_id],
        ),
        "sim_equity": (
            "SELECT COUNT(*) FROM sim_equity WHERE portfolio_id = ?",
            [portfolio_id],
        ),
    }
    return {
        table: (
            None
            if schemas[table]["status"] != "pass"
            else int(con.execute(statement, parameters).fetchone()[0])
        )
        for table, (statement, parameters) in queries.items()
    }


def _control_snapshot(
    con: duckdb.DuckDBPyConnection,
    plan: dict,
    schemas: dict[str, dict],
) -> list[dict]:
    controls = []
    portfolio_schema_ready = schemas["portfolios"]["status"] == "pass"
    equity_schema_ready = schemas["sim_equity"]["status"] == "pass"
    for expected in plan["required_existing_control_portfolios"]:
        portfolio_id = expected["portfolio_id"]
        rows = (
            []
            if not portfolio_schema_ready
            else con.execute(
                "SELECT id, strategy, config, created, active, cash, "
                "initial_cash, execution_profile FROM portfolios WHERE id = ?",
                [portfolio_id],
            ).fetchall()
        )
        identity_matches = False
        normalized_row = None
        if len(rows) == 1:
            row = rows[0]
            try:
                config_sha256 = canonical_sha256(loads_object(row[2]))
            except (TypeError, ValueError, UnicodeDecodeError):
                config_sha256 = None
            cash = _finite(row[5])
            initial_cash = _finite(row[6])
            normalized_row = {
                "portfolio_id": row[0],
                "strategy": row[1],
                "config_sha256": config_sha256,
                "created": row[3].isoformat() if type(row[3]) is date else None,
                "active": row[4] if type(row[4]) is bool else None,
                "cash": cash,
                "initial_cash": initial_cash,
                "execution_profile": row[7],
            }
            identity_matches = (
                normalized_row["portfolio_id"] == portfolio_id
                and normalized_row["strategy"] == expected["strategy"]
                and normalized_row["config_sha256"] == expected["config_sha256"]
                and normalized_row["created"] is not None
                and normalized_row["created"] <= expected["created_on_or_before"]
                and normalized_row["active"] is expected["active"]
                and normalized_row["initial_cash"] == expected["initial_cash"]
                and normalized_row["execution_profile"]
                == expected["execution_profile"]
                and cash is not None
                and cash >= 0
            )
        equity_rows = (
            []
            if not equity_schema_ready
            else con.execute(
                "SELECT date, equity, cash, n_positions FROM sim_equity "
                "WHERE portfolio_id = ? AND date = ?",
                [portfolio_id, expected["required_equity_date"]],
            ).fetchall()
        )
        normalized_equity = None
        if len(equity_rows) == 1:
            equity_date, equity, cash, positions = equity_rows[0]
            normalized_equity = {
                "date": (
                    equity_date.isoformat()
                    if type(equity_date) is date
                    else None
                ),
                "equity": _finite(equity),
                "cash": _finite(cash),
                "n_positions": (
                    positions
                    if isinstance(positions, int)
                    and not isinstance(positions, bool)
                    and positions >= 0
                    else None
                ),
            }
        controls.append(
            {
                "portfolio_id": portfolio_id,
                "portfolio_row_count": len(rows) if portfolio_schema_ready else None,
                "identity_matches": identity_matches,
                "portfolio_state": normalized_row,
                "required_equity_date": expected["required_equity_date"],
                "equity_row_count": len(equity_rows) if equity_schema_ready else None,
                "equity_available": (
                    normalized_equity is not None
                    and normalized_equity["date"] is not None
                    and normalized_equity["equity"] is not None
                    and normalized_equity["cash"] is not None
                    and normalized_equity["n_positions"] is not None
                ),
                "equity_state": normalized_equity,
                "mutation_allowed": False,
            }
        )
    return controls


def _capture(con: duckdb.DuckDBPyConnection, plan: dict) -> dict:
    schemas = {
        table: _schema(con, table)
        for table in plan["required_preexisting_tables"]
    }
    controls = _control_snapshot(con, plan, schemas)
    protected = [
        {
            "portfolio_id": control["portfolio_id"],
            "portfolio_state": control["portfolio_state"],
            "equity_state": control["equity_state"],
        }
        for control in controls
    ]
    return {
        "schemas": schemas,
        "reserved_row_counts": _reserved_counts(con, plan, schemas),
        "controls": controls,
        "protected_portfolio_snapshot_sha256": canonical_sha256(protected),
    }


def _gate(name: str, passed: bool, evidence: dict) -> dict:
    return {
        "name": name,
        "status": "pass" if passed else "blocked",
        "evidence": evidence,
    }


def assess(
    con: duckdb.DuckDBPyConnection,
    plan: dict,
    policy: dict,
) -> dict:
    """Assess one plan against current state without changing that state."""
    try:
        verified_plan = agent_paper_book_plan.verify_plan(plan, policy)
        first = _capture(con, verified_plan)
        second = _capture(con, verified_plan)
    except (duckdb.Error, agent_paper_book_plan.PaperBookPlanError) as exc:
        if isinstance(exc, agent_paper_book_plan.PaperBookPlanError):
            raise PaperBookPreflightError(str(exc)) from exc
        raise PaperBookPreflightError(
            "paper book preflight store is unreadable"
        ) from exc
    stable = first == second
    capture = second
    schema_ready = all(
        value["status"] == "pass" for value in capture["schemas"].values()
    )
    reservation_ready = schema_ready and all(
        count == 0 for count in capture["reserved_row_counts"].values()
    )
    controls_ready = all(
        control["identity_matches"] for control in capture["controls"]
    )
    equity_ready = all(
        control["equity_available"] for control in capture["controls"]
    ) and len(
        {
            control["equity_state"]["date"]
            for control in capture["controls"]
            if control["equity_state"] is not None
        }
    ) == 1
    inert = (
        verified_plan["portfolio_active"] is False
        and verified_plan["scheduler_integration_implemented"] is False
        and verified_plan["writer_implemented"] is True
        and verified_plan["writer_entrypoint"]
        == "tools.initialize_agent_paper_book"
        and verified_plan["database_mutation_performed"] is False
        and verified_plan["order_route_implemented"] is False
        and verified_plan["execution_authority"] == "none"
    )
    gates = [
        _gate(
            "verified_initialization_plan",
            True,
            {
                "plan_sha256": verified_plan["plan_sha256"],
                "policy_registration_sha256": verified_plan[
                    "policy_registration_sha256"
                ],
                "record_count": len(verified_plan["expected_records"]),
            },
        ),
        _gate(
            "required_persistence_schema",
            schema_ready,
            {"tables": list(capture["schemas"].values())},
        ),
        _gate(
            "reserved_identity_absent",
            reservation_ready,
            {
                "portfolio_id": verified_plan["portfolio_id"],
                "policy_id": verified_plan["policy_id"],
                "row_counts": capture["reserved_row_counts"],
            },
        ),
        _gate(
            "existing_control_portfolios",
            controls_ready,
            {
                "controls": [
                    {
                        "portfolio_id": control["portfolio_id"],
                        "portfolio_row_count": control["portfolio_row_count"],
                        "identity_matches": control["identity_matches"],
                        "mutation_allowed": False,
                    }
                    for control in capture["controls"]
                ],
                "protected_portfolio_snapshot_sha256": capture[
                    "protected_portfolio_snapshot_sha256"
                ],
            },
        ),
        _gate(
            "control_equity_anchor",
            equity_ready,
            {
                "controls": [
                    {
                        "portfolio_id": control["portfolio_id"],
                        "required_equity_date": control["required_equity_date"],
                        "equity_row_count": control["equity_row_count"],
                        "equity_available": control["equity_available"],
                        "selected_equity_date": (
                            None
                            if control["equity_state"] is None
                            else control["equity_state"]["date"]
                        ),
                    }
                    for control in capture["controls"]
                ]
            },
        ),
        _gate(
            "stable_read_snapshot",
            stable,
            {
                "capture_sha256": canonical_sha256(capture) if stable else None,
                "read_count": 2,
            },
        ),
        _gate(
            "inert_execution_surface",
            inert,
            {
                "writer_implemented": verified_plan["writer_implemented"],
                "writer_entrypoint": verified_plan["writer_entrypoint"],
                "scheduler_integration_implemented": verified_plan[
                    "scheduler_integration_implemented"
                ],
                "order_route_implemented": verified_plan[
                    "order_route_implemented"
                ],
                "execution_authority": verified_plan["execution_authority"],
            },
        ),
    ]
    passed = all(gate["status"] == "pass" for gate in gates)
    body = {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "status": (
            "ready_for_backup_gated_inactive_initialization"
            if passed
            else "blocked"
        ),
        "preconditions_passed": passed,
        "policy_id": verified_plan["policy_id"],
        "mode": verified_plan["mode"],
        "portfolio_id": verified_plan["portfolio_id"],
        "attribution_start_date": verified_plan["attribution_start_date"],
        "plan_sha256": verified_plan["plan_sha256"],
        "blockers": [
            gate["name"] for gate in gates if gate["status"] == "blocked"
        ],
        "gates": gates,
        "protected_portfolio_ids": verified_plan["protected_portfolio_ids"],
        "protected_portfolio_snapshot_sha256": capture[
            "protected_portfolio_snapshot_sha256"
        ],
        "database_mutation_performed": False,
        "writer_implemented": verified_plan["writer_implemented"],
        "writer_entrypoint": verified_plan["writer_entrypoint"],
        "scheduler_integration_implemented": False,
        "order_route_implemented": False,
        "initialization_authority": "none",
        "execution_authority": "none",
    }
    return {**body, "preflight_sha256": canonical_sha256(body)}


def assess_database(
    database: Path,
    policy_id: str,
    attribution_start_date: date,
    *,
    planned_at: datetime,
) -> dict:
    """Build and assess a plan through one read-only database connection."""
    try:
        policy = agent_policy.get(policy_id)
        initialization_plan = agent_paper_book_plan.plan(
            policy,
            attribution_start_date,
            planned_at=planned_at,
        )
    except (
        agent_policy.PolicyError,
        agent_paper_book_plan.PaperBookPlanError,
    ) as exc:
        raise PaperBookPreflightError(str(exc)) from exc
    con = engine_db.connect(database, read_only=True, wait_s=0)
    try:
        return assess(con, initialization_plan, policy)
    finally:
        con.close()


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
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)
    result = assess_database(
        args.db,
        args.policy_id,
        args.attribution_start_date,
        planned_at=datetime.now(timezone.utc),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["preconditions_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
