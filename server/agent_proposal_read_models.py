"""Bounded, read-only projection of the shadow agent proposal ledger."""

from __future__ import annotations

import re
from datetime import datetime

import duckdb

from engine.lib.util import table_exists

from . import agent_proposal_validation
from .json_utils import loads_strict
from .read_model_utils import (
    require_public_nonnegative_integer,
    require_public_positive_integer,
    require_public_positive_number,
    require_public_ticker,
    rows,
)

PROPOSALS_LIMIT = 100
PROPOSAL_STATUSES = frozenset({"shadow_accepted", "shadow_rejected"})
PROPOSAL_MODES = frozenset({"agent_only", "hybrid"})
PROPOSAL_SIDES = frozenset({"buy", "sell"})
MAX_PUBLIC_REASONS = 16
MAX_PUBLIC_REASON_CHARS = 512
MAX_STORED_REASONS_CHARS = 16_384
MAX_STORED_VALIDATION_CHARS = 131_072
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
PROJECTION_FIELDS = frozenset(
    {
        "status",
        "validation_scope",
        "execution_authority",
        "limit",
        "matching_count",
        "truncated",
        "proposals",
    }
)
PROPOSAL_FIELDS = frozenset(
    {
        "id",
        "proposal_id",
        "mode",
        "policy_id",
        "policy_registration_sha256",
        "agent_id",
        "model",
        "model_version",
        "strategy_id",
        "ticker",
        "side",
        "max_notional",
        "signal_at",
        "expires_at",
        "status",
        "context_sha256",
        "validated_context_sha256",
        "validation_status",
        "validation_sha256",
        "reasons",
        "received_at",
    }
)


def _require_identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"public agent proposal {field} is invalid")
    return value


def _require_model(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > 128
        or not value.isprintable()
    ):
        raise ValueError("public agent proposal model is invalid")
    return value


def _require_sha256(value: object, field: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"public agent proposal {field} is invalid")
    return value


def _reasons(value: object) -> list[str]:
    if not isinstance(value, str) or len(value) > MAX_STORED_REASONS_CHARS:
        raise ValueError("stored agent proposal reasons are invalid")
    try:
        reasons = loads_strict(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("stored agent proposal reasons are invalid") from exc
    if (
        not isinstance(reasons, list)
        or len(reasons) > MAX_PUBLIC_REASONS
        or not all(
            isinstance(reason, str)
            and reason.strip()
            and reason == reason.strip()
            and len(reason) <= MAX_PUBLIC_REASON_CHARS
            and reason.isprintable()
            for reason in reasons
        )
    ):
        raise ValueError("stored agent proposal reasons are invalid")
    return reasons


def _validation(
    payload: object,
    stored_sha256: object,
    *,
    policy_id: object,
    policy_registration_sha256: object,
    context_sha256: object,
    status: str,
    reasons: list[str],
) -> tuple[str, str | None]:
    if payload is None and stored_sha256 is None:
        return ("legacy_unvalidated" if status == "shadow_accepted" else "not_run", None)
    if (
        not isinstance(payload, str)
        or len(payload) > MAX_STORED_VALIDATION_CHARS
        or not isinstance(stored_sha256, str)
        or _SHA256.fullmatch(stored_sha256) is None
    ):
        raise ValueError("stored agent proposal validation is invalid")
    try:
        evidence = agent_proposal_validation.verify_binding(
            loads_strict(payload),
            validation_sha256=stored_sha256,
            policy_id=policy_id,
            policy_registration_sha256=policy_registration_sha256,
            context_sha256=context_sha256,
            proposal_status=status,
            reasons=reasons,
        )
    except (TypeError, ValueError, agent_proposal_validation.ValidationError) as exc:
        raise ValueError("stored agent proposal validation is invalid") from exc
    return evidence["status"], stored_sha256


def _validate_proposal(proposal: dict, requested_status: str | None) -> int:
    if not isinstance(proposal, dict) or set(proposal) != PROPOSAL_FIELDS:
        raise ValueError("public agent proposal shape is invalid")
    record_id = require_public_positive_integer(proposal["id"])
    _require_identifier(proposal["proposal_id"], "identifier")
    if proposal["mode"] not in PROPOSAL_MODES:
        raise ValueError("public agent proposal mode is invalid")
    if proposal["policy_id"] is None:
        if proposal["policy_registration_sha256"] is not None:
            raise ValueError("public legacy proposal policy identity is invalid")
        proposal["policy_id"] = "legacy_unregistered"
    else:
        _require_identifier(proposal["policy_id"], "policy identity")
        _require_sha256(
            proposal["policy_registration_sha256"],
            "policy registration identity",
        )
    _require_identifier(proposal["agent_id"], "agent identity")
    _require_model(proposal["model"])
    _require_identifier(proposal["model_version"], "model version")
    _require_identifier(proposal["strategy_id"], "strategy identity")
    require_public_ticker(proposal["ticker"])
    if proposal["side"] not in PROPOSAL_SIDES:
        raise ValueError("public agent proposal side is invalid")
    require_public_positive_number(proposal["max_notional"], "agent proposal notional")
    if (
        type(proposal["signal_at"]) is not datetime
        or proposal["signal_at"].tzinfo is not None
        or type(proposal["expires_at"]) is not datetime
        or proposal["expires_at"].tzinfo is not None
        or proposal["expires_at"] <= proposal["signal_at"]
        or type(proposal["received_at"]) is not datetime
        or proposal["received_at"].tzinfo is not None
    ):
        raise ValueError("public agent proposal timestamp is invalid")
    status = proposal["status"]
    if status not in PROPOSAL_STATUSES or (
        requested_status is not None and status != requested_status
    ):
        raise ValueError("public agent proposal status is invalid")
    context_sha256 = _require_sha256(proposal["context_sha256"], "context identity")
    validated_context_sha256 = _require_sha256(
        proposal["validated_context_sha256"],
        "validated context identity",
        optional=True,
    )
    reasons = proposal["reasons"]
    validation_status = proposal["validation_status"]
    validation_sha256 = _require_sha256(
        proposal["validation_sha256"],
        "validation identity",
        optional=True,
    )
    if (
        not isinstance(reasons, list)
        or status == "shadow_accepted"
        and (
            reasons
            or validated_context_sha256 != context_sha256
            or validation_status not in {"pass", "legacy_unvalidated"}
        )
        or status == "shadow_rejected"
        and not reasons
        or validation_status == "pass"
        and status != "shadow_accepted"
        or validation_status in {"fail", "not_run"}
        and status != "shadow_rejected"
        or validation_status in {"pass", "fail"}
        and validation_sha256 is None
        or validation_status in {"not_run", "legacy_unvalidated"}
        and validation_sha256 is not None
    ):
        raise ValueError("public agent proposal validation result is invalid")
    return record_id


def _validate_projection(payload: dict, requested_status: str | None) -> None:
    if not isinstance(payload, dict) or set(payload) != PROJECTION_FIELDS:
        raise ValueError("public agent proposal projection shape is invalid")
    if (
        payload["status"] != requested_status
        or payload["validation_scope"]
        != agent_proposal_validation.VALIDATION_SCOPE
        or payload["execution_authority"] != "none"
    ):
        raise ValueError("public agent proposal projection authority is invalid")
    limit = require_public_positive_integer(payload["limit"])
    matching_count = require_public_nonnegative_integer(payload["matching_count"])
    proposals = payload["proposals"]
    if (
        limit != PROPOSALS_LIMIT
        or not isinstance(proposals, list)
        or len(proposals) != min(matching_count, limit)
        or type(payload["truncated"]) is not bool
        or payload["truncated"] != (matching_count > len(proposals))
    ):
        raise ValueError("public agent proposal collection is inconsistent")
    seen_ids = set()
    previous_id = None
    for proposal in proposals:
        record_id = _validate_proposal(proposal, requested_status)
        if record_id in seen_ids:
            raise ValueError("public agent proposal identifier is duplicated")
        if previous_id is not None and record_id >= previous_id:
            raise ValueError("public agent proposals are not ordered")
        seen_ids.add(record_id)
        previous_id = record_id


def _payload(status: str | None, proposal_rows: list[dict]) -> dict:
    if status is not None and status not in PROPOSAL_STATUSES:
        raise ValueError("public agent proposal filter status is invalid")
    matching_count = (
        require_public_nonnegative_integer(proposal_rows[0].pop("_matching_count"))
        if proposal_rows
        else 0
    )
    for proposal in proposal_rows[1:]:
        proposal.pop("_matching_count")
    for proposal in proposal_rows:
        proposal["reasons"] = _reasons(proposal["reasons"])
        proposal["validation_status"], proposal["validation_sha256"] = _validation(
            proposal.pop("_validation_payload"),
            proposal["validation_sha256"],
            policy_id=proposal["policy_id"],
            policy_registration_sha256=proposal["policy_registration_sha256"],
            context_sha256=proposal["validated_context_sha256"],
            status=proposal["status"],
            reasons=proposal["reasons"],
        )
    payload = {
        "status": status,
        "validation_scope": agent_proposal_validation.VALIDATION_SCOPE,
        "execution_authority": "none",
        "limit": PROPOSALS_LIMIT,
        "matching_count": matching_count,
        "truncated": matching_count > PROPOSALS_LIMIT,
        "proposals": proposal_rows,
    }
    _validate_projection(payload, status)
    return payload


def _proposal_rows(
    con: duckdb.DuckDBPyConnection,
    status: str | None,
) -> list[dict]:
    status_clause = "WHERE status = ?" if status else ""
    parameters = [status] if status else []
    cursor = con.execute(
        "SELECT id, proposal_id, mode, policy_id, policy_registration_sha256, "
        "agent_id, model, model_version, strategy_id, "
        "ticker, side, max_notional, signal_at, expires_at, status, context_sha256, "
        "validated_context_sha256, validation_sha256, "
        "validation_payload AS _validation_payload, reasons, received_at, "
        f"COUNT(*) OVER () AS _matching_count FROM agent_proposals {status_clause} "
        "ORDER BY id DESC LIMIT ?",
        [*parameters, PROPOSALS_LIMIT],
    )
    return rows(cursor)


def proposals(con: duckdb.DuckDBPyConnection, status: str | None) -> dict:
    """Return the newest shadow proposal records without internal payload fields."""
    if status is not None and status not in PROPOSAL_STATUSES:
        raise ValueError("public agent proposal filter status is invalid")
    if not table_exists(con, "agent_proposals"):
        return _payload(status, [])
    return _payload(status, _proposal_rows(con, status))
