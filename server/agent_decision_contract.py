"""Closed model-output contract for one shadow decision window."""

from __future__ import annotations

import math
from typing import Any

from .agent_contract import (
    EVIDENCE_ID_MAX_CHARS,
    INVALIDATION_MAX_CHARS,
    MAX_EVIDENCE_IDS,
    THESIS_MAX_CHARS,
)

SCHEMA_VERSION = 1
NO_ACTION_FIELDS = frozenset({"schema_version", "decision", "reason"})
PROPOSAL_FIELDS = frozenset(
    {
        "schema_version",
        "decision",
        "side",
        "max_notional",
        "stop",
        "confidence",
        "thesis",
        "invalidation",
        "evidence_ids",
    }
)
NO_ACTION_REASON_MAX_CHARS = 512


class DecisionError(ValueError):
    """The model returned an object outside the frozen shadow contract."""


def _text(value: object, name: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > maximum
        or not value.isprintable()
    ):
        raise DecisionError(f"{name} is invalid")
    return value


def _finite(value: object, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DecisionError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        qualifier = "positive " if positive else ""
        raise DecisionError(f"{name} must be a {qualifier}finite number")
    return number


def _evidence_ids(value: object, allowed: frozenset[str]) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > MAX_EVIDENCE_IDS:
        raise DecisionError("evidence_ids must be a nonempty bounded array")
    result = []
    for item in value:
        evidence_id = _text(item, "evidence_id", EVIDENCE_ID_MAX_CHARS)
        if evidence_id not in allowed:
            raise DecisionError("evidence_ids contains a reference outside the context allowlist")
        result.append(evidence_id)
    if len(set(result)) != len(result):
        raise DecisionError("evidence_ids must not contain duplicates")
    return result


def normalize(body: dict[str, Any], *, allowed_evidence_ids: frozenset[str]) -> dict:
    """Normalize exactly one no-action or one bounded proposal claim."""
    if not isinstance(body, dict):
        raise DecisionError("model decision must be an object")
    decision = body.get("decision")
    if decision not in {"no_action", "proposal"}:
        raise DecisionError("decision must be no_action or proposal")
    expected = NO_ACTION_FIELDS if decision == "no_action" else PROPOSAL_FIELDS
    unknown = sorted(set(body) - expected)
    missing = sorted(expected - set(body))
    if unknown:
        raise DecisionError(f"unknown decision field(s): {', '.join(unknown)}")
    if missing:
        raise DecisionError(f"missing decision field(s): {', '.join(missing)}")
    if body.get("schema_version") != SCHEMA_VERSION or isinstance(
        body.get("schema_version"), bool
    ):
        raise DecisionError(f"schema_version must be {SCHEMA_VERSION}")
    if decision == "no_action":
        return {
            "schema_version": SCHEMA_VERSION,
            "decision": decision,
            "reason": _text(body.get("reason"), "reason", NO_ACTION_REASON_MAX_CHARS),
        }
    side = body.get("side")
    if side not in {"buy", "sell"}:
        raise DecisionError("side must be buy or sell")
    stop_value = body.get("stop")
    stop = None if stop_value is None else _finite(stop_value, "stop", positive=True)
    confidence = _finite(body.get("confidence"), "confidence")
    if not 0 <= confidence <= 1:
        raise DecisionError("confidence must be between 0 and 1")
    return {
        "schema_version": SCHEMA_VERSION,
        "decision": decision,
        "side": side,
        "max_notional": _finite(body.get("max_notional"), "max_notional", positive=True),
        "stop": stop,
        "confidence": confidence,
        "thesis": _text(body.get("thesis"), "thesis", THESIS_MAX_CHARS),
        "invalidation": _text(
            body.get("invalidation"),
            "invalidation",
            INVALIDATION_MAX_CHARS,
        ),
        "evidence_ids": _evidence_ids(body.get("evidence_ids"), allowed_evidence_ids),
    }


def output_schema() -> dict:
    """Return a JSON-only description embedded in every bounded model input."""
    return {
        "schema_version": SCHEMA_VERSION,
        "exactly_one_of": [
            {
                "schema_version": SCHEMA_VERSION,
                "decision": "no_action",
                "reason": "nonempty printable string",
            },
            {
                "schema_version": SCHEMA_VERSION,
                "decision": "proposal",
                "side": "buy or sell",
                "max_notional": "positive finite number",
                "stop": "null or positive finite number",
                "confidence": "finite number from 0 through 1",
                "thesis": "nonempty printable string",
                "invalidation": "nonempty printable string",
                "evidence_ids": "nonempty unique subset of allowed_evidence_ids",
            },
        ],
        "additional_fields": False,
    }
