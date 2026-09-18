"""Bounded operator projection for shadow decision attempts."""

from __future__ import annotations

import re
from datetime import date, datetime

import duckdb

from engine.lib.util import table_exists

from . import agent_shadow_store
from .json_utils import loads_object
from .read_model_utils import (
    require_public_nonnegative_integer,
    require_public_positive_integer,
    require_public_ticker,
    rows,
)

ATTEMPTS_LIMIT = 100
ATTEMPT_STATUSES = agent_shadow_store.TERMINAL_EVENT_TYPES | {"in_progress"}
MAX_REASON_CHARS = 512
INVOCATION_POLICY = {
    "manual": True,
    "systemd_timer": "trading-engine-agent-shadow.timer",
}
RETRY_POLICY = {
    "decision_regeneration": False,
    "completed_window_replay": True,
    "recorded_response_resume": True,
    "unrecorded_response_outcome": "uncertain",
}
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"public shadow attempt {field} is invalid")
    return value


def _hash(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"public shadow attempt {field} is invalid")
    return value


def _optional_hash(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _hash(value, field)


def _optional_identifier(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _identifier(value, field)


def _model(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > 128
        or not value.isprintable()
    ):
        raise ValueError("public shadow attempt model is invalid")
    return value


def _bounded_text(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > 128
        or not value.isprintable()
    ):
        raise ValueError(f"public shadow attempt {field} is invalid")
    return value


def _timestamp(value: object, field: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is not None:
        raise ValueError(f"public shadow attempt {field} is invalid")
    return value


def _optional_reason(value: object) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > MAX_REASON_CHARS
        or not value.isprintable()
    ):
        raise ValueError("public shadow attempt reason is invalid")
    return value


def _usage(value: object) -> dict[str, int] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "input_tokens",
        "output_tokens",
        "total_tokens",
    }:
        raise ValueError("public shadow attempt usage is invalid")
    result = {
        field: require_public_nonnegative_integer(value[field])
        for field in ("input_tokens", "output_tokens", "total_tokens")
    }
    if result["total_tokens"] != result["input_tokens"] + result["output_tokens"]:
        raise ValueError("public shadow attempt usage is inconsistent")
    return result


def _event_metadata(event_rows: list[tuple]) -> dict:
    response_id = None
    usage = None
    terminal = []
    for event_type, raw_payload, occurred_at in event_rows:
        payload = loads_object(raw_payload)
        if event_type == "model_response":
            if response_id is not None:
                raise ValueError("shadow attempt has multiple model responses")
            response_id = _bounded_text(payload.get("response_id"), "response identity")
            usage = _usage(payload.get("usage"))
        if event_type in agent_shadow_store.TERMINAL_EVENT_TYPES:
            terminal.append((event_type, payload, occurred_at))
    if len(terminal) > 1:
        raise ValueError("shadow attempt has multiple terminal events")
    if not terminal:
        return {
            "status": "in_progress",
            "completed_at": None,
            "response_id": response_id,
            "usage": usage,
            "reason": None,
            "proposal_record_id": None,
            "proposal_status": None,
        }
    event_type, payload, completed_at = terminal[0]
    result = payload.get("result")
    if not isinstance(result, dict) or result.get("status") is None:
        raise ValueError("shadow terminal event result is invalid")
    proposal = result.get("proposal_result")
    if proposal is not None and not isinstance(proposal, dict):
        raise ValueError("shadow terminal proposal result is invalid")
    proposal_record_id = None
    proposal_status = None
    if proposal is not None and event_type == "proposal_result":
        proposal_record_id = require_public_positive_integer(
            proposal.get("proposal_record_id")
        )
        proposal_status = proposal.get("status")
        if proposal_status not in {"shadow_accepted", "shadow_rejected"}:
            raise ValueError("shadow terminal proposal status is invalid")
    if response_id is None and payload.get("response_id") is not None:
        response_id = _bounded_text(payload.get("response_id"), "response identity")
    if usage is None and payload.get("usage") is not None:
        usage = _usage(payload.get("usage"))
    return {
        "status": event_type,
        "completed_at": _timestamp(completed_at, "completion time"),
        "response_id": response_id,
        "usage": usage,
        "reason": _optional_reason(result.get("reason")),
        "proposal_record_id": proposal_record_id,
        "proposal_status": proposal_status,
    }


def _attempt(con: duckdb.DuckDBPyConnection, row: dict) -> dict:
    attempt_id = require_public_positive_integer(row["id"])
    event_rows = con.execute(
        "SELECT event_type, payload, occurred_at FROM agent_shadow_events "
        "WHERE attempt_id = ? ORDER BY id",
        [attempt_id],
    ).fetchall()
    metadata = _event_metadata(event_rows)
    result = {
        "id": attempt_id,
        "decision_window": _identifier(row["decision_window"], "decision window"),
        "mode": row["mode"],
        "policy_id": (
            "legacy_unregistered"
            if row["policy_id"] is None
            else _identifier(row["policy_id"], "policy identity")
        ),
        "policy_registration_sha256": _optional_hash(
            row["policy_registration_sha256"],
            "policy registration identity",
        ),
        "strategy_id": _identifier(row["strategy_id"], "strategy identity"),
        "ticker": require_public_ticker(row["ticker"]),
        "market_date": row["market_date"],
        "context_sha256": _optional_hash(row["context_sha256"], "context identity"),
        "model": None if row["model"] is None else _model(row["model"]),
        "model_version": _optional_identifier(row["model_version"], "model version"),
        "request_sha256": _optional_hash(row["request_sha256"], "request identity"),
        "started_at": _timestamp(row["started_at"], "start time"),
        **metadata,
    }
    if result["mode"] not in {"agent_only", "hybrid"} or type(
        result["market_date"]
    ) is not date:
        raise ValueError("public shadow attempt registration is invalid")
    if result["policy_id"] == "legacy_unregistered":
        if result["policy_registration_sha256"] is not None:
            raise ValueError("public shadow attempt legacy policy identity is invalid")
    elif result["policy_registration_sha256"] is None:
        raise ValueError("public shadow attempt policy identity is invalid")
    if result["status"] == "cadence_no_action":
        if any(
            result[field] is not None
            for field in ("context_sha256", "model", "model_version", "request_sha256")
        ):
            raise ValueError("public cadence no-action attempt has model metadata")
    elif result["status"] == "hybrid_no_veto_candidate":
        if (
            result["context_sha256"] is None
            or result["model"] is None
            or result["model_version"] is None
            or result["request_sha256"] is not None
        ):
            raise ValueError("public deterministic hybrid attempt metadata is invalid")
    elif any(
        result[field] is None
        for field in ("context_sha256", "model", "model_version", "request_sha256")
    ):
        raise ValueError("public model attempt metadata is incomplete")
    if result["status"] not in ATTEMPT_STATUSES:
        raise ValueError("public shadow attempt status is invalid")
    return result


def attempts(con: duckdb.DuckDBPyConnection) -> dict:
    """Return newest attempts without retained context, prompt, or model output."""
    if not table_exists(con, "agent_shadow_attempts") or not table_exists(
        con, "agent_shadow_events"
    ):
        return {
            "execution_authority": "none",
            "invocation": INVOCATION_POLICY,
            "retry_policy": RETRY_POLICY,
            "limit": ATTEMPTS_LIMIT,
            "matching_count": 0,
            "truncated": False,
            "attempts": [],
        }
    attempt_rows = rows(
        con.execute(
            "SELECT id, decision_window, mode, strategy_id, ticker, market_date, "
            "context_sha256, model, model_version, request_sha256, started_at, "
            "policy_id, policy_registration_sha256, "
            "COUNT(*) OVER () AS _matching_count "
            "FROM agent_shadow_attempts ORDER BY id DESC LIMIT ?",
            [ATTEMPTS_LIMIT],
        )
    )
    matching_count = (
        require_public_nonnegative_integer(attempt_rows[0].pop("_matching_count"))
        if attempt_rows
        else 0
    )
    for row in attempt_rows[1:]:
        row.pop("_matching_count")
    projected = [_attempt(con, row) for row in attempt_rows]
    return {
        "execution_authority": "none",
        "invocation": INVOCATION_POLICY,
        "retry_policy": RETRY_POLICY,
        "limit": ATTEMPTS_LIMIT,
        "matching_count": matching_count,
        "truncated": matching_count > len(projected),
        "attempts": projected,
    }
