"""SQL persistence for discretionary tickets inside caller-owned transactions."""

from __future__ import annotations

import json
from datetime import date, datetime

import duckdb

from .read_model_utils import require_public_positive_integer


class IdentifierSpaceExhausted(RuntimeError):
    """Raised when a paper ledger can no longer allocate a public JSON-safe ID."""


def portfolio_active(
    con: duckdb.DuckDBPyConnection,
    discretionary_id: str,
) -> tuple[bool, bool | None]:
    """Return whether the book exists and its nullable active flag."""
    row = con.execute(
        "SELECT active FROM portfolios WHERE id = ?",
        [discretionary_id],
    ).fetchone()
    return (False, None) if row is None else (True, row[0])


def insert_portfolio(
    con: duckdb.DuckDBPyConnection,
    as_of: date,
    *,
    discretionary_id: str,
    initial_cash: float,
) -> None:
    con.execute(
        "INSERT INTO portfolios (id, name, strategy, config, created, active, "
        "cash, initial_cash, execution_profile) "
        "VALUES (?, ?, ?, ?, ?, TRUE, ?, ?, ?)",
        [
            discretionary_id,
            "Discretionary (paper)",
            "discretionary",
            json.dumps({"kind": "discretionary"}),
            as_of,
            initial_cash,
            initial_cash,
            "baseline_v1",
        ],
    )


def available_to_sell(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    *,
    discretionary_id: str,
) -> float:
    held = con.execute(
        "SELECT COALESCE(SUM(qty), 0) FROM sim_positions "
        "WHERE portfolio_id = ? AND ticker = ? AND qty > 0",
        [discretionary_id, ticker],
    ).fetchone()[0]
    pending = con.execute(
        "SELECT COALESCE(SUM(qty), 0) FROM sim_orders "
        "WHERE portfolio_id = ? AND ticker = ? AND side = 'sell' AND status = 'pending'",
        [discretionary_id, ticker],
    ).fetchone()[0]
    return float(held) - float(pending)


def _next_id(con: duckdb.DuckDBPyConnection, table: str) -> int:
    if table not in {"disc_tickets", "sim_orders"}:
        raise ValueError(f"unsupported ticket ID table: {table}")
    maximum = con.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table}").fetchone()[0]
    try:
        return require_public_positive_integer(maximum + 1)
    except (TypeError, ValueError) as exc:
        raise IdentifierSpaceExhausted(table) from exc


def insert_pending_order(
    con: duckdb.DuckDBPyConnection,
    ticket: dict,
    signal_date: date,
    *,
    discretionary_id: str,
) -> int:
    order_id = _next_id(con, "sim_orders")
    con.execute(
        "INSERT INTO sim_orders (id, portfolio_id, ticker, side, qty, "
        "signal_date, status, reject_reason) "
        "VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL)",
        [
            order_id,
            discretionary_id,
            ticket["ticker"],
            ticket["side"],
            ticket["qty"],
            signal_date,
        ],
    )
    return order_id


def insert_ticket(
    con: duckdb.DuckDBPyConnection,
    ticket: dict,
    gates: list[dict],
    status: str,
    order_id: int | None,
    submitted_at: datetime,
) -> int:
    ticket_id = _next_id(con, "disc_tickets")
    con.execute(
        "INSERT INTO disc_tickets (id, ticker, side, qty, entry_ref, stop, "
        "target, playbook, emotion, notes, gates, status, order_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ticket_id,
            ticket["ticker"],
            ticket["side"],
            ticket["qty"],
            ticket["entry_ref"],
            ticket["stop"],
            ticket["target"],
            ticket["playbook"],
            ticket["emotion"],
            ticket["notes"],
            json.dumps(gates, default=str),
            status,
            order_id,
            submitted_at,
        ],
    )
    return ticket_id


def ticket_order_id(
    con: duckdb.DuckDBPyConnection,
    ticket_id: int,
) -> tuple[bool, int | None]:
    row = con.execute(
        "SELECT order_id FROM disc_tickets WHERE id = ?",
        [ticket_id],
    ).fetchone()
    return (False, None) if row is None else (True, row[0])


def order_status(
    con: duckdb.DuckDBPyConnection,
    order_id: int,
) -> tuple[bool, str | None]:
    row = con.execute(
        "SELECT status FROM sim_orders WHERE id = ?",
        [order_id],
    ).fetchone()
    return (False, None) if row is None else (True, row[0])


def cancel_pending_order(
    con: duckdb.DuckDBPyConnection,
    ticket_id: int,
    order_id: int,
) -> None:
    con.execute(
        "UPDATE sim_orders SET status = 'cancelled', "
        "reject_reason = 'cancelled by user' WHERE id = ?",
        [order_id],
    )
    con.execute(
        "UPDATE disc_tickets SET status = 'cancelled' WHERE id = ?",
        [ticket_id],
    )


def insert_review_marker(con: duckdb.DuckDBPyConnection, timestamp: datetime) -> None:
    con.execute(
        "INSERT INTO review_markers (ts, kind) VALUES (?, ?)",
        [timestamp, "circuit_breaker"],
    )
