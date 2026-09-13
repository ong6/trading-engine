"""Read-only market-date, screen, and candidate projections."""

from __future__ import annotations

import math
from datetime import date

import duckdb

from engine.lib.db import (
    MARKET_DATE_MIN_COVERAGE,
    MARKET_DATE_MIN_NAMES,
    REAL_BAR_SQL,
    latest_operational_market_date,
)
from engine.lib.util import table_exists

from .read_model_utils import (
    require_public_finite_number,
    require_public_nonnegative_integer,
    require_public_nonnegative_number,
    require_public_positive_integer,
    require_public_positive_number,
    require_public_ticker,
    rows,
)

SCREEN_RESULTS_LIMIT = 100
CANDIDATE_BARS_LIMIT = 250
RECENT_MARKET_DATE_PROBE_LIMIT = 32
SCREEN_RESULT_COLUMNS = (
    "run_date, ticker, close, rs_rank, template_score, passes_template, "
    "dist_50d, dist_200d, off_52w_low, off_52w_high, base_tight, vol_dryup, new_today"
)
SCREEN_BOOLEAN_FIELDS = ("passes_template", "base_tight", "vol_dryup", "new_today")
SCREEN_FINITE_FIELDS = ("dist_50d", "dist_200d", "off_52w_low", "off_52w_high")
SCREEN_UNIVERSE_POLICIES = frozenset({"all", "ex-leveraged"})
SCREEN_RESULT_KEYS = frozenset(
    {
        "run_date",
        "ticker",
        "close",
        "rs_rank",
        "template_score",
        "passes_template",
        "dist_50d",
        "dist_200d",
        "off_52w_low",
        "off_52w_high",
        "base_tight",
        "vol_dryup",
        "new_today",
        "universe_policy",
    }
)
SCREEN_PROJECTION_KEYS = frozenset(
    {
        "run_date",
        "n_total",
        "n_passing",
        "n_new_today",
        "results_page",
        "results_offset",
        "results_limit",
        "results_matching_count",
        "results_total_pages",
        "results_new_today",
        "results_truncated",
        "results_has_previous",
        "results_has_next",
        "results",
    }
)
CANDIDATE_PROJECTION_KEYS = frozenset(
    {"ticker", "as_of", "n_bars", "bars", "latest_close_date", "latest_close", "screen"}
)
CANDIDATE_BAR_KEYS = frozenset({"date", "open", "high", "low", "close", "volume"})


def _screen_result_columns(con: duckdb.DuckDBPyConnection) -> str:
    columns = {
        row[0]
        for row in con.execute("SELECT name FROM pragma_table_info('screen_results')").fetchall()
    }
    has_policy = "universe_policy" in columns
    policy = (
        "COALESCE(universe_policy, 'all') AS universe_policy"
        if has_policy
        else "'all' AS universe_policy"
    )
    return f"{SCREEN_RESULT_COLUMNS}, {policy}"


def _required_market_breadth(con: duckdb.DuckDBPyConnection) -> int | None:
    if not table_exists(con, "universe"):
        return None
    active_liquid = int(
        con.execute(
            "SELECT COUNT(*) FROM universe WHERE active = TRUE AND liquid = TRUE"
        ).fetchone()[0]
    )
    if active_liquid == 0:
        return None
    return min(
        active_liquid,
        max(MARKET_DATE_MIN_NAMES, math.ceil(active_liquid * MARKET_DATE_MIN_COVERAGE)),
    )


def _real_bar_breadth(con: duckdb.DuckDBPyConnection, candidate: date) -> int:
    return int(
        con.execute(
            f"SELECT COUNT(DISTINCT p.ticker) FROM prices p "
            "JOIN universe u ON u.ticker = p.ticker "
            f"WHERE p.date = ? AND u.active = TRUE AND u.liquid = TRUE AND {REAL_BAR_SQL}",
            [candidate],
        ).fetchone()[0]
    )


def latest_prices_date(con: duckdb.DuckDBPyConnection) -> date | None:
    """Latest breadth-qualified market date, excluding partial/phantom tails.

    Operational reads normally need only the newest stored date. Probe a
    bounded recent tail one date at a time so the common path does not group
    the complete price archive. If an unusually long partial tail is present,
    defer to the canonical exhaustive implementation for an exact answer.
    """
    required = _required_market_breadth(con)
    if required is None:
        return None
    candidate = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    for _ in range(RECENT_MARKET_DATE_PROBE_LIMIT):
        if candidate is None:
            return None
        if _real_bar_breadth(con, candidate) >= required:
            return candidate
        candidate = con.execute(
            "SELECT MAX(date) FROM prices WHERE date < ?", [candidate]
        ).fetchone()[0]
    return latest_operational_market_date(con)


def _screen_date(
    con: duckdb.DuckDBPyConnection,
    run_date: date | None,
    through: date | None,
) -> date | None:
    if run_date is not None:
        return run_date
    if through is None:
        return con.execute("SELECT MAX(run_date) FROM screen_results").fetchone()[0]
    return con.execute(
        "SELECT MAX(run_date) FROM screen_results WHERE run_date <= ?", [through]
    ).fetchone()[0]


def _screen_header(con: duckdb.DuckDBPyConnection, run_date: date) -> tuple:
    return con.execute(
        "SELECT COUNT(*) AS n_total, "
        "SUM(CASE WHEN passes_template THEN 1 ELSE 0 END) AS n_passing, "
        "SUM(CASE WHEN passes_template AND new_today THEN 1 ELSE 0 END) AS n_new_today "
        "FROM screen_results WHERE run_date = ?",
        [run_date],
    ).fetchone()


def _validate_screen_result(
    result: dict,
    *,
    expected_run_date: date | None = None,
    expected_ticker: str | None = None,
    through: date | None = None,
    passing_only: bool = False,
) -> None:
    if set(result) != SCREEN_RESULT_KEYS:
        raise ValueError("public screen result shape is invalid")
    run_date = result["run_date"]
    if (
        type(run_date) is not date
        or (expected_run_date is not None and run_date != expected_run_date)
        or (through is not None and run_date > through)
    ):
        raise ValueError("public screen date is invalid")
    ticker = require_public_ticker(result["ticker"])
    if expected_ticker is not None and ticker != expected_ticker:
        raise ValueError("public screen ticker is invalid")
    require_public_positive_number(result["close"], "screen close")
    rank = require_public_positive_integer(result["rs_rank"])
    if rank > 99:
        raise ValueError("public screen rank is invalid")
    score = require_public_nonnegative_integer(result["template_score"])
    if score > 8:
        raise ValueError("public screen score is invalid")
    if any(type(result[field]) is not bool for field in SCREEN_BOOLEAN_FIELDS):
        raise ValueError("public screen boolean is invalid")
    if passing_only and result["passes_template"] is not True:
        raise ValueError("public screen passing state is invalid")
    for field in SCREEN_FINITE_FIELDS:
        require_public_finite_number(result[field], f"screen {field}")
    if result["universe_policy"] not in SCREEN_UNIVERSE_POLICIES:
        raise ValueError("public screen universe policy is invalid")


def _screen_page(
    con: duckdb.DuckDBPyConnection,
    run_date: date,
    offset: int,
    limit: int,
) -> list[dict]:
    results = rows(
        con.execute(
            f"SELECT {_screen_result_columns(con)} FROM screen_results "
            "WHERE run_date = ? AND passes_template "
            "ORDER BY rs_rank DESC, ticker LIMIT ? OFFSET ?",
            [run_date, limit, offset],
        )
    )
    for result in results:
        _validate_screen_result(result, expected_run_date=run_date, passing_only=True)
    return results


def _validate_screen_rows(results: object, run_date: date) -> int:
    if not isinstance(results, list):
        raise ValueError("public screen results are invalid")
    tickers: set[str] = set()
    previous: tuple[int, str] | None = None
    for result in results:
        _validate_screen_result(result, expected_run_date=run_date, passing_only=True)
        key = (-result["rs_rank"], result["ticker"])
        if result["ticker"] in tickers or (previous is not None and key <= previous):
            raise ValueError("public screen rows are not unique and ordered")
        tickers.add(result["ticker"])
        previous = key
    return sum(result["new_today"] is True for result in results)


def _validate_screen_pagination(payload: dict, matching_count: int) -> None:
    page = require_public_positive_integer(payload["results_page"])
    offset = require_public_nonnegative_integer(payload["results_offset"])
    limit = require_public_positive_integer(payload["results_limit"])
    total_pages = require_public_positive_integer(payload["results_total_pages"])
    results = payload["results"]
    if not isinstance(results, list):
        raise ValueError("public screen results are invalid")
    expected_offset = require_public_nonnegative_integer((page - 1) * limit)
    expected_size = min(limit, max(matching_count - expected_offset, 0))
    expected_pages = max(1, math.ceil(matching_count / limit))
    if offset != expected_offset or len(results) != expected_size or total_pages != expected_pages:
        raise ValueError("public screen pagination is inconsistent")
    expected_flags = (
        matching_count > len(results),
        page > 1,
        offset + len(results) < matching_count,
    )
    actual_flags = (
        payload["results_truncated"],
        payload["results_has_previous"],
        payload["results_has_next"],
    )
    if any(type(value) is not bool for value in actual_flags) or actual_flags != expected_flags:
        raise ValueError("public screen pagination flags are inconsistent")


def _validate_screen_projection(payload: dict) -> None:
    if set(payload) != SCREEN_PROJECTION_KEYS:
        raise ValueError("public screen projection shape is invalid")
    run_date = payload["run_date"]
    if type(run_date) is not date:
        raise ValueError("public screen date is invalid")
    total_count = require_public_nonnegative_integer(payload["n_total"])
    matching_count = require_public_nonnegative_integer(payload["n_passing"])
    new_today_count = require_public_nonnegative_integer(payload["n_new_today"])
    page_matching_count = require_public_nonnegative_integer(payload["results_matching_count"])
    page_new_count = require_public_nonnegative_integer(payload["results_new_today"])
    if total_count < matching_count or matching_count != page_matching_count:
        raise ValueError("public screen counts are inconsistent")
    if new_today_count > matching_count:
        raise ValueError("public screen new-today count is inconsistent")
    _validate_screen_pagination(payload, matching_count)
    if page_new_count != _validate_screen_rows(payload["results"], run_date):
        raise ValueError("public screen page count is inconsistent")


def _screen_payload(
    run_date: date,
    page: int,
    header: tuple,
    results: list[dict],
    limit: int = SCREEN_RESULTS_LIMIT,
) -> dict:
    if type(run_date) is not date:
        raise ValueError("public screen date is invalid")
    page = require_public_positive_integer(page)
    limit = require_public_positive_integer(limit)
    offset = require_public_nonnegative_integer((page - 1) * limit)
    total_count = require_public_nonnegative_integer(header[0])
    matching_count = require_public_nonnegative_integer(0 if header[1] is None else header[1])
    new_today_count = require_public_nonnegative_integer(0 if header[2] is None else header[2])
    result = {
        "run_date": run_date,
        "n_total": total_count,
        "n_passing": matching_count,
        "n_new_today": new_today_count,
        "results_page": page,
        "results_offset": offset,
        "results_limit": limit,
        "results_matching_count": matching_count,
        "results_total_pages": max(1, math.ceil(matching_count / limit)),
        "results_new_today": sum(row["new_today"] is True for row in results),
        "results_truncated": matching_count > len(results),
        "results_has_previous": page > 1,
        "results_has_next": offset + len(results) < matching_count,
        "results": results,
    }
    _validate_screen_projection(result)
    return result


def screen(
    con: duckdb.DuckDBPyConnection,
    run_date: date | None = None,
    *,
    through: date | None = None,
    page: int = 1,
) -> dict | None:
    """Return one bounded page of a screen, optionally capped at ``through``."""
    try:
        page = require_public_positive_integer(page)
        limit = require_public_positive_integer(SCREEN_RESULTS_LIMIT)
        require_public_nonnegative_integer((page - 1) * limit)
    except ValueError:
        raise ValueError("page must be positive") from None
    if not table_exists(con, "screen_results"):
        return None
    run_date = _screen_date(con, run_date, through)
    if run_date is None:
        return None
    header = _screen_header(con, run_date)
    if header[0] == 0:
        return None
    offset = (page - 1) * limit
    return _screen_payload(
        run_date,
        page,
        header,
        _screen_page(con, run_date, offset, limit),
        limit,
    )


def _candidate_bars(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    market_date: date,
    limit: int,
) -> list[dict]:
    return rows(
        con.execute(
            "SELECT date, open, high, low, close, volume FROM ("
            "  SELECT date, open, high, low, close, volume FROM prices "
            "  WHERE ticker = ? AND date <= ? ORDER BY date DESC LIMIT ?"
            ") ORDER BY date",
            [ticker, market_date, limit],
        )
    )


def _validate_candidate_bars(bars: list[dict], market_date: date) -> None:
    previous_date = None
    for bar in bars:
        if set(bar) != CANDIDATE_BAR_KEYS:
            raise ValueError("public candidate bar shape is invalid")
        bar_date = bar["date"]
        if (
            type(bar_date) is not date
            or bar_date > market_date
            or (previous_date is not None and bar_date <= previous_date)
        ):
            raise ValueError("public candidate bar date is invalid")
        open_price = require_public_positive_number(bar["open"], "candidate open")
        high = require_public_positive_number(bar["high"], "candidate high")
        low = require_public_positive_number(bar["low"], "candidate low")
        close = require_public_positive_number(bar["close"], "candidate close")
        require_public_nonnegative_number(bar["volume"], "candidate volume")
        if high < max(open_price, close, low) or low > min(open_price, close, high):
            raise ValueError("public candidate OHLC geometry is invalid")
        previous_date = bar_date


def _candidate_screen(
    con: duckdb.DuckDBPyConnection, ticker: str, market_date: date
) -> dict | None:
    if not table_exists(con, "screen_results"):
        return None
    screen_rows = rows(
        con.execute(
            f"SELECT {_screen_result_columns(con)} FROM screen_results "
            "WHERE ticker = ? AND run_date <= ? "
            "ORDER BY run_date DESC LIMIT 1",
            [ticker, market_date],
        )
    )
    if not screen_rows:
        return None
    result = screen_rows[0]
    _validate_screen_result(result, expected_ticker=ticker, through=market_date)
    return result


def _validate_latest_quote(
    latest_quote: tuple | None,
    bars: list[dict],
    market_date: date,
) -> None:
    if latest_quote is None:
        return
    quote_date, quote_close = latest_quote
    if type(quote_date) is not date or quote_date > market_date:
        raise ValueError("public candidate quote date is invalid")
    close = require_public_positive_number(quote_close, "candidate latest close")
    matching_bar = next((bar for bar in bars if bar["date"] == quote_date), None)
    if matching_bar is None or matching_bar["close"] != close:
        raise ValueError("public candidate quote does not match bars")


def _validate_candidate_projection(payload: dict, expected_ticker: str) -> None:
    if set(payload) != CANDIDATE_PROJECTION_KEYS:
        raise ValueError("public candidate projection shape is invalid")
    ticker = require_public_ticker(payload["ticker"])
    if ticker != expected_ticker:
        raise ValueError("public candidate ticker is invalid")
    market_date = payload["as_of"]
    if type(market_date) is not date:
        raise ValueError("public candidate as-of date is invalid")
    bars = payload["bars"]
    if not isinstance(bars, list):
        raise ValueError("public candidate bars are invalid")
    n_bars = require_public_positive_integer(payload["n_bars"])
    if n_bars != len(bars) or n_bars > CANDIDATE_BARS_LIMIT:
        raise ValueError("public candidate bar count is inconsistent")
    _validate_candidate_bars(bars, market_date)

    latest_date = payload["latest_close_date"]
    latest_close = payload["latest_close"]
    if (latest_date is None) != (latest_close is None):
        raise ValueError("public candidate quote is incomplete")
    _validate_latest_quote(
        None if latest_date is None else (latest_date, latest_close), bars, market_date
    )
    screen_result = payload["screen"]
    if screen_result is not None:
        _validate_screen_result(
            screen_result,
            expected_ticker=ticker,
            through=market_date,
        )


def candidate(con: duckdb.DuckDBPyConnection, ticker: str) -> dict | None:
    ticker = require_public_ticker(ticker.upper())
    bars_limit = require_public_positive_integer(CANDIDATE_BARS_LIMIT)
    if bars_limit != 250:
        raise ValueError("public candidate bar limit is invalid")
    market_date = latest_prices_date(con)
    if market_date is None:
        return None
    bars = _candidate_bars(con, ticker, market_date, bars_limit)
    if not bars:
        return None
    _validate_candidate_bars(bars, market_date)
    latest_quote = con.execute(
        f"SELECT date, close FROM prices WHERE ticker = ? AND date <= ? AND {REAL_BAR_SQL} "
        "ORDER BY date DESC LIMIT 1",
        [ticker, market_date],
    ).fetchone()
    _validate_latest_quote(latest_quote, bars, market_date)
    result = {
        "ticker": ticker,
        "as_of": market_date,
        "n_bars": require_public_nonnegative_integer(len(bars)),
        "bars": bars,
        "latest_close_date": latest_quote[0] if latest_quote else None,
        "latest_close": latest_quote[1] if latest_quote else None,
        "screen": _candidate_screen(con, ticker, market_date),
    }
    _validate_candidate_projection(result, ticker)
    return result
