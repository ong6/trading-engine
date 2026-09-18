"""Transactional admission for shadow-only agent trade proposals."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256
from engine.lib.settings import REPO_ROOT

from . import agent_context, agent_contract, agent_proposal_validation, agent_store
from .json_utils import loads_strict
from .read_model_utils import require_public_positive_integer

RESPONSE_FIELDS = frozenset(
    {
        "proposal_record_id",
        "proposal_id",
        "status",
        "validation_scope",
        "validation_status",
        "validation_sha256",
        "execution_authority",
        "context_sha256",
        "validated_context_sha256",
        "reasons",
        "replayed",
    }
)
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_PUBLIC_REASONS = 16
MAX_PUBLIC_REASON_CHARS = 512


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _result(
    record_id: int,
    proposal_id: str,
    status: str,
    context_sha256: str,
    validated_context_sha256: str | None,
    validation_status: str,
    validation_sha256: str | None,
    reasons: list[str],
    *,
    replayed: bool,
) -> dict:
    result = {
        "proposal_record_id": record_id,
        "proposal_id": proposal_id,
        "status": status,
        "validation_scope": "deterministic_shadow_recomputation_and_risk",
        "validation_status": validation_status,
        "validation_sha256": validation_sha256,
        "execution_authority": "none",
        "context_sha256": context_sha256,
        "validated_context_sha256": validated_context_sha256,
        "reasons": reasons,
        "replayed": replayed,
    }
    _validate_result(result)
    return result


def _validate_result(result: dict) -> None:
    if not isinstance(result, dict) or set(result) != RESPONSE_FIELDS:
        raise ValueError("public agent proposal result shape is invalid")
    require_public_positive_integer(result.get("proposal_record_id"))
    proposal_id = result.get("proposal_id")
    if not isinstance(proposal_id, str) or _IDENTIFIER.fullmatch(proposal_id) is None:
        raise ValueError("public agent proposal identifier is invalid")
    if result.get("status") not in {"shadow_accepted", "shadow_rejected"}:
        raise ValueError("public agent proposal status is invalid")
    if (
        result.get("validation_scope")
        != "deterministic_shadow_recomputation_and_risk"
    ):
        raise ValueError("public agent validation scope is invalid")
    validation_status = result.get("validation_status")
    if validation_status not in {"pass", "fail", "not_run", "legacy_unvalidated"}:
        raise ValueError("public agent validation status is invalid")
    validation_sha256 = result.get("validation_sha256")
    if validation_status in {"pass", "fail"}:
        if (
            not isinstance(validation_sha256, str)
            or _SHA256.fullmatch(validation_sha256) is None
        ):
            raise ValueError("public agent validation identity is invalid")
    elif validation_sha256 is not None:
        raise ValueError("public agent validation identity is invalid")
    if result.get("execution_authority") != "none":
        raise ValueError("public agent execution authority is invalid")
    context_sha256 = result.get("context_sha256")
    if not isinstance(context_sha256, str) or _SHA256.fullmatch(context_sha256) is None:
        raise ValueError("public agent context identity is invalid")
    validated_context_sha256 = result.get("validated_context_sha256")
    if validated_context_sha256 is not None and (
        not isinstance(validated_context_sha256, str)
        or _SHA256.fullmatch(validated_context_sha256) is None
    ):
        raise ValueError("public agent validated context identity is invalid")
    if type(result.get("replayed")) is not bool:
        raise ValueError("public agent replay flag is invalid")
    if (
        not isinstance(result.get("reasons"), list)
        or len(result["reasons"]) > MAX_PUBLIC_REASONS
        or not all(
            isinstance(reason, str)
            and reason.strip()
            and len(reason) <= MAX_PUBLIC_REASON_CHARS
            for reason in result["reasons"]
        )
    ):
        raise ValueError("public agent proposal reasons are invalid")
    if result["status"] == "shadow_accepted" and result["reasons"]:
        raise ValueError("accepted shadow proposal cannot have rejection reasons")
    if result["status"] == "shadow_rejected" and not result["reasons"]:
        raise ValueError("rejected shadow proposal must have a reason")
    if result["status"] == "shadow_accepted" and validation_status not in {
        "pass",
        "legacy_unvalidated",
    }:
        raise ValueError("accepted shadow proposal requires passing validation")
    if result["status"] == "shadow_rejected" and validation_status == "pass":
        raise ValueError("rejected shadow proposal cannot have passing validation")


def _context_reasons(proposal: dict, context: dict | None, error: Exception | None) -> list[str]:
    if error is not None:
        return [str(error)]
    if context is None:
        raise ValueError("validated agent context is unavailable")
    expected = {
        "mode": context["policy"]["mode"],
        "model": context["decision_model"]["model"],
        "model_version": context["decision_model"]["model_version"],
        "prompt_sha256": context["decision_model"]["instructions_sha256"],
        "toolset_sha256": context["decision_model"]["toolset_sha256"],
        "context_sha256": context["context_sha256"],
        "policy_id": context["policy"]["id"],
        "policy_registration_sha256": context["policy"]["registration_sha256"],
        "strategy_config_sha256": context["strategy"]["config_sha256"],
        "agent_boundary_sha256": context["provenance"]["agent_boundary_sha256"],
        "runtime_source_sha256": context["provenance"]["runtime_source_sha256"],
        "data_snapshot_sha256": context["provenance"]["data_snapshot_sha256"],
    }
    reasons = [
        f"{field} does not match current server context"
        for field, value in expected.items()
        if proposal[field] != value
    ]
    if context["policy"]["generation_enabled"] is not True:
        reasons.append("agent policy generation is disabled")
    if context["policy"]["mode"] == "hybrid":
        reasons.append("hybrid policy requires the veto-only decision boundary")
    return reasons


def _proposal_sha256(proposal: dict) -> str:
    identity = {
        **proposal,
        "signal_at": proposal["signal_at"].isoformat(),
        "expires_at": proposal["expires_at"].isoformat(),
    }
    return canonical_sha256(identity)


def _existing_result(
    rows: list[tuple],
    proposal: dict,
    proposal_sha256: str,
) -> dict | None:
    if not rows:
        return None
    exact = [
        row
        for row in rows
        if row[1] == proposal["proposal_id"] and row[2] == proposal["idempotency_key"]
    ]
    if len(rows) != 1 or len(exact) != 1 or exact[0][3] != proposal_sha256:
        raise agent_contract.ProposalError(
            409,
            "proposal_id or idempotency_key was already used by a different proposal",
        )
    row = exact[0]
    reasons = loads_strict(row[6])
    if not isinstance(reasons, list):
        raise ValueError("stored agent proposal reasons are invalid")
    validation = None if row[9] is None else loads_strict(row[9])
    if row[8] is not None:
        try:
            validation = agent_proposal_validation.verify_binding(
                validation,
                validation_sha256=row[8],
                policy_id=row[10],
                policy_registration_sha256=row[11],
                context_sha256=row[7],
                proposal_status=row[4],
                reasons=reasons,
            )
        except agent_proposal_validation.ValidationError as exc:
            raise ValueError("stored agent proposal validation is invalid") from exc
    elif validation is not None:
        raise ValueError("stored agent proposal validation identity is invalid")
    return _result(
        int(row[0]),
        row[1],
        row[4],
        row[5],
        row[7],
        (
            "legacy_unvalidated"
            if validation is None and row[4] == "shadow_accepted"
            else "not_run"
            if validation is None
            else validation["status"]
        ),
        row[8],
        reasons,
        replayed=True,
    )


def _audit(
    con: duckdb.DuckDBPyConnection,
    proposal: dict,
    result: dict,
    received_at: datetime,
) -> None:
    con.execute(
        "INSERT INTO audit_log (ts, actor, action, payload) VALUES (?, ?, ?, ?)",
        [
            received_at,
            f"agent:{proposal['agent_id']}",
            "agent_proposal_shadow",
            json.dumps(result, sort_keys=True, separators=(",", ":")),
        ],
    )


def submit(
    con: duckdb.DuckDBPyConnection,
    body: dict,
    *,
    now: datetime | None = None,
    repo_root: Path = REPO_ROOT,
) -> dict:
    """Validate and append one shadow proposal without creating an order."""
    received_at = (now or _now()).astimezone(timezone.utc)
    proposal = agent_contract.normalize(body, now=received_at)
    proposal_sha256 = _proposal_sha256(proposal)
    agent_store.init_schema(con)
    try:
        with engine_db.transaction(con):
            replay = _existing_result(
                agent_store.existing(
                    con,
                    proposal["proposal_id"],
                    proposal["idempotency_key"],
                ),
                proposal,
                proposal_sha256,
            )
            if replay is not None:
                return replay

            context = None
            context_error = None
            try:
                context = agent_context.build(
                    con,
                    proposal["strategy_id"],
                    proposal["ticker"],
                    policy_id=proposal["policy_id"],
                    repo_root=repo_root,
                )
            except agent_context.ContextError as exc:
                context_error = exc
            reasons = _context_reasons(proposal, context, context_error)
            validated_context_sha256 = (
                None if context is None else context["context_sha256"]
            )
            validation = None
            validation_status = "not_run"
            validation_sha256 = None
            if not reasons:
                if context is None:
                    raise ValueError("validated agent context is unavailable")
                try:
                    validation = agent_proposal_validation.evaluate(
                        con,
                        proposal,
                        context,
                    )
                except agent_proposal_validation.ValidationError as exc:
                    reasons.append(f"deterministic validation unavailable: {exc}")
                else:
                    validation_status = validation["status"]
                    validation_sha256 = validation["validation_sha256"]
                    reasons.extend(validation["failed_gates"])
            status = (
                "shadow_accepted"
                if not reasons and validation_status == "pass"
                else "shadow_rejected"
            )
            record_id = agent_store.insert(
                con,
                proposal,
                proposal_sha256=proposal_sha256,
                validated_context_sha256=validated_context_sha256,
                validated_context=context,
                validation_sha256=validation_sha256,
                validation_payload=validation,
                status=status,
                reasons=reasons,
                received_at=received_at,
            )
            result = _result(
                record_id,
                proposal["proposal_id"],
                status,
                proposal["context_sha256"],
                validated_context_sha256,
                validation_status,
                validation_sha256,
                reasons,
                replayed=False,
            )
            _audit(con, proposal, result, received_at)
            return result
    except agent_store.IdentifierSpaceExhausted as exc:
        raise agent_contract.ProposalError(
            503,
            "agent proposal identifier space exhausted",
        ) from exc
