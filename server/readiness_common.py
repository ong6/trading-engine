"""Shared normalization and validation for research-readiness projections."""

from collections.abc import Collection, Mapping
from datetime import date

from .read_model_utils import (
    require_public_date,
    require_public_finite_number,
    require_public_nonempty_string,
    require_public_nonnegative_integer,
)


def iso(value: date | None) -> str | None:
    return None if value is None else require_public_date(value, "readiness date").isoformat()


def span_days(first: date | None, last: date | None) -> int:
    if first is None and last is None:
        return 0
    if first is None or last is None:
        raise ValueError("readiness date range is incomplete")
    first = require_public_date(first, "readiness first date")
    last = require_public_date(last, "readiness last date")
    if last < first:
        raise ValueError("readiness date range is reversed")
    return (last - first).days


def count(value: int | None) -> int:
    """Normalize SQL aggregate NULLs from existing but empty source tables."""
    return require_public_nonnegative_integer(0 if value is None else value)


def positive_count(value: object, field: str) -> int:
    """Require a positive threshold that remains exact in JavaScript."""
    result = require_public_nonnegative_integer(value)
    if result == 0:
        raise ValueError(f"public {field} is invalid")
    return result


def coverage_fraction(value: object) -> int | float:
    """Require an interoperable fractional threshold in ``(0, 1]``."""
    result = require_public_finite_number(value, "minimum session coverage fraction")
    if result <= 0 or result > 1:
        raise ValueError("public minimum session coverage fraction is invalid")
    return result


def require_exact_fields(payload: object, expected: Collection[str], label: str) -> None:
    """Reject missing or unreviewed fields in a public readiness object."""
    if not isinstance(payload, Mapping) or set(payload) != set(expected):
        raise ValueError(f"{label} fields are invalid")


def _required_input_names(
    required: Mapping[str, Mapping[str, Collection[str]]],
) -> dict[str, set[str]]:
    if not isinstance(required, Mapping) or not required:
        raise ValueError("readiness required-input schema is invalid")
    names: dict[str, set[str]] = {}
    for table, columns in required.items():
        require_public_nonempty_string(table, "readiness table name")
        if not isinstance(columns, Mapping) or not columns:
            raise ValueError("readiness required-input schema is invalid")
        names[table] = set()
        for column, allowed_types in columns.items():
            require_public_nonempty_string(column, "readiness column name")
            if not isinstance(allowed_types, Collection) or isinstance(allowed_types, str):
                raise ValueError("readiness required-input schema is invalid")
            normalized_types = {
                require_public_nonempty_string(value, "readiness column type")
                for value in allowed_types
            }
            if not normalized_types:
                raise ValueError("readiness required-input schema is invalid")
            names[table].add(column)
    return names


def _schema_diagnostics(payload: Mapping[str, object]) -> tuple[object, object, object, object]:
    try:
        return (
            payload["input_status"],
            payload["missing_tables"],
            payload["missing_columns"],
            payload["incompatible_columns"],
        )
    except (KeyError, TypeError) as exc:
        raise ValueError("readiness input diagnostics are invalid") from exc


def _validate_missing_tables(missing_tables: object, expected_tables: set[str]) -> set[str]:
    if not isinstance(missing_tables, list) or missing_tables != sorted(set(missing_tables)):
        raise ValueError("readiness missing-table diagnostics are invalid")
    if not all(isinstance(table, str) and table in expected_tables for table in missing_tables):
        raise ValueError("readiness missing-table diagnostics are invalid")
    return set(missing_tables)


def _validate_missing_columns(
    missing_columns: object,
    expected_columns: Mapping[str, set[str]],
) -> None:
    if not isinstance(missing_columns, Mapping):
        raise ValueError("readiness column diagnostics are invalid")
    for table, columns in missing_columns.items():
        if (
            table not in expected_columns
            or not isinstance(columns, list)
            or not columns
            or columns != sorted(set(columns))
            or not set(columns) <= expected_columns[table]
        ):
            raise ValueError("readiness missing-column diagnostics are invalid")


def _validate_incompatible_columns(
    incompatible_columns: object,
    missing_columns: Mapping[str, list[str]],
    expected_columns: Mapping[str, set[str]],
) -> None:
    if not isinstance(incompatible_columns, Mapping):
        raise ValueError("readiness column diagnostics are invalid")
    for table, columns in incompatible_columns.items():
        if (
            table not in expected_columns
            or not isinstance(columns, Mapping)
            or not columns
            or not set(columns) <= expected_columns[table]
        ):
            raise ValueError("readiness incompatible-column diagnostics are invalid")
        if set(columns) & set(missing_columns.get(table, [])):
            raise ValueError("readiness column diagnostics overlap")
        for actual_type in columns.values():
            require_public_nonempty_string(actual_type, "readiness actual column type")


def validate_input_schema_status(
    payload: Mapping[str, object],
    required: Mapping[str, Mapping[str, Collection[str]]],
) -> None:
    """Require exact, internally coherent diagnostics for one input family."""
    expected_columns = _required_input_names(required)
    status, missing_tables, missing_columns, incompatible_columns = _schema_diagnostics(payload)
    if status not in {"ready", "missing", "invalid-schema"}:
        raise ValueError("readiness input status is invalid")
    missing_table_set = _validate_missing_tables(missing_tables, set(expected_columns))
    if not isinstance(missing_columns, Mapping) or not isinstance(incompatible_columns, Mapping):
        raise ValueError("readiness column diagnostics are invalid")
    diagnosed_tables = set(missing_columns) | set(incompatible_columns)
    if diagnosed_tables & missing_table_set:
        raise ValueError("readiness column diagnostics are invalid")
    _validate_missing_columns(missing_columns, expected_columns)
    _validate_incompatible_columns(incompatible_columns, missing_columns, expected_columns)
    expected_status = (
        "invalid-schema"
        if missing_columns or incompatible_columns
        else "missing"
        if missing_tables
        else "ready"
    )
    if status != expected_status:
        raise ValueError("readiness input status contradicts diagnostics")


def _projection_date(value: object, field: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"public {field} is invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"public {field} is invalid") from None
    if parsed.isoformat() != value:
        raise ValueError(f"public {field} is invalid")
    return parsed


def _validate_date_range(
    observations: int,
    first_value: object,
    last_value: object,
    field: str,
) -> tuple[date | None, date | None]:
    first = _projection_date(first_value, f"{field} first date")
    last = _projection_date(last_value, f"{field} last date")
    if observations == 0:
        if first is not None or last is not None:
            raise ValueError(f"public {field} date range is invalid")
        return None, None
    if first is None or last is None or first > last:
        raise ValueError(f"public {field} date range is invalid")
    if observations == 1 and first != last:
        raise ValueError(f"public {field} date range is invalid")
    if observations > (last - first).days + 1:
        raise ValueError(f"public {field} count exceeds its date range")
    return first, last


def validate_dated_coverage(
    payload: Mapping[str, object],
    *,
    observed_field: str,
    qualifying_field: str,
    observed_breadth_field: str,
    minimum_field: str,
    minimum_breadth_field: str,
) -> None:
    """Validate one dated family's counts, dates, thresholds, span, and status."""
    observed = count(payload[observed_field])
    qualifying = count(payload[qualifying_field])
    observed_breadth = count(payload[observed_breadth_field])
    minimum = positive_count(payload[minimum_field], minimum_field)
    minimum_span = positive_count(
        payload["minimum_calendar_span_days"], "minimum_calendar_span_days"
    )
    positive_count(payload[minimum_breadth_field], minimum_breadth_field)
    if qualifying > observed:
        raise ValueError("readiness qualifying count exceeds observed count")
    if (observed == 0) != (observed_breadth == 0):
        raise ValueError("readiness observed breadth contradicts observed count")

    first, last = _validate_date_range(
        observed, payload["first_date"], payload["last_date"], observed_field
    )
    qualifying_first, qualifying_last = _validate_date_range(
        qualifying,
        payload["qualifying_first_date"],
        payload["qualifying_last_date"],
        qualifying_field,
    )
    qualifying_span = count(payload["qualifying_calendar_span_days"])
    expected_span = (
        0
        if qualifying_first is None or qualifying_last is None
        else (qualifying_last - qualifying_first).days
    )
    if qualifying_span != expected_span:
        raise ValueError("readiness qualifying span contradicts its date range")
    if qualifying_first is not None and (
        first is None or last is None or qualifying_first < first or qualifying_last > last
    ):
        raise ValueError("readiness qualifying dates exceed observed dates")
    if payload["input_status"] != "ready" and (
        observed != 0 or qualifying != 0 or observed_breadth != 0
    ):
        raise ValueError("unusable readiness inputs reported coverage")

    expected_status = (
        "READY_FOR_CHARTER"
        if payload["input_status"] == "ready"
        and qualifying >= minimum
        and qualifying_span >= minimum_span
        else "WAITING"
    )
    if payload["status"] != expected_status:
        raise ValueError("readiness status contradicts measured coverage")


def _validate_interval_maps(payload: Mapping[str, object], intervals: list[str]) -> None:
    expected_keys = set(intervals)
    for field in (
        "observed_sessions",
        "first_date",
        "last_date",
        "minimum_observed_names_per_session",
        "minimum_usable_names_per_session",
        "qualifying_sessions",
        "qualifying_first_date",
        "qualifying_last_date",
        "qualifying_calendar_span_days",
    ):
        values = payload[field]
        if not isinstance(values, Mapping) or set(values) != expected_keys:
            raise ValueError(f"readiness {field} intervals are invalid")


def _validate_intraday_interval(
    payload: Mapping[str, object],
    interval: str,
    minimum_sessions: int,
    minimum_span: int,
) -> bool:
    observed = count(payload["observed_sessions"][interval])
    qualifying = count(payload["qualifying_sessions"][interval])
    observed_breadth = count(payload["minimum_observed_names_per_session"][interval])
    usable_breadth = count(payload["minimum_usable_names_per_session"][interval])
    if qualifying > observed or usable_breadth > observed_breadth:
        raise ValueError("readiness intraday coverage is impossible")
    if (observed == 0) != (observed_breadth == 0):
        raise ValueError("readiness observed breadth contradicts observed count")

    first, last = _validate_date_range(
        observed,
        payload["first_date"][interval],
        payload["last_date"][interval],
        f"{interval} observed sessions",
    )
    qualifying_first, qualifying_last = _validate_date_range(
        qualifying,
        payload["qualifying_first_date"][interval],
        payload["qualifying_last_date"][interval],
        f"{interval} qualifying sessions",
    )
    qualifying_span = count(payload["qualifying_calendar_span_days"][interval])
    expected_span = span_days(qualifying_first, qualifying_last)
    if qualifying_span != expected_span:
        raise ValueError("readiness qualifying span contradicts its date range")
    if qualifying_first is not None and (
        first is None or last is None or qualifying_first < first or qualifying_last > last
    ):
        raise ValueError("readiness qualifying dates exceed observed dates")
    if payload["input_status"] != "ready" and any(
        value != 0 for value in (observed, qualifying, observed_breadth, usable_breadth)
    ):
        raise ValueError("unusable readiness inputs reported coverage")
    return qualifying >= minimum_sessions and qualifying_span >= minimum_span


def validate_intraday_coverage(
    payload: Mapping[str, object],
    required_intervals: tuple[str, ...],
) -> None:
    """Validate the multi-interval intraday projection as one admission gate."""
    intervals = list(required_intervals)
    if not intervals or len(intervals) != len(set(intervals)):
        raise ValueError("readiness intervals are invalid")
    if payload["required_intervals"] != intervals:
        raise ValueError("readiness intervals contradict the configured gate")
    minimum_sessions = positive_count(
        payload["minimum_sessions_per_interval"], "minimum_sessions_per_interval"
    )
    minimum_span = positive_count(
        payload["minimum_calendar_span_days"], "minimum_calendar_span_days"
    )
    positive_count(payload["minimum_tickers_per_interval"], "minimum_tickers_per_interval")
    coverage_fraction(payload["minimum_session_coverage_fraction"])
    _validate_interval_maps(payload, intervals)
    interval_ready = [
        _validate_intraday_interval(payload, interval, minimum_sessions, minimum_span)
        for interval in intervals
    ]

    expected_status = (
        "READY_FOR_CHARTER"
        if payload["input_status"] == "ready" and all(interval_ready)
        else "WAITING"
    )
    if payload["status"] != expected_status:
        raise ValueError("readiness status contradicts measured coverage")


def _compatible_type(actual: str, allowed: Collection[str]) -> bool:
    return actual in allowed or ("DECIMAL" in allowed and actual.startswith("DECIMAL("))


def _table_schema(
    con, table: str, expected: Mapping[str, Collection[str]]
) -> tuple[list[str], dict[str, str]] | None:
    rows = con.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_catalog = current_catalog() AND table_schema = current_schema() "
        "AND table_name = ?",
        [table],
    ).fetchall()
    if not rows:
        return None
    actual = {name: data_type for name, data_type in rows}
    absent = sorted(set(expected) - set(actual))
    incompatible = {
        column: actual[column]
        for column, allowed_types in expected.items()
        if column in actual and not _compatible_type(actual[column], allowed_types)
    }
    return absent, incompatible


def input_schema_status(con, required: Mapping[str, Mapping[str, Collection[str]]]) -> dict:
    """Describe missing tables/columns without attempting a query that can fail open."""
    _required_input_names(required)
    missing_tables: list[str] = []
    missing_columns: dict[str, list[str]] = {}
    incompatible_columns: dict[str, dict[str, str]] = {}
    for table, expected in required.items():
        schema = _table_schema(con, table, expected)
        if schema is None:
            missing_tables.append(table)
            continue
        absent, incompatible = schema
        if absent:
            missing_columns[table] = absent
        if incompatible:
            incompatible_columns[table] = incompatible
    status = (
        "invalid-schema"
        if missing_columns or incompatible_columns
        else "missing"
        if missing_tables
        else "ready"
    )
    result = {
        "input_status": status,
        "missing_tables": sorted(missing_tables),
        "missing_columns": missing_columns,
        "incompatible_columns": incompatible_columns,
    }
    validate_input_schema_status(result, required)
    return result
