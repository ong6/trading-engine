"""Validate and canonicalize one walk-forward evidence cohort identity."""

from __future__ import annotations

import math
import re

from engine.lib.provenance import canonical_sha256
from server.status_validation import iso_date


def positive_number(value: object, message: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(message)
    return float(value)


def validated_protocol(value: object) -> tuple[str, dict[str, int]]:
    if not isinstance(value, dict):
        raise ValueError("invalid protocol")
    anchor = value.get("anchor")
    try:
        anchor = iso_date(anchor)
    except ValueError:
        raise ValueError("invalid protocol anchor") from None
    months = {name: value.get(name) for name in ("train_months", "validate_months", "step_months")}
    if any(
        isinstance(months_value, bool) or not isinstance(months_value, int) or months_value <= 0
        for months_value in months.values()
    ):
        raise ValueError("invalid protocol window")
    return anchor.isoformat(), months


def validate_registration_identity(payload: dict, registration: dict) -> None:
    config = payload.get("config")
    if not isinstance(config, dict) or canonical_sha256(config) != payload.get("config_sha256"):
        raise ValueError("embedded config does not match its hash")
    if payload.get("strategy") != registration["strategy"]:
        raise ValueError("result strategy does not match registration")
    if payload.get("data_floor") != registration["data_floor"]:
        raise ValueError("result data floor does not match registration")
    for field in ("fill_model", "universe_policy", "data_quality_class"):
        if payload.get(field) != registration[field]:
            raise ValueError(f"result {field} does not match registration")


def _validated_hash(value: object, message: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(message)
    return value


def _nonempty_string(value: object, message: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(message)
    return value


def _validated_profile(value: object) -> dict:
    if not isinstance(value, dict) or not value:
        raise ValueError("invalid execution profile")
    _nonempty_string(value.get("id"), "invalid execution profile id")
    return value


def _validated_snapshot(value: object) -> str:
    if not isinstance(value, dict):
        raise ValueError("invalid data snapshot")
    sha256 = _validated_hash(value.get("sha256"), "invalid data snapshot hash")
    tables = value.get("tables")
    if not isinstance(tables, dict):
        raise ValueError("invalid data snapshot tables")
    if canonical_sha256(tables) != sha256:
        raise ValueError("data snapshot hash mismatch")
    return sha256


def _validated_comparison(value: object) -> str:
    if not isinstance(value, dict):
        raise ValueError("invalid comparison declaration")
    return _nonempty_string(value.get("protocol"), "invalid comparison protocol")


def signature(payload: dict) -> tuple[dict, str]:
    """Validate and canonicalize assumptions shared by one evidence cohort."""
    anchor, months = validated_protocol(payload.get("protocol"))
    profile = _validated_profile(payload.get("execution_profile"))
    cohort = {
        "source_sha256": _validated_hash(payload.get("source_sha256"), "invalid source hash"),
        "anchor": anchor,
        **months,
        "fill_model": _nonempty_string(payload.get("fill_model"), "invalid fill model"),
        "universe_policy": _nonempty_string(
            payload.get("universe_policy"), "invalid universe policy"
        ),
        "initial_cash": positive_number(payload.get("initial_cash"), "invalid initial cash"),
        # The complete profile participates in the signature. Only its ID and
        # hash are exposed by /meta so operational responses stay compact.
        "execution_profile": profile,
        "data_snapshot_sha256": _validated_snapshot(payload.get("data_snapshot")),
        "comparison_protocol": _validated_comparison(payload.get("comparison")),
    }
    return cohort, canonical_sha256(cohort)
