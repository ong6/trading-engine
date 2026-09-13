"""Read-only paper-league standings and equity projections."""

from __future__ import annotations

from collections import deque
from datetime import date

import duckdb

from engine.lib.util import table_exists
from sim.league import _spy_return, regime_label
from sim.schema import INITIAL_CASH

from . import league_equity_read_models
from .market_read_models import latest_prices_date
from .read_model_utils import (
    require_public_date,
    require_public_finite_number,
    require_public_nonempty_string,
    require_public_nonnegative_integer,
    require_public_portfolio_id,
    require_public_positive_integer,
    require_public_positive_number,
)

LEAGUE_RANKING_BASIS = "total_return_since_each_portfolio_inception"
LEAGUE_COMPARISON_BASIS = "SPY_over_each_portfolio_inception_window"
LEAGUE_ROWS_LIMIT = 100
EQUITY_SERIES_LIMIT = league_equity_read_models.EQUITY_SERIES_LIMIT
EQUITY_SCAN_BATCH_SIZE = 256
LEAGUE_NOTICE = (
    "Operational paper scoreboard only: inception windows differ, SPY is context rather "
    "than every strategy's registered control, and rank is not evidence of profitability "
    "or a promotion signal."
)
LEAGUE_PROJECTION_FIELDS = frozenset(
    {
        "as_of",
        "regime",
        "reference_notional",
        "ranking_basis",
        "comparison_basis",
        "evidence_role",
        "notice",
        "limit",
        "matching_count",
        "truncated",
        "rows",
    }
)
LEAGUE_ROW_FIELDS = frozenset(
    {
        "id",
        "name",
        "inception",
        "initial_cash",
        "execution_profile",
        "equity_as_of",
        "current",
        "equity",
        "total_ret",
        "vs_spy",
        "mdd",
        "n_open",
        "n_fills",
        "last5",
        "rank",
    }
)


def _active_portfolios(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    portfolio_columns = {
        row[1] for row in con.execute("PRAGMA table_info('portfolios')").fetchall()
    }
    initial_expr = "initial_cash" if "initial_cash" in portfolio_columns else "NULL"
    profile_expr = "execution_profile" if "execution_profile" in portfolio_columns else "NULL"
    portfolios = con.execute(
        f"SELECT id, name, created, {initial_expr}, {profile_expr} "
        "FROM portfolios WHERE active ORDER BY id"
    ).fetchall()
    for portfolio in portfolios:
        require_public_portfolio_id(portfolio[0])
    return portfolios


def _equity_summaries_by_portfolio(
    con: duckdb.DuckDBPyConnection,
    as_of: date | None,
) -> dict[str, dict]:
    """Stream complete active-book equity into constant-size ranking summaries."""
    result: dict[str, dict] = {}
    if as_of is None or not table_exists(con, "sim_equity"):
        return result
    cursor = con.execute(
        "SELECT e.portfolio_id, e.date, e.equity FROM sim_equity e "
        "JOIN portfolios p ON p.id = e.portfolio_id "
        "WHERE p.active AND e.date <= ? ORDER BY e.portfolio_id, e.date",
        [as_of],
    )
    previous_dates: dict[str, date] = {}
    while batch := cursor.fetchmany(EQUITY_SCAN_BATCH_SIZE):
        for raw_portfolio_id, raw_equity_date, raw_equity in batch:
            portfolio_id = require_public_portfolio_id(raw_portfolio_id)
            equity_date = require_public_date(raw_equity_date, "league equity date")
            if equity_date > as_of:
                raise ValueError("public league equity date is invalid")
            previous_date = previous_dates.get(portfolio_id)
            if previous_date is not None and equity_date <= previous_date:
                raise ValueError("public league equity dates are not strictly ordered")
            previous_dates[portfolio_id] = equity_date
            equity = require_public_finite_number(raw_equity, "league equity")
            summary = result.setdefault(
                portfolio_id,
                {"peak": -1e18, "mdd": 0.0, "tail": deque(maxlen=6)},
            )
            summary["equity_as_of"] = equity_date
            summary["equity"] = equity
            summary["tail"].append(equity)
            summary["peak"] = max(summary["peak"], equity)
            if summary["peak"] > 0:
                summary["mdd"] = min(summary["mdd"], equity / summary["peak"] - 1)
    return result


def _counts_by_portfolio(
    con: duckdb.DuckDBPyConnection,
    table: str,
    predicate: str = "",
) -> dict[str, int]:
    if not table_exists(con, table):
        return {}
    where = f"WHERE {predicate}" if predicate else ""
    return {
        portfolio_id: require_public_nonnegative_integer(count)
        for portfolio_id, count in con.execute(
            f"SELECT portfolio_id, COUNT(*) FROM {table} {where} GROUP BY portfolio_id"
        ).fetchall()
    }


def _comparison_returns(
    con: duckdb.DuckDBPyConnection,
    created: date,
    equity_as_of: date,
    equity: float,
    initial_cash: float | None,
    spy_returns: dict[tuple[date, date], float | None],
) -> tuple[float | None, float | None]:
    total_return = equity / initial_cash - 1 if initial_cash is not None else None
    if total_return is not None:
        require_public_finite_number(total_return, "league total return")
    comparison_window = (created, equity_as_of)
    if comparison_window not in spy_returns:
        spy_returns[comparison_window] = _spy_return(con, created, equity_as_of)
    spy_return = spy_returns[comparison_window]
    if spy_return is not None:
        require_public_finite_number(spy_return, "league comparison return")
    versus_spy = None if spy_return is None or total_return is None else total_return - spy_return
    if versus_spy is not None:
        require_public_finite_number(versus_spy, "league relative return")
    return total_return, versus_spy


def _league_row(
    con: duckdb.DuckDBPyConnection,
    portfolio: tuple,
    equity_summary: dict,
    open_positions: dict[str, int],
    fills: dict[str, int],
    as_of: date | None,
    spy_returns: dict[tuple[date, date], float | None],
) -> dict:
    portfolio_id, name, created, initial_cash, profile_id = portfolio
    require_public_portfolio_id(portfolio_id)
    require_public_nonempty_string(name, "portfolio name")
    require_public_date(created, "portfolio inception")
    if profile_id is not None:
        require_public_nonempty_string(profile_id, "execution profile")
    equity_as_of = require_public_date(equity_summary["equity_as_of"], "league equity date")
    if as_of is None or equity_as_of > as_of:
        raise ValueError("public league equity date is invalid")
    equity = require_public_finite_number(equity_summary["equity"], "league equity")
    tail = equity_summary["tail"]
    current = equity_as_of == as_of
    initial_cash = (
        None
        if initial_cash is None
        else float(require_public_positive_number(initial_cash, "portfolio initial cash"))
    )
    total_return, versus_spy = _comparison_returns(
        con, created, equity_as_of, equity, initial_cash, spy_returns
    )
    drawdown = require_public_finite_number(equity_summary["mdd"], "league drawdown")
    last_five = None
    if len(tail) >= 6 and tail[0] != 0:
        last_five = tail[-1] / tail[0] - 1
        require_public_finite_number(last_five, "league recent return")
    return {
        "id": portfolio_id,
        "name": name,
        "inception": created,
        "initial_cash": initial_cash,
        "execution_profile": profile_id,
        "equity_as_of": equity_as_of,
        "current": current,
        "equity": equity,
        "total_ret": total_return,
        "vs_spy": versus_spy,
        "mdd": drawdown,
        "n_open": require_public_nonnegative_integer(open_positions.get(portfolio_id, 0)),
        "n_fills": require_public_nonnegative_integer(fills.get(portfolio_id, 0)),
        "last5": last_five,
    }


def _league_rows(
    con: duckdb.DuckDBPyConnection,
    as_of: date | None,
) -> list[dict]:
    result_rows = []
    if not table_exists(con, "portfolios"):
        return result_rows
    equity_by_portfolio = _equity_summaries_by_portfolio(con, as_of)
    open_positions = _counts_by_portfolio(con, "sim_positions", "qty > 0")
    fills = _counts_by_portfolio(con, "sim_fills")
    spy_returns: dict[tuple[date, date], float | None] = {}
    for portfolio in _active_portfolios(con):
        equity_summary = equity_by_portfolio.get(portfolio[0])
        if equity_summary:
            result_rows.append(
                _league_row(
                    con,
                    portfolio,
                    equity_summary,
                    open_positions,
                    fills,
                    as_of,
                    spy_returns,
                )
            )
    return result_rows


def _rank_league_rows(result_rows: list[dict]) -> None:
    result_rows.sort(key=_league_ranking_key)
    rank = 0
    for row in result_rows:
        if row["current"]:
            rank += 1
            row["rank"] = rank
        else:
            row["rank"] = None


def _visible_league_rows(
    con: duckdb.DuckDBPyConnection,
    as_of: date | None,
) -> tuple[list[dict], int]:
    """Rank the complete eligible cohort, then bound only its serialized rows."""
    result_rows = _league_rows(con, as_of)
    _rank_league_rows(result_rows)
    matching_count = require_public_nonnegative_integer(len(result_rows))
    return result_rows[:LEAGUE_ROWS_LIMIT], matching_count


def _validate_league_semantics(payload: dict) -> date | None:
    as_of = payload["as_of"]
    if as_of is not None:
        as_of = require_public_date(as_of, "league as-of date")
    if payload["regime"] not in {"risk-on", "risk-off", "unknown"}:
        raise ValueError("public league regime is invalid")
    require_public_positive_number(payload["reference_notional"], "reference notional")
    if (
        payload["ranking_basis"] != LEAGUE_RANKING_BASIS
        or payload["comparison_basis"] != LEAGUE_COMPARISON_BASIS
        or payload["evidence_role"] != "operational_only"
        or payload["notice"] != LEAGUE_NOTICE
    ):
        raise ValueError("public league semantics are invalid")
    return as_of


def _validate_league_collection(payload: dict) -> list[dict]:
    limit = require_public_positive_integer(payload["limit"])
    matching_count = require_public_nonnegative_integer(payload["matching_count"])
    rows = payload["rows"]
    if (
        limit != LEAGUE_ROWS_LIMIT
        or not isinstance(rows, list)
        or len(rows) != min(matching_count, limit)
        or type(payload["truncated"]) is not bool
        or payload["truncated"] != (matching_count > len(rows))
    ):
        raise ValueError("public league collection is inconsistent")
    return rows


def _validate_league_row_metadata(row: dict, seen_ids: set[str]) -> None:
    if not isinstance(row, dict) or set(row) != LEAGUE_ROW_FIELDS:
        raise ValueError("public league row shape is invalid")
    portfolio_id = require_public_portfolio_id(row["id"])
    if portfolio_id in seen_ids:
        raise ValueError("public league portfolio is duplicated")
    seen_ids.add(portfolio_id)
    require_public_nonempty_string(row["name"], "portfolio name")
    require_public_date(row["inception"], "portfolio inception")
    if row["initial_cash"] is not None:
        require_public_positive_number(row["initial_cash"], "portfolio initial cash")
    if row["execution_profile"] is not None:
        require_public_nonempty_string(row["execution_profile"], "execution profile")


def _validate_league_row_state(
    row: dict,
    *,
    as_of: date | None,
    expected_rank: int,
) -> int:
    equity_as_of = require_public_date(row["equity_as_of"], "league equity date")
    if as_of is None or equity_as_of > as_of or type(row["current"]) is not bool:
        raise ValueError("public league equity state is invalid")
    if row["current"] != (equity_as_of == as_of):
        raise ValueError("public league current state is inconsistent")
    require_public_finite_number(row["equity"], "league equity")
    for field in ("total_ret", "vs_spy", "mdd", "last5"):
        if row[field] is not None:
            require_public_finite_number(row[field], f"league {field}")
    require_public_nonnegative_integer(row["n_open"])
    require_public_nonnegative_integer(row["n_fills"])
    if row["current"]:
        if require_public_positive_integer(row["rank"]) != expected_rank:
            raise ValueError("public league rank is inconsistent")
        return expected_rank + 1
    if row["rank"] is not None:
        raise ValueError("public league stale rank is invalid")
    return expected_rank


def _league_ranking_key(row: dict) -> tuple:
    return (
        not row["current"],
        row["total_ret"] is None,
        -(row["total_ret"] if row["total_ret"] is not None else 0.0),
        row["id"],
    )


def _validate_league_projection(payload: dict) -> None:
    if not isinstance(payload, dict) or set(payload) != LEAGUE_PROJECTION_FIELDS:
        raise ValueError("public league projection shape is invalid")
    as_of = _validate_league_semantics(payload)
    rows = _validate_league_collection(payload)
    seen_ids: set[str] = set()
    expected_rank = 1
    for row in rows:
        _validate_league_row_metadata(row, seen_ids)
        expected_rank = _validate_league_row_state(
            row,
            as_of=as_of,
            expected_rank=expected_rank,
        )
    if rows != sorted(rows, key=_league_ranking_key):
        raise ValueError("public league rows are not ordered")


def league(con: duckdb.DuckDBPyConnection) -> dict:
    as_of = latest_prices_date(con)
    if as_of is not None:
        require_public_date(as_of, "league as-of date")
    result_rows, matching_count = _visible_league_rows(con, as_of)
    regime = "unknown" if as_of is None else regime_label(con, as_of)
    if regime not in {"risk-on", "risk-off", "unknown"}:
        raise ValueError("public league regime is invalid")
    reference_notional = require_public_positive_number(INITIAL_CASH, "reference notional")
    payload = {
        "as_of": as_of,
        "regime": regime,
        "reference_notional": reference_notional,
        "ranking_basis": LEAGUE_RANKING_BASIS,
        "comparison_basis": LEAGUE_COMPARISON_BASIS,
        "evidence_role": "operational_only",
        "notice": LEAGUE_NOTICE,
        "limit": LEAGUE_ROWS_LIMIT,
        "matching_count": matching_count,
        "truncated": matching_count > LEAGUE_ROWS_LIMIT,
        "rows": result_rows,
    }
    _validate_league_projection(payload)
    return payload


def equity(con: duckdb.DuckDBPyConnection, portfolio_id: str) -> dict | None:
    """Return one active portfolio's bounded equity series, or ``None`` if inactive."""
    return league_equity_read_models.project_equity(con, portfolio_id, latest_prices_date)


def equities(con: duckdb.DuckDBPyConnection) -> dict:
    """Return bounded equity windows for the same ranked books exposed by ``league``."""
    as_of = latest_prices_date(con)
    if as_of is not None:
        require_public_date(as_of, "league as-of date")
    visible_rows, matching_count = _visible_league_rows(con, as_of)
    return league_equity_read_models.project_equities(
        con,
        [row["id"] for row in visible_rows],
        as_of,
        portfolio_matching_count=matching_count,
        portfolio_limit=LEAGUE_ROWS_LIMIT,
    )
