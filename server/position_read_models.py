"""Read-only active paper-position projections."""

from __future__ import annotations

from datetime import date

import duckdb

from engine.lib.db import REAL_BAR_SQL
from engine.lib.util import table_exists

from . import market_read_models
from .read_model_utils import (
    require_public_finite_number,
    require_public_nonnegative_integer,
    require_public_portfolio_id,
    require_public_positive_integer,
    require_public_positive_number,
    require_public_ticker,
)

POSITIONS_LIMIT = 500
POSITIONS_PROJECTION_FIELDS = frozenset(
    {"portfolio", "limit", "matching_count", "truncated", "positions"}
)
POSITION_BASE_FIELDS = frozenset({"portfolio_id", "ticker", "qty", "avg_cost", "close"})
POSITION_VALUATION_FIELDS = frozenset({"market_value", "unrealized_pnl", "unrealized_pnl_pct"})
POSITION_RISK_FIELDS = frozenset({"stop"})
POSITION_RISK_VALUATION_FIELDS = frozenset({"dist_to_stop_pct", "unrealized_r"})


def _empty_payload(portfolio: str | None) -> dict:
    payload = {
        "portfolio": portfolio,
        "limit": POSITIONS_LIMIT,
        "matching_count": 0,
        "truncated": False,
        "positions": [],
    }
    _validate_positions_projection(payload, discretionary_id="discretionary")
    return payload


def _position_closes(
    con: duckdb.DuckDBPyConnection,
    as_of: date | None,
    tickers: list[str],
) -> dict[str, float]:
    if as_of is None or not tickers:
        return {}
    result = {}
    for raw_ticker, close in con.execute(
        "SELECT ticker, close FROM ("
        "  SELECT px.ticker, px.close, "
        "  ROW_NUMBER() OVER (PARTITION BY px.ticker ORDER BY px.date DESC) AS recency "
        "  FROM prices px WHERE px.date <= ? "
        f"  AND {REAL_BAR_SQL} "
        "  AND px.ticker = ANY(?)"
        ") WHERE recency = 1",
        [as_of, tickers],
    ).fetchall():
        ticker = require_public_ticker(raw_ticker)
        if close is not None:
            result[ticker] = float(require_public_positive_number(close, "position close"))
    return result


def _discretionary_stops(con: duckdb.DuckDBPyConnection, tickers: list[str]) -> dict[str, float]:
    if not tickers or not table_exists(con, "disc_tickets"):
        return {}
    result = {}
    for raw_ticker, stop in con.execute(
        "SELECT ticker, stop FROM ("
        "  SELECT ticker, stop, ROW_NUMBER() OVER ("
        "    PARTITION BY ticker ORDER BY created_at DESC, id DESC"
        "  ) AS recency FROM disc_tickets "
        "  WHERE ticker = ANY(?) AND stop IS NOT NULL "
        "  AND status IN ('submitted', 'filled')"
        ") WHERE recency = 1",
        [tickers],
    ).fetchall():
        ticker = require_public_ticker(raw_ticker)
        if stop is not None:
            result[ticker] = float(require_public_positive_number(stop, "position stop"))
    return result


def _active_portfolio_exists(con: duckdb.DuckDBPyConnection, portfolio: str) -> bool:
    return (
        con.execute("SELECT 1 FROM portfolios WHERE id = ? AND active", [portfolio]).fetchone()
        is not None
    )


def _position_rows(con: duckdb.DuckDBPyConnection, portfolio: str | None) -> list[tuple]:
    portfolio_clause = "AND p.portfolio_id = ?" if portfolio else ""
    parameters = [portfolio] if portfolio else []
    return con.execute(
        "SELECT p.portfolio_id, p.ticker, p.qty, p.avg_cost, "
        "COUNT(*) OVER () AS _matching_count "
        "FROM sim_positions p JOIN portfolios pf ON pf.id = p.portfolio_id "
        f"WHERE pf.active AND (p.qty != 0 OR p.qty IS NULL) {portfolio_clause} "
        "ORDER BY p.portfolio_id, p.ticker LIMIT ?",
        [*parameters, POSITIONS_LIMIT],
    ).fetchall()


def _position_item(row: tuple, close: float | None) -> dict:
    portfolio_id, ticker, quantity, average_cost, _matching_count = row
    require_public_portfolio_id(portfolio_id)
    require_public_ticker(ticker)
    quantity = require_public_positive_number(quantity, "position quantity")
    average_cost = require_public_positive_number(average_cost, "position average cost")
    if close is not None:
        close = require_public_positive_number(close, "position close")
    item = {
        "portfolio_id": portfolio_id,
        "ticker": ticker,
        "qty": quantity,
        "avg_cost": average_cost,
        "close": close,
    }
    if close is not None:
        item["market_value"] = require_public_finite_number(
            quantity * close, "position market value"
        )
        item["unrealized_pnl"] = require_public_finite_number(
            quantity * (close - average_cost), "position unrealized P&L"
        )
        item["unrealized_pnl_pct"] = require_public_finite_number(
            (close - average_cost) / average_cost, "position unrealized P&L percentage"
        )
    return item


def _add_discretionary_risk(item: dict, stop: float | None) -> None:
    if stop is not None:
        stop = require_public_positive_number(stop, "position stop")
    item["stop"] = stop
    close = item["close"]
    if stop is None or close is None:
        return
    item["dist_to_stop_pct"] = require_public_finite_number(
        (close - stop) / close, "position distance to stop"
    )
    risk_per_share = item["avg_cost"] - stop
    item["unrealized_r"] = (
        require_public_finite_number(
            (close - item["avg_cost"]) / risk_per_share,
            "position unrealized R",
        )
        if risk_per_share
        else None
    )


def _expected_position_fields(item: dict, discretionary_id: str) -> frozenset[str]:
    fields = POSITION_BASE_FIELDS
    if item.get("close") is not None:
        fields |= POSITION_VALUATION_FIELDS
    if item.get("portfolio_id") == discretionary_id:
        fields |= POSITION_RISK_FIELDS
        if item.get("stop") is not None and item.get("close") is not None:
            fields |= POSITION_RISK_VALUATION_FIELDS
    return fields


def _validate_position_valuation(item: dict) -> tuple[float | int, float | int | None]:
    quantity = require_public_positive_number(item["qty"], "position quantity")
    average_cost = require_public_positive_number(item["avg_cost"], "position average cost")
    close = item["close"]
    if close is not None:
        close = require_public_positive_number(close, "position close")
        expected_values = {
            "market_value": quantity * close,
            "unrealized_pnl": quantity * (close - average_cost),
            "unrealized_pnl_pct": (close - average_cost) / average_cost,
        }
        for field, expected in expected_values.items():
            actual = require_public_finite_number(item[field], f"position {field}")
            if actual != expected:
                raise ValueError("public position valuation is inconsistent")
    return average_cost, close


def _validate_position_risk(item: dict, average_cost: float | int, close: float | int) -> None:
    stop = require_public_positive_number(item["stop"], "position stop")
    distance = require_public_finite_number(item["dist_to_stop_pct"], "position distance to stop")
    if distance != (close - stop) / close:
        raise ValueError("public position stop distance is inconsistent")
    risk_per_share = average_cost - stop
    unrealized_r = item["unrealized_r"]
    if risk_per_share == 0:
        if unrealized_r is not None:
            raise ValueError("public position unrealized R is inconsistent")
    elif (
        require_public_finite_number(unrealized_r, "position unrealized R")
        != (close - average_cost) / risk_per_share
    ):
        raise ValueError("public position unrealized R is inconsistent")


def _validate_position_item(item: dict, portfolio: str | None, discretionary_id: str) -> None:
    if not isinstance(item, dict) or set(item) != _expected_position_fields(item, discretionary_id):
        raise ValueError("public position shape is invalid")
    portfolio_id = require_public_portfolio_id(item["portfolio_id"])
    require_public_ticker(item["ticker"])
    if portfolio is not None and portfolio_id != portfolio:
        raise ValueError("public position portfolio is invalid")
    average_cost, close = _validate_position_valuation(item)
    if portfolio_id == discretionary_id:
        stop = item["stop"]
        if stop is not None:
            stop = require_public_positive_number(stop, "position stop")
        if stop is not None and close is not None:
            _validate_position_risk(item, average_cost, close)


def _validate_positions_projection(payload: dict, *, discretionary_id: str) -> None:
    if not isinstance(payload, dict) or set(payload) != POSITIONS_PROJECTION_FIELDS:
        raise ValueError("public positions projection shape is invalid")
    portfolio = payload["portfolio"]
    if portfolio is not None:
        portfolio = require_public_portfolio_id(portfolio)
    limit = require_public_positive_integer(payload["limit"])
    matching_count = require_public_nonnegative_integer(payload["matching_count"])
    positions = payload["positions"]
    if (
        limit != POSITIONS_LIMIT
        or not isinstance(positions, list)
        or len(positions) != min(matching_count, limit)
        or type(payload["truncated"]) is not bool
        or payload["truncated"] != (matching_count > len(positions))
    ):
        raise ValueError("public positions collection is inconsistent")
    keys: set[tuple[str, str]] = set()
    for item in positions:
        _validate_position_item(item, portfolio, discretionary_id)
        key = (item["portfolio_id"], item["ticker"])
        if key in keys:
            raise ValueError("public position is duplicated")
        keys.add(key)
    if positions != sorted(positions, key=lambda item: (item["portfolio_id"], item["ticker"])):
        raise ValueError("public positions are not ordered")


def positions(
    con: duckdb.DuckDBPyConnection,
    portfolio: str | None,
    *,
    discretionary_id: str,
) -> dict | None:
    """Project open positions for active portfolios only."""
    if portfolio is not None:
        require_public_portfolio_id(portfolio)
    if not table_exists(con, "portfolios"):
        return None if portfolio else _empty_payload(None)
    if portfolio and not _active_portfolio_exists(con, portfolio):
        return None
    if not table_exists(con, "sim_positions"):
        return _empty_payload(portfolio)
    rows = _position_rows(con, portfolio)
    matching_count = require_public_nonnegative_integer(rows[0][4]) if rows else 0
    as_of = market_read_models.latest_prices_date(con)
    tickers = sorted({row[1] for row in rows})
    closes = _position_closes(con, as_of, tickers)
    discretionary_tickers = sorted({row[1] for row in rows if row[0] == discretionary_id})
    stops = _discretionary_stops(con, discretionary_tickers)
    result = []
    for row in rows:
        portfolio_id, ticker, _quantity, _average_cost, _matching_count = row
        item = _position_item(row, closes.get(ticker))
        if portfolio_id == discretionary_id:
            _add_discretionary_risk(item, stops.get(ticker))
        result.append(item)
    payload = {
        "portfolio": portfolio,
        "limit": POSITIONS_LIMIT,
        "matching_count": matching_count,
        "truncated": matching_count > POSITIONS_LIMIT,
        "positions": result,
    }
    _validate_positions_projection(payload, discretionary_id=discretionary_id)
    return payload
