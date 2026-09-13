"""Accumulated intraday-data research admission gate."""

from datetime import date
from functools import lru_cache
from math import ceil

import duckdb
import pandas_market_calendars as mcal

from .read_model_utils import require_public_nonempty_string
from .readiness_common import (
    count,
    coverage_fraction,
    input_schema_status,
    iso,
    positive_count,
    require_exact_fields,
    span_days,
    validate_input_schema_status,
    validate_intraday_coverage,
)

MIN_SESSIONS = 252  # about one trading year at both stored resolutions
MIN_CALENDAR_DAYS = 365
MIN_TICKERS_PER_INTERVAL = 500
REQUIRED_INTERVALS = ("1m", "5m")
MIN_SESSION_COVERAGE_FRACTION = 0.75
SESSION_SCHEDULE_SOURCE = "pandas_market_calendars:NYSE"
REQUIRED_INPUTS = {
    "intraday_prices": {
        "ticker": {"VARCHAR"},
        "ts": {"TIMESTAMP", "TIMESTAMP WITH TIME ZONE"},
        "interval": {"VARCHAR"},
    }
}
PUBLIC_FIELDS = frozenset(
    {
        "input_status",
        "missing_tables",
        "missing_columns",
        "incompatible_columns",
        "status",
        "observed_sessions",
        "first_date",
        "last_date",
        "minimum_observed_names_per_session",
        "minimum_usable_names_per_session",
        "qualifying_sessions",
        "qualifying_first_date",
        "qualifying_last_date",
        "qualifying_calendar_span_days",
        "minimum_sessions_per_interval",
        "minimum_calendar_span_days",
        "minimum_tickers_per_interval",
        "minimum_session_coverage_fraction",
        "session_schedule_source",
        "required_intervals",
        "usable_observation_rule",
        "limitation",
    }
)


@lru_cache(maxsize=16)
def _session_bar_expectations(first: date, last: date) -> tuple[tuple[date, str, int], ...]:
    """Expected regular-session bars from the published NYSE schedule.

    The exchange calendar is deterministic for a date range but relatively
    expensive to construct. Cache only this derived schedule; live database
    coverage is still queried and reconciled on every request.
    """
    schedule = mcal.get_calendar("NYSE").schedule(start_date=first, end_date=last)
    rows: list[tuple[date, str, int]] = []
    for session, values in schedule.iterrows():
        minutes = int((values["market_close"] - values["market_open"]).total_seconds() // 60)
        rows.extend(
            (
                (session.date(), "1m", minutes),
                (session.date(), "5m", ceil(minutes / 5)),
            )
        )
    return tuple(rows)


def _empty_coverage() -> dict:
    return {
        "observed_sessions": {interval: 0 for interval in REQUIRED_INTERVALS},
        "first_date": {interval: None for interval in REQUIRED_INTERVALS},
        "last_date": {interval: None for interval in REQUIRED_INTERVALS},
        "minimum_observed_names_per_session": {interval: 0 for interval in REQUIRED_INTERVALS},
        "minimum_usable_names_per_session": {interval: 0 for interval in REQUIRED_INTERVALS},
        "qualifying_sessions": {interval: 0 for interval in REQUIRED_INTERVALS},
        "qualifying_first_date": {interval: None for interval in REQUIRED_INTERVALS},
        "qualifying_last_date": {interval: None for interval in REQUIRED_INTERVALS},
        "qualifying_calendar_span_days": {interval: 0 for interval in REQUIRED_INTERVALS},
    }


def _expected_schedule(con: duckdb.DuckDBPyConnection) -> tuple[str, list]:
    first_date, last_date = con.execute(
        "SELECT MIN(CAST(ts AS DATE)), MAX(CAST(ts AS DATE)) "
        "FROM intraday_prices WHERE interval IN ('1m', '5m')"
    ).fetchone()
    expected_rows = (
        _session_bar_expectations(first_date, last_date)
        if first_date is not None and last_date is not None
        else []
    )
    expected_values = ", ".join("(?, ?, ?)" for _ in expected_rows) or (
        "(CAST(NULL AS DATE), CAST(NULL AS VARCHAR), CAST(NULL AS INTEGER))"
    )
    expected_params = [value for row in expected_rows for value in row]
    return expected_values, expected_params


def _coverage_rows(
    con: duckdb.DuckDBPyConnection,
    minimum_tickers: int,
    minimum_coverage_fraction: int | float,
) -> list[tuple]:
    expected_values, expected_params = _expected_schedule(con)
    return con.execute(
        f"WITH expected(date, interval, expected_bars) AS (VALUES {expected_values}), "
        "ticker_sessions AS ("
        "  SELECT interval, CAST(ts AS DATE) AS date, ticker, COUNT(*) AS n_bars "
        "  FROM intraday_prices WHERE interval IN ('1m', '5m') "
        "  GROUP BY interval, CAST(ts AS DATE), ticker"
        "), sessions AS ("
        "  SELECT t.interval, t.date, COUNT(*) AS n_names, "
        "         SUM(CASE WHEN e.expected_bars IS NOT NULL "
        "              AND t.n_bars >= CEIL(e.expected_bars * ?) "
        "              THEN 1 ELSE 0 END) AS n_usable_names "
        "  FROM ticker_sessions t "
        "  LEFT JOIN expected e USING (date, interval) "
        "  GROUP BY t.interval, t.date"
        ") SELECT interval, COUNT(*), MIN(date), MAX(date), MIN(n_names), "
        "MIN(n_usable_names), SUM(CASE WHEN n_usable_names >= ? THEN 1 ELSE 0 END), "
        "MIN(CASE WHEN n_usable_names >= ? THEN date END), "
        "MAX(CASE WHEN n_usable_names >= ? THEN date END) "
        "FROM sessions GROUP BY interval",
        [
            *expected_params,
            minimum_coverage_fraction,
            *([minimum_tickers] * 3),
        ],
    ).fetchall()


def _coverage(
    con: duckdb.DuckDBPyConnection,
    minimum_tickers: int,
    minimum_coverage_fraction: int | float,
) -> dict:
    coverage = _empty_coverage()
    for row in _coverage_rows(con, minimum_tickers, minimum_coverage_fraction):
        interval = row[0]
        if interval not in REQUIRED_INTERVALS:
            continue
        coverage["observed_sessions"][interval] = count(row[1])
        coverage["first_date"][interval] = iso(row[2])
        coverage["last_date"][interval] = iso(row[3])
        coverage["minimum_observed_names_per_session"][interval] = count(row[4])
        coverage["minimum_usable_names_per_session"][interval] = count(row[5])
        coverage["qualifying_sessions"][interval] = count(row[6])
        coverage["qualifying_first_date"][interval] = iso(row[7])
        coverage["qualifying_last_date"][interval] = iso(row[8])
        coverage["qualifying_calendar_span_days"][interval] = span_days(row[7], row[8])
    return coverage


def _is_ready(inputs: dict, coverage: dict, minimum_sessions: int, minimum_span: int) -> bool:
    return inputs["input_status"] == "ready" and all(
        coverage["qualifying_sessions"][interval] >= minimum_sessions
        and coverage["qualifying_calendar_span_days"][interval] >= minimum_span
        for interval in REQUIRED_INTERVALS
    )


def validate(payload: dict) -> None:
    require_exact_fields(payload, PUBLIC_FIELDS, "intraday-readiness")
    validate_input_schema_status(payload, REQUIRED_INPUTS)
    validate_intraday_coverage(payload, REQUIRED_INTERVALS)
    if payload["session_schedule_source"] != "pandas_market_calendars:NYSE":
        raise ValueError("intraday-readiness schedule source is invalid")
    require_public_nonempty_string(
        payload["usable_observation_rule"], "intraday-readiness observation rule"
    )
    require_public_nonempty_string(payload["limitation"], "intraday-readiness limitation")


def assess(con: duckdb.DuckDBPyConnection) -> dict:
    minimum_sessions = positive_count(MIN_SESSIONS, "minimum_sessions_per_interval")
    minimum_span = positive_count(MIN_CALENDAR_DAYS, "minimum_calendar_span_days")
    minimum_tickers = positive_count(MIN_TICKERS_PER_INTERVAL, "minimum_tickers_per_interval")
    minimum_coverage_fraction = coverage_fraction(MIN_SESSION_COVERAGE_FRACTION)
    inputs = input_schema_status(con, REQUIRED_INPUTS)
    coverage = (
        _coverage(con, minimum_tickers, minimum_coverage_fraction)
        if inputs["input_status"] == "ready"
        else _empty_coverage()
    )
    result = {
        **inputs,
        "status": (
            "READY_FOR_CHARTER"
            if _is_ready(inputs, coverage, minimum_sessions, minimum_span)
            else "WAITING"
        ),
        **coverage,
        "minimum_sessions_per_interval": minimum_sessions,
        "minimum_calendar_span_days": minimum_span,
        "minimum_tickers_per_interval": minimum_tickers,
        "minimum_session_coverage_fraction": minimum_coverage_fraction,
        "session_schedule_source": SESSION_SCHEDULE_SOURCE,
        "required_intervals": list(REQUIRED_INTERVALS),
        "usable_observation_rule": (
            "A ticker-session must retain at least 75% of the bars expected from the published "
            "NYSE schedule for that date and interval; unknown or closed dates contribute zero "
            "usable breadth."
        ),
        "limitation": (
            "Coverage alone does not establish an event or microstructure effect; a charter "
            "must also freeze event definitions, costs, controls, and the total trial count."
        ),
    }
    validate(result)
    return result
