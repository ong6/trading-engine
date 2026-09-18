"""Retained agent-only evidence is loaded without caller-supplied trust hashes."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import pytest

from engine.lib.provenance import canonical_sha256
from server import (
    agent_model_client,
    agent_paper_evidence,
    agent_shadow_runner,
)
from server.broker_contract import SubmitOrderRequest
from tests.agent_test_helpers import complete_dual_momentum_history, fixed_etf_market
from tests.test_agent_shadow_runner import connector_result

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


@contextmanager
def _no_lock(_path):
    yield


@contextmanager
def _borrowed_connection(factory):
    yield factory()


def _accepted(con, monkeypatch):
    fixed_etf_market(con)
    complete_dual_momentum_history(con)
    monkeypatch.setattr(agent_shadow_runner, "advisory_file_lock", _no_lock)
    monkeypatch.setattr(agent_shadow_runner, "_connection", _borrowed_connection)
    monkeypatch.setattr(agent_shadow_runner, "is_month_signal", lambda *_args: True)

    def generate(model_input):
        context = model_input["context"]
        return connector_result(
            model_input,
            {
                "schema_version": 1,
                "decision": "proposal",
                "side": "buy",
                "max_notional": 1_000.0,
                "stop": 90.0,
                "confidence": 0.6,
                "thesis": "Retained evidence supports a bounded paper candidate.",
                "invalidation": "Invalidate if the retained evidence expires.",
                "evidence_ids": [context["context_sha256"]],
            },
        )

    return agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="agent_only",
        generate=generate,
        connection_factory=lambda: con,
        now=NOW,
    )


def _request(*, quantity=5.0, symbol="SPY", account_id=None):
    return SubmitOrderRequest(
        idempotency_key="future-paper-order-1",
        account_id=account_id or "agent_dual_momentum_shadow_v1",
        symbol=symbol,
        side="buy",
        quantity=quantity,
        signal_date=date(2026, 9, 11),
    )


def _hybrid_context(monkeypatch, *, orders):
    original = agent_shadow_runner.agent_context.build

    def build(con, strategy_id, ticker, **kwargs):
        payload = original(con, strategy_id, ticker, **kwargs)
        candidate = payload["algorithm_candidate"]
        body = {
            **candidate,
            "status": "materialized",
            "cadence_admitted": True,
            "orders": orders,
            "order_count": len(orders),
            "buy_order_count": sum(order["side"] == "buy" for order in orders),
            "sell_order_count": sum(order["side"] == "sell" for order in orders),
        }
        body.pop("candidate_sha256", None)
        candidate = {**body, "candidate_sha256": canonical_sha256(body)}
        context_body = {**payload, "algorithm_candidate": candidate}
        context_body.pop("context_sha256")
        return {
            **context_body,
            "context_sha256": canonical_sha256(context_body),
        }

    monkeypatch.setattr(agent_shadow_runner.agent_context, "build", build)


def _hybrid_order(
    *,
    sequence=1,
    ticker="SPY",
    side="buy",
    quantity=10.0,
):
    return {
        "sequence": sequence,
        "portfolio_id": "dual_momentum",
        "ticker": ticker,
        "side": side,
        "quantity": quantity,
        "signal_date": "2026-09-11",
        "signal_close": 100.0,
        "signal_notional": quantity * 100.0,
        "veto_eligible": side == "buy",
    }


def _hybrid_request(
    *,
    symbol="SPY",
    side="buy",
    quantity=10.0,
    account_id="hybrid_dual_momentum_veto_shadow_v1",
):
    return SubmitOrderRequest(
        idempotency_key="future-hybrid-paper-order-1",
        account_id=account_id,
        symbol=symbol,
        side=side,
        quantity=quantity,
        signal_date=date(2026, 9, 11),
    )


def _hybrid_run(con, monkeypatch, *, orders, decision="allow"):
    fixed_etf_market(con)
    _hybrid_context(monkeypatch, orders=orders)
    monkeypatch.setattr(agent_shadow_runner, "advisory_file_lock", _no_lock)
    monkeypatch.setattr(agent_shadow_runner, "_connection", _borrowed_connection)
    monkeypatch.setattr(agent_shadow_runner, "is_month_signal", lambda *_args: True)

    def generate(model_input):
        candidate = model_input["context"]["algorithm_candidate"]
        return connector_result(
            model_input,
            {
                "schema_version": 1,
                "decision": decision,
                "candidate_sha256": candidate["candidate_sha256"],
                "reason": f"Retained evidence supports {decision}.",
                "evidence_ids": [candidate["candidate_sha256"]],
            },
        )

    return agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="hybrid",
        policy_id="dual_momentum_hybrid_veto_shadow_v1",
        generate=generate,
        connection_factory=lambda: con,
        now=NOW,
    )


def test_loader_derives_agent_only_binding_from_complete_retained_path(
    con,
    monkeypatch,
):
    result = _accepted(con, monkeypatch)
    counts_before = {
        table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "agent_shadow_attempts",
            "agent_shadow_events",
            "agent_proposals",
            "sim_orders",
        )
    }

    loaded = agent_paper_evidence.load_agent_only_intent(
        con,
        _request(),
        decision_window_id=result["decision_window"],
    )

    assert loaded.attempt_id == result["attempt_id"]
    assert loaded.proposal_record_id == result["proposal_result"]["proposal_record_id"]
    assert len(loaded.terminal_event_sha256) == 64
    assert len(loaded.evidence_sha256) == 64
    assert loaded.execution_authority == "none"
    assert loaded.bindings.mode == "agent_only"
    assert loaded.bindings.proposal_status == "shadow_accepted"
    assert loaded.bindings.validation_status == "pass"
    assert loaded.bindings.decision_window_id == result["decision_window"]
    assert loaded.bindings.max_notional == 1_000.0
    assert loaded.bindings.proposal_expires_at > NOW
    assert loaded.signal_close == 120.0
    assert loaded.request_notional == 600.0
    assert loaded.stop == 90.0
    assert loaded.confidence == 0.6
    assert loaded.thesis == "Retained evidence supports a bounded paper candidate."
    assert loaded.invalidation == "Invalidate if the retained evidence expires."
    assert loaded.evidence_observed_at >= NOW
    assert {
        table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in counts_before
    } == counts_before


@pytest.mark.parametrize(
    ("broker_request", "detail"),
    [
        (_request(quantity=9.0), "does not match"),
        (_request(symbol="EFA"), "does not match"),
        (_request(account_id="different-paper-account"), "does not match"),
    ],
)
def test_loader_rejects_request_outside_retained_proposal(
    con,
    monkeypatch,
    broker_request,
    detail,
):
    result = _accepted(con, monkeypatch)

    with pytest.raises(agent_paper_evidence.AgentPaperEvidenceError, match=detail):
        agent_paper_evidence.load_agent_only_intent(
            con,
            broker_request,
            decision_window_id=result["decision_window"],
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE agent_shadow_attempts SET request_sha256 = repeat('f', 64)",
        "UPDATE agent_shadow_events SET payload = '{}' WHERE event_type = 'model_response'",
        "UPDATE agent_proposals SET proposal_sha256 = repeat('f', 64)",
        "UPDATE agent_proposals SET validation_payload = '{}'",
        "UPDATE agent_proposals SET validated_context = '{}'",
        "UPDATE audit_log SET actor = 'agent:tampered'",
    ],
)
def test_loader_fails_closed_on_retained_evidence_tampering(
    con,
    monkeypatch,
    mutation,
):
    result = _accepted(con, monkeypatch)
    con.execute(mutation)

    with pytest.raises(agent_paper_evidence.AgentPaperEvidenceError):
        agent_paper_evidence.load_agent_only_intent(
            con,
            _request(),
            decision_window_id=result["decision_window"],
        )


def test_loader_rejects_non_proposal_terminal_path(con, monkeypatch):
    fixed_etf_market(con)
    monkeypatch.setattr(agent_shadow_runner, "advisory_file_lock", _no_lock)
    monkeypatch.setattr(agent_shadow_runner, "_connection", _borrowed_connection)
    monkeypatch.setattr(agent_shadow_runner, "is_month_signal", lambda *_args: True)
    result = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="agent_only",
        generate=lambda model_input: connector_result(
            model_input,
            {
                "schema_version": 1,
                "decision": "no_action",
                "reason": "No retained proposal.",
            },
        ),
        connection_factory=lambda: con,
        now=NOW,
    )

    with pytest.raises(
        agent_paper_evidence.AgentPaperEvidenceError,
        match="event sequence",
    ):
        agent_paper_evidence.load_agent_only_intent(
            con,
            _request(),
            decision_window_id=result["decision_window"],
        )


def test_loader_rejects_unversioned_or_alternate_model_tampering(con, monkeypatch):
    result = _accepted(con, monkeypatch)
    con.execute(
        "UPDATE agent_shadow_attempts SET model = 'alternate-model' "
        "WHERE id = ?",
        [result["attempt_id"]],
    )

    with pytest.raises(
        agent_paper_evidence.AgentPaperEvidenceError,
        match="attempt binding",
    ):
        agent_paper_evidence.load_agent_only_intent(
            con,
            _request(),
            decision_window_id=result["decision_window"],
        )

    assert agent_model_client.MODEL == "GPT-5.6-Sol:max"


def test_hybrid_loader_derives_allow_binding_without_writes(con, monkeypatch):
    result = _hybrid_run(
        con,
        monkeypatch,
        orders=[_hybrid_order()],
    )
    counts_before = {
        table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("agent_shadow_attempts", "agent_shadow_events", "sim_orders")
    }

    loaded = agent_paper_evidence.load_hybrid_intent(
        con,
        _hybrid_request(),
        decision_window_id=result["decision_window"],
    )

    assert loaded.attempt_id == result["attempt_id"]
    assert loaded.execution_authority == "none"
    assert len(loaded.terminal_event_sha256) == 64
    assert len(loaded.evidence_sha256) == 64
    assert loaded.bindings.mode == "hybrid"
    assert loaded.bindings.terminal_status == "hybrid_allow"
    assert loaded.bindings.veto_eligible is True
    assert loaded.bindings.effective_order_included is True
    assert loaded.bindings.candidate_sha256 == result["proposal_result"][
        "candidate_sha256"
    ]
    assert loaded.bindings.effective_orders_sha256 == result["proposal_result"][
        "effective_orders_sha256"
    ]
    assert loaded.source_portfolio_id == "dual_momentum"
    assert loaded.signal_close == 100.0
    assert loaded.signal_notional == 1_000.0
    assert loaded.candidate_order_count == 1
    assert loaded.effective_order_count == 1
    assert loaded.vetoed_order_count == 0
    assert loaded.model_decision == "allow"
    assert loaded.decision_reason == "Retained evidence supports allow."
    assert {
        table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in counts_before
    } == counts_before


def test_hybrid_loader_refuses_vetoed_buy_but_loads_surviving_sell(
    con,
    monkeypatch,
):
    result = _hybrid_run(
        con,
        monkeypatch,
        orders=[
            _hybrid_order(),
            _hybrid_order(sequence=2, ticker="EFA", side="sell", quantity=4.0),
        ],
        decision="veto",
    )

    with pytest.raises(
        agent_paper_evidence.AgentPaperEvidenceError,
        match="effective order set",
    ):
        agent_paper_evidence.load_hybrid_intent(
            con,
            _hybrid_request(),
            decision_window_id=result["decision_window"],
        )

    loaded = agent_paper_evidence.load_hybrid_intent(
        con,
        _hybrid_request(symbol="EFA", side="sell", quantity=4.0),
        decision_window_id=result["decision_window"],
    )
    assert loaded.bindings.terminal_status == "hybrid_veto"
    assert loaded.bindings.veto_eligible is False
    assert loaded.bindings.side == "sell"


def test_hybrid_loader_accepts_exact_transport_fallback(con, monkeypatch):
    fixed_etf_market(con)
    _hybrid_context(monkeypatch, orders=[_hybrid_order()])
    monkeypatch.setattr(agent_shadow_runner, "advisory_file_lock", _no_lock)
    monkeypatch.setattr(agent_shadow_runner, "_connection", _borrowed_connection)
    monkeypatch.setattr(agent_shadow_runner, "is_month_signal", lambda *_args: True)
    result = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="hybrid",
        policy_id="dual_momentum_hybrid_veto_shadow_v1",
        generate=lambda _model_input: (_ for _ in ()).throw(
            agent_model_client.ConnectorError("Trae proxy is unavailable")
        ),
        connection_factory=lambda: con,
        now=NOW,
    )

    loaded = agent_paper_evidence.load_hybrid_intent(
        con,
        _hybrid_request(),
        decision_window_id=result["decision_window"],
    )

    assert loaded.bindings.terminal_status == "hybrid_fallback_allow"
    assert loaded.bindings.veto_eligible is True


def test_hybrid_loader_accepts_exact_model_output_fallback(con, monkeypatch):
    fixed_etf_market(con)
    _hybrid_context(monkeypatch, orders=[_hybrid_order()])
    monkeypatch.setattr(agent_shadow_runner, "advisory_file_lock", _no_lock)
    monkeypatch.setattr(agent_shadow_runner, "_connection", _borrowed_connection)
    monkeypatch.setattr(agent_shadow_runner, "is_month_signal", lambda *_args: True)

    def malformed(model_input):
        request_sha256 = canonical_sha256(
            agent_model_client.veto_request_payload(model_input)
        )
        raise agent_model_client.ModelOutputError(
            "model output is not one strict JSON object",
            response_id="resp-malformed",
            request_sha256=request_sha256,
            response_sha256="d" * 64,
            usage={"input_tokens": 50, "output_tokens": 3, "total_tokens": 53},
        )

    result = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="hybrid",
        policy_id="dual_momentum_hybrid_veto_shadow_v1",
        generate=malformed,
        connection_factory=lambda: con,
        now=NOW,
    )

    loaded = agent_paper_evidence.load_hybrid_intent(
        con,
        _hybrid_request(),
        decision_window_id=result["decision_window"],
    )
    assert loaded.bindings.terminal_status == "hybrid_fallback_allow"


def test_hybrid_loader_accepts_exact_invalid_veto_fallback(con, monkeypatch):
    fixed_etf_market(con)
    _hybrid_context(monkeypatch, orders=[_hybrid_order()])
    monkeypatch.setattr(agent_shadow_runner, "advisory_file_lock", _no_lock)
    monkeypatch.setattr(agent_shadow_runner, "_connection", _borrowed_connection)
    monkeypatch.setattr(agent_shadow_runner, "is_month_signal", lambda *_args: True)

    def invalid(model_input):
        candidate = model_input["context"]["algorithm_candidate"]
        return connector_result(
            model_input,
            {
                "schema_version": 1,
                "decision": "veto",
                "candidate_sha256": "f" * 64,
                "reason": "This response references another candidate.",
                "evidence_ids": [candidate["candidate_sha256"]],
            },
        )

    result = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="hybrid",
        policy_id="dual_momentum_hybrid_veto_shadow_v1",
        generate=invalid,
        connection_factory=lambda: con,
        now=NOW,
    )

    loaded = agent_paper_evidence.load_hybrid_intent(
        con,
        _hybrid_request(),
        decision_window_id=result["decision_window"],
    )
    assert loaded.bindings.terminal_status == "hybrid_fallback_allow"


def test_hybrid_loader_accepts_exact_interrupted_fallback(con, monkeypatch):
    fixed_etf_market(con)
    _hybrid_context(monkeypatch, orders=[_hybrid_order()])
    monkeypatch.setattr(agent_shadow_runner, "advisory_file_lock", _no_lock)
    monkeypatch.setattr(agent_shadow_runner, "_connection", _borrowed_connection)
    monkeypatch.setattr(agent_shadow_runner, "is_month_signal", lambda *_args: True)
    with pytest.raises(BaseException, match="simulated process death"):
        agent_shadow_runner.run(
            "dual_momentum",
            "SPY",
            mode="hybrid",
            policy_id="dual_momentum_hybrid_veto_shadow_v1",
            generate=lambda _model_input: (_ for _ in ()).throw(
                BaseException("simulated process death")
            ),
            connection_factory=lambda: con,
            now=NOW,
        )
    result = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="hybrid",
        policy_id="dual_momentum_hybrid_veto_shadow_v1",
        generate=lambda _model_input: pytest.fail("must not retry"),
        connection_factory=lambda: con,
        now=NOW + timedelta(minutes=1),
    )

    loaded = agent_paper_evidence.load_hybrid_intent(
        con,
        _hybrid_request(),
        decision_window_id=result["decision_window"],
    )
    assert loaded.bindings.terminal_status == "hybrid_fallback_allow"


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE agent_shadow_attempts SET context_sha256 = repeat('f', 64)",
        "UPDATE agent_shadow_events SET payload = '{}' "
        "WHERE event_type = 'model_response'",
        "UPDATE agent_shadow_events SET payload = '{}' "
        "WHERE event_type = 'hybrid_allow'",
        "UPDATE agent_shadow_events SET event_type = 'hybrid_veto' "
        "WHERE event_type = 'hybrid_allow'",
    ],
)
def test_hybrid_loader_fails_closed_on_retained_evidence_tampering(
    con,
    monkeypatch,
    mutation,
):
    result = _hybrid_run(con, monkeypatch, orders=[_hybrid_order()])
    con.execute(mutation)

    with pytest.raises(agent_paper_evidence.AgentPaperEvidenceError):
        agent_paper_evidence.load_hybrid_intent(
            con,
            _hybrid_request(),
            decision_window_id=result["decision_window"],
        )


def test_hybrid_loader_rejects_hash_consistent_candidate_state_tampering(
    con,
    monkeypatch,
):
    _hybrid_run(con, monkeypatch, orders=[_hybrid_order()])
    raw = con.execute("SELECT context_payload FROM agent_shadow_attempts").fetchone()[0]
    context = agent_paper_evidence.loads_object(raw)
    state = context["algorithm_candidate"]["portfolio_state"]
    state["cash"] = state["cash"] + 1
    state_body = {key: value for key, value in state.items() if key != "state_sha256"}
    state["state_sha256"] = canonical_sha256(state_body)
    candidate = context["algorithm_candidate"]
    candidate_body = {
        key: value for key, value in candidate.items() if key != "candidate_sha256"
    }
    candidate["candidate_sha256"] = canonical_sha256(candidate_body)
    context_body = {
        key: value for key, value in context.items() if key != "context_sha256"
    }
    context["context_sha256"] = canonical_sha256(context_body)

    with pytest.raises(
        agent_paper_evidence.AgentPaperEvidenceError,
        match="portfolio state",
    ):
        agent_paper_evidence._algorithm_candidate(context)


@pytest.mark.parametrize(
    "broker_request",
    [
        _hybrid_request(account_id="wrong-hybrid-account"),
        _hybrid_request(symbol="EFA"),
        _hybrid_request(side="sell"),
        _hybrid_request(quantity=9.0),
        SubmitOrderRequest(
            idempotency_key="future-hybrid-paper-order-1",
            account_id="hybrid_dual_momentum_veto_shadow_v1",
            symbol="SPY",
            side="buy",
            quantity=10.0,
            signal_date=date(2026, 9, 10),
        ),
    ],
)
def test_hybrid_loader_rejects_request_outside_effective_order(
    con,
    monkeypatch,
    broker_request,
):
    result = _hybrid_run(con, monkeypatch, orders=[_hybrid_order()])

    with pytest.raises(
        agent_paper_evidence.AgentPaperEvidenceError,
        match="effective order set",
    ):
        agent_paper_evidence.load_hybrid_intent(
            con,
            broker_request,
            decision_window_id=result["decision_window"],
        )


def test_module_has_no_mutation_or_execution_surface():
    assert {
        "insert",
        "update",
        "submit",
        "submit_order",
        "cancel_order",
        "activate",
        "authorize",
    }.isdisjoint(vars(agent_paper_evidence))
