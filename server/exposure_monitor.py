"""Read-only projection of active exposure lacking current real bars."""

from __future__ import annotations

from datetime import date

import duckdb

from engine.lib.db import REAL_BAR_SQL
from engine.lib.util import table_exists

from .read_model_utils import (
    require_public_date,
    require_public_portfolio_id,
    require_public_positive_integer,
    require_public_positive_number,
    require_public_ticker,
    rows,
)

STALE_DETAIL_LIMIT = 100
ORDER_SIDES = frozenset({"buy", "sell"})


def _empty_status(as_of: date | None) -> dict:
    return {
        "as_of": None if as_of is None else as_of.isoformat(),
        "ticker_count": 0,
        "position_count": 0,
        "pending_order_count": 0,
        "positions": [],
        "positions_limit": STALE_DETAIL_LIMIT,
        "positions_truncated": False,
        "pending_orders": [],
        "pending_orders_limit": STALE_DETAIL_LIMIT,
        "pending_orders_truncated": False,
    }


def _active_exposure(con: duckdb.DuckDBPyConnection, as_of: date) -> list[dict]:
    exposure = rows(
        con.execute(
            "  SELECT 'position' AS record_type, NULL::INTEGER AS id, p.portfolio_id, "
            "  p.ticker, NULL::VARCHAR AS side, p.qty, NULL::DATE AS signal_date "
            "  FROM sim_positions p JOIN portfolios pf ON pf.id = p.portfolio_id "
            "  WHERE pf.active AND (p.qty IS NULL OR p.qty != 0) "
            "  UNION ALL "
            "  SELECT 'pending_order', o.id, o.portfolio_id, o.ticker, o.side, o.qty, "
            "  o.signal_date FROM sim_orders o "
            "  JOIN portfolios pf ON pf.id = o.portfolio_id "
            "  WHERE pf.active AND o.status = 'pending'"
        )
    )
    for item in exposure:
        record_type = item["record_type"]
        if record_type == "pending_order":
            require_public_positive_integer(item["id"])
            if item["side"] not in ORDER_SIDES:
                raise ValueError("pending-order side is invalid")
            signal_date = require_public_date(item["signal_date"], "pending-order signal date")
            if signal_date > as_of:
                raise ValueError("pending-order signal date is after the operational date")
        elif record_type != "position" or any(
            item[field] is not None for field in ("id", "side", "signal_date")
        ):
            raise ValueError("stale-exposure record type is invalid")
        require_public_portfolio_id(item["portfolio_id"])
        require_public_ticker(item["ticker"])
        require_public_positive_number(item["qty"], "stale-exposure quantity")
    return exposure


def _stale_exposure(
    con: duckdb.DuckDBPyConnection,
    as_of: date,
    exposure: list[dict],
) -> list[dict]:
    exposure_tickers = sorted({item["ticker"] for item in exposure})
    if not exposure_tickers:
        return []
    current_tickers = {
        ticker
        for (ticker,) in con.execute(
            f"SELECT DISTINCT ticker FROM prices WHERE date = ? "
            f"AND ticker = ANY(?) AND {REAL_BAR_SQL}",
            [as_of, exposure_tickers],
        ).fetchall()
    }
    stale_tickers = sorted(set(exposure_tickers) - current_tickers)
    if not stale_tickers:
        return []
    last_traded = {
        ticker: traded
        for ticker, traded in con.execute(
            f"SELECT ticker, MAX(date) FROM prices WHERE date < ? "
            f"AND ticker = ANY(?) AND {REAL_BAR_SQL} GROUP BY ticker",
            [as_of, stale_tickers],
        ).fetchall()
    }
    return [
        {**item, "last_traded": last_traded.get(item["ticker"])}
        for item in exposure
        if item["ticker"] in stale_tickers
    ]


def _sort_key(item: dict) -> tuple:
    traded = item["last_traded"]
    return (
        traded is not None,
        traded or date.min,
        item["portfolio_id"],
        item["id"] or 0,
        item["ticker"],
    )


def _bounded_details(stale_rows: list[dict], record_type: str) -> list[dict]:
    selected = sorted(
        (item for item in stale_rows if item["record_type"] == record_type),
        key=_sort_key,
    )[:STALE_DETAIL_LIMIT]
    omitted = {"record_type"}
    if record_type == "position":
        omitted.update({"id", "side", "signal_date"})
    return [
        {key: value for key, value in item.items() if key not in omitted}
        for item in selected
    ]


def _status_payload(as_of: date, stale_rows: list[dict]) -> dict:
    position_rows = [item for item in stale_rows if item["record_type"] == "position"]
    pending_rows = [item for item in stale_rows if item["record_type"] == "pending_order"]
    position_count = len(position_rows)
    pending_order_count = len(pending_rows)
    positions = _bounded_details(stale_rows, "position")
    pending = _bounded_details(stale_rows, "pending_order")
    return {
        "as_of": as_of.isoformat(),
        "ticker_count": len({item["ticker"] for item in stale_rows}),
        "position_count": position_count,
        "pending_order_count": pending_order_count,
        "positions": positions,
        "positions_limit": STALE_DETAIL_LIMIT,
        "positions_truncated": position_count > len(positions),
        "pending_orders": pending,
        "pending_orders_limit": STALE_DETAIL_LIMIT,
        "pending_orders_truncated": pending_order_count > len(pending),
    }


def status(con: duckdb.DuckDBPyConnection, as_of: date | None) -> dict:
    """Return held or pending-order names without a real bar on the latest session."""
    empty = _empty_status(as_of)
    if as_of is None or not all(
        table_exists(con, table)
        for table in ("prices", "portfolios", "sim_positions", "sim_orders")
    ):
        return empty
    stale_rows = _stale_exposure(con, as_of, _active_exposure(con, as_of))
    return _status_payload(as_of, stale_rows) if stale_rows else empty
