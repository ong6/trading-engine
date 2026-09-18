"""Policy-separated attribution for completed shadow decision windows."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import duckdb

from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists

from . import (
    agent_paper_attribution,
    agent_policy,
    agent_proposal_validation,
    agent_shadow_store,
)
from .json_utils import loads_object, loads_strict
from .read_model_utils import (
    require_public_nonnegative_integer,
    require_public_positive_integer,
    rows,
)

ATTRIBUTION_LIMIT = 100
ATTRIBUTION_EVIDENCE_LIMIT = 10_000
ATTRIBUTION_SCOPE = "registered_shadow_decision_contribution_only"
RETURN_ATTRIBUTION_STATUS = "unavailable_no_isolated_paper_portfolio"
AUTOMATIC_PAPER_MINIMUM_SESSIONS = 60
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_AGENT_TERMINALS = frozenset(
    {
        "cadence_no_action",
        "no_action",
        "malformed_output",
        "transport_failure",
        "proposal_result",
        "proposal_failure",
        "uncertain",
    }
)
_HYBRID_TERMINALS = frozenset(
    {
        "cadence_no_action",
        "hybrid_no_veto_candidate",
        "hybrid_allow",
        "hybrid_veto",
        "hybrid_fallback_allow",
    }
)
_NO_ACTION_CONTRIBUTIONS = {
    "cadence_no_action": "cadence_no_action",
    "no_action": "model_no_action",
    "malformed_output": "model_output_failure_no_action",
    "transport_failure": "model_transport_failure_no_action",
    "proposal_failure": "proposal_boundary_failure_no_action",
    "uncertain": "interrupted_request_no_action",
}


def _hash(value: object, field: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"agent attribution {field} is invalid")
    return value


def _count(value: object, field: str) -> int:
    try:
        return require_public_nonnegative_integer(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"agent attribution {field} is invalid") from exc


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"agent attribution {field} is invalid")
    return value


def _context(attempt: dict, *, required: bool) -> dict | None:
    raw = attempt["context_payload"]
    context_sha256 = _hash(
        attempt["context_sha256"],
        "context identity",
        optional=not required,
    )
    if raw is None:
        if required or context_sha256 is not None:
            raise ValueError("agent attribution context is unavailable")
        return None
    if context_sha256 is None:
        raise ValueError("agent attribution context identity is unavailable")
    context = loads_object(raw)
    if (
        context.get("context_sha256") != context_sha256
        or canonical_sha256(
            {key: value for key, value in context.items() if key != "context_sha256"}
        )
        != context_sha256
        or context.get("policy", {}).get("id") != attempt["policy_id"]
        or context.get("policy", {}).get("registration_sha256")
        != attempt["policy_registration_sha256"]
    ):
        raise ValueError("agent attribution context binding is invalid")
    return context


def _terminal_event(con: duckdb.DuckDBPyConnection, attempt_id: int) -> tuple | None:
    placeholders = ",".join("?" for _ in agent_shadow_store.TERMINAL_EVENT_TYPES)
    terminal = con.execute(
        "SELECT id, event_type, payload, occurred_at FROM agent_shadow_events "
        f"WHERE attempt_id = ? AND event_type IN ({placeholders}) ORDER BY id",
        [attempt_id, *sorted(agent_shadow_store.TERMINAL_EVENT_TYPES)],
    ).fetchall()
    if len(terminal) > 1:
        raise ValueError("agent attribution attempt has multiple terminal events")
    return None if not terminal else terminal[0]


def _response_recorded(con: duckdb.DuckDBPyConnection, attempt_id: int) -> bool:
    count = con.execute(
        "SELECT COUNT(*) FROM agent_shadow_events "
        "WHERE attempt_id = ? AND event_type = 'model_response'",
        [attempt_id],
    ).fetchone()[0]
    if count not in {0, 1}:
        raise ValueError("agent attribution attempt has multiple model responses")
    return count == 1


def _proposal_attribution(
    con: duckdb.DuckDBPyConnection,
    attempt: dict,
    result: dict,
) -> dict:
    proposal = result.get("proposal_result")
    if not isinstance(proposal, dict):
        raise ValueError("agent attribution proposal result is invalid")
    proposal_id = require_public_positive_integer(proposal.get("proposal_record_id"))
    row = con.execute(
        "SELECT policy_id, policy_registration_sha256, status, "
        "validated_context_sha256, validation_sha256, validation_payload, reasons "
        "FROM agent_proposals WHERE id = ?",
        [proposal_id],
    ).fetchone()
    if row is None:
        raise ValueError("agent attribution proposal record is unavailable")
    (
        policy_id,
        registration_sha256,
        status,
        context_sha256,
        validation_sha256,
        validation_payload,
        raw_reasons,
    ) = row
    if (
        policy_id != attempt["policy_id"]
        or registration_sha256 != attempt["policy_registration_sha256"]
        or status != proposal.get("status")
        or context_sha256 != attempt["context_sha256"]
        or status not in {"shadow_accepted", "shadow_rejected"}
    ):
        raise ValueError("agent attribution proposal binding is invalid")
    try:
        reasons = loads_strict(raw_reasons)
    except (TypeError, ValueError) as exc:
        raise ValueError("agent attribution proposal reasons are invalid") from exc
    if not isinstance(reasons, list) or not all(
        isinstance(reason, str) and reason for reason in reasons
    ):
        raise ValueError("agent attribution proposal reasons are invalid")
    validation_status = "not_run"
    attributable_orders = []
    decision_evidence_sha256 = None
    if validation_sha256 is not None or validation_payload is not None:
        if validation_sha256 is None or validation_payload is None:
            raise ValueError("agent attribution proposal validation is incomplete")
        try:
            evidence = agent_proposal_validation.verify_binding(
                loads_strict(validation_payload),
                validation_sha256=validation_sha256,
                policy_id=policy_id,
                policy_registration_sha256=registration_sha256,
                context_sha256=context_sha256,
                proposal_status=status,
                reasons=reasons,
            )
        except (TypeError, ValueError, agent_proposal_validation.ValidationError) as exc:
            raise ValueError("agent attribution proposal validation is invalid") from exc
        validation_status = evidence["status"]
        decision_evidence_sha256 = evidence["validation_sha256"]
        if status == "shadow_accepted":
            claim = evidence["recomputed_claim"]
            try:
                signal_date = date.fromisoformat(claim["signal_date"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    "agent attribution proposal order evidence is invalid"
                ) from exc
            attributable_orders = [
                {
                    "sequence": 1,
                    "ticker": claim.get("ticker"),
                    "side": claim.get("side"),
                    "quantity": claim.get("quantity_at_signal_close"),
                    "signal_date": signal_date,
                    "quantity_rule": "maximum",
                }
            ]
    elif status == "shadow_accepted":
        validation_status = "legacy_unvalidated"
    return {
        "decision_contribution": (
            "agent_shadow_proposal"
            if status == "shadow_accepted"
            else "agent_proposal_rejected_no_action"
        ),
        "proposal_record_id": proposal_id,
        "proposal_status": status,
        "validation_status": validation_status,
        "validation_sha256": _hash(
            validation_sha256,
            "proposal validation identity",
            optional=True,
        ),
        "candidate_sha256": None,
        "candidate_order_count": 1,
        "counterfactual_order_count": int(status == "shadow_accepted"),
        "vetoed_order_count": 0,
        "effective_orders_sha256": None,
        "fallback_applied": False,
        "_attributable_orders": attributable_orders,
        "_decision_evidence_sha256": decision_evidence_sha256,
    }


def _hybrid_attribution(
    attempt: dict,
    context: dict,
    result: dict,
    event_type: str,
) -> dict:
    proposal = result.get("proposal_result")
    if not isinstance(proposal, dict):
        raise ValueError("agent attribution hybrid result is invalid")
    candidate = context.get("algorithm_candidate")
    if not isinstance(candidate, dict):
        raise ValueError("agent attribution hybrid candidate is unavailable")
    candidate_sha256 = _hash(
        proposal.get("candidate_sha256"),
        "candidate identity",
    )
    if (
        candidate_sha256 != candidate.get("candidate_sha256")
        or canonical_sha256(
            {key: value for key, value in candidate.items() if key != "candidate_sha256"}
        )
        != candidate_sha256
    ):
        raise ValueError("agent attribution hybrid candidate identity is invalid")
    candidate_count = _count(proposal.get("candidate_order_count"), "candidate count")
    veto_eligible_count = _count(
        proposal.get("veto_eligible_order_count"),
        "veto-eligible count",
    )
    effective_count = _count(
        proposal.get("effective_order_count"),
        "counterfactual order count",
    )
    vetoed_count = _count(proposal.get("vetoed_order_count"), "vetoed count")
    expected_effective = (
        [order for order in candidate["orders"] if not order["veto_eligible"]]
        if event_type == "hybrid_veto"
        else candidate["orders"]
    )
    expected_effect = (
        "veto_buy_candidates"
        if event_type == "hybrid_veto"
        else "unmodified_algorithm_signal"
    )
    if (
        candidate_count != candidate.get("order_count")
        or veto_eligible_count
        != sum(order.get("veto_eligible") is True for order in candidate["orders"])
        or effective_count != len(expected_effective)
        or vetoed_count != candidate_count - effective_count
        or proposal.get("policy_effect") != expected_effect
        or proposal.get("effective_orders_sha256")
        != canonical_sha256(expected_effective)
        or proposal.get("execution_authority") != "none"
    ):
        raise ValueError("agent attribution hybrid outcome is inconsistent")
    contribution = {
        "hybrid_no_veto_candidate": "unmodified_algorithm_signal",
        "hybrid_allow": "model_allowed_algorithm_signal",
        "hybrid_veto": "model_vetoed_buy_candidates",
        "hybrid_fallback_allow": "model_failure_unmodified_algorithm_signal",
    }[event_type]
    return {
        "decision_contribution": contribution,
        "proposal_record_id": None,
        "proposal_status": None,
        "validation_status": None,
        "validation_sha256": None,
        "candidate_sha256": candidate_sha256,
        "candidate_order_count": candidate_count,
        "counterfactual_order_count": effective_count,
        "vetoed_order_count": vetoed_count,
        "effective_orders_sha256": _hash(
            proposal.get("effective_orders_sha256"),
            "effective orders identity",
        ),
        "fallback_applied": event_type == "hybrid_fallback_allow",
        "_attributable_orders": [
            {
                "sequence": order["sequence"],
                "ticker": order["ticker"],
                "side": order["side"],
                "quantity": order["quantity"],
                "signal_date": date.fromisoformat(order["signal_date"]),
                "quantity_rule": "exact",
            }
            for order in expected_effective
        ],
        "_decision_evidence_sha256": canonical_sha256(expected_effective),
    }


def _record(
    con: duckdb.DuckDBPyConnection,
    attempt: dict,
    policy: dict,
    terminal: tuple,
) -> dict:
    event_id, event_type, raw_payload, completed_at = terminal
    allowed = _AGENT_TERMINALS if policy["mode"] == "agent_only" else _HYBRID_TERMINALS
    if event_type not in allowed:
        raise ValueError("agent attribution terminal event does not match policy mode")
    payload = loads_object(raw_payload)
    result = payload.get("result")
    if (
        not isinstance(result, dict)
        or result.get("attempt_id") != attempt["id"]
        or result.get("decision_window") != attempt["decision_window"]
        or result.get("execution_authority") != "none"
    ):
        raise ValueError("agent attribution terminal result identity is invalid")
    if type(attempt["market_date"]) is not date or type(completed_at) is not datetime:
        raise ValueError("agent attribution timestamp is invalid")
    if (
        attempt["execution_authority"] != "none"
        or _identifier(attempt["decision_window"], "decision window")
        != result["decision_window"]
    ):
        raise ValueError("agent attribution attempt authority is invalid")
    context = _context(attempt, required=event_type != "cadence_no_action")
    expected_status = result.get("status")
    if event_type == "proposal_result":
        if expected_status not in {"shadow_accepted", "shadow_rejected"}:
            raise ValueError("agent attribution proposal status is invalid")
        contribution = _proposal_attribution(con, attempt, result)
    elif event_type in _HYBRID_TERMINALS - {"cadence_no_action"}:
        if expected_status != event_type:
            raise ValueError("agent attribution hybrid status is invalid")
        if context is None:
            raise ValueError("agent attribution hybrid context is unavailable")
        contribution = _hybrid_attribution(attempt, context, result, event_type)
    else:
        if expected_status != event_type:
            raise ValueError("agent attribution no-action status is invalid")
        contribution = {
            "decision_contribution": _NO_ACTION_CONTRIBUTIONS[event_type],
            "proposal_record_id": None,
            "proposal_status": None,
            "validation_status": None,
            "validation_sha256": None,
            "candidate_sha256": None,
            "candidate_order_count": 0,
            "counterfactual_order_count": 0,
            "vetoed_order_count": 0,
            "effective_orders_sha256": None,
            "fallback_applied": False,
            "_attributable_orders": [],
            "_decision_evidence_sha256": None,
        }
    model_requested = (
        _hash(
            attempt["request_sha256"],
            "request identity",
            optional=True,
        )
        is not None
    )
    response_recorded = _response_recorded(con, attempt["id"])
    if event_type == "cadence_no_action" and (model_requested or response_recorded):
        raise ValueError("agent attribution cadence no-action contacted the model")
    if event_type == "hybrid_no_veto_candidate" and model_requested:
        raise ValueError("agent attribution no-candidate outcome contacted the model")
    if response_recorded and not model_requested:
        raise ValueError("agent attribution model response has no request")
    terminal_event_sha256 = canonical_sha256(
        {
            "event_id": require_public_positive_integer(event_id),
            "attempt_id": require_public_positive_integer(attempt["id"]),
            "event_type": event_type,
            "payload": payload,
            "occurred_at": completed_at.replace(tzinfo=None).isoformat() + "Z",
        }
    )
    return {
        "attempt_id": require_public_positive_integer(attempt["id"]),
        "decision_window": _identifier(attempt["decision_window"], "decision window"),
        "market_date": attempt["market_date"],
        "completed_at": completed_at,
        "policy_id": policy["id"],
        "policy_registration_sha256": policy["registration_sha256"],
        "mode": policy["mode"],
        "strategy_id": policy["strategy_id"],
        "strategy_control_id": policy["attribution"]["strategy_control_id"],
        "algorithm_control_id": policy["attribution"]["algorithm_control_id"],
        "reserved_portfolio_id": policy["reserved_portfolio_id"],
        "terminal_outcome": event_type,
        "model_requested": model_requested,
        "normalized_model_response_recorded": response_recorded,
        **contribution,
        "return_attribution_status": RETURN_ATTRIBUTION_STATUS,
        "execution_authority": "none",
        "_terminal_event_sha256": terminal_event_sha256,
    }


def verified_decision_record(
    con: duckdb.DuckDBPyConnection,
    decision_window: str,
    *,
    registration_path: Path = agent_policy.REGISTRATION_PATH,
) -> dict:
    """Reconstruct one complete decision with its private attribution bindings."""
    decision_window = _identifier(decision_window, "decision window")
    attempts = rows(
        con.execute(
            "SELECT id, decision_window, mode, policy_id, "
            "policy_registration_sha256, strategy_id, market_date, "
            "context_sha256, context_payload, request_sha256, "
            "execution_authority FROM agent_shadow_attempts "
            "WHERE decision_window = ? LIMIT 2",
            [decision_window],
        )
    )
    if len(attempts) != 1:
        raise ValueError("agent decision window is unavailable or ambiguous")
    attempt = attempts[0]
    policy_id = attempt["policy_id"]
    if policy_id is None:
        raise ValueError("agent decision window has no registered policy")
    policy = agent_policy.get(policy_id, path=registration_path)
    agent_policy.validate_live_registration(
        con,
        policy,
        allow_reserved_portfolio=True,
    )
    if (
        attempt["mode"] != policy["mode"]
        or attempt["strategy_id"] != policy["strategy_id"]
        or attempt["policy_registration_sha256"]
        != policy["registration_sha256"]
    ):
        raise ValueError("agent decision policy binding is invalid")
    terminal = _terminal_event(con, attempt["id"])
    if terminal is None:
        raise ValueError("agent decision window is not complete")
    return _record(con, attempt, policy, terminal)


def attribution(
    con: duckdb.DuckDBPyConnection,
    *,
    registration_path: Path = agent_policy.REGISTRATION_PATH,
    require_live_registration: bool = True,
) -> dict:
    """Expose bounded decision contribution without inventing return attribution."""
    registry = agent_policy.registry(registration_path)
    policies = {
        policy["id"]: agent_policy.get(policy["id"], path=registration_path)
        for policy in registry["policies"]
    }
    if require_live_registration:
        for policy in policies.values():
            agent_policy.validate_live_registration(
                con,
                policy,
                allow_reserved_portfolio=True,
            )
    if not table_exists(con, "agent_shadow_attempts") or not table_exists(
        con, "agent_shadow_events"
    ):
        attempts = []
        registered_completed = 0
        legacy_count = 0
    else:
        counts = {
            policy_id: require_public_nonnegative_integer(count)
            for policy_id, count in con.execute(
                "SELECT policy_id, COUNT(*) FROM agent_shadow_attempts "
                "GROUP BY policy_id"
            ).fetchall()
        }
        unknown = set(counts) - set(policies) - {None}
        if unknown:
            raise ValueError("agent attribution references an unregistered policy")
        legacy_count = counts.get(None, 0)
        placeholders = ",".join(
            "?" for _ in agent_shadow_store.TERMINAL_EVENT_TYPES
        )
        registered_completed = require_public_nonnegative_integer(
            con.execute(
                "SELECT COUNT(*) FROM agent_shadow_attempts a "
                "WHERE a.policy_id IS NOT NULL AND EXISTS ("
                "SELECT 1 FROM agent_shadow_events e WHERE e.attempt_id = a.id "
                f"AND e.event_type IN ({placeholders}))",
                list(sorted(agent_shadow_store.TERMINAL_EVENT_TYPES)),
            ).fetchone()[0]
        )
        if registered_completed > ATTRIBUTION_EVIDENCE_LIMIT:
            raise ValueError("agent attribution evidence exceeds the verification bound")
        attempts = rows(
            con.execute(
                "SELECT id, decision_window, mode, policy_id, "
                "policy_registration_sha256, strategy_id, market_date, "
                "context_sha256, context_payload, request_sha256, "
                "execution_authority "
                "FROM agent_shadow_attempts a WHERE a.policy_id IS NOT NULL "
                "AND EXISTS (SELECT 1 FROM agent_shadow_events e "
                "WHERE e.attempt_id = a.id "
                f"AND e.event_type IN ({placeholders})) "
                "ORDER BY id DESC LIMIT ?",
                [
                    *sorted(agent_shadow_store.TERMINAL_EVENT_TYPES),
                    ATTRIBUTION_EVIDENCE_LIMIT,
                ],
            )
        )
    records = []
    for attempt in attempts:
        policy_id = attempt["policy_id"]
        policy = policies[policy_id]
        if (
            attempt["mode"] != policy["mode"]
            or attempt["strategy_id"] != policy["strategy_id"]
            or attempt["policy_registration_sha256"]
            != policy["registration_sha256"]
        ):
            raise ValueError("agent attribution policy binding is invalid")
        terminal = _terminal_event(con, attempt["id"])
        if terminal is None:  # pragma: no cover - bounded query requires one
            raise ValueError("agent attribution completed attempt has no outcome")
        records.append(_record(con, attempt, policy, terminal))
    summaries = []
    policy_attribution = {}
    for policy in policies.values():
        policy_records = [
            record for record in records if record["policy_id"] == policy["id"]
        ]
        returned_policy_records = [
            record
            for record in records[:ATTRIBUTION_LIMIT]
            if record["policy_id"] == policy["id"]
        ]
        paper_attribution = agent_paper_attribution.assess_policy(
            con,
            policy,
            decision_records=policy_records,
        )
        policy_attribution[policy["id"]] = paper_attribution
        completed_count = require_public_nonnegative_integer(
            con.execute(
                "SELECT COUNT(*) FROM agent_shadow_attempts a "
                "WHERE a.policy_id = ? AND EXISTS ("
                "SELECT 1 FROM agent_shadow_events e WHERE e.attempt_id = a.id "
                f"AND e.event_type IN ({placeholders}))",
                [
                    policy["id"],
                    *sorted(agent_shadow_store.TERMINAL_EVENT_TYPES),
                ],
            ).fetchone()[0]
        ) if attempts else 0
        completed_sessions = require_public_nonnegative_integer(
            con.execute(
                "SELECT COUNT(DISTINCT a.market_date) "
                "FROM agent_shadow_attempts a "
                "WHERE a.policy_id = ? AND EXISTS ("
                "SELECT 1 FROM agent_shadow_events e WHERE e.attempt_id = a.id "
                f"AND e.event_type IN ({placeholders}))",
                [
                    policy["id"],
                    *sorted(agent_shadow_store.TERMINAL_EVENT_TYPES),
                ],
            ).fetchone()[0]
        ) if attempts else 0
        outcomes = {
            event_type: require_public_nonnegative_integer(
                con.execute(
                    "SELECT COUNT(*) FROM agent_shadow_attempts a "
                    "WHERE a.policy_id = ? AND EXISTS ("
                    "SELECT 1 FROM agent_shadow_events e WHERE e.attempt_id = a.id "
                    "AND e.event_type = ?)",
                    [policy["id"], event_type],
                ).fetchone()[0]
            )
            for event_type in sorted(agent_shadow_store.TERMINAL_EVENT_TYPES)
        } if attempts else {
            event_type: 0
            for event_type in sorted(agent_shadow_store.TERMINAL_EVENT_TYPES)
        }
        summaries.append(
            {
                "policy_id": policy["id"],
                "mode": policy["mode"],
                "completed_attempt_count": completed_count,
                "completed_market_sessions": completed_sessions,
                "terminal_outcomes": outcomes,
                "records_returned": len(returned_policy_records),
                "reserved_portfolio_created": paper_attribution[
                    "portfolio_created"
                ],
                "return_attribution_status": paper_attribution["status"],
                "paper_book_attribution": paper_attribution,
                "automatic_paper_minimum_sessions": AUTOMATIC_PAPER_MINIMUM_SESSIONS,
                "automatic_paper_session_gate_passed": (
                    completed_sessions >= AUTOMATIC_PAPER_MINIMUM_SESSIONS
                ),
                "execution_authority": "none",
            }
        )
    statuses = {item["status"] for item in policy_attribution.values()}
    if statuses == {agent_paper_attribution.STATUS_AVAILABLE}:
        return_status = agent_paper_attribution.STATUS_AVAILABLE
    elif agent_paper_attribution.STATUS_NO_PORTFOLIO in statuses:
        return_status = agent_paper_attribution.STATUS_NO_PORTFOLIO
    elif agent_paper_attribution.STATUS_NO_CONTRACT in statuses:
        return_status = agent_paper_attribution.STATUS_NO_CONTRACT
    else:
        return_status = agent_paper_attribution.STATUS_NO_EQUITY
    public_records = [
        {
            key: value
            for key, value in record.items()
            if not key.startswith("_")
        }
        for record in records[:ATTRIBUTION_LIMIT]
    ]
    for record in public_records:
        record["return_attribution_status"] = policy_attribution[
            record["policy_id"]
        ]["status"]
    return {
        "schema_version": 1,
        "registry_sha256": registry["registry_sha256"],
        "attribution_scope": ATTRIBUTION_SCOPE,
        "return_attribution_status": return_status,
        "performance_claim": "none",
        "evidence_pooling": "prohibited",
        "execution_authority": "none",
        "limit": ATTRIBUTION_LIMIT,
        "matching_count": registered_completed,
        "truncated": registered_completed > len(public_records),
        "legacy_attempt_count": legacy_count,
        "legacy_included": False,
        "policy_summaries": summaries,
        "records": public_records,
    }
