"""Pure automatic-paper lease contract and admission tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from engine.lib.provenance import canonical_sha256
from server import agent_model_client, broker_paper_lease

NOW = datetime(2026, 9, 14, 14, 30, tzinfo=timezone.utc)
HASHES = tuple(format(index, "x") * 64 for index in range(13))


def _lease(**changes):
    model_identity = agent_model_client.identity()
    values = {
        "lease_id": "paper-lease-1",
        "approval_id": "operator-approval-1",
        "approved_by": "operator-1",
        "approval_evidence_sha256": HASHES[0],
        "authority_stage": "automatic_paper",
        "environment": "simulator",
        "mode": "agent_only",
        "policy_id": "dual_momentum_agent_shadow_v1",
        "policy_registration_sha256": HASHES[1],
        "account_id": "agent_dual_momentum_shadow_v1",
        "strategy_id": "dual_momentum",
        "strategy_config_sha256": HASHES[2],
        "data_snapshot_sha256": HASHES[3],
        "transport": model_identity["transport"],
        "endpoint": model_identity["endpoint"],
        "model": model_identity["model"],
        "model_version": "provider-revision-1",
        "required_proxy_version": model_identity["required_proxy_version"],
        "prompt_sha256": model_identity["instructions_sha256"],
        "toolset_sha256": model_identity["toolset_sha256"],
        "execution_profile_id": "baseline_v1",
        "execution_profile_sha256": HASHES[6],
        "risk_policy_id": "paper-risk-v1",
        "risk_policy_sha256": HASHES[7],
        "release_manifest_sha256": HASHES[8],
        "authority_readiness_sha256": HASHES[9],
        "decision_window_id": "dual-momentum:2026-09-14",
        "allowed_symbols": ("BIL", "EFA", "SPY"),
        "capital_ceiling": 39_000.0,
        "max_order_notional": 10_000.0,
        "max_orders": 3,
        "approved_at": NOW - timedelta(seconds=1),
        "not_before": NOW,
        "expires_at": NOW + timedelta(seconds=60),
    }
    values.update(changes)
    return broker_paper_lease.PaperAuthorityLease(**values)


def _bindings(lease=None, **changes):
    lease = lease or _lease()
    values = {
        field: getattr(lease, field)
        for field in (
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
    }
    values.update(
        {
            "release_eligible": True,
            "automatic_paper_gate_passed": True,
            "startup_assessment_sha256": HASHES[10],
            "startup_status": "reconciled_halted",
            "startup_safe_halted": True,
            "startup_submission_authority": "none",
        }
    )
    values.update(changes)
    return broker_paper_lease.PaperAuthorityBindings(**values)


def _assess(lease=None, bindings=None, **changes):
    lease = lease or _lease()
    values = {
        "trusted_lease_sha256": lease.sha256(),
        "approval_evidence_sha256": lease.approval_evidence_sha256,
        "now": NOW + timedelta(seconds=1),
    }
    values.update(changes)
    return broker_paper_lease.assess_candidate(
        lease,
        bindings or _bindings(lease),
        **values,
    )


def test_exact_candidate_can_only_be_admissible_for_future_activation():
    lease = _lease()
    result = _assess(lease)

    assert result["status"] == "admissible_for_future_activation"
    assert result["candidate_admissible"] is True
    assert result["activation_implemented"] is False
    assert result["submission_authority"] == "none"
    assert result["blockers"] == []
    assert all(gate["status"] == "pass" for gate in result["gates"])
    body = {key: value for key, value in result.items() if key != "assessment_sha256"}
    assert result["assessment_sha256"] == canonical_sha256(body)


@pytest.mark.parametrize(
    ("change", "gate"),
    [
        ({"trusted_lease_sha256": "f" * 64}, "trusted_approval_reference"),
        ({"approval_evidence_sha256": "f" * 64}, "trusted_approval_reference"),
        ({"now": NOW - timedelta(seconds=1)}, "lease_time_window"),
        ({"now": NOW + timedelta(seconds=60)}, "lease_time_window"),
    ],
)
def test_trust_and_time_fail_closed(change, gate):
    result = _assess(**change)

    assert result["status"] == "blocked"
    assert result["candidate_admissible"] is False
    assert result["submission_authority"] == "none"
    assert gate in result["blockers"]


@pytest.mark.parametrize(
    ("change", "gate"),
    [
        ({"policy_id": "different-policy"}, "immutable_runtime_bindings"),
        ({"decision_window_id": "different-window"}, "immutable_runtime_bindings"),
        ({"capital_ceiling": 38_999.0}, "bounded_risk_budget"),
        ({"max_order_notional": 9_999.0}, "bounded_risk_budget"),
        ({"max_orders": 2}, "bounded_risk_budget"),
        ({"release_eligible": False}, "reviewed_release"),
        ({"automatic_paper_gate_passed": False}, "automatic_paper_readiness"),
        ({"startup_status": "blocked"}, "reconciled_halted_startup"),
        ({"startup_safe_halted": False}, "reconciled_halted_startup"),
    ],
)
def test_current_bindings_must_match_and_pass_every_gate(change, gate):
    result = _assess(bindings=_bindings(**change))

    assert result["status"] == "blocked"
    assert result["candidate_admissible"] is False
    assert gate in result["blockers"]


@pytest.mark.parametrize(
    "change",
    [
        {"authority_stage": "shadow"},
        {"environment": "paper"},
        {"mode": "algorithm_only"},
        {"transport": "direct_provider"},
        {"endpoint": "https://api.openai.com/v1/responses"},
        {"model": "another-model"},
        {"model_version": "unversioned-catalog-alias"},
        {"required_proxy_version": "0.5"},
        {"prompt_sha256": HASHES[11]},
        {"toolset_sha256": HASHES[12]},
        {"allowed_symbols": ("SPY", "BIL")},
        {"capital_ceiling": float("nan")},
        {"max_order_notional": 40_000.0},
        {"max_orders": 0},
        {"expires_at": NOW + timedelta(seconds=301)},
        {"approved_at": NOW + timedelta(seconds=1)},
    ],
)
def test_lease_shape_rejects_broadened_or_invalid_authority(change):
    with pytest.raises(broker_paper_lease.PaperLeaseError):
        _lease(**change)


def test_lease_payload_is_detached_hash_bound_and_has_no_live_fields():
    lease = _lease()
    payload = lease.payload()

    assert payload["schema_version"] == 1
    assert payload["environment"] == "simulator"
    assert payload["authority_stage"] == "automatic_paper"
    assert payload["transport"] == "trae_cli_proxy"
    assert payload["endpoint"] == "http://127.0.0.1:8317/v1/responses"
    assert payload["allowed_symbols"] == ["BIL", "EFA", "SPY"]
    assert lease.sha256() == canonical_sha256(payload)
    assert {
        "broker",
        "credentials",
        "live",
        "token",
        "secret",
    }.isdisjoint(payload)
    assert {
        "issue",
        "sign",
        "persist",
        "activate",
        "consume",
        "renew",
        "revoke",
        "submit",
    }.isdisjoint(vars(broker_paper_lease))


def test_lease_and_bindings_are_immutable_values():
    lease = _lease()
    bindings = _bindings(lease)

    with pytest.raises(AttributeError):
        lease.max_orders = 4
    with pytest.raises(AttributeError):
        bindings.release_eligible = False
    assert replace(lease, max_orders=1).sha256() != lease.sha256()
