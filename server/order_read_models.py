"""Read-only active paper-order projections."""

from __future__ import annotations

from datetime import date

import duckdb

from engine.lib.util import table_exists

from .read_model_utils import (
    bound_text_fields,
    require_public_nonnegative_integer,
    require_public_portfolio_id,
    require_public_positive_integer,
    require_public_positive_number,
    require_public_ticker,
    rows,
)
from .ticket_contract import PLAYBOOK_MAX_CHARS

ORDERS_LIMIT = 500
REJECT_REASON_MAX_CHARS = 4_096
ORDER_SIDES = frozenset({"buy", "sell"})
ORDER_STATUSES = frozenset({"pending", "filled", "rejected", "cancelled"})
TERMINAL_WITHOUT_FILL_STATUSES = frozenset({"rejected", "cancelled"})
ORDERS_PROJECTION_FIELDS = frozenset({"status", "limit", "matching_count", "truncated", "orders"})
ORDER_ROW_FIELDS = frozenset(
    {
        "id",
        "portfolio_id",
        "ticker",
        "side",
        "qty",
        "signal_date",
        "status",
        "reject_reason",
        "ticket_id",
        "playbook",
        "stop",
        "target",
        "detail_truncated",
    }
)


def _bound_order_text(order: dict) -> None:
    order["detail_truncated"] = bound_text_fields(
        order,
        {
            "reject_reason": REJECT_REASON_MAX_CHARS,
            "playbook": PLAYBOOK_MAX_CHARS,
        },
    )


def _validate_reject_reason(status: str, reject_reason: object) -> None:
    if status in TERMINAL_WITHOUT_FILL_STATUSES:
        if not isinstance(reject_reason, str) or not reject_reason.strip():
            raise ValueError("public order rejection reason is invalid")
    elif reject_reason is not None:
        raise ValueError("public order rejection reason is invalid")


def _validate_order_ticket_fields(order: dict) -> None:
    if order["ticket_id"] is not None:
        require_public_positive_integer(order["ticket_id"])
    if order["playbook"] is not None and not isinstance(order["playbook"], str):
        raise ValueError("public order playbook is invalid")
    for field in ("stop", "target"):
        if order[field] is not None:
            require_public_positive_number(order[field], f"order {field}")


def _validate_order_display_text(order: dict) -> None:
    lengths = []
    for field, limit in (
        ("playbook", PLAYBOOK_MAX_CHARS),
        ("reject_reason", REJECT_REASON_MAX_CHARS),
    ):
        value = order[field]
        if value is not None:
            if not isinstance(value, str) or len(value) > limit:
                raise ValueError(f"public order {field} is invalid")
            lengths.append((len(value), limit))
    if type(order["detail_truncated"]) is not bool or (
        order["detail_truncated"] and not any(length == limit for length, limit in lengths)
    ):
        raise ValueError("public order truncation state is invalid")


def _validate_order(order: dict, requested_status: str | None) -> int:
    if not isinstance(order, dict) or set(order) != ORDER_ROW_FIELDS:
        raise ValueError("public order shape is invalid")
    order_id = require_public_positive_integer(order["id"])
    require_public_portfolio_id(order["portfolio_id"])
    require_public_ticker(order["ticker"])
    if order["side"] not in ORDER_SIDES:
        raise ValueError("public order side is invalid")
    require_public_positive_number(order["qty"], "order quantity")
    if type(order["signal_date"]) is not date:
        raise ValueError("public order signal date is invalid")
    status = order["status"]
    if status not in ORDER_STATUSES or (
        requested_status is not None and status != requested_status
    ):
        raise ValueError("public order status is invalid")
    _validate_reject_reason(status, order["reject_reason"])
    _validate_order_ticket_fields(order)
    _validate_order_display_text(order)
    return order_id


def _validate_orders_projection(payload: dict, requested_status: str | None) -> None:
    if not isinstance(payload, dict) or set(payload) != ORDERS_PROJECTION_FIELDS:
        raise ValueError("public orders projection shape is invalid")
    if payload["status"] != requested_status:
        raise ValueError("public order filter status is invalid")
    limit = require_public_positive_integer(payload["limit"])
    matching_count = require_public_nonnegative_integer(payload["matching_count"])
    orders = payload["orders"]
    if (
        limit != ORDERS_LIMIT
        or not isinstance(orders, list)
        or len(orders) != min(matching_count, limit)
        or type(payload["truncated"]) is not bool
        or payload["truncated"] != (matching_count > len(orders))
    ):
        raise ValueError("public orders collection is inconsistent")
    seen_ids = set()
    previous_id = None
    for order in orders:
        order_id = _validate_order(order, requested_status)
        if order_id in seen_ids:
            raise ValueError("public order identifier is duplicated")
        if previous_id is not None and order_id >= previous_id:
            raise ValueError("public orders are not ordered")
        seen_ids.add(order_id)
        previous_id = order_id


def _orders_payload(status: str | None, order_rows: list[dict]) -> dict:
    if status is not None and status not in ORDER_STATUSES:
        raise ValueError("public order filter status is invalid")
    matching_count = (
        require_public_nonnegative_integer(order_rows[0].pop("_matching_count"))
        if order_rows
        else 0
    )
    for order in order_rows[1:]:
        order.pop("_matching_count")
    for order in order_rows:
        _bound_order_text(order)
    payload = {
        "status": status,
        "limit": ORDERS_LIMIT,
        "matching_count": matching_count,
        "truncated": matching_count > ORDERS_LIMIT,
        "orders": order_rows,
    }
    _validate_orders_projection(payload, status)
    return payload


def _order_rows(con: duckdb.DuckDBPyConnection, status: str | None) -> list[dict]:
    has_tickets = table_exists(con, "disc_tickets")
    status_clause = " AND o.status = ?" if status else ""
    parameters = [status] if status else []
    ticket_columns = (
        ", t.id AS ticket_id, t.playbook, t.stop, t.target"
        if has_tickets
        else ", NULL AS ticket_id, NULL AS playbook, NULL AS stop, NULL AS target"
    )
    ticket_join = " LEFT JOIN disc_tickets t ON t.order_id = matching.id" if has_tickets else ""
    cursor = con.execute(
        "WITH matching AS ("
        "SELECT o.id, o.portfolio_id, o.ticker, o.side, o.qty, o.signal_date, "
        "o.status, o.reject_reason, COUNT(*) OVER () AS _matching_count "
        "FROM sim_orders o JOIN portfolios pf ON pf.id = o.portfolio_id "
        f"WHERE pf.active{status_clause}"
        ") SELECT matching.id, matching.portfolio_id, matching.ticker, matching.side, "
        "matching.qty, matching.signal_date, matching.status, matching.reject_reason, "
        "matching._matching_count"
        f"{ticket_columns} FROM matching{ticket_join} "
        "ORDER BY matching.id DESC LIMIT ?",
        [*parameters, ORDERS_LIMIT],
    )
    return rows(cursor)


def orders(con: duckdb.DuckDBPyConnection, status: str | None) -> dict:
    """Project the newest matching orders of active portfolios only."""
    if not table_exists(con, "sim_orders") or not table_exists(con, "portfolios"):
        return _orders_payload(status, [])
    return _orders_payload(status, _order_rows(con, status))
