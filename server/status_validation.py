"""Shared strict validators for read-only operational evidence projections."""

from __future__ import annotations

from datetime import date, datetime, timezone


def iso_date(value: object, message: str = "date must be YYYY-MM-DD") -> date:
    """Parse only the canonical calendar-date spelling used by API evidence."""
    if not isinstance(value, str):
        raise ValueError(message)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError(message) from None
    if parsed.isoformat() != value:
        raise ValueError(message)
    return parsed


def iso_timestamp(
    value: object,
    message: str = "timestamp must be canonical ISO 8601",
    *,
    require_timezone: bool = True,
) -> datetime:
    """Parse a canonical ISO timestamp, optionally accepting a trailing ``Z``."""
    if not isinstance(value, str):
        raise ValueError(message)
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise ValueError(message) from None
    canonical = parsed.isoformat()
    if value.endswith("Z") and canonical.endswith("+00:00"):
        canonical = f"{canonical[:-6]}Z"
    if canonical != value or (require_timezone and parsed.tzinfo is None):
        raise ValueError(message)
    return parsed


def metadata_timestamp(raw: object) -> datetime:
    """Return an evidence ``last_run`` as an aware UTC timestamp."""
    if not isinstance(raw, dict):
        raise ValueError("evidence is not an object")
    parsed = iso_timestamp(raw["last_run"], "last_run must be a canonical ISO timestamp")
    return parsed.astimezone(timezone.utc)


def nonnegative_int(raw: dict, field: str) -> int:
    """Read a strict non-negative integer, rejecting booleans and coercion."""
    value = raw[field]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value
