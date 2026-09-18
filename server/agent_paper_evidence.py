"""Read-only verification of retained agent-only evidence for future paper use.

The loader joins one completed shadow decision window to its accepted proposal,
retained context, model request/response, and deterministic validation. It
derives ``PaperIntentBindings`` from those rows instead of accepting a caller-
selected trust hash. It does not issue a lease, mutate state, or grant
submission authority.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone

import duckdb

from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists

from . import (
    agent_context,
    agent_contract,
    agent_decision_contract,
    agent_model_client,
    agent_policy,
    agent_proposal_validation,
    agent_veto_contract,
)
from .broker_contract import SubmitOrderRequest, require_identifier
from .broker_paper_intent import HybridPaperIntentBindings, PaperIntentBindings
from .json_utils import loads_object, loads_strict

EVIDENCE_SCHEMA_VERSION = 2
MAX_EVENT_ROWS = 8
MAX_RESULT_REASON_CHARS = 512


class AgentPaperEvidenceError(ValueError):
    """Retained agent-only evidence is absent, ambiguous, or inconsistent."""


@dataclass(frozen=True, slots=True)
class LoadedAgentPaperIntent:
    """Verified retained evidence bound to one caller-owned broker request."""

    request: SubmitOrderRequest
    bindings: PaperIntentBindings
    signal_close: float
    request_notional: float
    stop: float | None
    confidence: float
    thesis: str
    invalidation: str
    attempt_id: int
    proposal_record_id: int
    terminal_event_sha256: str
    evidence_observed_at: datetime
    evidence_sha256: str
    execution_authority: str = "none"


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _utc(value: object, label: str) -> datetime:
    if type(value) is not datetime:
        raise AgentPaperEvidenceError(f"{label} is invalid")
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    if aware.utcoffset() is None or aware.utcoffset().total_seconds() != 0:
        raise AgentPaperEvidenceError(f"{label} is invalid")
    return aware.astimezone(timezone.utc)


def _context(value: object, *, expected_mode: str) -> dict:
    try:
        context = loads_object(value)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise AgentPaperEvidenceError("retained agent context is invalid") from exc
    context_sha256 = context.get("context_sha256")
    body = {key: item for key, item in context.items() if key != "context_sha256"}
    policy = context.get("policy")
    strategy = context.get("strategy")
    instrument = context.get("instrument")
    provenance = context.get("provenance")
    model = context.get("decision_model")
    if (
        context.get("schema_version") != agent_context.CONTEXT_SCHEMA_VERSION
        or context.get("mode") != "shadow"
        or context.get("execution_authority") != "none"
        or canonical_sha256(body) != context_sha256
        or not isinstance(policy, dict)
        or policy.get("mode") != expected_mode
        or policy.get("authority_stage") != "shadow_proposal_only"
        or policy.get("execution_authority") != "none"
        or not isinstance(strategy, dict)
        or not isinstance(instrument, dict)
        or not isinstance(provenance, dict)
        or not isinstance(model, dict)
        or (
            expected_mode == "agent_only"
            and context.get("algorithm_candidate") is not None
        )
        or (
            expected_mode == "hybrid"
            and not isinstance(context.get("algorithm_candidate"), dict)
        )
    ):
        raise AgentPaperEvidenceError("retained agent context is invalid")
    return context


def _allowlisted_evidence(context: dict) -> frozenset[str]:
    result = {context["context_sha256"]}
    pending = [context]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            for key, item in value.items():
                if key.endswith("_sha256") and isinstance(item, str) and len(item) == 64:
                    result.add(item)
                pending.append(item)
        elif isinstance(value, list):
            pending.extend(value)
    return frozenset(result)


def _verify_model_response(
    response: object,
    *,
    context: dict,
    request_sha256: str,
) -> dict:
    if (
        not isinstance(response, dict)
        or set(response)
        != {
            "output",
            "response_id",
            "model",
            "model_version",
            "proxy_version",
            "traecli_runtime",
            "model_catalog_entry_sha256",
            "request_sha256",
            "usage",
        }
        or response["model"] != context["decision_model"]["model"]
        or response["model_version"] != context["decision_model"]["model_version"]
        or response["proxy_version"]
        != context["decision_model"]["required_proxy_version"]
        or response["traecli_runtime"]
        != context["decision_model"]["required_traecli_runtime"]
        or response["model_catalog_entry_sha256"]
        != context["decision_model"]["model_catalog_entry_sha256"]
        or response["request_sha256"] != request_sha256
        or not isinstance(response["response_id"], str)
        or not response["response_id"]
        or len(response["response_id"]) > 128
        or not response["response_id"].isprintable()
        or not isinstance(response["usage"], dict)
        or set(response["usage"])
        != {"input_tokens", "output_tokens", "total_tokens"}
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in response["usage"].values()
        )
        or response["usage"]["total_tokens"]
        != response["usage"]["input_tokens"] + response["usage"]["output_tokens"]
    ):
        raise AgentPaperEvidenceError("retained agent model response is invalid")
    return response


def _attempt(
    con: duckdb.DuckDBPyConnection,
    decision_window_id: str,
    *,
    expected_mode: str,
) -> tuple[dict, dict, dict, datetime]:
    cursor = con.execute(
        "SELECT id, decision_window, schema_version, mode, policy_id, "
        "policy_registration_sha256, agent_id, strategy_id, ticker, market_date, "
        "context_sha256, context_payload, model_input, model_request, request_sha256, "
        "model, model_version, prompt_sha256, toolset_sha256, "
        "required_proxy_version, execution_authority, started_at "
        "FROM agent_shadow_attempts WHERE decision_window = ?",
        [decision_window_id],
    )
    row = cursor.fetchone()
    if row is None or cursor.fetchone() is not None:
        raise AgentPaperEvidenceError("agent decision window is unavailable or ambiguous")
    stored = dict(zip((item[0] for item in cursor.description), row, strict=True))
    try:
        context = _context(stored["context_payload"], expected_mode=expected_mode)
        model_input = loads_object(stored["model_input"])
        model_request = loads_object(stored["model_request"])
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        if isinstance(exc, AgentPaperEvidenceError):
            raise
        raise AgentPaperEvidenceError("retained agent request is invalid") from exc
    policy = context["policy"]
    strategy = context["strategy"]
    instrument = context["instrument"]
    model = context["decision_model"]
    try:
        registered_policy = agent_policy.get(policy["id"])
    except agent_policy.PolicyError as exc:
        raise AgentPaperEvidenceError(
            "retained agent policy is no longer registered"
        ) from exc
    expected_policy = {
        "id": registered_policy["id"],
        "registration_sha256": registered_policy["registration_sha256"],
        "registry_sha256": registered_policy["registry_sha256"],
        "mode": registered_policy["mode"],
        "authority_stage": registered_policy["authority_stage"],
        "reserved_portfolio_id": registered_policy["reserved_portfolio_id"],
        "control_id": registered_policy["control_id"],
        "cadence": registered_policy["cadence"],
        "model_role": registered_policy["model_role"],
        "model_failure_policy": registered_policy["model_failure_policy"],
        "hybrid_behavior": registered_policy["hybrid_behavior"],
        "allowed_symbols": registered_policy["allowed_symbols"],
        "capital_ceiling": registered_policy["capital_ceiling"],
        "max_order_notional": registered_policy["max_order_notional"],
        "execution_profile_id": registered_policy["execution_profile_id"],
        "execution_profile_sha256": registered_policy["execution_profile_sha256"],
        "attribution": registered_policy["attribution"],
        "generation_enabled": registered_policy["generation_enabled"],
        "execution_authority": "none",
    }
    role = "proposal" if expected_mode == "agent_only" else "veto"
    expected_input = {
        "schema_version": 2,
        "task": (
            "choose exactly one shadow decision under the supplied output contract"
            if expected_mode == "agent_only"
            else "allow or veto the exact deterministic candidate"
        ),
        "requested_mode": expected_mode,
        "policy_id": policy["id"],
        "policy_registration_sha256": policy["registration_sha256"],
        "model_role": policy["model_role"],
        "execution_authority": "none",
        "output_contract": (
            agent_decision_contract.output_schema()
            if expected_mode == "agent_only"
            else agent_veto_contract.output_schema()
        ),
        "allowed_evidence_ids": sorted(_allowlisted_evidence(context)),
        "context": context,
    }
    expected_request = (
        agent_model_client.request_payload(model_input)
        if expected_mode == "agent_only"
        else agent_model_client.veto_request_payload(model_input)
    )
    started_at = _utc(stored["started_at"], "agent attempt start time")
    expected_window = (
        "agent-shadow-v2:"
        + canonical_sha256(
            {
                "schema_version": 2,
                "policy_id": policy["id"],
                "policy_registration_sha256": policy["registration_sha256"],
                "mode": expected_mode,
                "agent_id": stored["agent_id"],
                "strategy_id": strategy["id"],
                "ticker": instrument["ticker"],
                "market_date": stored["market_date"].isoformat(),
            }
        )
    )
    if (
        stored["decision_window"] != decision_window_id
        or stored["decision_window"] != expected_window
        or stored["schema_version"] != 2
        or stored["mode"] != expected_mode
        or stored["policy_id"] != policy["id"]
        or stored["policy_registration_sha256"] != policy["registration_sha256"]
        or stored["strategy_id"] != strategy["id"]
        or stored["ticker"] != instrument["ticker"]
        or stored["market_date"].isoformat() != context["market_date"]
        or stored["context_sha256"] != context["context_sha256"]
        or stored["model"] != model["model"]
        or stored["model_version"] != model["model_version"]
        or stored["prompt_sha256"] != model["instructions_sha256"]
        or stored["toolset_sha256"] != model["toolset_sha256"]
        or stored["required_proxy_version"] != model["required_proxy_version"]
        or stored["execution_authority"] != "none"
        or policy != expected_policy
        or model != agent_model_client.identity(role=role)
        or model_input != expected_input
        or model_request != expected_request
        or stored["request_sha256"] != canonical_sha256(model_request)
    ):
        raise AgentPaperEvidenceError("retained agent attempt binding is invalid")
    return stored, context, model_input, started_at


def _events(
    con: duckdb.DuckDBPyConnection,
    *,
    attempt_id: int,
    request_sha256: str,
    context: dict,
    started_at: datetime,
) -> tuple[dict, dict, str, datetime]:
    rows = con.execute(
        "SELECT id, event_type, payload, occurred_at FROM agent_shadow_events "
        "WHERE attempt_id = ? ORDER BY id LIMIT ?",
        [attempt_id, MAX_EVENT_ROWS + 1],
    ).fetchall()
    if len(rows) != 3 or len(rows) > MAX_EVENT_ROWS:
        raise AgentPaperEvidenceError(
            "agent decision window does not have one accepted terminal path"
        )
    if [row[1] for row in rows] != ["started", "model_response", "proposal_result"]:
        raise AgentPaperEvidenceError("agent decision event sequence is invalid")
    if [row[0] for row in rows] != sorted({row[0] for row in rows}):
        raise AgentPaperEvidenceError("agent decision event identifiers are invalid")
    times = [_utc(row[3], "agent decision event time") for row in rows]
    if times != sorted(times) or times[0] < started_at:
        raise AgentPaperEvidenceError("agent decision event time is invalid")
    try:
        started = loads_object(rows[0][2])
        response = loads_object(rows[1][2])
        terminal = loads_object(rows[2][2])
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise AgentPaperEvidenceError("agent decision event payload is invalid") from exc
    if started != {
        "request_sha256": request_sha256,
        "execution_authority": "none",
    }:
        raise AgentPaperEvidenceError("agent decision start event is invalid")
    response = _verify_model_response(
        response,
        context=context,
        request_sha256=request_sha256,
    )
    try:
        decision = agent_decision_contract.normalize(
            response["output"],
            allowed_evidence_ids=_allowlisted_evidence(context),
        )
    except agent_decision_contract.DecisionError as exc:
        raise AgentPaperEvidenceError("retained agent decision is invalid") from exc
    if (
        decision.get("decision") != "proposal"
        or set(terminal) != {"decision", "result"}
        or terminal["decision"] != decision
        or not isinstance(terminal["result"], dict)
    ):
        raise AgentPaperEvidenceError("retained agent terminal event is invalid")
    terminal_sha256 = canonical_sha256(
        {
            "event_id": rows[2][0],
            "attempt_id": attempt_id,
            "event_type": rows[2][1],
            "payload": terminal,
            "occurred_at": times[2].isoformat().replace("+00:00", "Z"),
        }
    )
    return decision, terminal["result"], terminal_sha256, times[2]


def _proposal(
    con: duckdb.DuckDBPyConnection,
    *,
    attempt_id: int,
    decision_window_id: str,
    context: dict,
    decision: dict,
    terminal_result: dict,
    started_at: datetime,
    terminal_at: datetime,
) -> tuple[dict, dict, int, str]:
    if not table_exists(con, "agent_proposals"):
        raise AgentPaperEvidenceError("accepted agent proposal is unavailable")
    cursor = con.execute(
        "SELECT * FROM agent_proposals WHERE idempotency_key = ? ORDER BY id LIMIT 2",
        [decision_window_id],
    )
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise AgentPaperEvidenceError("accepted agent proposal is unavailable or ambiguous")
    stored = dict(
        zip((item[0] for item in cursor.description), rows[0], strict=True)
    )
    try:
        raw_proposal = loads_object(stored["normalized_proposal"])
        received_at = _utc(stored["received_at"], "agent proposal receipt time")
        if not isinstance(raw_proposal.get("signal_at"), str) or not isinstance(
            raw_proposal.get("expires_at"), str
        ):
            raise ValueError("retained proposal timestamps are invalid")
        normalized_input = dict(raw_proposal)
        for field in ("signal_at", "expires_at"):
            parsed = datetime.fromisoformat(raw_proposal[field])
            normalized_input[field] = _utc(
                parsed,
                f"agent proposal {field}",
            ).isoformat()
        proposal = agent_contract.normalize(normalized_input, now=received_at)
        retained_context = _context(
            stored["validated_context"],
            expected_mode="agent_only",
        )
        reasons = loads_strict(stored["reasons"])
        evidence_ids = loads_strict(stored["evidence_ids"])
        validation = loads_object(stored["validation_payload"])
        verified_validation = agent_proposal_validation.verify_binding(
            validation,
            validation_sha256=stored["validation_sha256"],
            policy_id=stored["policy_id"],
            policy_registration_sha256=stored["policy_registration_sha256"],
            context_sha256=stored["validated_context_sha256"],
            proposal_status=stored["status"],
            reasons=reasons,
        )
    except (
        TypeError,
        ValueError,
        UnicodeDecodeError,
        agent_contract.ProposalError,
        agent_proposal_validation.ValidationError,
    ) as exc:
        raise AgentPaperEvidenceError("retained accepted proposal is invalid") from exc
    proposal_identity = {
        **proposal,
        "signal_at": proposal["signal_at"].isoformat(),
        "expires_at": proposal["expires_at"].isoformat(),
    }
    if raw_proposal != loads_object(_canonical(proposal)):
        raise AgentPaperEvidenceError("retained accepted proposal is invalid")
    scalar_fields = (
        "proposal_id",
        "idempotency_key",
        "schema_version",
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
        "thesis",
        "invalidation",
    )
    expected_proposal_result = {
        "proposal_record_id": int(stored["id"]),
        "proposal_id": stored["proposal_id"],
        "status": "shadow_accepted",
        "validation_scope": agent_proposal_validation.VALIDATION_SCOPE,
        "validation_status": "pass",
        "validation_sha256": stored["validation_sha256"],
        "execution_authority": "none",
        "context_sha256": context["context_sha256"],
        "validated_context_sha256": context["context_sha256"],
        "reasons": [],
        "replayed": False,
    }
    expected_terminal = {
        "schema_version": 2,
        "attempt_id": attempt_id,
        "decision_window": decision_window_id,
        "status": "shadow_accepted",
        "reason": None,
        "proposal_result": expected_proposal_result,
        "execution_authority": "none",
        "replayed": False,
    }
    proposal_result = terminal_result.get("proposal_result")
    claim = verified_validation["recomputed_claim"]
    signal_close = context["instrument"].get("close")
    quantity = claim.get("quantity_at_signal_close")
    claim_binding_valid = (
        claim.get("ticker") == proposal["ticker"]
        and claim.get("side") == proposal["side"]
        and claim.get("signal_date") == context["market_date"]
        and claim.get("signal_close") == signal_close
        and claim.get("maximum_notional") == proposal["max_notional"]
        and claim.get("stop") == proposal["stop"]
        and claim.get("reserved_portfolio_id")
        == context["policy"]["reserved_portfolio_id"]
        and claim.get("execution_profile_id")
        == context["policy"]["execution_profile_id"]
        and claim.get("execution_profile_sha256")
        == context["policy"]["execution_profile_sha256"]
        and not isinstance(quantity, bool)
        and isinstance(quantity, (int, float))
        and math.isfinite(quantity)
        and quantity > 0
        and not isinstance(signal_close, bool)
        and isinstance(signal_close, (int, float))
        and math.isfinite(signal_close)
        and signal_close > 0
        and math.isclose(
            quantity * signal_close,
            proposal["max_notional"],
            rel_tol=1e-12,
            abs_tol=1e-9,
        )
    )
    if (
        stored["status"] != "shadow_accepted"
        or reasons != []
        or retained_context != context
        or stored["validated_context_sha256"] != context["context_sha256"]
        or stored["proposal_sha256"] != canonical_sha256(proposal_identity)
        or any(stored[field] != proposal[field] for field in scalar_fields)
        or _utc(stored["signal_at"], "agent proposal signal time")
        != proposal["signal_at"]
        or proposal["signal_at"] != started_at
        or received_at < started_at
        or received_at != terminal_at
        or _utc(stored["expires_at"], "agent proposal expiry")
        != proposal["expires_at"]
        or evidence_ids != proposal["evidence_ids"]
        or proposal["idempotency_key"] != decision_window_id
        or proposal["mode"] != "agent_only"
        or proposal["context_sha256"] != context["context_sha256"]
        or proposal["policy_id"] != context["policy"]["id"]
        or proposal["policy_registration_sha256"]
        != context["policy"]["registration_sha256"]
        or proposal["data_snapshot_sha256"]
        != context["provenance"]["data_snapshot_sha256"]
        or proposal["ticker"] != context["instrument"]["ticker"]
        or proposal["side"] != decision["side"]
        or proposal["max_notional"] != decision["max_notional"]
        or proposal["stop"] != decision["stop"]
        or proposal["confidence"] != decision["confidence"]
        or proposal["thesis"] != decision["thesis"]
        or proposal["invalidation"] != decision["invalidation"]
        or proposal["evidence_ids"] != decision["evidence_ids"]
        or not claim_binding_valid
        or terminal_result != expected_terminal
        or proposal_result != expected_proposal_result
    ):
        raise AgentPaperEvidenceError("retained accepted proposal binding is invalid")
    audit_payload = _canonical(expected_proposal_result)
    audit_rows = con.execute(
        "SELECT ts, actor, action, payload FROM audit_log "
        "WHERE action = 'agent_proposal_shadow' AND payload = ? LIMIT 2",
        [audit_payload],
    ).fetchall()
    if (
        len(audit_rows) != 1
        or _utc(audit_rows[0][0], "agent proposal audit time") != received_at
        or audit_rows[0][1] != f"agent:{proposal['agent_id']}"
        or audit_rows[0][2] != "agent_proposal_shadow"
    ):
        raise AgentPaperEvidenceError("retained agent proposal audit is invalid")
    return proposal, verified_validation, int(stored["id"]), stored["proposal_sha256"]


def load_agent_only_intent(
    con: duckdb.DuckDBPyConnection,
    request: SubmitOrderRequest,
    *,
    decision_window_id: str,
) -> LoadedAgentPaperIntent:
    """Derive trusted agent-only bindings from retained append-only evidence."""
    if not isinstance(request, SubmitOrderRequest):
        raise TypeError("request must be a SubmitOrderRequest")
    require_identifier(decision_window_id, "agent decision-window identifier")
    if not all(
        table_exists(con, table)
        for table in (
            "agent_shadow_attempts",
            "agent_shadow_events",
        )
    ):
        raise AgentPaperEvidenceError("retained agent evidence is unavailable")
    stored_attempt, context, _model_input, started_at = _attempt(
        con,
        decision_window_id,
        expected_mode="agent_only",
    )
    decision, terminal_result, terminal_sha256, terminal_at = _events(
        con,
        attempt_id=int(stored_attempt["id"]),
        request_sha256=stored_attempt["request_sha256"],
        context=context,
        started_at=started_at,
    )
    proposal, validation, proposal_record_id, proposal_sha256 = _proposal(
        con,
        attempt_id=int(stored_attempt["id"]),
        decision_window_id=decision_window_id,
        context=context,
        decision=decision,
        terminal_result=terminal_result,
        started_at=started_at,
        terminal_at=terminal_at,
    )
    claim = validation["recomputed_claim"]
    signal_close = claim.get("signal_close")
    if (
        isinstance(signal_close, bool)
        or not isinstance(signal_close, (int, float))
        or not math.isfinite(signal_close)
        or signal_close <= 0
    ):
        raise AgentPaperEvidenceError("retained agent signal price is invalid")
    request_notional = request.quantity * signal_close
    if (
        request.account_id != context["policy"].get("reserved_portfolio_id")
        or request.symbol != claim.get("ticker")
        or request.side != claim.get("side")
        or request.signal_date.isoformat() != claim.get("signal_date")
        or request.order_type != "market"
        or request.time_in_force != "day"
        or request.extended_hours is not False
        or not math.isfinite(request_notional)
        or request_notional > proposal["max_notional"]
    ):
        raise AgentPaperEvidenceError(
            "broker request does not match retained agent proposal"
        )
    request_payload = {
        "idempotency_key": request.idempotency_key,
        "account_id": request.account_id,
        "symbol": request.symbol,
        "side": request.side,
        "quantity": request.quantity,
        "signal_date": request.signal_date.isoformat(),
        "order_type": request.order_type,
        "time_in_force": request.time_in_force,
        "extended_hours": request.extended_hours,
    }
    bindings = PaperIntentBindings(
        mode="agent_only",
        policy_id=proposal["policy_id"],
        policy_registration_sha256=proposal["policy_registration_sha256"],
        data_snapshot_sha256=proposal["data_snapshot_sha256"],
        context_sha256=proposal["context_sha256"],
        proposal_id=proposal["proposal_id"],
        proposal_sha256=proposal_sha256,
        proposal_status="shadow_accepted",
        validation_sha256=validation["validation_sha256"],
        validation_status="pass",
        decision_window_id=decision_window_id,
        request_sha256=canonical_sha256(request_payload),
        symbol=request.symbol,
        side=request.side,
        max_notional=proposal["max_notional"],
        signal_date=request.signal_date,
        proposal_expires_at=proposal["expires_at"],
    )
    evidence_body = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "attempt_id": int(stored_attempt["id"]),
        "proposal_record_id": proposal_record_id,
        "decision_window_id": decision_window_id,
        "context_sha256": context["context_sha256"],
        "model_request_sha256": stored_attempt["request_sha256"],
        "terminal_event_sha256": terminal_sha256,
        "proposal_sha256": proposal_sha256,
        "validation_sha256": validation["validation_sha256"],
        "intent_bindings_sha256": bindings.sha256(),
        "request_sha256": bindings.request_sha256,
        "signal_close": signal_close,
        "request_notional": request_notional,
        "stop": proposal["stop"],
        "confidence": proposal["confidence"],
        "thesis": proposal["thesis"],
        "invalidation": proposal["invalidation"],
        "execution_authority": "none",
    }
    return LoadedAgentPaperIntent(
        request=request,
        bindings=bindings,
        signal_close=float(signal_close),
        request_notional=float(request_notional),
        stop=proposal["stop"],
        confidence=proposal["confidence"],
        thesis=proposal["thesis"],
        invalidation=proposal["invalidation"],
        attempt_id=int(stored_attempt["id"]),
        proposal_record_id=proposal_record_id,
        terminal_event_sha256=terminal_sha256,
        evidence_observed_at=terminal_at,
        evidence_sha256=canonical_sha256(evidence_body),
    )


@dataclass(frozen=True, slots=True)
class LoadedHybridPaperIntent:
    """Verified retained hybrid evidence bound to one effective order."""

    request: SubmitOrderRequest
    bindings: HybridPaperIntentBindings
    source_portfolio_id: str
    signal_close: float
    signal_notional: float
    candidate_order_count: int
    effective_order_count: int
    vetoed_order_count: int
    model_decision: str | None
    decision_reason: str
    attempt_id: int
    terminal_event_sha256: str
    evidence_sha256: str
    execution_authority: str = "none"


def _algorithm_candidate(context: dict) -> dict:
    candidate = context["algorithm_candidate"]
    expected_fields = {
        "schema_version",
        "status",
        "market_date",
        "cadence",
        "cadence_admitted",
        "policy_id",
        "policy_registration_sha256",
        "strategy_id",
        "strategy_config_sha256",
        "source_portfolio_id",
        "execution_profile_id",
        "execution_profile_sha256",
        "portfolio_state",
        "orders",
        "order_count",
        "buy_order_count",
        "sell_order_count",
        "veto_scope",
        "execution_authority",
        "candidate_sha256",
    }
    body = {
        key: value for key, value in candidate.items() if key != "candidate_sha256"
    }
    orders = candidate.get("orders")
    state = candidate.get("portfolio_state")
    if (
        set(candidate) != expected_fields
        or candidate.get("schema_version") != 1
        or candidate.get("status") != "materialized"
        or candidate.get("cadence_admitted") is not True
        or candidate.get("cadence") != context["policy"]["cadence"]
        or candidate.get("policy_id") != context["policy"]["id"]
        or candidate.get("policy_registration_sha256")
        != context["policy"]["registration_sha256"]
        or candidate.get("strategy_id") != context["strategy"]["id"]
        or candidate.get("source_portfolio_id") != context["strategy"]["id"]
        or candidate.get("strategy_config_sha256")
        != context["strategy"]["config_sha256"]
        or candidate.get("execution_profile_id")
        != context["policy"]["execution_profile_id"]
        or candidate.get("execution_profile_sha256")
        != context["policy"]["execution_profile_sha256"]
        or candidate.get("market_date") != context["market_date"]
        or candidate.get("veto_scope") != "buy_orders_only"
        or candidate.get("execution_authority") != "none"
        or isinstance(candidate.get("order_count"), bool)
        or not isinstance(candidate.get("order_count"), int)
        or isinstance(candidate.get("buy_order_count"), bool)
        or not isinstance(candidate.get("buy_order_count"), int)
        or isinstance(candidate.get("sell_order_count"), bool)
        or not isinstance(candidate.get("sell_order_count"), int)
        or not isinstance(orders, list)
        or not orders
        or len(orders) != candidate.get("order_count")
        or candidate.get("buy_order_count")
        != sum(isinstance(order, dict) and order.get("side") == "buy" for order in orders)
        or candidate.get("sell_order_count")
        != sum(isinstance(order, dict) and order.get("side") == "sell" for order in orders)
        or canonical_sha256(body) != candidate.get("candidate_sha256")
    ):
        raise AgentPaperEvidenceError("retained hybrid candidate is invalid")
    _hybrid_portfolio_state(
        state,
        source_portfolio_id=candidate["source_portfolio_id"],
        market_date=candidate["market_date"],
        allowed_symbols=frozenset(context["policy"]["allowed_symbols"]),
    )
    seen_sequences = set()
    for index, order in enumerate(orders, 1):
        if (
            not isinstance(order, dict)
            or set(order)
            != {
                "sequence",
                "portfolio_id",
                "ticker",
                "side",
                "quantity",
                "signal_date",
                "signal_close",
                "signal_notional",
                "veto_eligible",
            }
            or order["sequence"] != index
            or order["sequence"] in seen_sequences
            or order["portfolio_id"] != candidate["source_portfolio_id"]
            or order["signal_date"] != candidate["market_date"]
            or order["ticker"] not in context["policy"]["allowed_symbols"]
            or order["side"] not in {"buy", "sell"}
            or order["veto_eligible"] is not (order["side"] == "buy")
            or isinstance(order["quantity"], bool)
            or not isinstance(order["quantity"], (int, float))
            or not math.isfinite(order["quantity"])
            or order["quantity"] <= 0
            or isinstance(order["signal_close"], bool)
            or not isinstance(order["signal_close"], (int, float))
            or not math.isfinite(order["signal_close"])
            or order["signal_close"] <= 0
            or isinstance(order["signal_notional"], bool)
            or not isinstance(order["signal_notional"], (int, float))
            or not math.isfinite(order["signal_notional"])
            or order["signal_notional"] <= 0
            or not math.isclose(
                order["quantity"] * order["signal_close"],
                order["signal_notional"],
                rel_tol=1e-12,
                abs_tol=1e-9,
            )
        ):
            raise AgentPaperEvidenceError("retained hybrid candidate order is invalid")
        seen_sequences.add(order["sequence"])
    return candidate


def _hybrid_portfolio_state(
    state: object,
    *,
    source_portfolio_id: str,
    market_date: str,
    allowed_symbols: frozenset[str],
) -> None:
    expected_fields = {
        "portfolio_id",
        "as_of",
        "cash",
        "equity",
        "equity_source",
        "positions",
        "state_sha256",
    }
    if not isinstance(state, dict) or set(state) != expected_fields:
        raise AgentPaperEvidenceError("retained hybrid portfolio state is invalid")
    body = {key: value for key, value in state.items() if key != "state_sha256"}
    cash = state.get("cash")
    equity = state.get("equity")
    positions = state.get("positions")
    if (
        state.get("portfolio_id") != source_portfolio_id
        or state.get("as_of") != market_date
        or state.get("equity_source")
        not in {
            "recomputed_current_state",
            "stored_equity_reconciled_to_current_state",
        }
        or isinstance(cash, bool)
        or not isinstance(cash, (int, float))
        or not math.isfinite(cash)
        or cash < 0
        or isinstance(equity, bool)
        or not isinstance(equity, (int, float))
        or not math.isfinite(equity)
        or equity <= 0
        or not isinstance(positions, list)
        or canonical_sha256(body) != state.get("state_sha256")
    ):
        raise AgentPaperEvidenceError("retained hybrid portfolio state is invalid")
    tickers = []
    market_value = 0.0
    for position in positions:
        if not isinstance(position, dict) or set(position) != {
            "ticker",
            "quantity",
            "average_cost",
            "mark_date",
            "mark_close",
            "market_value",
            "carried",
        }:
            raise AgentPaperEvidenceError("retained hybrid portfolio position is invalid")
        ticker = position.get("ticker")
        quantity = position.get("quantity")
        average_cost = position.get("average_cost")
        mark_close = position.get("mark_close")
        value = position.get("market_value")
        mark_date = position.get("mark_date")
        try:
            parsed_mark_date = date.fromisoformat(mark_date)
        except (TypeError, ValueError):
            parsed_mark_date = None
        if (
            ticker not in allowed_symbols
            or parsed_mark_date is None
            or parsed_mark_date.isoformat() != mark_date
            or mark_date > market_date
            or type(position.get("carried")) is not bool
            or position["carried"] is not (mark_date != market_date)
            or any(
                isinstance(number, bool)
                or not isinstance(number, (int, float))
                or not math.isfinite(number)
                or number <= 0
                for number in (quantity, average_cost, mark_close, value)
            )
            or not math.isclose(
                quantity * mark_close,
                value,
                rel_tol=1e-12,
                abs_tol=1e-9,
            )
        ):
            raise AgentPaperEvidenceError("retained hybrid portfolio position is invalid")
        tickers.append(ticker)
        market_value += value
    if tickers != sorted(set(tickers)) or not math.isclose(
        cash + market_value,
        equity,
        rel_tol=1e-12,
        abs_tol=1e-8,
    ):
        raise AgentPaperEvidenceError("retained hybrid portfolio state is invalid")


def _bounded_reason(prefix: str, detail: str) -> str:
    return f"{prefix}; {detail}"[:MAX_RESULT_REASON_CHARS]


def _optional_sha256(value: object, label: str) -> None:
    if value is not None and (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise AgentPaperEvidenceError(f"{label} is invalid")


def _model_output_failure_metadata(terminal: dict, request_sha256: str) -> None:
    response_id = terminal.get("response_id")
    if response_id is not None and (
        not isinstance(response_id, str)
        or not response_id
        or len(response_id) > 128
        or not response_id.isprintable()
    ):
        raise AgentPaperEvidenceError("hybrid model-output response identity is invalid")
    retained_request_sha256 = terminal.get("request_sha256")
    if retained_request_sha256 not in {None, request_sha256}:
        raise AgentPaperEvidenceError("hybrid model-output request identity is invalid")
    _optional_sha256(
        terminal.get("response_sha256"),
        "hybrid model-output response identity",
    )
    usage = terminal.get("usage")
    if usage is not None and (
        not isinstance(usage, dict)
        or set(usage) != {"input_tokens", "output_tokens", "total_tokens"}
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in usage.values()
        )
        or usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]
    ):
        raise AgentPaperEvidenceError("hybrid model-output usage is invalid")


def _hybrid_fallback_reason(
    *,
    event_types: list[str],
    payloads: list[dict],
    context: dict,
    candidate: dict,
    request_sha256: str,
) -> str:
    terminal = payloads[-1]
    if event_types == ["started", "model_response", "hybrid_fallback_allow"]:
        response = _verify_model_response(
            payloads[1],
            context=context,
            request_sha256=request_sha256,
        )
        try:
            agent_veto_contract.normalize(
                response["output"],
                expected_candidate_sha256=candidate["candidate_sha256"],
                allowed_evidence_ids=_allowlisted_evidence(context),
            )
        except agent_veto_contract.VetoDecisionError as exc:
            detail = str(exc)
        else:
            raise AgentPaperEvidenceError("hybrid fallback retained a valid veto decision")
        if terminal != {
            "detail": detail,
            "fallback_policy": "unmodified_algorithm_signal",
            "result": terminal.get("result"),
        }:
            raise AgentPaperEvidenceError("hybrid invalid-output fallback is invalid")
        return _bounded_reason("invalid veto output", detail)
    if terminal.get("interrupted_request") is True:
        expected = {
            "fallback_policy": "unmodified_algorithm_signal",
            "interrupted_request": True,
            "result": terminal.get("result"),
        }
        if event_types != ["started", "hybrid_fallback_allow"] or terminal != expected:
            raise AgentPaperEvidenceError("hybrid interrupted fallback is invalid")
        return (
            "a prior process ended after recording the request but before "
            "recording a response; model-failure policy preserves the "
            "unmodified algorithm signal"
        )
    detail = terminal.get("detail")
    error_type = terminal.get("error_type")
    if (
        event_types != ["started", "hybrid_fallback_allow"]
        or not isinstance(detail, str)
        or not detail
        or detail != detail.strip()
        or not detail.isprintable()
    ):
        raise AgentPaperEvidenceError("hybrid model-failure fallback is invalid")
    if error_type == "ConnectorError":
        expected = {
            "error_type": "ConnectorError",
            "detail": detail,
            "result": terminal.get("result"),
        }
        prefix = "model transport failure"
    elif error_type == "ModelOutputError":
        _model_output_failure_metadata(terminal, request_sha256)
        expected = {
            "error_type": "ModelOutputError",
            "detail": detail,
            "response_id": terminal.get("response_id"),
            "request_sha256": terminal.get("request_sha256"),
            "response_sha256": terminal.get("response_sha256"),
            "usage": terminal.get("usage"),
            "result": terminal.get("result"),
        }
        if terminal["request_sha256"] not in {None, request_sha256}:
            raise AgentPaperEvidenceError("hybrid model-output fallback is invalid")
        prefix = "model output failure"
    else:
        raise AgentPaperEvidenceError("hybrid model-failure fallback is invalid")
    if terminal != expected:
        raise AgentPaperEvidenceError("hybrid model-failure fallback is invalid")
    return _bounded_reason(prefix, detail)


def _hybrid_terminal(
    con: duckdb.DuckDBPyConnection,
    *,
    attempt_id: int,
    request_sha256: str,
    context: dict,
    started_at: datetime,
    decision_window_id: str,
) -> tuple[str, list[dict], str, datetime, str | None, str]:
    rows = con.execute(
        "SELECT id, event_type, payload, occurred_at FROM agent_shadow_events "
        "WHERE attempt_id = ? ORDER BY id LIMIT ?",
        [attempt_id, MAX_EVENT_ROWS + 1],
    ).fetchall()
    if not 2 <= len(rows) <= 3 or len(rows) > MAX_EVENT_ROWS:
        raise AgentPaperEvidenceError("hybrid decision event sequence is invalid")
    event_types = [row[1] for row in rows]
    terminal_type = event_types[-1]
    if (
        event_types[0] != "started"
        or terminal_type
        not in {"hybrid_allow", "hybrid_veto", "hybrid_fallback_allow"}
        or event_types not in (
            ["started", terminal_type],
            ["started", "model_response", terminal_type],
        )
    ):
        raise AgentPaperEvidenceError("hybrid decision event sequence is invalid")
    if [row[0] for row in rows] != sorted({row[0] for row in rows}):
        raise AgentPaperEvidenceError("hybrid decision event identifiers are invalid")
    times = [_utc(row[3], "hybrid decision event time") for row in rows]
    if times != sorted(times) or times[0] < started_at:
        raise AgentPaperEvidenceError("hybrid decision event time is invalid")
    try:
        payloads = [loads_object(row[2]) for row in rows]
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise AgentPaperEvidenceError("hybrid decision event payload is invalid") from exc
    if payloads[0] != {
        "request_sha256": request_sha256,
        "execution_authority": "none",
    }:
        raise AgentPaperEvidenceError("hybrid decision start event is invalid")
    candidate = _algorithm_candidate(context)
    terminal = payloads[-1]
    decision = terminal.get("decision")
    if terminal_type in {"hybrid_allow", "hybrid_veto"}:
        if event_types != ["started", "model_response", terminal_type]:
            raise AgentPaperEvidenceError("hybrid model decision has no retained response")
        response = payloads[1]
        response = _verify_model_response(
            response,
            context=context,
            request_sha256=request_sha256,
        )
        if response["output"] != decision:
            raise AgentPaperEvidenceError("retained hybrid model response is invalid")
        try:
            decision = agent_veto_contract.normalize(
                decision,
                expected_candidate_sha256=candidate["candidate_sha256"],
                allowed_evidence_ids=_allowlisted_evidence(context),
            )
        except agent_veto_contract.VetoDecisionError as exc:
            raise AgentPaperEvidenceError("retained hybrid decision is invalid") from exc
        if decision["decision"] != terminal_type.removeprefix("hybrid_"):
            raise AgentPaperEvidenceError("retained hybrid decision outcome is invalid")
        if terminal != {"decision": decision, "result": terminal.get("result")}:
            raise AgentPaperEvidenceError("retained hybrid decision payload is invalid")
        expected_reason = decision["reason"]
    else:
        if decision is not None:
            raise AgentPaperEvidenceError("hybrid fallback contains a model decision")
        expected_reason = _hybrid_fallback_reason(
            event_types=event_types,
            payloads=payloads,
            context=context,
            candidate=candidate,
            request_sha256=request_sha256,
        )
    result = terminal.get("result")
    effective_orders = (
        [order for order in candidate["orders"] if not order["veto_eligible"]]
        if terminal_type == "hybrid_veto"
        else candidate["orders"]
    )
    expected_result = {
        "schema_version": 2,
        "attempt_id": attempt_id,
        "decision_window": decision_window_id,
        "status": terminal_type,
        "reason": expected_reason,
        "proposal_result": {
            "policy_effect": (
                "veto_buy_candidates"
                if terminal_type == "hybrid_veto"
                else "unmodified_algorithm_signal"
            ),
            "candidate_sha256": candidate["candidate_sha256"],
            "candidate_order_count": candidate["order_count"],
            "veto_eligible_order_count": sum(
                order["veto_eligible"] for order in candidate["orders"]
            ),
            "effective_order_count": len(effective_orders),
            "vetoed_order_count": candidate["order_count"] - len(effective_orders),
            "effective_orders_sha256": canonical_sha256(effective_orders),
            "decision": None if decision is None else decision["decision"],
            "execution_authority": "none",
        },
        "execution_authority": "none",
        "replayed": False,
    }
    if (
        not isinstance(result, dict)
        or result != expected_result
    ):
        raise AgentPaperEvidenceError("retained hybrid terminal result is invalid")
    terminal_sha256 = canonical_sha256(
        {
            "event_id": rows[-1][0],
            "attempt_id": attempt_id,
            "event_type": terminal_type,
            "payload": terminal,
            "occurred_at": times[-1].isoformat().replace("+00:00", "Z"),
        }
    )
    model_decision = None if decision is None else decision["decision"]
    return (
        terminal_type,
        effective_orders,
        terminal_sha256,
        times[-1],
        model_decision,
        expected_reason,
    )


def load_hybrid_intent(
    con: duckdb.DuckDBPyConnection,
    request: SubmitOrderRequest,
    *,
    decision_window_id: str,
) -> LoadedHybridPaperIntent:
    """Derive hybrid bindings only for an order surviving the retained veto."""
    if not isinstance(request, SubmitOrderRequest):
        raise TypeError("request must be a SubmitOrderRequest")
    require_identifier(decision_window_id, "hybrid decision-window identifier")
    if not all(
        table_exists(con, table)
        for table in ("agent_shadow_attempts", "agent_shadow_events")
    ):
        raise AgentPaperEvidenceError("retained hybrid evidence is unavailable")
    stored, context, _model_input, started_at = _attempt(
        con,
        decision_window_id,
        expected_mode="hybrid",
    )
    (
        terminal_type,
        effective_orders,
        terminal_sha256,
        terminal_at,
        model_decision,
        decision_reason,
    ) = _hybrid_terminal(
        con,
        attempt_id=int(stored["id"]),
        request_sha256=stored["request_sha256"],
        context=context,
        started_at=started_at,
        decision_window_id=decision_window_id,
    )
    candidate = _algorithm_candidate(context)
    matching = [
        order
        for order in effective_orders
        if (
            order["ticker"],
            order["side"],
            order["quantity"],
            order["signal_date"],
        )
        == (
            request.symbol,
            request.side,
            request.quantity,
            request.signal_date.isoformat(),
        )
    ]
    if (
        request.account_id != context["policy"]["reserved_portfolio_id"]
        or request.order_type != "market"
        or request.time_in_force != "day"
        or request.extended_hours is not False
        or len(matching) != 1
    ):
        raise AgentPaperEvidenceError(
            "broker request is not in the retained hybrid effective order set"
        )
    request_payload = {
        "idempotency_key": request.idempotency_key,
        "account_id": request.account_id,
        "symbol": request.symbol,
        "side": request.side,
        "quantity": request.quantity,
        "signal_date": request.signal_date.isoformat(),
        "order_type": request.order_type,
        "time_in_force": request.time_in_force,
        "extended_hours": request.extended_hours,
    }
    bindings = HybridPaperIntentBindings(
        mode="hybrid",
        policy_id=context["policy"]["id"],
        policy_registration_sha256=context["policy"]["registration_sha256"],
        data_snapshot_sha256=context["provenance"]["data_snapshot_sha256"],
        context_sha256=context["context_sha256"],
        decision_window_id=decision_window_id,
        candidate_sha256=candidate["candidate_sha256"],
        terminal_event_sha256=terminal_sha256,
        terminal_status=terminal_type,
        effective_orders_sha256=canonical_sha256(effective_orders),
        effective_order_included=True,
        veto_eligible=matching[0]["veto_eligible"],
        request_sha256=canonical_sha256(request_payload),
        symbol=request.symbol,
        side=request.side,
        quantity=request.quantity,
        signal_date=request.signal_date,
        evidence_observed_at=terminal_at,
    )
    evidence_body = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "attempt_id": int(stored["id"]),
        "decision_window_id": decision_window_id,
        "context_sha256": context["context_sha256"],
        "model_request_sha256": stored["request_sha256"],
        "candidate_sha256": candidate["candidate_sha256"],
        "terminal_event_sha256": terminal_sha256,
        "effective_orders_sha256": bindings.effective_orders_sha256,
        "intent_bindings_sha256": bindings.sha256(),
        "request_sha256": bindings.request_sha256,
        "source_portfolio_id": candidate["source_portfolio_id"],
        "signal_close": matching[0]["signal_close"],
        "signal_notional": matching[0]["signal_notional"],
        "candidate_order_count": candidate["order_count"],
        "effective_order_count": len(effective_orders),
        "vetoed_order_count": candidate["order_count"] - len(effective_orders),
        "model_decision": model_decision,
        "decision_reason": decision_reason,
        "execution_authority": "none",
    }
    return LoadedHybridPaperIntent(
        request=request,
        bindings=bindings,
        source_portfolio_id=candidate["source_portfolio_id"],
        signal_close=float(matching[0]["signal_close"]),
        signal_notional=float(matching[0]["signal_notional"]),
        candidate_order_count=candidate["order_count"],
        effective_order_count=len(effective_orders),
        vetoed_order_count=candidate["order_count"] - len(effective_orders),
        model_decision=model_decision,
        decision_reason=decision_reason,
        attempt_id=int(stored["id"]),
        terminal_event_sha256=terminal_sha256,
        evidence_sha256=canonical_sha256(evidence_body),
    )
