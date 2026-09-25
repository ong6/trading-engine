"""Isolated P15 comparator-book contracts and lifecycle."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import duckdb

from engine.lib.provenance import canonical_sha256
from sim.schema import init_sim_schema

BOOK_IDS = ("p15_ai_ranked", "p15_rule_control", "p15_hybrid_veto")
INITIAL_CASH = 10_000.0
MECHANICS_VERSION = "p15-book-v1"
COMMON_CONFIG = {
    "mechanics_version": MECHANICS_VERSION,
    "initial_cash": INITIAL_CASH,
    "spy_sleeve": "whole_shares",
    "risk_fraction": 0.01,
    "atr_period": 14,
    "atr_multiple": 2.5,
    "max_name_fraction": 0.15,
    "max_positions": 8,
    "max_new_entries": 2,
    "time_exit_sessions": 10,
    "drawdown_halt": -0.20,
    "execution_profile": "baseline_v1",
    "entry_order_type": "limit_on_open",
}
SELECTION_POLICY = {
    "p15_ai_ranked": "ai_ranked",
    "p15_rule_control": "rule_ranked",
    "p15_hybrid_veto": "rule_ranked_ai_veto",
}


class P15BookError(ValueError):
    """P15 books or their isolated evidence violate the registered contract."""


def _config(portfolio_id: str) -> dict:
    return {**COMMON_CONFIG, "selection_policy": SELECTION_POLICY[portfolio_id]}


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    init_sim_schema(con)
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_book_contracts (
        portfolio_id VARCHAR PRIMARY KEY, mechanics_version VARCHAR NOT NULL,
        config_sha256 VARCHAR NOT NULL UNIQUE, initialized_at TIMESTAMP NOT NULL)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_book_state (
        portfolio_id VARCHAR PRIMARY KEY, peak_equity DOUBLE NOT NULL,
        entry_halted BOOLEAN NOT NULL, updated_at TIMESTAMP NOT NULL)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_order_intents (
        id BIGINT PRIMARY KEY, decision_id BIGINT, portfolio_id VARCHAR NOT NULL,
        ticker VARCHAR NOT NULL, side VARCHAR NOT NULL, qty DOUBLE NOT NULL,
        signal_date DATE NOT NULL, order_role VARCHAR NOT NULL, priority INTEGER NOT NULL,
        signal_close DOUBLE NOT NULL, entry_atr DOUBLE, limit_px DOUBLE,
        status VARCHAR NOT NULL, reason VARCHAR, sim_order_id BIGINT UNIQUE,
        created_at TIMESTAMP NOT NULL,
        UNIQUE(decision_id,portfolio_id,order_role),
        UNIQUE(portfolio_id,ticker,side,signal_date,order_role))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_position_rules (
        portfolio_id VARCHAR NOT NULL, ticker VARCHAR NOT NULL,
        entry_intent_id BIGINT NOT NULL UNIQUE, entry_order_id BIGINT NOT NULL UNIQUE,
        entry_date DATE NOT NULL, entry_atr DOUBLE NOT NULL, stop_px DOUBLE NOT NULL,
        status VARCHAR NOT NULL, PRIMARY KEY(portfolio_id,ticker))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_limit_attempts (
        intent_id BIGINT NOT NULL, attempt_date DATE NOT NULL, limit_px DOUBLE NOT NULL,
        open_px DOUBLE, counterfactual_fill_px DOUBLE, outcome VARCHAR NOT NULL,
        reject_reason VARCHAR, PRIMARY KEY(intent_id,attempt_date))"""
    )


def initialize_books(
    con: duckdb.DuckDBPyConnection,
    created: date,
    *,
    initialized_at: datetime | None = None,
) -> dict:
    """Create or verify the exact three inactive books without runtime rows."""
    init_schema(con)
    initialized = (initialized_at or datetime.now(timezone.utc)).replace(tzinfo=None)
    for portfolio_id in BOOK_IDS:
        config = _config(portfolio_id)
        encoded = json.dumps(config, sort_keys=True, separators=(",", ":"))
        digest = canonical_sha256(config)
        row = con.execute(
            "SELECT strategy,config,created,active,cash,initial_cash,execution_profile "
            "FROM portfolios WHERE id=?",
            [portfolio_id],
        ).fetchone()
        expected = (
            "agent_only_policy", encoded, created, False, INITIAL_CASH,
            INITIAL_CASH, "baseline_v1",
        )
        if row is None:
            con.execute(
                "INSERT INTO portfolios "
                "(id,name,strategy,config,created,active,cash,initial_cash,execution_profile) "
                "VALUES (?,?,?,?,?,FALSE,?,?,?)",
                [portfolio_id, portfolio_id, "agent_only_policy", encoded, created,
                 INITIAL_CASH, INITIAL_CASH, "baseline_v1"],
            )
            con.execute(
                "INSERT INTO p15_book_contracts VALUES (?,?,?,?)",
                [portfolio_id, MECHANICS_VERSION, digest, initialized],
            )
        elif row != expected:
            raise P15BookError(f"P15 book {portfolio_id} differs from its contract")
        contract = con.execute(
            "SELECT mechanics_version,config_sha256 FROM p15_book_contracts "
            "WHERE portfolio_id=?",
            [portfolio_id],
        ).fetchone()
        if contract != (MECHANICS_VERSION, digest):
            raise P15BookError(f"P15 book {portfolio_id} contract is missing or invalid")
    runtime_counts = {
        table: int(con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE portfolio_id IN (?,?,?)", list(BOOK_IDS)
        ).fetchone()[0])
        for table in ("sim_orders", "sim_fills", "sim_positions", "sim_equity")
    }
    states = con.execute(
        "SELECT id,active FROM portfolios WHERE id IN (?,?,?) ORDER BY id", list(BOOK_IDS)
    ).fetchall()
    return {"status": "ready", "book_count": len(states), "active_count": sum(row[1] for row in states),
            "runtime_counts": runtime_counts}


def activation_state(con: duckdb.DuckDBPyConnection) -> str:
    rows = con.execute(
        "SELECT id,active FROM portfolios WHERE id IN (?,?,?) ORDER BY id", list(BOOK_IDS)
    ).fetchall()
    if len(rows) != len(BOOK_IDS):
        return "absent"
    active = sum(bool(row[1]) for row in rows)
    if active == 0:
        return "inactive"
    if active == len(BOOK_IDS):
        return "active"
    raise P15BookError("P15 books have mixed activation state")


def activate_books(con: duckdb.DuckDBPyConnection, checkpoint: date) -> dict:
    """Atomically activate exact empty books at an already-completed checkpoint."""
    if activation_state(con) != "inactive":
        raise P15BookError("P15 books are not jointly inactive")
    for table in ("sim_orders", "sim_fills", "sim_positions", "sim_equity"):
        if con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE portfolio_id IN (?,?,?)", list(BOOK_IDS)
        ).fetchone()[0]:
            raise P15BookError("P15 books already contain runtime state")
    latest = con.execute(
        "SELECT MAX(date) FROM sim_equity WHERE portfolio_id NOT IN (?,?,?)", list(BOOK_IDS)
    ).fetchone()[0]
    if latest is None or checkpoint != latest:
        raise P15BookError("P15 activation checkpoint is not the completed league date")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for portfolio_id in BOOK_IDS:
        con.execute("UPDATE portfolios SET active=TRUE WHERE id=?", [portfolio_id])
        con.execute(
            "INSERT INTO sim_equity VALUES (?,?,?,?,?)",
            [portfolio_id, checkpoint, INITIAL_CASH, INITIAL_CASH, 0],
        )
        con.execute(
            "INSERT INTO p15_book_state VALUES (?,?,FALSE,?)",
            [portfolio_id, INITIAL_CASH, now],
        )
    return {"status": "active", "book_count": len(BOOK_IDS),
            "checkpoint": checkpoint.isoformat()}
