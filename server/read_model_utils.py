"""Shared primitives for read-only API projections."""

from __future__ import annotations

import math
from datetime import date

import duckdb

PUBLIC_PORTFOLIO_ID_MAX_CHARS = 128
PUBLIC_TICKER_MAX_CHARS = 32
PUBLIC_SAFE_INTEGER_MAX = 9_007_199_254_740_991


def require_public_date(value: object, field: str) -> date:
    """Return an exact calendar date, rejecting datetimes and other coercions."""
    if type(value) is not date:
        raise ValueError(f"public {field} is invalid")
    return value


def require_public_nonempty_string(value: object, field: str) -> str:
    """Return a nonblank string without changing display text."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"public {field} is invalid")
    return value


def require_public_portfolio_id(value: object) -> str:
    """Return one canonical public portfolio key or reject malformed stored state."""
    if not isinstance(value, str):
        raise ValueError("portfolio identifier is invalid")
    normalized = value.strip()
    if (
        not normalized
        or normalized != value
        or len(normalized) > PUBLIC_PORTFOLIO_ID_MAX_CHARS
        or not normalized.isprintable()
    ):
        raise ValueError("portfolio identifier is invalid")
    return normalized


def require_public_ticker(value: object) -> str:
    """Return one canonical public ticker key or reject malformed state."""
    if not isinstance(value, str):
        raise ValueError("ticker is invalid")
    normalized = value.strip()
    if (
        not normalized
        or normalized != value
        or len(normalized) > PUBLIC_TICKER_MAX_CHARS
        or not normalized.isprintable()
    ):
        raise ValueError("ticker is invalid")
    return normalized


def require_public_positive_integer(value: object) -> int:
    """Return an integer that remains exact in interoperable JSON consumers."""
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > PUBLIC_SAFE_INTEGER_MAX
    ):
        raise ValueError("public identifier is invalid")
    return value


def require_public_nonnegative_integer(value: object) -> int:
    """Return a non-negative count that remains exact for JSON consumers."""
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > PUBLIC_SAFE_INTEGER_MAX
    ):
        raise ValueError("public count is invalid")
    return value


def require_public_finite_number(value: object, field: str) -> int | float:
    """Return a finite JSON number, rejecting booleans and non-numeric values."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"public {field} is invalid")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f"public {field} is invalid")
    return value


def require_public_positive_number(value: object, field: str) -> int | float:
    """Return a finite number strictly above zero."""
    number = require_public_finite_number(value, field)
    if number <= 0:
        raise ValueError(f"public {field} is invalid")
    return number


def require_public_nonnegative_number(value: object, field: str) -> int | float:
    """Return a finite number at or above zero."""
    number = require_public_finite_number(value, field)
    if number < 0:
        raise ValueError(f"public {field} is invalid")
    return number


def bound_text_fields(item: dict, limits: dict[str, int]) -> bool:
    """Clip display-only strings in place and report whether any was shortened."""
    truncated = False
    for field, limit in limits.items():
        value = item[field]
        if isinstance(value, str) and len(value) > limit:
            item[field] = value[:limit]
            truncated = True
    return truncated


def rows(cur: duckdb.DuckDBPyConnection) -> list[dict]:
    """Materialize the current cursor as dictionaries keyed by column name."""
    columns = [column[0] for column in cur.description]
    return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]
