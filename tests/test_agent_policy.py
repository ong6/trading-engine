"""Agent and hybrid policy registrations remain isolated and source-bound."""

from __future__ import annotations

import json

import pytest

from server import (
    agent_context,
    agent_policy,
    agent_policy_read_models,
    agent_shadow_store,
    agent_store,
)
from tests.agent_test_helpers import fixed_etf_market


def test_registry_freezes_agent_only_and_hybrid_without_creating_books(con):
    fixed_etf_market(con)

    registry = agent_policy.registry()
    policies = {item["mode"]: item for item in registry["policies"]}

    assert set(policies) == {"agent_only", "hybrid"}
    assert policies["agent_only"]["generation_enabled"] is True
    assert policies["agent_only"]["model_role"] == "independent_shadow_proposal"
    assert policies["hybrid"]["generation_enabled"] is True
    assert policies["hybrid"]["hybrid_behavior"] == "veto_only"
    assert (
        policies["hybrid"]["model_failure_policy"]
        == "unmodified_algorithm_signal"
    )
    assert {
        item["reserved_portfolio_id"] for item in registry["policies"]
    }.isdisjoint(
        {row[0] for row in con.execute("SELECT id FROM portfolios").fetchall()}
    )
    for policy in registry["policies"]:
        agent_policy.validate_live_registration(
            con,
            agent_policy.get(policy["id"]),
        )


def test_registry_rejects_source_hash_drift(tmp_path):
    payload = json.loads(agent_policy.REGISTRATION_PATH.read_text())
    payload["policies"][0]["strategy_config_sha256"] = "0" * 64
    path = tmp_path / "policies.json"
    path.write_text(json.dumps(payload))

    with pytest.raises(agent_policy.PolicyError, match="does not match source"):
        agent_policy.registry(path)


def test_reserved_book_can_be_inspected_but_not_used_by_shadow_generation(con):
    fixed_etf_market(con)
    policy = agent_policy.get("dual_momentum_agent_shadow_v1")
    con.execute(
        "INSERT INTO portfolios "
        "(id, name, strategy, config, created, active, cash, initial_cash, "
        "execution_profile) VALUES (?, 'reserved', 'agent_only_policy', '{}', "
        "DATE '2026-09-11', FALSE, 39000, 39000, 'baseline_v1')",
        [policy["reserved_portfolio_id"]],
    )

    with pytest.raises(agent_policy.PolicyError, match="already exists"):
        agent_policy.validate_live_registration(con, policy)
    with pytest.raises(agent_context.ContextError, match="already exists"):
        agent_context.build(con, "dual_momentum", "SPY")

    agent_policy.validate_live_registration(
        con,
        policy,
        allow_reserved_portfolio=True,
    )


def test_evaluation_never_pools_modes_or_legacy_evidence(con):
    fixed_etf_market(con)
    agent_shadow_store.init_schema(con)
    agent_store.init_schema(con)
    agent_id = "dual_momentum_agent_shadow_v1"
    hybrid_id = "dual_momentum_hybrid_veto_shadow_v1"
    con.execute(
        "INSERT INTO agent_shadow_attempts "
        "(id, decision_window, mode, policy_id, strategy_id, ticker, market_date) "
        "VALUES (1, 'legacy', 'agent_only', NULL, 'dual_momentum', 'SPY', "
        "DATE '2026-09-11'), "
        "(2, 'agent', 'agent_only', ?, 'dual_momentum', 'SPY', DATE '2026-09-30'), "
        "(3, 'hybrid', 'hybrid', ?, 'dual_momentum', 'SPY', DATE '2026-09-30')",
        [agent_id, hybrid_id],
    )
    con.execute(
        "INSERT INTO agent_proposals "
        "(id, proposal_id, mode, policy_id) VALUES "
        "(1, 'legacy-proposal', 'hybrid', NULL), "
        "(2, 'agent-proposal', 'agent_only', ?), "
        "(3, 'hybrid-proposal', 'hybrid', ?)",
        [agent_id, hybrid_id],
    )
    con.execute(
        "INSERT INTO agent_shadow_events "
        "(id, attempt_id, event_type, payload, occurred_at) VALUES "
        "(1, 1, 'no_action', '{}', TIMESTAMP '2026-09-13 12:00:00'), "
        "(2, 2, 'proposal_result', '{}', TIMESTAMP '2026-10-01 12:00:00'), "
        "(3, 3, 'hybrid_veto', '{}', TIMESTAMP '2026-10-01 12:00:00')"
    )

    result = agent_policy_read_models.evaluation(con)
    by_mode = {item["mode"]: item for item in result["policies"]}

    assert result["evidence_pooling"] == "prohibited"
    assert result["performance_claim"] == "none"
    assert by_mode["agent_only"]["attempt_count"] == 1
    assert by_mode["agent_only"]["proposal_count"] == 1
    assert by_mode["hybrid"]["attempt_count"] == 1
    assert by_mode["hybrid"]["proposal_count"] == 1
    assert by_mode["hybrid"]["generation_enabled"] is True
    assert by_mode["agent_only"]["terminal_outcomes"]["proposal_result"] == 1
    assert by_mode["agent_only"]["terminal_outcomes"]["hybrid_veto"] == 0
    assert by_mode["hybrid"]["terminal_outcomes"]["hybrid_veto"] == 1
    assert by_mode["hybrid"]["terminal_outcomes"]["proposal_result"] == 0
    assert result["legacy_unregistered"] == {
        "policy_id": "legacy_unregistered",
        "mode": "legacy",
        "attempt_count": 1,
        "proposal_count": 1,
        "terminal_outcomes": {
            event_type: int(event_type == "no_action")
            for event_type in agent_policy_read_models.TERMINAL_OUTCOMES
        },
        "included_in_registered_policy_evaluation": False,
    }


def test_evaluation_rejects_unknown_policy_evidence(con):
    fixed_etf_market(con)
    agent_shadow_store.init_schema(con)
    con.execute(
        "INSERT INTO agent_shadow_attempts "
        "(id, decision_window, mode, policy_id, strategy_id, ticker, market_date) "
        "VALUES (1, 'unknown', 'agent_only', 'unknown-policy', "
        "'dual_momentum', 'SPY', DATE '2026-09-30')"
    )

    with pytest.raises(ValueError, match="unregistered policy"):
        agent_policy_read_models.evaluation(con)
