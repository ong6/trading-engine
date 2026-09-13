"""Closed HTTP shape and normalization rules for discretionary tickets."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from .read_model_utils import PUBLIC_TICKER_MAX_CHARS, require_public_ticker

TICKET_FIELDS = frozenset(
    {
        "ticker",
        "side",
        "qty",
        "entry_ref",
        "stop",
        "target",
        "playbook",
        "emotion",
        "notes",
        "acknowledge_earnings",
        "override_regime",
        "override_reason",
    }
)
TICKER_MAX_CHARS = PUBLIC_TICKER_MAX_CHARS
PLAYBOOK_MAX_CHARS = 128
EMOTION_MAX_CHARS = 32
NOTES_MAX_CHARS = 4_096
OVERRIDE_REASON_MAX_CHARS = 512


@dataclass(frozen=True, slots=True)
class TicketRequest:
    """Closed HTTP shape; ``object`` fields preserve raw types for domain validation."""

    __pydantic_config__ = {"extra": "forbid"}

    ticker: str = field(metadata={"max_length": TICKER_MAX_CHARS})
    qty: object
    side: Literal["buy", "sell"] = "buy"
    entry_ref: object = None
    stop: object = None
    target: object = None
    playbook: str | None = field(
        default=None, metadata={"max_length": PLAYBOOK_MAX_CHARS}
    )
    emotion: str | None = field(
        default=None, metadata={"max_length": EMOTION_MAX_CHARS}
    )
    notes: str | None = field(default=None, metadata={"max_length": NOTES_MAX_CHARS})
    acknowledge_earnings: object = False
    override_regime: object = False
    override_reason: str | None = field(
        default=None, metadata={"max_length": OVERRIDE_REASON_MAX_CHARS}
    )


class TicketError(Exception):
    """A client-visible ticket rejection with an HTTP-compatible status code."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _required_text(body: dict, field: str, *, max_chars: int) -> str:
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        raise TicketError(400, f"{field} required")
    normalized = value.strip()
    if len(normalized) > max_chars:
        raise TicketError(400, f"{field} must be at most {max_chars} characters")
    return normalized


def _optional_text(body: dict, field: str, *, max_chars: int) -> str | None:
    value = body.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TicketError(400, f"{field} must be text")
    if len(value) > max_chars:
        raise TicketError(400, f"{field} must be at most {max_chars} characters")
    return value


def _positive_quantity(body: dict) -> float:
    value = body.get("qty")
    if isinstance(value, bool):
        raise TicketError(400, "qty must be a number")
    try:
        quantity = float(value or 0)
    except (TypeError, ValueError) as exc:
        raise TicketError(400, "qty must be a number") from exc
    if not math.isfinite(quantity) or quantity <= 0:
        raise TicketError(400, "qty must be a positive number")
    return quantity


def _optional_number(body: dict, field: str) -> float | None:
    value = body.get(field)
    if value is None:
        return None
    if isinstance(value, bool):
        raise TicketError(400, f"{field} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise TicketError(400, f"{field} must be a positive finite number") from exc
    if not math.isfinite(number) or number <= 0:
        raise TicketError(400, f"{field} must be a positive finite number")
    return number


def _optional_boolean(body: dict, field: str) -> bool:
    value = body.get(field, False)
    if not isinstance(value, bool):
        raise TicketError(400, f"{field} must be a boolean")
    return value


def normalize(body: dict) -> dict:
    """Validate and normalize one raw discretionary-ticket payload."""
    unknown_fields = sorted(set(body) - TICKET_FIELDS)
    if unknown_fields:
        raise TicketError(400, f"unknown ticket field(s): {', '.join(unknown_fields)}")
    ticker = _required_text(body, "ticker", max_chars=TICKER_MAX_CHARS).upper()
    try:
        ticker = require_public_ticker(ticker)
    except ValueError as exc:
        raise TicketError(400, "ticker is invalid") from exc
    side_value = body.get("side", "buy")
    if not isinstance(side_value, str):
        raise TicketError(400, "side must be 'buy' or 'sell'")
    side = side_value.lower().strip()
    if side not in {"buy", "sell"}:
        raise TicketError(400, "side must be 'buy' or 'sell'")
    return {
        "ticker": ticker,
        "side": side,
        "qty": _positive_quantity(body),
        "entry_ref": _optional_number(body, "entry_ref"),
        "stop": _optional_number(body, "stop"),
        "target": _optional_number(body, "target"),
        "playbook": _optional_text(body, "playbook", max_chars=PLAYBOOK_MAX_CHARS),
        "emotion": _optional_text(body, "emotion", max_chars=EMOTION_MAX_CHARS),
        "notes": _optional_text(body, "notes", max_chars=NOTES_MAX_CHARS),
        "acknowledge_earnings": _optional_boolean(body, "acknowledge_earnings"),
        "override_regime": _optional_boolean(body, "override_regime"),
        "override_reason": _optional_text(
            body,
            "override_reason",
            max_chars=OVERRIDE_REASON_MAX_CHARS,
        ),
    }
