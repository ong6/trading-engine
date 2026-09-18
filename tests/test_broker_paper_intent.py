"""Pure lease-to-intent eligibility checks remain non-authorizing."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from engine.lib.provenance import canonical_sha256
from server import (
    agent_model_client,
    broker_paper_intent,
    broker_paper_lease,
    broker_risk,
)
from server.broker_contract import SubmitOrderRequest

NOW = datetime(2026, 9, 14, 14, 30, 30, tzinfo=timezone.utc)
SIGNAL_DATE = date(2026, 9, 14)
HASHES = tuple(format(index, "x") * 64 for index in range(1, 14))


def _risk_policy(**changes):
    values = {
        "policy_id": "paper-risk-v1",
        "account_id": "agent-paper-account",
        "strategy_id": "dual-momentum",
        "release_sha256": HASHES[0],
        "strategy_config_sha256": HASHES[1],
        "execution_profile_id": "baseline-v1",
        "execution_profile_sha256": HASHES[2],
        "allowed_symbols": ("BIL", "EFA", "SPY"),
        "capital_ceiling": 39_000.0,
        "max_gross_exposure": 39_000.0,
        "max_position_fraction": 0.50,
        "max_order_notional": 10_000.0,
        "max_daily_turnover": 20_000.0,
        "max_daily_orders": 8,
        "max_participation": 0.01,
        "max_daily_loss_fraction": 0.02,
        "max_drawdown_fraction": 0.10,
        "max_reference_deviation_fraction": 0.02,
        "max_quote_age_seconds": 60,
        "max_reconciliation_age_seconds": 60,
        "decision_ttl_seconds": 30,
    }
    values.update(changes)
    return broker_risk.RiskPolicy(**values)


def _risk_identity(policy=None):
    policy = policy or _risk_policy()
    return broker_risk.RiskIdentity(
        policy_id=policy.policy_id,
        strategy_id=policy.strategy_id,
        release_sha256=policy.release_sha256,
        strategy_config_sha256=policy.strategy_config_sha256,
        execution_profile_id=policy.execution_profile_id,
        execution_profile_sha256=policy.execution_profile_sha256,
    )


def _request(**changes):
    values = {
        "idempotency_key": "agent-paper-intent-1",
        "account_id": "agent-paper-account",
        "symbol": "SPY",
        "side": "buy",
        "quantity": 10.0,
        "signal_date": SIGNAL_DATE,
    }
    values.update(changes)
    return SubmitOrderRequest(**values)


def _snapshot(**changes):
    values = {
        "as_of": SIGNAL_DATE,
        "quote_date": SIGNAL_DATE,
        "observed_at": NOW,
        "quote_at": NOW - timedelta(seconds=5),
        "reconciliation_at": NOW - timedelta(seconds=2),
        "account_snapshot_sha256": HASHES[3],
        "reconciliation_sha256": HASHES[4],
        "market_state_sha256": HASHES[5],
        "performance_state_sha256": HASHES[6],
        "operational_control_sha256": HASHES[7],
        "quote_price": 100.0,
        "reference_price": 100.5,
        "median_dollar_volume": 1_000_000.0,
        "account_active": True,
        "margin_enabled": False,
        "instrument_type": "etf",
        "instrument_active": True,
        "instrument_liquid": True,
        "instrument_quarantined": False,
        "market_session_open": True,
        "clock_synchronized": True,
        "storage_healthy": True,
        "broker_healthy": True,
        "reconciled": True,
        "operational_halt": False,
        "corporate_action_clear": True,
        "currency": "USD",
        "cash": 39_000.0,
        "buying_power": 39_000.0,
        "equity": 39_000.0,
        "gross_exposure": 2_000.0,
        "symbol_exposure": 1_000.0,
        "held_quantity": 20.0,
        "pending_sell_quantity": 0.0,
        "reserved_buy_notional": 0.0,
        "reserved_symbol_buy_notional": 0.0,
        "reserved_turnover_notional": 0.0,
        "reserved_order_count": 0,
        "daily_turnover": 500.0,
        "daily_order_count": 1,
        "daily_pnl": -100.0,
        "drawdown_fraction": 0.03,
    }
    values.update(changes)
    return broker_risk.PreTradeSnapshot(**values)


def _policy_sha256(policy):
    payload = {
        **{
            field: getattr(policy, field)
            for field in policy.__dataclass_fields__
        },
        "allowed_symbols": list(policy.allowed_symbols),
    }
    return canonical_sha256(payload)


def _lease(policy=None, **changes):
    policy = policy or _risk_policy()
    model_identity = agent_model_client.identity()
    values = {
        "lease_id": "paper-lease-1",
        "approval_id": "operator-approval-1",
        "approved_by": "operator-1",
        "approval_evidence_sha256": HASHES[8],
        "authority_stage": "automatic_paper",
        "environment": "simulator",
        "mode": "agent_only",
        "policy_id": "dual-momentum-agent-shadow-v1",
        "policy_registration_sha256": HASHES[9],
        "account_id": policy.account_id,
        "strategy_id": policy.strategy_id,
        "strategy_config_sha256": policy.strategy_config_sha256,
        "data_snapshot_sha256": HASHES[10],
        "transport": model_identity["transport"],
        "endpoint": model_identity["endpoint"],
        "model": model_identity["model"],
        "model_version": "provider-revision-1",
        "required_proxy_version": model_identity["required_proxy_version"],
        "prompt_sha256": model_identity["instructions_sha256"],
        "toolset_sha256": model_identity["toolset_sha256"],
        "execution_profile_id": policy.execution_profile_id,
        "execution_profile_sha256": policy.execution_profile_sha256,
        "risk_policy_id": policy.policy_id,
        "risk_policy_sha256": _policy_sha256(policy),
        "release_manifest_sha256": policy.release_sha256,
        "authority_readiness_sha256": HASHES[11],
        "decision_window_id": "dual-momentum:2026-09-14",
        "allowed_symbols": policy.allowed_symbols,
        "capital_ceiling": policy.capital_ceiling,
        "max_order_notional": policy.max_order_notional,
        "max_orders": 3,
        "approved_at": NOW - timedelta(seconds=2),
        "not_before": NOW - timedelta(seconds=1),
        "expires_at": NOW + timedelta(seconds=60),
    }
    values.update(changes)
    return broker_paper_lease.PaperAuthorityLease(**values)


def _candidate(lease):
    fields = (
        "mode",
        "policy_id",
        "policy_registration_sha256",
        "account_id",
        "strategy_id",
        "strategy_config_sha256",
        "data_snapshot_sha256",
        "transport",
        "endpoint",
        "model",
        "model_version",
        "required_proxy_version",
        "prompt_sha256",
        "toolset_sha256",
        "execution_profile_id",
        "execution_profile_sha256",
        "risk_policy_id",
        "risk_policy_sha256",
        "release_manifest_sha256",
        "authority_readiness_sha256",
        "decision_window_id",
        "allowed_symbols",
        "capital_ceiling",
        "max_order_notional",
        "max_orders",
    )
    bindings = broker_paper_lease.PaperAuthorityBindings(
        **{field: getattr(lease, field) for field in fields},
        release_eligible=True,
        automatic_paper_gate_passed=True,
        startup_assessment_sha256=HASHES[12],
        startup_status="reconciled_halted",
        startup_safe_halted=True,
        startup_submission_authority="none",
    )
    return broker_paper_lease.assess_candidate(
        lease,
        bindings,
        trusted_lease_sha256=lease.sha256(),
        approval_evidence_sha256=lease.approval_evidence_sha256,
        now=NOW,
    )


def _intent_bindings(lease, **changes):
    request = _request()
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
    values = {
        "mode": lease.mode,
        "policy_id": lease.policy_id,
        "policy_registration_sha256": lease.policy_registration_sha256,
        "data_snapshot_sha256": lease.data_snapshot_sha256,
        "context_sha256": HASHES[3],
        "proposal_id": "agent-paper-proposal-1",
        "proposal_sha256": HASHES[4],
        "proposal_status": "shadow_accepted",
        "validation_sha256": HASHES[5],
        "validation_status": "pass",
        "decision_window_id": lease.decision_window_id,
        "request_sha256": canonical_sha256(request_payload),
        "symbol": request.symbol,
        "side": request.side,
        "max_notional": 1_100.0,
        "signal_date": SIGNAL_DATE,
        "proposal_expires_at": NOW + timedelta(seconds=45),
    }
    values.update(changes)
    return broker_paper_intent.PaperIntentBindings(**values)


def _usage(lease, **changes):
    values = {
        "lease_id": lease.lease_id,
        "lease_sha256": lease.sha256(),
        "consumed_order_count": 1,
        "consumed_notional": 2_000.0,
    }
    values.update(changes)
    return broker_paper_intent.PaperLeaseUsage(**values)


def _inputs():
    policy = _risk_policy()
    lease = _lease(policy)
    request = _request()
    risk_decision = broker_risk.evaluate(
        policy,
        _risk_identity(policy),
        request,
        _snapshot(),
    )
    candidate = _candidate(lease)
    bindings = _intent_bindings(lease)
    usage = _usage(lease)
    return lease, candidate, request, risk_decision, bindings, usage


def _assess(
    lease,
    candidate,
    request,
    risk_decision,
    bindings,
    usage,
    **changes,
):
    values = {
        "trusted_assessment_sha256": candidate["assessment_sha256"],
        "trusted_intent_bindings_sha256": bindings.sha256(),
        "trusted_usage_sha256": usage.sha256(),
        "now": NOW + timedelta(seconds=1),
    }
    values.update(changes)
    return broker_paper_intent.assess_future_consumption(
        lease,
        candidate,
        request,
        risk_decision,
        bindings,
        usage,
        **values,
    )


def test_exact_intent_is_only_eligible_for_future_consumption():
    inputs = _inputs()

    result = _assess(*inputs)

    assert result["status"] == "eligible_for_future_consumption"
    assert result["candidate_eligible"] is True
    assert result["activation_implemented"] is False
    assert result["consumption_implemented"] is False
    assert result["submission_authority"] == "none"
    assert result["order_notional"] == 1_005.0
    assert result["resulting_consumed_order_count"] == 2
    assert result["resulting_consumed_notional"] == 3_005.0
    assert result["blockers"] == []
    assert all(gate["status"] == "pass" for gate in result["gates"])
    body = {key: value for key, value in result.items() if key != "eligibility_sha256"}
    assert result["eligibility_sha256"] == canonical_sha256(body)


@pytest.mark.parametrize(
    ("mutate", "gate"),
    [
        (
            lambda values: values.__setitem__(
                4,
                replace(values[4], policy_id="different-agent-policy"),
            ),
            "trusted_agent_intent",
        ),
        (
            lambda values: values.__setitem__(
                2,
                replace(values[2], quantity=9.0),
            ),
            "exact_risk_request",
        ),
        (
            lambda values: values.__setitem__(
                5,
                replace(values[5], consumed_order_count=3),
            ),
            "lease_budget",
        ),
        (
            lambda values: values.__setitem__(
                5,
                replace(values[5], consumed_notional=38_500.0),
            ),
            "lease_budget",
        ),
        (
            lambda values: values.__setitem__(
                4,
                replace(values[4], max_notional=1_000.0),
            ),
            "trusted_agent_intent",
        ),
        (
            lambda values: values.__setitem__(
                4,
                replace(
                    values[4],
                    proposal_expires_at=NOW + timedelta(milliseconds=500),
                ),
            ),
            "trusted_agent_intent",
        ),
    ],
)
def test_agent_request_and_budget_drift_fail_closed(mutate, gate):
    values = list(_inputs())
    mutate(values)

    result = _assess(*values)

    assert result["status"] == "blocked"
    assert result["candidate_eligible"] is False
    assert result["submission_authority"] == "none"
    assert gate in result["blockers"]


def test_untrusted_usage_hash_fails_budget_gate():
    inputs = _inputs()

    result = _assess(*inputs, trusted_usage_sha256="f" * 64)

    assert "lease_budget" in result["blockers"]
    assert result["consumption_implemented"] is False


def test_untrusted_agent_intent_bridge_fails_closed():
    inputs = _inputs()

    result = _assess(*inputs, trusted_intent_bindings_sha256="f" * 64)

    assert "trusted_agent_intent" in result["blockers"]
    assert result["submission_authority"] == "none"


def _hybrid_inputs(*, quantity=None):
    policy = _risk_policy()
    lease = _lease(
        policy,
        mode="hybrid",
        policy_id="dual-momentum-hybrid-veto-shadow-v1",
        prompt_sha256=agent_model_client.identity(role="veto")[
            "instructions_sha256"
        ],
    )
    request = _request()
    risk_decision = broker_risk.evaluate(
        policy,
        _risk_identity(policy),
        request,
        _snapshot(),
    )
    candidate = _candidate(lease)
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
    bindings = broker_paper_intent.HybridPaperIntentBindings(
        mode="hybrid",
        policy_id=lease.policy_id,
        policy_registration_sha256=lease.policy_registration_sha256,
        data_snapshot_sha256=lease.data_snapshot_sha256,
        context_sha256=HASHES[3],
        decision_window_id=lease.decision_window_id,
        candidate_sha256=HASHES[4],
        terminal_event_sha256=HASHES[5],
        terminal_status="hybrid_allow",
        effective_orders_sha256=HASHES[6],
        effective_order_included=True,
        veto_eligible=True,
        request_sha256=canonical_sha256(request_payload),
        symbol=request.symbol,
        side=request.side,
        quantity=request.quantity if quantity is None else quantity,
        signal_date=request.signal_date,
        evidence_observed_at=NOW,
    )
    return lease, candidate, request, risk_decision, bindings, _usage(lease)


def test_hybrid_candidate_order_can_only_be_future_eligible():
    result = _assess(*_hybrid_inputs())

    assert result["status"] == "eligible_for_future_consumption"
    assert result["consumption_implemented"] is False
    assert result["submission_authority"] == "none"


def test_hybrid_request_quantity_drift_fails_closed():
    result = _assess(*_hybrid_inputs(quantity=11.0))

    assert "trusted_agent_intent" in result["blockers"]
    assert result["submission_authority"] == "none"


def test_hybrid_vetoed_buy_cannot_enter_the_future_consumption_bridge():
    values = list(_hybrid_inputs())

    with pytest.raises(
        broker_paper_intent.PaperIntentError,
        match="veto removed",
    ):
        replace(values[4], terminal_status="hybrid_veto")


def test_failed_or_expired_risk_decision_fails_closed():
    values = list(_inputs())
    policy = _risk_policy()
    values[3] = broker_risk.evaluate(
        policy,
        _risk_identity(policy),
        values[2],
        _snapshot(market_session_open=False),
    )

    failed = _assess(*values)
    expired = _assess(*_inputs(), now=NOW + timedelta(seconds=31))

    assert "risk_pass_and_freshness" in failed["blockers"]
    assert "risk_pass_and_freshness" in expired["blockers"]
    assert failed["submission_authority"] == expired["submission_authority"] == "none"


def test_lease_expiry_is_independent_from_risk_expiry():
    inputs = _inputs()

    result = _assess(*inputs, now=NOW + timedelta(seconds=60))

    assert "lease_time_window" in result["blockers"]
    assert result["candidate_eligible"] is False


def test_assessment_from_the_future_fails_lease_time_gate():
    values = list(_inputs())
    candidate = values[1]
    body = {
        **{
            key: value
            for key, value in candidate.items()
            if key != "assessment_sha256"
        },
        "observed_at": (NOW + timedelta(seconds=2)).isoformat().replace(
            "+00:00",
            "Z",
        ),
    }
    values[1] = {
        **body,
        "assessment_sha256": canonical_sha256(body),
    }

    result = _assess(
        *values,
        trusted_assessment_sha256=values[1]["assessment_sha256"],
    )

    assert "lease_time_window" in result["blockers"]
    assert result["submission_authority"] == "none"


def test_risk_policy_identity_must_match_lease():
    values = list(_inputs())
    different_policy = _risk_policy(policy_id="different-risk-policy")
    values[3] = broker_risk.evaluate(
        different_policy,
        _risk_identity(different_policy),
        values[2],
        _snapshot(),
    )

    result = _assess(*values)

    assert "risk_identity" in result["blockers"]
    assert result["submission_authority"] == "none"


def test_tampered_or_untrusted_candidate_assessment_is_rejected():
    values = list(_inputs())
    candidate = values[1]
    values[1] = {**candidate, "candidate_admissible": False}

    with pytest.raises(
        broker_paper_intent.PaperIntentError,
        match="assessment hash does not match",
    ):
        _assess(*values)
    with pytest.raises(
        broker_paper_intent.PaperIntentError,
        match="not externally trusted",
    ):
        _assess(*_inputs(), trusted_assessment_sha256="f" * 64)


def test_hash_valid_invented_candidate_gate_set_is_rejected():
    values = list(_inputs())
    candidate = values[1]
    body = {
        **{
            key: value
            for key, value in candidate.items()
            if key != "assessment_sha256"
        },
        "gates": [{"name": "invented_gate", "status": "pass"}],
    }
    values[1] = {
        **body,
        "assessment_sha256": canonical_sha256(body),
    }

    with pytest.raises(
        broker_paper_intent.PaperIntentError,
        match="assessment gates are invalid",
    ):
        _assess(
            *values,
            trusted_assessment_sha256=values[1]["assessment_sha256"],
        )


def test_contract_has_no_activation_consumption_persistence_or_submission_surface():
    forbidden = {
        "activate",
        "consume",
        "persist",
        "reserve",
        "submit",
        "renew",
        "revoke",
    }

    assert forbidden.isdisjoint(vars(broker_paper_intent))
    assert set(broker_paper_intent.assess_future_consumption.__globals__).isdisjoint(
        {
            "duckdb",
            "db",
            "http",
            "requests",
            "urllib",
            "socket",
            "subprocess",
            "os",
            "BrokerAdapter",
        }
    )
