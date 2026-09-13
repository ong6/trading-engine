"""Shared primitives for fail-closed prospective-monitor API projections."""

from __future__ import annotations

import math


def invalid_status() -> dict:
    return {"status": "INVALID", "paper_only": True, "automatic_action": "none"}


def validate_report_envelope(
    payload: dict,
    allowed_statuses: frozenset[str],
    label: str,
) -> str:
    if payload["schema_version"] != 2:
        raise ValueError(f"unsupported {label} forward report schema")
    status = payload["status"]
    if status not in allowed_statuses:
        raise ValueError(f"unexpected {label} forward status: {status!r}")
    if payload["paper_only"] is not True or payload["automatic_action"] != "none":
        raise ValueError(f"{label} forward report violated paper-only/no-action invariant")
    return status


def require_expected_fields(actual: dict, expected: dict, message: str) -> None:
    if any(actual[key] != value for key, value in expected.items()):
        raise ValueError(message)


def validate_pair_registration(
    payload: dict,
    expected_candidate: dict,
    expected_control: dict,
    message: str,
) -> None:
    require_expected_fields(payload["candidate"], expected_candidate, message)
    require_expected_fields(payload["control"], expected_control, message)


def valid_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def finite_metric(metrics: dict, key: str, message: str) -> int | float:
    value = metrics[key]
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(message)
    return value
