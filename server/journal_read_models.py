"""Read-only discretionary journal and recent league-event projections."""

from __future__ import annotations

from datetime import date, datetime

import duckdb

from engine.lib.util import table_exists

from . import risk_history
from .json_utils import loads_strict
from .read_model_utils import (
    bound_text_fields,
    require_public_finite_number,
    require_public_nonnegative_integer,
    require_public_portfolio_id,
    require_public_positive_integer,
    require_public_positive_number,
    require_public_ticker,
    rows,
)
from .ticket_contract import EMOTION_MAX_CHARS, NOTES_MAX_CHARS, PLAYBOOK_MAX_CHARS

DISCRETIONARY_TICKETS_LIMIT = 100
ROUND_TRIPS_LIMIT = 100
LEAGUE_EVENTS_LIMIT = 100
TICKET_FILLS_LIMIT = 100
GATES_ERROR_MALFORMED_JSON = "malformed-json"
GATES_ERROR_NOT_ARRAY = "not-an-array"
GATES_ERROR_INVALID_ENTRIES = "invalid-entries"
MAX_STORED_GATES_CHARS = 65_536
MAX_PUBLIC_GATES = 32
MAX_GATE_NAME_CHARS = 128
MAX_GATE_DETAIL_CHARS = 4_096
JOURNAL_SIDES = frozenset({"buy", "sell"})
TICKET_STATUSES = frozenset({"submitted", "rejected", "cancelled", "filled"})
GATES_ERRORS = frozenset(
    {GATES_ERROR_MALFORMED_JSON, GATES_ERROR_NOT_ARRAY, GATES_ERROR_INVALID_ENTRIES}
)
JOURNAL_PROJECTION_FIELDS = frozenset(
    {
        "discretionary",
        "league_events",
        "league_events_limit",
        "league_events_matching_count",
        "league_events_truncated",
    }
)
DISCRETIONARY_FIELDS = frozenset(
    {
        "tickets",
        "tickets_limit",
        "tickets_matching_count",
        "tickets_truncated",
        "round_trips",
        "round_trips_limit",
        "round_trips_matching_count",
        "round_trips_truncated",
    }
)
TICKET_FIELDS = frozenset(
    {
        "id",
        "ticker",
        "side",
        "qty",
        "entry_ref",
        "stop",
        "target",
        "playbook",
        "emotion",
        "notes",
        "detail_truncated",
        "status",
        "order_id",
        "created_at",
        "gates",
        "fills",
        "fills_limit",
        "fills_matching_count",
        "fills_truncated",
    }
)
GATE_FIELDS = frozenset({"name", "status", "detail"})
FILL_FIELDS = frozenset({"ticker", "side", "qty", "fill_date", "fill_px"})
ROUND_TRIP_FIELDS = frozenset({"ticker", "qty", "entry_px", "exit_px", "exit_date", "realized_r"})
LEAGUE_EVENT_FIELDS = frozenset(
    {"order_id", "portfolio_id", "ticker", "side", "qty", "fill_date", "fill_px"}
)


def _bound_ticket_text(ticket: dict) -> None:
    ticket["detail_truncated"] = bound_text_fields(
        ticket,
        {
            "playbook": PLAYBOOK_MAX_CHARS,
            "emotion": EMOTION_MAX_CHARS,
            "notes": NOTES_MAX_CHARS,
        },
    )


def _public_gate(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    name = value.get("name")
    status = value.get("status")
    detail = value.get("detail")
    if (
        not isinstance(name, str)
        or not name.strip()
        or len(name) > MAX_GATE_NAME_CHARS
        or status not in {"pass", "fail", "unknown"}
        or not isinstance(detail, str)
        or len(detail) > MAX_GATE_DETAIL_CHARS
    ):
        return None
    return {"name": name, "status": status, "detail": detail}


def _parse_ticket_gates(ticket: dict) -> None:
    raw_gates = ticket.get("gates")
    if not raw_gates:
        ticket["gates"] = []
        return
    if not isinstance(raw_gates, str) or len(raw_gates) > MAX_STORED_GATES_CHARS:
        ticket["gates"] = []
        ticket["gates_error"] = GATES_ERROR_INVALID_ENTRIES
        return
    try:
        parsed_gates = loads_strict(raw_gates)
    except (TypeError, ValueError):
        ticket["gates"] = []
        ticket["gates_error"] = GATES_ERROR_MALFORMED_JSON
        return
    if not isinstance(parsed_gates, list):
        ticket["gates"] = []
        ticket["gates_error"] = GATES_ERROR_NOT_ARRAY
        return
    if len(parsed_gates) > MAX_PUBLIC_GATES:
        ticket["gates"] = []
        ticket["gates_error"] = GATES_ERROR_INVALID_ENTRIES
        return
    public_gates = [_public_gate(gate) for gate in parsed_gates]
    if any(gate is None for gate in public_gates):
        ticket["gates"] = []
        ticket["gates_error"] = GATES_ERROR_INVALID_ENTRIES
        return
    ticket["gates"] = public_gates


def _validate_side(value: object, kind: str) -> str:
    if value not in JOURNAL_SIDES:
        raise ValueError(f"public {kind} side is invalid")
    return value


def _validate_fill(fill: dict, *, ticker: str | None = None, side: str | None = None) -> None:
    actual_ticker = require_public_ticker(fill["ticker"])
    actual_side = _validate_side(fill["side"], "fill")
    if ticker is not None and actual_ticker != ticker:
        raise ValueError("public fill ticker is invalid")
    if side is not None and actual_side != side:
        raise ValueError("public fill side is invalid")
    require_public_positive_number(fill["qty"], "fill quantity")
    if type(fill["fill_date"]) is not date:
        raise ValueError("public fill date is invalid")
    require_public_positive_number(fill["fill_px"], "fill price")


def _validate_ticket(ticket: dict) -> None:
    require_public_positive_integer(ticket["id"])
    require_public_ticker(ticket["ticker"])
    _validate_side(ticket["side"], "ticket")
    require_public_positive_number(ticket["qty"], "ticket quantity")
    for field in ("entry_ref", "stop", "target"):
        if ticket[field] is not None:
            require_public_finite_number(ticket[field], f"ticket {field}")
    for field in ("playbook", "emotion", "notes"):
        if ticket[field] is not None and not isinstance(ticket[field], str):
            raise ValueError(f"public ticket {field} is invalid")
    status = ticket["status"]
    if status not in TICKET_STATUSES:
        raise ValueError("public ticket status is invalid")
    order_id = ticket["order_id"]
    if status == "rejected":
        if order_id is not None:
            raise ValueError("public ticket order link is invalid")
    elif order_id is None:
        raise ValueError("public ticket order link is invalid")
    else:
        require_public_positive_integer(order_id)
    if type(ticket["created_at"]) is not datetime or ticket["created_at"].tzinfo is not None:
        raise ValueError("public ticket timestamp is invalid")


def _validate_round_trip(round_trip: dict) -> None:
    require_public_ticker(round_trip["ticker"])
    require_public_positive_number(round_trip["qty"], "round-trip quantity")
    require_public_positive_number(round_trip["entry_px"], "round-trip entry price")
    require_public_positive_number(round_trip["exit_px"], "round-trip exit price")
    if type(round_trip["exit_date"]) is not date:
        raise ValueError("public round-trip exit date is invalid")
    require_public_finite_number(round_trip["realized_r"], "round-trip realized R")


def _validate_collection(
    payload: dict,
    items_field: str,
    limit_field: str,
    count_field: str,
    truncated_field: str,
    expected_limit: int,
) -> list[dict]:
    limit = require_public_positive_integer(payload[limit_field])
    matching_count = require_public_nonnegative_integer(payload[count_field])
    items = payload[items_field]
    if (
        limit != expected_limit
        or not isinstance(items, list)
        or len(items) != min(matching_count, limit)
        or type(payload[truncated_field]) is not bool
        or payload[truncated_field] != (matching_count > len(items))
    ):
        raise ValueError(f"public journal {items_field} collection is inconsistent")
    return items


def _validate_gate(gate: dict) -> None:
    if not isinstance(gate, dict) or set(gate) != GATE_FIELDS or _public_gate(gate) != gate:
        raise ValueError("public journal gate shape is invalid")


def _validate_ticket_text(ticket: dict) -> None:
    limits = {
        "playbook": PLAYBOOK_MAX_CHARS,
        "emotion": EMOTION_MAX_CHARS,
        "notes": NOTES_MAX_CHARS,
    }
    for field, limit in limits.items():
        value = ticket[field]
        if value is not None and (not isinstance(value, str) or len(value) > limit):
            raise ValueError(f"public ticket {field} is invalid")
    clipped = any(
        isinstance(ticket[field], str) and len(ticket[field]) == limit
        for field, limit in limits.items()
    )
    if type(ticket["detail_truncated"]) is not bool or (ticket["detail_truncated"] and not clipped):
        raise ValueError("public ticket truncation marker is invalid")


def _validate_public_ticket(ticket: dict) -> int:
    if not isinstance(ticket, dict):
        raise ValueError("public journal ticket shape is invalid")
    expected_fields = TICKET_FIELDS | ({"gates_error"} if "gates_error" in ticket else set())
    if set(ticket) != expected_fields:
        raise ValueError("public journal ticket shape is invalid")
    _validate_ticket(ticket)
    _validate_ticket_text(ticket)
    gates = ticket["gates"]
    if not isinstance(gates, list) or len(gates) > MAX_PUBLIC_GATES:
        raise ValueError("public journal gates collection is invalid")
    for gate in gates:
        _validate_gate(gate)
    if "gates_error" in ticket and (ticket["gates_error"] not in GATES_ERRORS or gates):
        raise ValueError("public journal gates error is invalid")
    fills = _validate_collection(
        ticket,
        "fills",
        "fills_limit",
        "fills_matching_count",
        "fills_truncated",
        TICKET_FILLS_LIMIT,
    )
    for fill in fills:
        if not isinstance(fill, dict) or set(fill) != FILL_FIELDS:
            raise ValueError("public journal fill shape is invalid")
        _validate_fill(fill, ticker=ticket["ticker"], side=ticket["side"])
    if fills != sorted(
        fills,
        key=lambda fill: (
            fill["fill_date"],
            fill["ticker"],
            fill["side"],
            fill["qty"],
            fill["fill_px"],
        ),
    ):
        raise ValueError("public journal fills are not ordered")
    return ticket["id"]


def _validate_discretionary(discretionary: dict) -> None:
    if not isinstance(discretionary, dict) or set(discretionary) != DISCRETIONARY_FIELDS:
        raise ValueError("public discretionary journal shape is invalid")
    tickets = _validate_collection(
        discretionary,
        "tickets",
        "tickets_limit",
        "tickets_matching_count",
        "tickets_truncated",
        DISCRETIONARY_TICKETS_LIMIT,
    )
    ticket_ids = [_validate_public_ticket(ticket) for ticket in tickets]
    if len(ticket_ids) != len(set(ticket_ids)):
        raise ValueError("public journal ticket identifier is duplicated")
    if tickets != sorted(
        tickets, key=lambda ticket: (ticket["created_at"], ticket["id"]), reverse=True
    ):
        raise ValueError("public journal tickets are not ordered")
    round_trips = _validate_collection(
        discretionary,
        "round_trips",
        "round_trips_limit",
        "round_trips_matching_count",
        "round_trips_truncated",
        ROUND_TRIPS_LIMIT,
    )
    for round_trip in round_trips:
        if not isinstance(round_trip, dict) or set(round_trip) != ROUND_TRIP_FIELDS:
            raise ValueError("public journal round-trip shape is invalid")
        _validate_round_trip(round_trip)
    if round_trips != sorted(
        round_trips, key=lambda round_trip: round_trip["exit_date"], reverse=True
    ):
        raise ValueError("public journal round trips are not ordered")


def _validate_journal_projection(payload: dict) -> None:
    if not isinstance(payload, dict) or set(payload) != JOURNAL_PROJECTION_FIELDS:
        raise ValueError("public journal projection shape is invalid")
    _validate_discretionary(payload["discretionary"])
    events = _validate_collection(
        payload,
        "league_events",
        "league_events_limit",
        "league_events_matching_count",
        "league_events_truncated",
        LEAGUE_EVENTS_LIMIT,
    )
    for event in events:
        if not isinstance(event, dict) or set(event) != LEAGUE_EVENT_FIELDS:
            raise ValueError("public journal league-event shape is invalid")
        require_public_positive_integer(event["order_id"])
        require_public_portfolio_id(event["portfolio_id"])
        _validate_fill(event)
    if events != sorted(
        events,
        key=lambda event: (event["fill_date"], event["order_id"]),
        reverse=True,
    ):
        raise ValueError("public journal league events are not ordered")


def _fills_by_order(
    con: duckdb.DuckDBPyConnection,
    order_ids: set[int],
) -> dict[int, dict]:
    if not order_ids or not table_exists(con, "sim_fills"):
        return {}
    placeholders = ", ".join("?" for _ in order_ids)
    result: dict[int, dict] = {}
    for fill in rows(
        con.execute(
            "WITH ranked AS ("
            "SELECT f.order_id, f.ticker, f.side, f.qty, f.fill_date, f.fill_px, "
            "COUNT(*) OVER (PARTITION BY f.order_id) AS _matching_count, "
            "ROW_NUMBER() OVER (PARTITION BY f.order_id ORDER BY "
            "f.fill_date DESC, f.ticker, f.side, f.qty, f.fill_px) AS _recency "
            f"FROM sim_fills f WHERE f.order_id IN ({placeholders})"
            ") SELECT * FROM ranked WHERE _recency <= ? "
            "ORDER BY order_id, fill_date, ticker, side, qty, fill_px",
            [*sorted(order_ids), TICKET_FILLS_LIMIT],
        )
    ):
        order_id = fill.pop("order_id")
        require_public_positive_integer(order_id)
        matching_count = require_public_nonnegative_integer(fill.pop("_matching_count"))
        fill.pop("_recency")
        _validate_fill(fill)
        group = result.setdefault(order_id, {"fills": [], "matching_count": matching_count})
        group["fills"].append(fill)
    return result


def _tickets(con: duckdb.DuckDBPyConnection) -> tuple[list[dict], int]:
    if not table_exists(con, "disc_tickets"):
        return [], 0
    ticket_rows = rows(
        con.execute(
            "WITH matching AS ("
            "SELECT t.id, t.ticker, t.side, t.qty, t.entry_ref, t.stop, t.target, "
            "t.playbook, t.emotion, t.notes, t.gates, t.status, t.order_id, t.created_at, "
            "COUNT(*) OVER () AS _matching_count FROM disc_tickets t"
            ") SELECT * FROM matching ORDER BY created_at DESC, id DESC LIMIT ?",
            [DISCRETIONARY_TICKETS_LIMIT],
        )
    )
    matching_count = (
        require_public_nonnegative_integer(ticket_rows[0].pop("_matching_count"))
        if ticket_rows
        else 0
    )
    for ticket in ticket_rows[1:]:
        ticket.pop("_matching_count")
    for ticket in ticket_rows:
        _validate_ticket(ticket)
    return ticket_rows, matching_count


def _league_events(con: duckdb.DuckDBPyConnection) -> tuple[list[dict], int]:
    if not table_exists(con, "sim_fills") or not table_exists(con, "portfolios"):
        return [], 0
    event_rows = rows(
        con.execute(
            "WITH matching AS ("
            "SELECT f.order_id, f.portfolio_id, f.ticker, f.side, f.qty, "
            "f.fill_date, f.fill_px, COUNT(*) OVER () AS _matching_count "
            "FROM sim_fills f JOIN portfolios pf ON pf.id = f.portfolio_id WHERE pf.active"
            ") SELECT * FROM matching ORDER BY fill_date DESC, order_id DESC LIMIT ?",
            [LEAGUE_EVENTS_LIMIT],
        )
    )
    for event in event_rows:
        require_public_positive_integer(event["order_id"])
        require_public_portfolio_id(event["portfolio_id"])
        _validate_fill(event)
    matching_count = (
        require_public_nonnegative_integer(event_rows[0].pop("_matching_count"))
        if event_rows
        else 0
    )
    for event in event_rows[1:]:
        event.pop("_matching_count")
    return event_rows, matching_count


def journal(con: duckdb.DuckDBPyConnection) -> dict:
    """Project bounded discretionary history and the active-book fill feed."""
    tickets, tickets_matching_count = _tickets(con)
    order_ids = {
        ticket["order_id"] for ticket in tickets if isinstance(ticket.get("order_id"), int)
    }
    fills_by_order = _fills_by_order(con, order_ids)
    for ticket in tickets:
        _bound_ticket_text(ticket)
        _parse_ticket_gates(ticket)
        fill_group = fills_by_order.get(ticket.get("order_id"), {"fills": [], "matching_count": 0})
        for fill in fill_group["fills"]:
            _validate_fill(fill, ticker=ticket["ticker"], side=ticket["side"])
        ticket["fills"] = fill_group["fills"]
        ticket["fills_limit"] = TICKET_FILLS_LIMIT
        ticket["fills_matching_count"] = fill_group["matching_count"]
        ticket["fills_truncated"] = fill_group["matching_count"] > TICKET_FILLS_LIMIT
    round_trips, round_trips_matching_count = risk_history.recent_round_trips(
        con, ROUND_TRIPS_LIMIT
    )
    round_trips_matching_count = require_public_nonnegative_integer(round_trips_matching_count)
    for round_trip in round_trips:
        _validate_round_trip(round_trip)
    league_events, league_events_matching_count = _league_events(con)
    payload = {
        "discretionary": {
            "tickets": tickets,
            "tickets_limit": DISCRETIONARY_TICKETS_LIMIT,
            "tickets_matching_count": tickets_matching_count,
            "tickets_truncated": tickets_matching_count > DISCRETIONARY_TICKETS_LIMIT,
            "round_trips": round_trips,
            "round_trips_limit": ROUND_TRIPS_LIMIT,
            "round_trips_matching_count": round_trips_matching_count,
            "round_trips_truncated": round_trips_matching_count > ROUND_TRIPS_LIMIT,
        },
        "league_events": league_events,
        "league_events_limit": LEAGUE_EVENTS_LIMIT,
        "league_events_matching_count": league_events_matching_count,
        "league_events_truncated": league_events_matching_count > LEAGUE_EVENTS_LIMIT,
    }
    _validate_journal_projection(payload)
    return payload
