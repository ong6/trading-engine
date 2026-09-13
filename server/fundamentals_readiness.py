"""Point-in-time fundamentals research admission gate."""

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

MIN_SNAPSHOTS = 156  # about three years of weekly snapshots
MIN_CALENDAR_DAYS = 1095
MIN_NAMES_PER_SNAPSHOT = 1_000
REQUIRED_INPUTS = {
    "fundamentals": {
        "ticker": {"VARCHAR"},
        "as_of": {"DATE"},
        "quote_type": {"VARCHAR"},
        "market_cap": {"FLOAT", "DOUBLE", "DECIMAL"},
        "trailing_pe": {"FLOAT", "DOUBLE", "DECIMAL"},
        "price_to_book": {"FLOAT", "DOUBLE", "DECIMAL"},
        "ev_to_ebitda": {"FLOAT", "DOUBLE", "DECIMAL"},
    }
}
PUBLIC_FIELDS = frozenset(
    {
        "input_status",
        "missing_tables",
        "missing_columns",
        "incompatible_columns",
        "status",
        "observed_snapshots",
        "first_date",
        "last_date",
        "minimum_observed_names_per_snapshot",
        "qualifying_snapshots",
        "qualifying_first_date",
        "qualifying_last_date",
        "qualifying_calendar_span_days",
        "minimum_snapshots",
        "minimum_calendar_span_days",
        "minimum_names_per_snapshot",
        "numeric_rule",
        "usable_observation_rule",
        "limitation",
    }
)


def _empty_coverage() -> dict:
    return {
        "observed_snapshots": 0,
        "first_date": None,
        "last_date": None,
        "minimum_observed_names_per_snapshot": 0,
        "qualifying_snapshots": 0,
        "qualifying_first_date": None,
        "qualifying_last_date": None,
        "qualifying_calendar_span_days": 0,
    }


def _coverage_row(con: duckdb.DuckDBPyConnection, minimum_names: int) -> tuple:
    return con.execute(
        "WITH snapshots AS ("
        "  SELECT as_of, COUNT(DISTINCT ticker) AS n_names "
        "  FROM fundamentals "
        "  WHERE quote_type = 'EQUITY' "
        "    AND COALESCE(isfinite(market_cap) AND market_cap > 0, FALSE) "
        "    AND (COALESCE(isfinite(trailing_pe), FALSE) "
        "         OR COALESCE(isfinite(price_to_book), FALSE) "
        "         OR COALESCE(isfinite(ev_to_ebitda), FALSE)) "
        "  GROUP BY as_of"
        ") SELECT COUNT(*), MIN(as_of), MAX(as_of), MIN(n_names), "
        "SUM(CASE WHEN n_names >= ? THEN 1 ELSE 0 END), "
        "MIN(CASE WHEN n_names >= ? THEN as_of END), "
        "MAX(CASE WHEN n_names >= ? THEN as_of END) FROM snapshots",
        [minimum_names] * 3,
    ).fetchone()


def _coverage(con: duckdb.DuckDBPyConnection, minimum_names: int) -> dict:
    snapshots, first, last, minimum_names, qualifying, qualifying_first, qualifying_last = (
        _coverage_row(con, minimum_names)
    )
    return {
        "observed_snapshots": count(snapshots),
        "first_date": iso(first),
        "last_date": iso(last),
        "minimum_observed_names_per_snapshot": count(minimum_names),
        "qualifying_snapshots": count(qualifying),
        "qualifying_first_date": iso(qualifying_first),
        "qualifying_last_date": iso(qualifying_last),
        "qualifying_calendar_span_days": span_days(qualifying_first, qualifying_last),
    }


def _is_ready(inputs: dict, coverage: dict, minimum_snapshots: int, minimum_span: int) -> bool:
    return (
        inputs["input_status"] == "ready"
        and coverage["qualifying_snapshots"] >= minimum_snapshots
        and coverage["qualifying_calendar_span_days"] >= minimum_span
    )


def validate(payload: dict) -> None:
    require_exact_fields(payload, PUBLIC_FIELDS, "fundamentals-readiness")
    validate_input_schema_status(payload, REQUIRED_INPUTS)
    validate_dated_coverage(
        payload,
        observed_field="observed_snapshots",
        qualifying_field="qualifying_snapshots",
        observed_breadth_field="minimum_observed_names_per_snapshot",
        minimum_field="minimum_snapshots",
        minimum_breadth_field="minimum_names_per_snapshot",
    )
    if payload["numeric_rule"] != "finite_positive_market_cap_and_finite_valuation":
        raise ValueError("fundamentals-readiness numeric rule is invalid")
    require_public_nonempty_string(
        payload["usable_observation_rule"], "fundamentals-readiness observation rule"
    )
    require_public_nonempty_string(payload["limitation"], "fundamentals-readiness limitation")


def assess(con: duckdb.DuckDBPyConnection) -> dict:
    minimum_snapshots = positive_count(MIN_SNAPSHOTS, "minimum_snapshots")
    minimum_span = positive_count(MIN_CALENDAR_DAYS, "minimum_calendar_span_days")
    minimum_names = positive_count(MIN_NAMES_PER_SNAPSHOT, "minimum_names_per_snapshot")
    inputs = input_schema_status(con, REQUIRED_INPUTS)
    coverage = (
        _coverage(con, minimum_names) if inputs["input_status"] == "ready" else _empty_coverage()
    )
    result = {
        **inputs,
        "status": (
            "READY_FOR_CHARTER"
            if _is_ready(inputs, coverage, minimum_snapshots, minimum_span)
            else "WAITING"
        ),
        **coverage,
        "minimum_snapshots": minimum_snapshots,
        "minimum_calendar_span_days": minimum_span,
        "minimum_names_per_snapshot": minimum_names,
        "numeric_rule": "finite_positive_market_cap_and_finite_valuation",
        "usable_observation_rule": (
            "quote_type=EQUITY, finite positive market_cap, and at least one finite "
            "trailing_pe/price_to_book/ev_to_ebitda value; finite negative ratios remain valid"
        ),
        "limitation": (
            "Current fundamentals must not be joined backward into historical prices; "
            "publication-time snapshots or an independent point-in-time source are required."
        ),
    }
    validate(result)
    return result
