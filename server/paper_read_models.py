"""Read-only discretionary ticket-context projection."""

from __future__ import annotations

from datetime import date

import duckdb

from engine.lib.util import table_exists
from sim.schema import INITIAL_CASH

from . import market_read_models, risk, risk_book
from .read_model_utils import (
    require_public_date,
    require_public_positive_number,
)

TICKET_CONTEXT_FIELDS = frozenset(
    {
        "portfolio_id",
        "status",
        "as_of",
        "equity",
        "equity_source",
        "risk_pct",
        "experiment_max_pct",
        "max_open_r",
    }
)
TICKET_CONTEXT_STATUSES = frozenset({"active", "not-created", "inactive", "unavailable"})
EQUITY_SOURCES = {
    "active": "current_discretionary_equity",
    "not-created": "configured_initial_cash",
}


def _portfolio_row(con: duckdb.DuckDBPyConnection) -> tuple[bool] | None:
    if not table_exists(con, "portfolios"):
        return None
    return con.execute("SELECT active FROM portfolios WHERE id = ?", [risk_book.DISC_ID]).fetchone()


def _equity_context(
    con: duckdb.DuckDBPyConnection,
    row: tuple[bool] | None,
    market_date: date | None,
) -> tuple[str, float | None, str | None]:
    if market_date is None:
        return "unavailable", None, None
    if row is not None:
        if type(row[0]) is not bool:
            raise ValueError("public ticket-context portfolio state is invalid")
        if not row[0]:
            return "inactive", None, None
    if row is None:
        equity = require_public_positive_number(INITIAL_CASH, "ticket-context equity")
        return "not-created", float(equity), "configured_initial_cash"
    equity = risk_book.disc_state(con, as_of=market_date)["equity"]
    try:
        equity = require_public_positive_number(equity, "ticket-context equity")
    except ValueError:
        return "inactive", None, None
    return "active", float(equity), "current_discretionary_equity"


def _risk_limits() -> tuple[float, float, float]:
    risk_pct = require_public_positive_number(risk_book.RISK_PCT, "ticket-context risk percent")
    experiment_max = require_public_positive_number(
        risk.EXPERIMENT_MAX, "ticket-context experiment limit"
    )
    max_open_r = require_public_positive_number(risk.MAX_OPEN_R, "ticket-context open risk")
    if risk_pct > 1 or experiment_max > risk_pct:
        raise ValueError("public ticket-context risk limits are invalid")
    return float(risk_pct), float(experiment_max), float(max_open_r)


def _validate_ticket_context_projection(payload: dict) -> None:
    if not isinstance(payload, dict) or set(payload) != TICKET_CONTEXT_FIELDS:
        raise ValueError("public ticket-context projection shape is invalid")
    if payload["portfolio_id"] != risk_book.DISC_ID:
        raise ValueError("public ticket-context portfolio is invalid")
    status = payload["status"]
    if status not in TICKET_CONTEXT_STATUSES:
        raise ValueError("public ticket-context status is invalid")
    risk_pct = require_public_positive_number(payload["risk_pct"], "ticket-context risk percent")
    experiment_max = require_public_positive_number(
        payload["experiment_max_pct"], "ticket-context experiment limit"
    )
    require_public_positive_number(payload["max_open_r"], "ticket-context open risk")
    if risk_pct > 1 or experiment_max > risk_pct:
        raise ValueError("public ticket-context risk limits are invalid")
    expected_source = EQUITY_SOURCES.get(status)
    if expected_source is not None:
        require_public_date(payload["as_of"], "ticket-context as-of date")
        require_public_positive_number(payload["equity"], "ticket-context equity")
        if payload["equity_source"] != expected_source:
            raise ValueError("public ticket-context equity source is invalid")
        return
    if status == "inactive":
        require_public_date(payload["as_of"], "ticket-context as-of date")
    elif payload["as_of"] is not None:
        raise ValueError("public ticket-context unavailable state is invalid")
    if payload["equity"] is not None or payload["equity_source"] is not None:
        raise ValueError("public ticket-context unavailable state is invalid")


def ticket_context(con: duckdb.DuckDBPyConnection) -> dict:
    """Return the authoritative, read-only discretionary sizing context."""
    market_date = market_read_models.latest_prices_date(con)
    if market_date is not None:
        require_public_date(market_date, "ticket-context as-of date")
    status, equity, equity_source = _equity_context(con, _portfolio_row(con), market_date)
    risk_pct, experiment_max_pct, max_open_r = _risk_limits()
    payload = {
        "portfolio_id": risk_book.DISC_ID,
        "status": status,
        "as_of": market_date,
        "equity": equity,
        "equity_source": equity_source,
        "risk_pct": risk_pct,
        "experiment_max_pct": experiment_max_pct,
        "max_open_r": max_open_r,
    }
    _validate_ticket_context_projection(payload)
    return payload
