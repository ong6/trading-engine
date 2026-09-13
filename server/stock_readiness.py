"""Point-in-time stock-selection research admission gate."""

import duckdb

from .read_model_utils import require_public_nonempty_string
from .readiness_common import (
    count,
    input_schema_status,
    iso,
    positive_count,
    require_exact_fields,
    span_days,
    validate_dated_coverage,
    validate_input_schema_status,
)

MIN_SHARED_DATES = 756  # about three trading years
MIN_CALENDAR_DAYS = 1095
MIN_NAMES_PER_DATE = 1_000
REQUIRED_INPUTS = {
    "universe_snapshot": {"snapshot_date": {"DATE"}, "ticker": {"VARCHAR"}},
    "screen_results": {"run_date": {"DATE"}, "ticker": {"VARCHAR"}},
}
PUBLIC_FIELDS = frozenset(
    {
        "input_status",
        "missing_tables",
        "missing_columns",
        "incompatible_columns",
        "status",
        "observed_shared_dates",
        "first_date",
        "last_date",
        "minimum_observed_names_per_date",
        "qualifying_shared_dates",
        "qualifying_first_date",
        "qualifying_last_date",
        "qualifying_calendar_span_days",
        "minimum_shared_dates",
        "minimum_calendar_span_days",
        "minimum_names_per_date",
        "breadth_rule",
        "limitation",
    }
)


def _empty_coverage() -> dict:
    return {
        "observed_shared_dates": 0,
        "first_date": None,
        "last_date": None,
        "minimum_observed_names_per_date": 0,
        "qualifying_shared_dates": 0,
        "qualifying_first_date": None,
        "qualifying_last_date": None,
        "qualifying_calendar_span_days": 0,
    }


def _coverage_row(con: duckdb.DuckDBPyConnection, minimum_names: int) -> tuple:
    return con.execute(
        "WITH shared AS ("
        "  SELECT u.snapshot_date AS date, COUNT(DISTINCT u.ticker) AS n_names "
        "  FROM universe_snapshot u JOIN screen_results s "
        "    ON s.run_date = u.snapshot_date AND s.ticker = u.ticker "
        "  GROUP BY u.snapshot_date"
        ") SELECT COUNT(*), MIN(date), MAX(date), MIN(n_names), "
        "SUM(CASE WHEN n_names >= ? THEN 1 ELSE 0 END), "
        "MIN(CASE WHEN n_names >= ? THEN date END), "
        "MAX(CASE WHEN n_names >= ? THEN date END) FROM shared",
        [minimum_names] * 3,
    ).fetchone()


def _coverage(con: duckdb.DuckDBPyConnection, minimum_names: int) -> dict:
    shared, first, last, minimum_names, qualifying, qualifying_first, qualifying_last = (
        _coverage_row(con, minimum_names)
    )
    return {
        "observed_shared_dates": count(shared),
        "first_date": iso(first),
        "last_date": iso(last),
        "minimum_observed_names_per_date": count(minimum_names),
        "qualifying_shared_dates": count(qualifying),
        "qualifying_first_date": iso(qualifying_first),
        "qualifying_last_date": iso(qualifying_last),
        "qualifying_calendar_span_days": span_days(qualifying_first, qualifying_last),
    }


def _is_ready(inputs: dict, coverage: dict, minimum_dates: int, minimum_span: int) -> bool:
    return (
        inputs["input_status"] == "ready"
        and coverage["qualifying_shared_dates"] >= minimum_dates
        and coverage["qualifying_calendar_span_days"] >= minimum_span
    )


def validate(payload: dict) -> None:
    require_exact_fields(payload, PUBLIC_FIELDS, "stock-readiness")
    validate_input_schema_status(payload, REQUIRED_INPUTS)
    validate_dated_coverage(
        payload,
        observed_field="observed_shared_dates",
        qualifying_field="qualifying_shared_dates",
        observed_breadth_field="minimum_observed_names_per_date",
        minimum_field="minimum_shared_dates",
        minimum_breadth_field="minimum_names_per_date",
    )
    if payload["breadth_rule"] != "same_date_ticker_intersection":
        raise ValueError("stock-readiness breadth rule is invalid")
    require_public_nonempty_string(payload["limitation"], "stock-readiness limitation")


def assess(con: duckdb.DuckDBPyConnection) -> dict:
    minimum_dates = positive_count(MIN_SHARED_DATES, "minimum_shared_dates")
    minimum_span = positive_count(MIN_CALENDAR_DAYS, "minimum_calendar_span_days")
    minimum_names = positive_count(MIN_NAMES_PER_DATE, "minimum_names_per_date")
    inputs = input_schema_status(con, REQUIRED_INPUTS)
    coverage = (
        _coverage(con, minimum_names) if inputs["input_status"] == "ready" else _empty_coverage()
    )
    result = {
        **inputs,
        "status": (
            "READY_FOR_CHARTER"
            if _is_ready(inputs, coverage, minimum_dates, minimum_span)
            else "WAITING"
        ),
        **coverage,
        "minimum_shared_dates": minimum_dates,
        "minimum_calendar_span_days": minimum_span,
        "minimum_names_per_date": minimum_names,
        "breadth_rule": "same_date_ticker_intersection",
        "limitation": (
            "Historical stock selection is survivor-biased until this gate is met or an "
            "independent timestamped membership history is supplied."
        ),
    }
    validate(result)
    return result
