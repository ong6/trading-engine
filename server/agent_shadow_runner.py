"""One-shot, idempotent shadow decisions through the local Trae proxy."""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator

import duckdb

from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256
from engine.lib.resources import advisory_file_lock
from engine.lib.settings import DEFAULT_DB, REPO_ROOT
from sim.calendar import is_month_signal

from . import (
    agent_context,
    agent_contract,
    agent_corporate_action_observations,
    agent_decision_contract,
    agent_model_client,
    agent_policy,
    agent_price_observations,
    agent_proposals,
    agent_shadow_store,
    agent_veto_contract,
)
from .json_utils import loads_object
from .market_read_models import latest_prices_date

RUNNER_SCHEMA_VERSION = 2
AGENT_ID = "paper-research-agent"
LOCK_PATH = REPO_ROOT / ".agent-shadow.lock"
PROPOSAL_VALIDITY = timedelta(days=1)
MAX_RESULT_REASON_CHARS = 512
TERMINAL_EVENTS = agent_shadow_store.TERMINAL_EVENT_TYPES


class ShadowRunError(RuntimeError):
    """The manual shadow runner could not safely establish an attempt."""


ConnectionFactory = Callable[[], duckdb.DuckDBPyConnection]
Generate = Callable[[dict], agent_model_client.ConnectorResult]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _decision_window(
    policy_id: str,
    policy_registration_sha256: str,
    mode: str,
    strategy_id: str,
    ticker: str,
    market_date,
) -> str:
    identity = {
        "schema_version": RUNNER_SCHEMA_VERSION,
        "policy_id": policy_id,
        "policy_registration_sha256": policy_registration_sha256,
        "mode": mode,
        "agent_id": AGENT_ID,
        "strategy_id": strategy_id,
        "ticker": ticker,
        "market_date": market_date.isoformat(),
    }
    return f"agent-shadow-v2:{canonical_sha256(identity)}"


def _legacy_decision_window(
    mode: str,
    strategy_id: str,
    ticker: str,
    market_date,
) -> str:
    identity = {
        "schema_version": 1,
        "mode": mode,
        "agent_id": AGENT_ID,
        "strategy_id": strategy_id,
        "ticker": ticker,
        "market_date": market_date.isoformat(),
    }
    return f"agent-shadow-v1:{canonical_sha256(identity)}"


def _evidence_allowlist(context: dict) -> frozenset[str]:
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


def _model_input(context: dict, mode: str = "agent_only") -> dict:
    output_contract = (
        agent_veto_contract.output_schema()
        if mode == "hybrid"
        else agent_decision_contract.output_schema()
    )
    return {
        "schema_version": RUNNER_SCHEMA_VERSION,
        "task": (
            "allow or veto the exact deterministic candidate"
            if mode == "hybrid"
            else "choose exactly one shadow decision under the supplied output contract"
        ),
        "requested_mode": mode,
        "policy_id": context["policy"]["id"],
        "policy_registration_sha256": context["policy"]["registration_sha256"],
        "model_role": context["policy"]["model_role"],
        "execution_authority": "none",
        "output_contract": output_contract,
        "allowed_evidence_ids": sorted(_evidence_allowlist(context)),
        "context": context,
    }


def _result(
    *,
    attempt_id: int,
    decision_window: str,
    status: str,
    reason: str | None = None,
    proposal_result: dict | None = None,
    replayed: bool = False,
) -> dict:
    if reason is not None:
        reason = reason[:MAX_RESULT_REASON_CHARS]
    return {
        "schema_version": RUNNER_SCHEMA_VERSION,
        "attempt_id": attempt_id,
        "decision_window": decision_window,
        "status": status,
        "reason": reason,
        "proposal_result": proposal_result,
        "execution_authority": "none",
        "replayed": replayed,
    }


def _connect_factory(database: Path) -> ConnectionFactory:
    def connect() -> duckdb.DuckDBPyConnection:
        return engine_db.connect(database, wait_s=0)

    return connect


@contextmanager
def _connection(factory: ConnectionFactory) -> Iterator[duckdb.DuckDBPyConnection]:
    con = factory()
    try:
        yield con
    finally:
        con.close()


def _append(
    con: duckdb.DuckDBPyConnection,
    attempt_id: int,
    event_type: str,
    payload: dict,
    *,
    now: datetime,
) -> None:
    with engine_db.transaction(con):
        agent_shadow_store.append_event(
            con,
            attempt_id,
            event_type,
            payload,
            occurred_at=now,
        )


def _stored_result(rows: list[tuple]) -> dict | None:
    terminal = [row for row in rows if row[1] in TERMINAL_EVENTS]
    if not terminal:
        return None
    if len(terminal) != 1:
        raise ShadowRunError("shadow attempt has multiple terminal events")
    payload = loads_object(terminal[0][2])
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ShadowRunError("shadow terminal event has no valid result")
    return {**result, "replayed": True}


def _resume_attempt(
    con: duckdb.DuckDBPyConnection,
    attempt: agent_shadow_store.ShadowAttempt,
    *,
    now: datetime,
) -> tuple[str, dict]:
    """Classify one unfinished attempt without making another model request."""
    rows = agent_shadow_store.events(con, int(attempt.id))
    if _stored_result(rows) is not None:  # pragma: no cover - query excludes terminal rows
        raise ShadowRunError("unfinished shadow attempt already has a terminal event")
    response_rows = [row for row in rows if row[1] == "model_response"]
    if len(response_rows) > 1:
        raise ShadowRunError("shadow attempt has multiple model responses")
    if response_rows:
        return "response", loads_object(response_rows[0][2])
    if attempt.mode == "hybrid":
        context = loads_object(attempt.context_payload)
        candidate = context["algorithm_candidate"]
        result = _hybrid_result(
            attempt_id=int(attempt.id),
            window=attempt.decision_window,
            event_type="hybrid_fallback_allow",
            reason=(
                "a prior process ended after recording the request but before "
                "recording a response; model-failure policy preserves the "
                "unmodified algorithm signal"
            ),
            candidate=candidate,
            decision=None,
        )
        _append(
            con,
            int(attempt.id),
            "hybrid_fallback_allow",
            {
                "fallback_policy": "unmodified_algorithm_signal",
                "interrupted_request": True,
                "result": result,
            },
            now=now,
        )
        return "uncertain", result
    result = _result(
        attempt_id=int(attempt.id),
        decision_window=attempt.decision_window,
        status="uncertain",
        reason=(
            "a prior process ended after recording the request but before "
            "recording a response; automatic retry is prohibited"
        ),
    )
    _append(
        con,
        int(attempt.id),
        "uncertain",
        {"result": result},
        now=now,
    )
    return "uncertain", result


def _proposal_body(
    context: dict,
    decision: dict,
    *,
    mode: str,
    window: str,
    started_at: datetime,
) -> dict:
    identity = canonical_sha256({"decision_window": window})
    model = context["decision_model"]
    return {
        "schema_version": agent_contract.SCHEMA_VERSION,
        "proposal_id": f"agent-shadow-proposal:{identity}",
        "idempotency_key": window,
        "mode": mode,
        "policy_id": context["policy"]["id"],
        "policy_registration_sha256": context["policy"]["registration_sha256"],
        "agent_id": AGENT_ID,
        "model": model["model"],
        "model_version": model["model_version"],
        "prompt_sha256": model["instructions_sha256"],
        "toolset_sha256": model["toolset_sha256"],
        "strategy_id": context["strategy"]["id"],
        "strategy_config_sha256": context["strategy"]["config_sha256"],
        "agent_boundary_sha256": context["provenance"]["agent_boundary_sha256"],
        "runtime_source_sha256": context["provenance"]["runtime_source_sha256"],
        "data_snapshot_sha256": context["provenance"]["data_snapshot_sha256"],
        "context_sha256": context["context_sha256"],
        "ticker": context["instrument"]["ticker"],
        "side": decision["side"],
        "max_notional": decision["max_notional"],
        "stop": decision["stop"],
        "confidence": decision["confidence"],
        "signal_at": _timestamp(started_at),
        "expires_at": _timestamp(started_at + PROPOSAL_VALIDITY),
        "thesis": decision["thesis"],
        "invalidation": decision["invalidation"],
        "evidence_ids": decision["evidence_ids"],
    }


def _complete_response(
    factory: ConnectionFactory,
    attempt: agent_shadow_store.ShadowAttempt,
    response_payload: dict,
    *,
    now: datetime,
    repo_root: Path,
) -> dict:
    attempt_id = int(attempt.id)
    window = attempt.decision_window
    context = loads_object(attempt.context_payload)
    output = response_payload.get("output")
    try:
        decision = agent_decision_contract.normalize(
            output,
            allowed_evidence_ids=_evidence_allowlist(context),
        )
    except agent_decision_contract.DecisionError as exc:
        result = _result(
            attempt_id=attempt_id,
            decision_window=window,
            status="malformed_output",
            reason=str(exc),
        )
        with _connection(factory) as con:
            agent_shadow_store.init_schema(con)
            _append(
                con,
                attempt_id,
                "malformed_output",
                {"detail": str(exc), "result": result},
                now=now,
            )
        return result

    if decision["decision"] == "no_action":
        result = _result(
            attempt_id=attempt_id,
            decision_window=window,
            status="no_action",
            reason=decision["reason"],
        )
        with _connection(factory) as con:
            agent_shadow_store.init_schema(con)
            _append(
                con,
                attempt_id,
                "no_action",
                {"decision": decision, "result": result},
                now=now,
            )
        return result

    if "policy" not in context:
        result = _result(
            attempt_id=attempt_id,
            decision_window=window,
            status="proposal_failure",
            reason="legacy unregistered attempt cannot create a policy-bound proposal",
        )
        with _connection(factory) as con:
            agent_shadow_store.init_schema(con)
            _append(
                con,
                attempt_id,
                "proposal_failure",
                {"detail": result["reason"], "result": result},
                now=now,
            )
        return result

    body = _proposal_body(
        context,
        decision,
        mode=attempt.mode,
        window=window,
        started_at=attempt.started_at.replace(tzinfo=timezone.utc),
    )
    try:
        with _connection(factory) as con:
            proposal_result = agent_proposals.submit(
                con,
                body,
                now=now,
                repo_root=repo_root,
            )
    except agent_contract.ProposalError as exc:
        result = _result(
            attempt_id=attempt_id,
            decision_window=window,
            status="proposal_failure",
            reason=exc.detail,
        )
        with _connection(factory) as con:
            agent_shadow_store.init_schema(con)
            _append(
                con,
                attempt_id,
                "proposal_failure",
                {"detail": exc.detail, "result": result},
                now=now,
            )
        return result

    result = _result(
        attempt_id=attempt_id,
        decision_window=window,
        status=proposal_result["status"],
        proposal_result=proposal_result,
    )
    with _connection(factory) as con:
        agent_shadow_store.init_schema(con)
        _append(
            con,
            attempt_id,
            "proposal_result",
            {"decision": decision, "result": result},
            now=now,
        )
    return result


def _hybrid_result(
    *,
    attempt_id: int,
    window: str,
    event_type: str,
    reason: str,
    candidate: dict,
    decision: dict | None,
) -> dict:
    effective_orders = (
        [order for order in candidate["orders"] if not order["veto_eligible"]]
        if event_type == "hybrid_veto"
        else candidate["orders"]
    )
    return _result(
        attempt_id=attempt_id,
        decision_window=window,
        status=event_type,
        reason=reason,
        proposal_result={
            "policy_effect": (
                "veto_buy_candidates"
                if event_type == "hybrid_veto"
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
    )


def _complete_hybrid_response(
    factory: ConnectionFactory,
    attempt: agent_shadow_store.ShadowAttempt,
    response_payload: dict,
    *,
    now: datetime,
) -> dict:
    attempt_id = int(attempt.id)
    context = loads_object(attempt.context_payload)
    candidate = context["algorithm_candidate"]
    try:
        decision = agent_veto_contract.normalize(
            response_payload.get("output"),
            expected_candidate_sha256=candidate["candidate_sha256"],
            allowed_evidence_ids=_evidence_allowlist(context),
        )
    except agent_veto_contract.VetoDecisionError as exc:
        result = _hybrid_result(
            attempt_id=attempt_id,
            window=attempt.decision_window,
            event_type="hybrid_fallback_allow",
            reason=f"invalid veto output; {exc}",
            candidate=candidate,
            decision=None,
        )
        payload = {"detail": str(exc), "fallback_policy": "unmodified_algorithm_signal"}
    else:
        event_type = (
            "hybrid_veto" if decision["decision"] == "veto" else "hybrid_allow"
        )
        result = _hybrid_result(
            attempt_id=attempt_id,
            window=attempt.decision_window,
            event_type=event_type,
            reason=decision["reason"],
            candidate=candidate,
            decision=decision,
        )
        payload = {"decision": decision}
    with _connection(factory) as con:
        agent_shadow_store.init_schema(con)
        _append(
            con,
            attempt_id,
            result["status"],
            {**payload, "result": result},
            now=now,
        )
    return result


def run(
    strategy_id: str,
    ticker: str,
    *,
    mode: str,
    policy_id: str = "dual_momentum_agent_shadow_v1",
    policy_path: Path = agent_policy.REGISTRATION_PATH,
    database: Path = DEFAULT_DB,
    repo_root: Path = REPO_ROOT,
    lock_path: Path = LOCK_PATH,
    now: datetime | None = None,
    generate: Generate | None = None,
    connection_factory: ConnectionFactory | None = None,
) -> dict:
    """Consume at most one model decision for one strategy/ticker/market date."""
    if not isinstance(strategy_id, str) or not strategy_id:
        raise ShadowRunError("strategy_id must be nonempty")
    if not isinstance(ticker, str) or not ticker:
        raise ShadowRunError("ticker must be nonempty")
    ticker = ticker.upper()
    try:
        policy = agent_policy.get(policy_id, path=policy_path)
    except agent_policy.PolicyError as exc:
        raise ShadowRunError(str(exc)) from exc
    if (
        policy["mode"] != mode
        or policy["strategy_id"] != strategy_id
        or ticker not in policy["allowed_symbols"]
    ):
        raise ShadowRunError("runner request does not match the frozen agent policy")
    if policy["generation_enabled"] is not True:
        raise ShadowRunError("agent policy generation is disabled")
    if generate is None:
        generate = (
            agent_model_client.generate_veto_json
            if mode == "hybrid"
            else agent_model_client.generate_json
        )
    observed_at = (now or _utc_now()).astimezone(timezone.utc)
    factory = connection_factory or _connect_factory(database)

    with advisory_file_lock(lock_path):
        with _connection(factory) as con:
            agent_shadow_store.init_schema(con)
            unfinished = agent_shadow_store.unfinished_attempts(
                con,
                mode=mode,
                strategy_id=strategy_id,
                ticker=ticker,
                policy_id=policy_id,
            )
            if len(unfinished) > 1:
                raise ShadowRunError("multiple unfinished shadow attempts require operator review")
            if unfinished:
                attempt = unfinished[0]
                recovery, recovery_payload = _resume_attempt(
                    con,
                    attempt,
                    now=observed_at,
                )
                if recovery == "uncertain":
                    return recovery_payload
                response_payload = recovery_payload
                existing = attempt
            else:
                market_date = latest_prices_date(con)
                if market_date is None:
                    raise agent_context.ContextError("no breadth-qualified market date")
                window = _decision_window(
                    policy_id,
                    policy["registration_sha256"],
                    mode,
                    strategy_id,
                    ticker,
                    market_date,
                )
                existing = agent_shadow_store.find_window(con, window)
                if existing is None:
                    existing = agent_shadow_store.find_window(
                        con,
                        _legacy_decision_window(
                            mode,
                            strategy_id,
                            ticker,
                            market_date,
                        ),
                    )
            if existing is None:
                if policy["cadence"] != "monthly":
                    raise ShadowRunError("registered policy cadence is not implemented")
                if not is_month_signal(con, market_date):
                    with engine_db.transaction(con):
                        attempt_id = agent_shadow_store.insert_cadence_no_action(
                            con,
                            decision_window=window,
                            mode=mode,
                            policy_id=policy_id,
                            policy_registration_sha256=policy[
                                "registration_sha256"
                            ],
                            agent_id=AGENT_ID,
                            strategy_id=strategy_id,
                            ticker=ticker,
                            market_date=market_date,
                            started_at=observed_at,
                        )
                    return _result(
                        attempt_id=attempt_id,
                        decision_window=window,
                        status="cadence_no_action",
                        reason="market date is not a registered strategy signal date",
                    )
                try:
                    agent_price_observations.capture_strategy_scope(
                        con,
                        strategy_id,
                        market_date,
                        observed_at=observed_at,
                    )
                    agent_corporate_action_observations.capture_strategy_scope(
                        con,
                        strategy_id,
                        market_date,
                        observed_at=observed_at,
                    )
                except (
                    agent_corporate_action_observations.ObservationError,
                    agent_price_observations.ObservationError,
                ) as exc:
                    raise ShadowRunError(
                        f"agent data observation capture failed: {exc}"
                    ) from exc
                context = agent_context.build(
                    con,
                    strategy_id,
                    ticker,
                    policy_id=policy_id,
                    repo_root=repo_root,
                    policy_path=policy_path,
                )
                if context["market_date"] != market_date.isoformat():
                    raise ShadowRunError("shadow context market date changed during admission")
                if mode == "hybrid":
                    candidate = context["algorithm_candidate"]
                    veto_eligible = [
                        order for order in candidate["orders"] if order["veto_eligible"]
                    ]
                    if not veto_eligible:
                        result = _result(
                            attempt_id=0,
                            decision_window=window,
                            status="hybrid_no_veto_candidate",
                            reason="deterministic candidate has no veto-eligible buy order",
                            proposal_result={
                                "policy_effect": "unmodified_algorithm_signal",
                                "candidate_sha256": candidate["candidate_sha256"],
                                "candidate_order_count": candidate["order_count"],
                                "veto_eligible_order_count": 0,
                                "effective_order_count": candidate["order_count"],
                                "vetoed_order_count": 0,
                                "effective_orders_sha256": canonical_sha256(
                                    candidate["orders"]
                                ),
                                "decision": None,
                                "execution_authority": "none",
                            },
                        )
                        with engine_db.transaction(con):
                            attempt_id = (
                                agent_shadow_store.insert_deterministic_attempt(
                                    con,
                                    decision_window=window,
                                    mode=mode,
                                    policy_id=policy_id,
                                    policy_registration_sha256=policy[
                                        "registration_sha256"
                                    ],
                                    agent_id=AGENT_ID,
                                    strategy_id=strategy_id,
                                    ticker=ticker,
                                    market_date=market_date,
                                    context=context,
                                    model_identity=context["decision_model"],
                                    event_type="hybrid_no_veto_candidate",
                                    event_payload={
                                        "candidate_sha256": candidate[
                                            "candidate_sha256"
                                        ],
                                        "model_requested": False,
                                        "result": result,
                                    },
                                    started_at=observed_at,
                                )
                            )
                        result["attempt_id"] = attempt_id
                        return result
                model_input = _model_input(context, mode)
                model_request = (
                    agent_model_client.veto_request_payload(model_input)
                    if mode == "hybrid"
                    else agent_model_client.request_payload(model_input)
                )
                request_sha256 = canonical_sha256(model_request)
                with engine_db.transaction(con):
                    attempt_id = agent_shadow_store.insert_attempt(
                        con,
                        decision_window=window,
                        mode=mode,
                        policy_id=policy_id,
                        policy_registration_sha256=policy[
                            "registration_sha256"
                        ],
                        agent_id=AGENT_ID,
                        strategy_id=strategy_id,
                        ticker=ticker,
                        market_date=market_date,
                        context=context,
                        model_input=model_input,
                        model_request=model_request,
                        request_sha256=request_sha256,
                        model_identity=context["decision_model"],
                        started_at=observed_at,
                    )
                attempt = agent_shadow_store.find_window(con, window)
                if attempt is None or attempt[0] != attempt_id:  # pragma: no cover
                    raise ShadowRunError("new shadow attempt is unavailable")
                rows = agent_shadow_store.events(con, attempt_id)
            else:
                attempt = existing
                if (
                    attempt.mode != mode
                    or attempt.strategy_id != strategy_id
                    or attempt.ticker != ticker
                    or attempt.policy_id not in {None, policy_id}
                    or (
                        attempt.policy_id is not None
                        and attempt.policy_registration_sha256
                        != policy["registration_sha256"]
                    )
                ):
                    raise ShadowRunError("stored shadow decision window identity is invalid")
                window = attempt.decision_window
                rows = agent_shadow_store.events(con, int(attempt.id))
                result = _stored_result(rows)
                if result is not None:
                    return result
                model_input = loads_object(attempt.model_input)
                model_request = loads_object(attempt.model_request)
                request_sha256 = attempt.request_sha256
                if canonical_sha256(model_request) != request_sha256:
                    raise ShadowRunError("stored shadow request identity is invalid")
                if not unfinished:
                    recovery, recovery_payload = _resume_attempt(
                        con,
                        attempt,
                        now=observed_at,
                    )
                    if recovery == "uncertain":
                        return recovery_payload
                    response_payload = recovery_payload
        if existing is not None:
            return (
                _complete_hybrid_response(
                    factory,
                    attempt,
                    response_payload,
                    now=observed_at,
                )
                if mode == "hybrid"
                else _complete_response(
                    factory,
                    attempt,
                    response_payload,
                    now=observed_at,
                    repo_root=repo_root,
                )
            )

        try:
            response = generate(model_input)
        except agent_model_client.ModelOutputError as exc:
            if (
                exc.request_sha256 is not None
                and exc.request_sha256 != request_sha256
            ):
                raise ShadowRunError(
                    "connector malformed-output request identity differs from "
                    "the persisted request"
                ) from exc
            if mode == "hybrid":
                context = loads_object(attempt.context_payload)
                result = _hybrid_result(
                    attempt_id=int(attempt.id),
                    window=window,
                    event_type="hybrid_fallback_allow",
                    reason=f"model output failure; {exc}",
                    candidate=context["algorithm_candidate"],
                    decision=None,
                )
                event_type = "hybrid_fallback_allow"
            else:
                result = _result(
                    attempt_id=int(attempt.id),
                    decision_window=window,
                    status="malformed_output",
                    reason=str(exc),
                )
                event_type = "malformed_output"
            with _connection(factory) as con:
                agent_shadow_store.init_schema(con)
                _append(
                    con,
                    int(attempt.id),
                    event_type,
                    {
                        "error_type": type(exc).__name__,
                        "detail": str(exc),
                        "response_id": exc.response_id,
                        "request_sha256": exc.request_sha256,
                        "response_sha256": exc.response_sha256,
                        "usage": exc.usage,
                        "result": result,
                    },
                    now=observed_at,
                )
            return result
        except agent_model_client.ConnectorError as exc:
            if mode == "hybrid":
                context = loads_object(attempt.context_payload)
                result = _hybrid_result(
                    attempt_id=int(attempt.id),
                    window=window,
                    event_type="hybrid_fallback_allow",
                    reason=f"model transport failure; {exc}",
                    candidate=context["algorithm_candidate"],
                    decision=None,
                )
                event_type = "hybrid_fallback_allow"
            else:
                result = _result(
                    attempt_id=int(attempt.id),
                    decision_window=window,
                    status="transport_failure",
                    reason=str(exc),
                )
                event_type = "transport_failure"
            with _connection(factory) as con:
                agent_shadow_store.init_schema(con)
                _append(
                    con,
                    int(attempt.id),
                    event_type,
                    {
                        "error_type": type(exc).__name__,
                        "detail": str(exc),
                        "result": result,
                    },
                    now=observed_at,
                )
            return result

        if response.request_sha256 != request_sha256:
            raise ShadowRunError("connector request identity differs from the persisted request")
        expected_model = loads_object(attempt.context_payload)["decision_model"]
        if (
            response.model != expected_model["model"]
            or response.model_version != expected_model["model_version"]
            or response.proxy_version != expected_model["required_proxy_version"]
            or response.traecli_runtime
            != expected_model["required_traecli_runtime"]
            or response.model_catalog_entry_sha256
            != expected_model["model_catalog_entry_sha256"]
        ):
            raise ShadowRunError("connector response identity differs from the persisted context")
        response_payload = {
            "output": response.output,
            "response_id": response.response_id,
            "model": response.model,
            "model_version": response.model_version,
            "proxy_version": response.proxy_version,
            "traecli_runtime": response.traecli_runtime,
            "model_catalog_entry_sha256": response.model_catalog_entry_sha256,
            "request_sha256": response.request_sha256,
            "usage": response.usage,
        }
        with _connection(factory) as con:
            agent_shadow_store.init_schema(con)
            _append(
                con,
                int(attempt.id),
                "model_response",
                response_payload,
                now=observed_at,
            )
        return (
            _complete_hybrid_response(
                factory,
                attempt,
                response_payload,
                now=observed_at,
            )
            if mode == "hybrid"
            else _complete_response(
                factory,
                attempt,
                response_payload,
                now=observed_at,
                repo_root=repo_root,
            )
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("strategy_id")
    parser.add_argument("ticker")
    parser.add_argument("--mode", required=True, choices=("agent_only", "hybrid"))
    parser.add_argument(
        "--policy-id",
        default="dual_momentum_agent_shadow_v1",
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)
    try:
        result = run(
            args.strategy_id,
            args.ticker,
            mode=args.mode,
            policy_id=args.policy_id,
            database=args.database,
        )
    except (
        ShadowRunError,
        agent_context.ContextError,
        agent_shadow_store.IdentifierSpaceExhausted,
        duckdb.Error,
        OSError,
    ) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
