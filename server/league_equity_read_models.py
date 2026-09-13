"""Bounded single-book and bulk paper-equity history projections."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import duckdb

from engine.lib.util import table_exists

from .read_model_utils import (
    require_public_date,
    require_public_finite_number,
    require_public_nonnegative_integer,
    require_public_portfolio_id,
    require_public_positive_integer,
    rows,
)

EQUITY_SERIES_LIMIT = 500
EQUITY_ROW_FIELDS = frozenset({"portfolio_id", "date", "equity", "cash", "n_positions"})
EQUITY_PROJECTION_FIELDS = frozenset(
    {"portfolio_id", "as_of", "limit", "matching_count", "truncated", "equity"}
)
BULK_EQUITY_PROJECTION_FIELDS = frozenset(
    {
        "as_of",
        "portfolio_limit",
        "portfolio_matching_count",
        "portfolios_truncated",
        "limit_per_portfolio",
        "equity_by_portfolio",
        "matching_count_by_portfolio",
        "truncated_by_portfolio",
    }
)


def _validate_equity_row(
    row: dict,
    as_of: date | None,
    *,
    expected_portfolio_id: str | None = None,
) -> tuple[str, date]:
    if not isinstance(row, dict) or set(row) != EQUITY_ROW_FIELDS:
        raise ValueError("public equity row shape is invalid")
    portfolio_id = require_public_portfolio_id(row["portfolio_id"])
    if expected_portfolio_id is not None and portfolio_id != expected_portfolio_id:
        raise ValueError("public equity portfolio is invalid")
    equity_date = require_public_date(row["date"], "equity date")
    if as_of is None or equity_date > as_of:
        raise ValueError("public equity date is invalid")
    require_public_finite_number(row["equity"], "equity value")
    require_public_finite_number(row["cash"], "equity cash")
    require_public_nonnegative_integer(row["n_positions"])
    return portfolio_id, equity_date


def _validate_equity_series(
    equity_rows: list[dict],
    as_of: date | None,
    *,
    expected_portfolio_id: str,
) -> None:
    if not isinstance(equity_rows, list):
        raise ValueError("public equity series is invalid")
    previous_date = None
    for row in equity_rows:
        _, equity_date = _validate_equity_row(
            row,
            as_of,
            expected_portfolio_id=expected_portfolio_id,
        )
        if previous_date is not None and equity_date <= previous_date:
            raise ValueError("public equity dates are not strictly ordered")
        previous_date = equity_date


def _validate_equity_projection(payload: dict, expected_portfolio_id: str) -> None:
    if not isinstance(payload, dict) or set(payload) != EQUITY_PROJECTION_FIELDS:
        raise ValueError("public equity projection shape is invalid")
    portfolio_id = require_public_portfolio_id(payload["portfolio_id"])
    if portfolio_id != expected_portfolio_id:
        raise ValueError("public equity portfolio is invalid")
    as_of = payload["as_of"]
    if as_of is not None:
        as_of = require_public_date(as_of, "equity as-of date")
    limit = require_public_positive_integer(payload["limit"])
    matching_count = require_public_nonnegative_integer(payload["matching_count"])
    equity_rows = payload["equity"]
    _validate_equity_series(
        equity_rows,
        as_of,
        expected_portfolio_id=portfolio_id,
    )
    if (
        limit != EQUITY_SERIES_LIMIT
        or len(equity_rows) != min(matching_count, limit)
        or type(payload["truncated"]) is not bool
        or payload["truncated"] != (matching_count > len(equity_rows))
    ):
        raise ValueError("public equity collection is inconsistent")


def _equity_payload(
    portfolio_id: str,
    as_of: date | None,
    equity_rows: list[dict],
    matching_count: int,
) -> dict:
    if as_of is not None:
        as_of = require_public_date(as_of, "equity as-of date")
    matching_count = require_public_nonnegative_integer(matching_count)
    _validate_equity_series(
        equity_rows,
        as_of,
        expected_portfolio_id=portfolio_id,
    )
    payload = {
        "portfolio_id": portfolio_id,
        "as_of": as_of,
        "limit": EQUITY_SERIES_LIMIT,
        "matching_count": matching_count,
        "truncated": matching_count > EQUITY_SERIES_LIMIT,
        "equity": equity_rows,
    }
    _validate_equity_projection(payload, portfolio_id)
    return payload


def _recent_equity_rows(
    con: duckdb.DuckDBPyConnection,
    portfolio_id: str,
    as_of: date,
) -> tuple[list[dict], int]:
    equity_rows = rows(
        con.execute(
            "WITH matching AS ("
            "  SELECT portfolio_id, date, equity, cash, n_positions, "
            "  COUNT(*) OVER () AS _matching_count FROM sim_equity "
            "  WHERE portfolio_id = ? AND date <= ?"
            "), recent AS ("
            "  SELECT * FROM matching ORDER BY date DESC LIMIT ?"
            ") SELECT * FROM recent ORDER BY date",
            [portfolio_id, as_of, EQUITY_SERIES_LIMIT],
        )
    )
    matching_count = (
        require_public_nonnegative_integer(equity_rows[0].pop("_matching_count"))
        if equity_rows
        else 0
    )
    for row in equity_rows[1:]:
        row.pop("_matching_count")
    return equity_rows, matching_count


def project_equity(
    con: duckdb.DuckDBPyConnection,
    portfolio_id: str,
    resolve_as_of: Callable[[duckdb.DuckDBPyConnection], date | None],
) -> dict | None:
    """Return one active portfolio's bounded equity series, or ``None`` if inactive."""
    require_public_portfolio_id(portfolio_id)
    if (
        not table_exists(con, "portfolios")
        or con.execute(
            "SELECT 1 FROM portfolios WHERE id = ? AND active", [portfolio_id]
        ).fetchone()
        is None
    ):
        return None
    as_of = resolve_as_of(con)
    if as_of is not None:
        as_of = require_public_date(as_of, "equity as-of date")
    if as_of is None or not table_exists(con, "sim_equity"):
        return _equity_payload(portfolio_id, as_of, [], 0)
    equity_rows, matching_count = _recent_equity_rows(con, portfolio_id, as_of)
    return _equity_payload(portfolio_id, as_of, equity_rows, matching_count)


def _empty_equities_payload(
    as_of: date | None,
    *,
    portfolio_matching_count: int,
    portfolio_limit: int,
) -> dict:
    portfolio_matching_count = require_public_nonnegative_integer(portfolio_matching_count)
    payload = {
        "as_of": as_of,
        "portfolio_limit": portfolio_limit,
        "portfolio_matching_count": portfolio_matching_count,
        "portfolios_truncated": portfolio_matching_count > portfolio_limit,
        "limit_per_portfolio": EQUITY_SERIES_LIMIT,
        "equity_by_portfolio": {},
        "matching_count_by_portfolio": {},
        "truncated_by_portfolio": {},
    }
    _validate_equities_projection(
        payload,
        expected_portfolio_ids=[],
        expected_portfolio_limit=portfolio_limit,
    )
    return payload


def _validate_equities_projection(
    payload: dict,
    *,
    expected_portfolio_ids: list[str],
    expected_portfolio_limit: int,
) -> None:
    if not isinstance(payload, dict) or set(payload) != BULK_EQUITY_PROJECTION_FIELDS:
        raise ValueError("public bulk equity projection shape is invalid")
    as_of = payload["as_of"]
    if as_of is not None:
        as_of = require_public_date(as_of, "equity as-of date")
    portfolio_limit = require_public_positive_integer(payload["portfolio_limit"])
    matching_count = require_public_nonnegative_integer(payload["portfolio_matching_count"])
    series_limit = require_public_positive_integer(payload["limit_per_portfolio"])
    if (
        portfolio_limit != expected_portfolio_limit
        or series_limit != EQUITY_SERIES_LIMIT
        or type(payload["portfolios_truncated"]) is not bool
        or payload["portfolios_truncated"] != (matching_count > portfolio_limit)
    ):
        raise ValueError("public bulk equity collection is inconsistent")
    if len(expected_portfolio_ids) != len(set(expected_portfolio_ids)) or len(
        expected_portfolio_ids
    ) != min(matching_count, portfolio_limit):
        raise ValueError("public bulk equity portfolios are inconsistent")
    for portfolio_id in expected_portfolio_ids:
        require_public_portfolio_id(portfolio_id)

    equity_by_portfolio = payload["equity_by_portfolio"]
    counts = payload["matching_count_by_portfolio"]
    truncated = payload["truncated_by_portfolio"]
    expected_keys = set(expected_portfolio_ids)
    if (
        not isinstance(equity_by_portfolio, dict)
        or not isinstance(counts, dict)
        or not isinstance(truncated, dict)
        or set(equity_by_portfolio) != expected_keys
        or set(counts) != expected_keys
        or set(truncated) != expected_keys
    ):
        raise ValueError("public bulk equity portfolio keys are inconsistent")
    for portfolio_id in expected_portfolio_ids:
        matching = require_public_nonnegative_integer(counts[portfolio_id])
        series = equity_by_portfolio[portfolio_id]
        _validate_equity_series(
            series,
            as_of,
            expected_portfolio_id=portfolio_id,
        )
        if (
            len(series) != min(matching, series_limit)
            or type(truncated[portfolio_id]) is not bool
            or truncated[portfolio_id] != (matching > len(series))
            or not series
        ):
            raise ValueError("public bulk equity series is inconsistent")


def _recent_equity_rows_by_portfolio(
    con: duckdb.DuckDBPyConnection,
    portfolio_ids: list[str],
    as_of: date | None,
) -> tuple[dict[str, list[dict]], dict[str, int]]:
    equity_by_portfolio = {portfolio_id: [] for portfolio_id in portfolio_ids}
    matching_count_by_portfolio = dict.fromkeys(portfolio_ids, 0)
    if not portfolio_ids or as_of is None or not table_exists(con, "sim_equity"):
        return equity_by_portfolio, matching_count_by_portfolio
    equity_rows = rows(
        con.execute(
            "WITH ranked AS ("
            "  SELECT e.portfolio_id, e.date, e.equity, e.cash, e.n_positions, "
            "  COUNT(*) OVER (PARTITION BY e.portfolio_id) AS _matching_count, "
            "  ROW_NUMBER() OVER (PARTITION BY e.portfolio_id ORDER BY e.date DESC) AS _recency "
            "  FROM sim_equity e JOIN portfolios p ON p.id = e.portfolio_id "
            "  WHERE p.active AND e.date <= ? AND e.portfolio_id = ANY(?)"
            ") SELECT * FROM ranked WHERE _recency <= ? "
            "ORDER BY portfolio_id, date",
            [as_of, portfolio_ids, EQUITY_SERIES_LIMIT],
        )
    )
    previous_dates: dict[str, date] = {}
    for row in equity_rows:
        matching_count = require_public_nonnegative_integer(row.pop("_matching_count"))
        row.pop("_recency")
        portfolio_id, equity_date = _validate_equity_row(row, as_of)
        if portfolio_id not in equity_by_portfolio:
            raise ValueError("public equity portfolio is invalid")
        previous_date = previous_dates.get(portfolio_id)
        if previous_date is not None and equity_date <= previous_date:
            raise ValueError("public equity dates are not strictly ordered")
        previous_dates[portfolio_id] = equity_date
        matching_count_by_portfolio[portfolio_id] = matching_count
        equity_by_portfolio[portfolio_id].append(row)
    return equity_by_portfolio, matching_count_by_portfolio


def project_equities(
    con: duckdb.DuckDBPyConnection,
    portfolio_ids: list[str],
    as_of: date | None,
    *,
    portfolio_matching_count: int,
    portfolio_limit: int,
) -> dict:
    """Return bounded equity windows for an already-ranked portfolio selection."""
    if as_of is not None:
        as_of = require_public_date(as_of, "equity as-of date")
    portfolio_matching_count = require_public_nonnegative_integer(portfolio_matching_count)
    for portfolio_id in portfolio_ids:
        require_public_portfolio_id(portfolio_id)
    if not table_exists(con, "portfolios"):
        return _empty_equities_payload(
            as_of,
            portfolio_matching_count=portfolio_matching_count,
            portfolio_limit=portfolio_limit,
        )
    equity_by_portfolio, matching_count_by_portfolio = _recent_equity_rows_by_portfolio(
        con, portfolio_ids, as_of
    )
    payload = {
        "as_of": as_of,
        "portfolio_limit": portfolio_limit,
        "portfolio_matching_count": portfolio_matching_count,
        "portfolios_truncated": portfolio_matching_count > portfolio_limit,
        "limit_per_portfolio": EQUITY_SERIES_LIMIT,
        "equity_by_portfolio": equity_by_portfolio,
        "matching_count_by_portfolio": matching_count_by_portfolio,
        "truncated_by_portfolio": {
            portfolio_id: matching_count > EQUITY_SERIES_LIMIT
            for portfolio_id, matching_count in matching_count_by_portfolio.items()
        },
    }
    _validate_equities_projection(
        payload,
        expected_portfolio_ids=portfolio_ids,
        expected_portfolio_limit=portfolio_limit,
    )
    return payload
