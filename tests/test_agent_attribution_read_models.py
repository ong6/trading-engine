"""Shadow attribution separates policy decisions without claiming returns."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256
from server import (
    agent_attribution_read_models,
    agent_context,
    agent_model_client,
    agent_policy,
    agent_shadow_runner,
    agent_shadow_store,
)
from tests.agent_test_helpers import complete_dual_momentum_history, fixed_etf_market

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


@contextmanager
def _no_lock(_path):
    yield


@contextmanager
def _borrowed_connection(factory):
    yield factory()


def _connector_result(model_input: dict, output: dict):
    request = agent_model_client.request_payload(model_input)
    return agent_model_client.ConnectorResult(
        output=output,
        response_id="resp-attribution",
        model=agent_model_client.MODEL,
        model_version=agent_model_client.MODEL_VERSION,
        proxy_version=agent_model_client.REQUIRED_PROXY_VERSION,
        traecli_runtime=agent_model_client.REQUIRED_TRAECLI_RUNTIME,
        model_catalog_entry_sha256=(
            agent_model_client.MODEL_CATALOG_ENTRY_SHA256
        ),
        request_sha256=canonical_sha256(request),
        usage={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
    )


def test_empty_attribution_contract_has_no_performance_claim(con):
    fixed_etf_market(con)

    payload = agent_attribution_read_models.attribution(con)

    assert payload == {
        "schema_version": 1,
        "registry_sha256": agent_policy.registry()["registry_sha256"],
        "attribution_scope": "registered_shadow_decision_contribution_only",
        "return_attribution_status": "unavailable_no_isolated_paper_portfolio",
        "performance_claim": "none",
        "evidence_pooling": "prohibited",
        "execution_authority": "none",
        "limit": 100,
        "matching_count": 0,
        "truncated": False,
        "legacy_attempt_count": 0,
        "legacy_included": False,
        "policy_summaries": [
            {
                "policy_id": policy["id"],
                "mode": policy["mode"],
                "completed_attempt_count": 0,
                "completed_market_sessions": 0,
                "terminal_outcomes": {
                    event_type: 0
                    for event_type in sorted(
                        agent_shadow_store.TERMINAL_EVENT_TYPES
                    )
                },
                "records_returned": 0,
                "reserved_portfolio_created": False,
                "return_attribution_status": (
                    "unavailable_no_isolated_paper_portfolio"
                ),
                "paper_book_attribution": {
                    "status": "unavailable_no_isolated_paper_portfolio",
                    "portfolio_id": policy["reserved_portfolio_id"],
                    "portfolio_created": False,
                    "persisted_contract_present": False,
                    "book_contract_sha256": None,
                    "attribution_start_date": None,
                    "order_count": 0,
                    "attributed_order_count": 0,
                    "fill_count": 0,
                    "position_count": 0,
                    "dividend_count": 0,
                    "equity_observation_count": 0,
                    "equity_start_date": None,
                    "equity_end_date": None,
                    "equity_path_sha256": None,
                    "comparison_portfolio_ids": [
                        policy["attribution"]["algorithm_control_id"],
                        policy["attribution"]["strategy_control_id"],
                    ],
                    "evidence_pooling": "prohibited",
                    "execution_authority": "none",
                },
                "automatic_paper_minimum_sessions": 60,
                "automatic_paper_session_gate_passed": False,
                "execution_authority": "none",
            }
            for policy in agent_policy.registry()["policies"]
        ],
        "records": [],
    }


def test_registered_cadence_no_action_is_attributed_without_model_or_order(con):
    fixed_etf_market(con)
    policy = agent_policy.get("dual_momentum_agent_shadow_v1")
    agent_shadow_store.init_schema(con)
    with engine_db.transaction(con):
        attempt_id = agent_shadow_store.insert_cadence_no_action(
            con,
            decision_window="agent-shadow-v2:" + "1" * 64,
            mode="agent_only",
            policy_id=policy["id"],
            policy_registration_sha256=policy["registration_sha256"],
            agent_id="paper-research-agent",
            strategy_id="dual_momentum",
            ticker="SPY",
            market_date=NOW.date(),
            started_at=NOW,
        )

    payload = agent_attribution_read_models.attribution(con)

    assert payload["matching_count"] == 1
    assert payload["legacy_attempt_count"] == 0
    summary = next(
        item
        for item in payload["policy_summaries"]
        if item["policy_id"] == policy["id"]
    )
    assert summary["completed_attempt_count"] == 1
    assert summary["completed_market_sessions"] == 1
    assert summary["automatic_paper_minimum_sessions"] == 60
    assert summary["automatic_paper_session_gate_passed"] is False
    assert summary["terminal_outcomes"]["cadence_no_action"] == 1
    record = payload["records"][0]
    assert record["attempt_id"] == attempt_id
    assert record["policy_id"] == policy["id"]
    assert record["mode"] == "agent_only"
    assert record["terminal_outcome"] == "cadence_no_action"
    assert record["decision_contribution"] == "cadence_no_action"
    assert record["model_requested"] is False
    assert record["normalized_model_response_recorded"] is False
    assert record["counterfactual_order_count"] == 0
    assert record["return_attribution_status"] == (
        "unavailable_no_isolated_paper_portfolio"
    )
    assert record["execution_authority"] == "none"
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


def test_validated_agent_proposal_is_bound_to_attribution_record(
    con,
    monkeypatch,
):
    fixed_etf_market(con)
    complete_dual_momentum_history(con)
    monkeypatch.setattr(agent_shadow_runner, "advisory_file_lock", _no_lock)
    monkeypatch.setattr(agent_shadow_runner, "_connection", _borrowed_connection)
    monkeypatch.setattr(agent_shadow_runner, "is_month_signal", lambda *_args: True)

    def generate(model_input):
        return _connector_result(
            model_input,
            {
                "schema_version": 1,
                "decision": "proposal",
                "side": "buy",
                "max_notional": 1_000,
                "stop": 90,
                "confidence": 0.6,
                "thesis": "Bounded shadow proposal.",
                "invalidation": "Invalidate when the frozen context expires.",
                "evidence_ids": [model_input["context"]["context_sha256"]],
            },
        )

    run = agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="agent_only",
        now=NOW,
        generate=generate,
        connection_factory=lambda: con,
    )
    payload = agent_attribution_read_models.attribution(con)

    assert run["status"] == "shadow_accepted"
    record = payload["records"][0]
    assert record["terminal_outcome"] == "proposal_result"
    assert record["decision_contribution"] == "agent_shadow_proposal"
    assert record["proposal_record_id"] == run["proposal_result"]["proposal_record_id"]
    assert record["proposal_status"] == "shadow_accepted"
    assert record["validation_status"] == "pass"
    assert record["validation_sha256"] == run["proposal_result"]["validation_sha256"]
    assert record["candidate_order_count"] == 1
    assert record["counterfactual_order_count"] == 1
    assert record["model_requested"] is True
    assert record["normalized_model_response_recorded"] is True
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


def test_hybrid_no_candidate_attributes_unmodified_algorithm_signal(con):
    fixed_etf_market(con)
    policy = agent_policy.get("dual_momentum_hybrid_veto_shadow_v1")
    context = agent_context.build(
        con,
        "dual_momentum",
        "SPY",
        policy_id=policy["id"],
    )
    candidate = context["algorithm_candidate"]
    window = "agent-shadow-v2:" + "2" * 64
    result = {
        "schema_version": 2,
        "attempt_id": 0,
        "decision_window": window,
        "status": "hybrid_no_veto_candidate",
        "reason": "deterministic candidate has no veto-eligible buy order",
        "proposal_result": {
            "policy_effect": "unmodified_algorithm_signal",
            "candidate_sha256": candidate["candidate_sha256"],
            "candidate_order_count": candidate["order_count"],
            "veto_eligible_order_count": 0,
            "effective_order_count": candidate["order_count"],
            "vetoed_order_count": 0,
            "effective_orders_sha256": canonical_sha256(candidate["orders"]),
            "decision": None,
            "execution_authority": "none",
        },
        "execution_authority": "none",
        "replayed": False,
    }
    agent_shadow_store.init_schema(con)
    with engine_db.transaction(con):
        agent_shadow_store.insert_deterministic_attempt(
            con,
            decision_window=window,
            mode="hybrid",
            policy_id=policy["id"],
            policy_registration_sha256=policy["registration_sha256"],
            agent_id="paper-research-agent",
            strategy_id="dual_momentum",
            ticker="SPY",
            market_date=NOW.date(),
            context=context,
            model_identity=context["decision_model"],
            event_type="hybrid_no_veto_candidate",
            event_payload={
                "candidate_sha256": candidate["candidate_sha256"],
                "model_requested": False,
                "result": result,
            },
            started_at=NOW,
        )

    record = agent_attribution_read_models.attribution(con)["records"][0]

    assert record["mode"] == "hybrid"
    assert record["decision_contribution"] == "unmodified_algorithm_signal"
    assert record["candidate_sha256"] == candidate["candidate_sha256"]
    assert record["model_requested"] is False
    assert record["counterfactual_order_count"] == candidate["order_count"]
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


def test_legacy_attempts_are_counted_but_excluded(con):
    fixed_etf_market(con)
    agent_shadow_store.init_schema(con)
    con.execute(
        "INSERT INTO agent_shadow_attempts "
        "(id, decision_window, mode, strategy_id, market_date) VALUES "
        "(1, 'agent-shadow-v1:legacy', 'agent_only', 'dual_momentum', "
        "DATE '2026-09-11')"
    )

    payload = agent_attribution_read_models.attribution(con)

    assert payload["matching_count"] == 0
    assert payload["legacy_attempt_count"] == 1
    assert payload["legacy_included"] is False
    assert payload["records"] == []


def test_attribution_fails_closed_on_context_or_terminal_tampering(con):
    fixed_etf_market(con)
    policy = agent_policy.get("dual_momentum_agent_shadow_v1")
    agent_shadow_store.init_schema(con)
    with engine_db.transaction(con):
        attempt_id = agent_shadow_store.insert_cadence_no_action(
            con,
            decision_window="agent-shadow-v2:" + "3" * 64,
            mode="agent_only",
            policy_id=policy["id"],
            policy_registration_sha256=policy["registration_sha256"],
            agent_id="paper-research-agent",
            strategy_id="dual_momentum",
            ticker="SPY",
            market_date=NOW.date(),
            started_at=NOW,
        )
    con.execute(
        "UPDATE agent_shadow_events SET payload = ? WHERE attempt_id = ?",
        ['{"result":{"status":"cadence_no_action"}}', attempt_id],
    )

    with pytest.raises(ValueError, match="terminal result identity"):
        agent_attribution_read_models.attribution(con)
