"""Closed, versioned contract for shadow-only agent trade proposals."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

from .read_model_utils import PUBLIC_TICKER_MAX_CHARS, require_public_ticker
from .status_validation import iso_timestamp

SCHEMA_VERSION = 2
PROPOSAL_FIELDS = frozenset(
    {
        "schema_version",
        "proposal_id",
        "idempotency_key",
        "mode",
        "policy_id",
        "policy_registration_sha256",
        "agent_id",
        "model",
        "model_version",
        "prompt_sha256",
        "toolset_sha256",
        "strategy_id",
        "strategy_config_sha256",
        "agent_boundary_sha256",
        "runtime_source_sha256",
        "data_snapshot_sha256",
        "context_sha256",
        "ticker",
        "side",
        "max_notional",
        "stop",
        "confidence",
        "signal_at",
        "expires_at",
        "thesis",
        "invalidation",
        "evidence_ids",
    }
)
IDENTIFIER_MAX_CHARS = 128
MODEL_MAX_CHARS = 128
THESIS_MAX_CHARS = 4_096
INVALIDATION_MAX_CHARS = 2_048
MAX_EVIDENCE_IDS = 32
EVIDENCE_ID_MAX_CHARS = 256
MAX_SIGNAL_AGE = timedelta(days=1)
MAX_CLOCK_SKEW = timedelta(minutes=5)
MAX_EXPIRY = timedelta(days=7)
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class TradeProposalRequest:
    """Closed HTTP shape; scalar objects retain raw types for strict validation."""

    __pydantic_config__ = {"extra": "forbid"}

    schema_version: object
    proposal_id: str = field(metadata={"max_length": IDENTIFIER_MAX_CHARS})
    idempotency_key: str = field(metadata={"max_length": IDENTIFIER_MAX_CHARS})
    mode: Literal["agent_only", "hybrid"]
    policy_id: str = field(metadata={"max_length": IDENTIFIER_MAX_CHARS})
    policy_registration_sha256: str = field(metadata={"max_length": 64, "min_length": 64})
    agent_id: str = field(metadata={"max_length": IDENTIFIER_MAX_CHARS})
    model: str = field(metadata={"max_length": MODEL_MAX_CHARS})
    model_version: str = field(metadata={"max_length": IDENTIFIER_MAX_CHARS})
    prompt_sha256: str = field(metadata={"max_length": 64, "min_length": 64})
    toolset_sha256: str = field(metadata={"max_length": 64, "min_length": 64})
    strategy_id: str = field(metadata={"max_length": IDENTIFIER_MAX_CHARS})
    strategy_config_sha256: str = field(metadata={"max_length": 64, "min_length": 64})
    agent_boundary_sha256: str = field(metadata={"max_length": 64, "min_length": 64})
    runtime_source_sha256: str = field(metadata={"max_length": 64, "min_length": 64})
    data_snapshot_sha256: str = field(metadata={"max_length": 64, "min_length": 64})
    context_sha256: str = field(metadata={"max_length": 64, "min_length": 64})
    ticker: str = field(metadata={"max_length": PUBLIC_TICKER_MAX_CHARS})
    side: Literal["buy", "sell"]
    max_notional: object
    stop: object
    confidence: object
    signal_at: str = field(metadata={"max_length": 40})
    expires_at: str = field(metadata={"max_length": 40})
    thesis: str = field(metadata={"max_length": THESIS_MAX_CHARS})
    invalidation: str = field(metadata={"max_length": INVALIDATION_MAX_CHARS})
    evidence_ids: list[str]


class ProposalError(Exception):
    """A client-visible proposal rejection with an HTTP-compatible status."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _identifier(body: dict, name: str, *, max_chars: int = IDENTIFIER_MAX_CHARS) -> str:
    value = body.get(name)
    if (
        not isinstance(value, str)
        or len(value) > max_chars
        or _IDENTIFIER.fullmatch(value) is None
    ):
        raise ProposalError(400, f"{name} is invalid")
    return value


def _text(body: dict, name: str, *, max_chars: int) -> str:
    value = body.get(name)
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > max_chars
        or not value.isprintable()
    ):
        raise ProposalError(400, f"{name} is invalid")
    return value


def _hash(body: dict, name: str) -> str:
    value = body.get(name)
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ProposalError(400, f"{name} must be a lowercase SHA-256")
    return value


def _finite_number(body: dict, name: str, *, positive: bool = False) -> float:
    value = body.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProposalError(400, f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        qualifier = "positive " if positive else ""
        raise ProposalError(400, f"{name} must be a {qualifier}finite number")
    return number


def _optional_stop(body: dict) -> float | None:
    if body.get("stop") is None:
        return None
    return _finite_number(body, "stop", positive=True)


def _timestamp(body: dict, name: str) -> datetime:
    try:
        return iso_timestamp(body.get(name), f"{name} must be a canonical ISO timestamp")
    except ValueError as exc:
        raise ProposalError(400, str(exc)) from exc


def _evidence_ids(body: dict) -> list[str]:
    values = body.get("evidence_ids")
    if (
        not isinstance(values, list)
        or not values
        or len(values) > MAX_EVIDENCE_IDS
    ):
        raise ProposalError(400, "evidence_ids must be a nonempty bounded array")
    normalized = []
    for value in values:
        if (
            not isinstance(value, str)
            or not value.strip()
            or value != value.strip()
            or len(value) > EVIDENCE_ID_MAX_CHARS
            or not value.isprintable()
        ):
            raise ProposalError(400, "evidence_ids contains an invalid identifier")
        normalized.append(value)
    if len(set(normalized)) != len(normalized):
        raise ProposalError(400, "evidence_ids must not contain duplicates")
    return normalized


def normalize(body: dict, *, now: datetime | None = None) -> dict:
    """Strictly normalize one proposal before any database write."""
    unknown = sorted(set(body) - PROPOSAL_FIELDS)
    missing = sorted(PROPOSAL_FIELDS - set(body))
    if unknown:
        raise ProposalError(400, f"unknown proposal field(s): {', '.join(unknown)}")
    if missing:
        raise ProposalError(400, f"missing proposal field(s): {', '.join(missing)}")
    if body.get("schema_version") != SCHEMA_VERSION or isinstance(
        body.get("schema_version"), bool
    ):
        raise ProposalError(400, f"schema_version must be {SCHEMA_VERSION}")

    ticker_value = body.get("ticker")
    try:
        ticker = require_public_ticker(ticker_value)
    except ValueError as exc:
        raise ProposalError(400, "ticker is invalid") from exc
    if ticker != ticker.upper():
        raise ProposalError(400, "ticker must be canonical uppercase")

    mode = body.get("mode")
    if mode not in {"agent_only", "hybrid"}:
        raise ProposalError(400, "mode must be agent_only or hybrid")
    side = body.get("side")
    if side not in {"buy", "sell"}:
        raise ProposalError(400, "side must be buy or sell")

    signal_at = _timestamp(body, "signal_at").astimezone(timezone.utc)
    expires_at = _timestamp(body, "expires_at").astimezone(timezone.utc)
    received_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if signal_at < received_at - MAX_SIGNAL_AGE or signal_at > received_at + MAX_CLOCK_SKEW:
        raise ProposalError(400, "signal_at is outside the accepted clock window")
    if expires_at <= signal_at:
        raise ProposalError(400, "expires_at must be after signal_at")
    if expires_at <= received_at or expires_at > received_at + MAX_EXPIRY:
        raise ProposalError(400, "expires_at is outside the accepted validity window")

    confidence = _finite_number(body, "confidence")
    if not 0 <= confidence <= 1:
        raise ProposalError(400, "confidence must be between 0 and 1")

    return {
        "schema_version": SCHEMA_VERSION,
        "proposal_id": _identifier(body, "proposal_id"),
        "idempotency_key": _identifier(body, "idempotency_key"),
        "mode": mode,
        "policy_id": _identifier(body, "policy_id"),
        "policy_registration_sha256": _hash(body, "policy_registration_sha256"),
        "agent_id": _identifier(body, "agent_id"),
        "model": _text(body, "model", max_chars=MODEL_MAX_CHARS),
        "model_version": _identifier(body, "model_version"),
        "prompt_sha256": _hash(body, "prompt_sha256"),
        "toolset_sha256": _hash(body, "toolset_sha256"),
        "strategy_id": _identifier(body, "strategy_id"),
        "strategy_config_sha256": _hash(body, "strategy_config_sha256"),
        "agent_boundary_sha256": _hash(body, "agent_boundary_sha256"),
        "runtime_source_sha256": _hash(body, "runtime_source_sha256"),
        "data_snapshot_sha256": _hash(body, "data_snapshot_sha256"),
        "context_sha256": _hash(body, "context_sha256"),
        "ticker": ticker,
        "side": side,
        "max_notional": _finite_number(body, "max_notional", positive=True),
        "stop": _optional_stop(body),
        "confidence": confidence,
        "signal_at": signal_at,
        "expires_at": expires_at,
        "thesis": _text(body, "thesis", max_chars=THESIS_MAX_CHARS),
        "invalidation": _text(
            body,
            "invalidation",
            max_chars=INVALIDATION_MAX_CHARS,
        ),
        "evidence_ids": _evidence_ids(body),
    }
