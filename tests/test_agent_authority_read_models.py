"""Later paper authority remains closed until every explicit gate passes."""

from __future__ import annotations

from datetime import datetime, timezone

from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256
from server import (
    agent_authority_read_models,
    agent_context,
    agent_corporate_action_observations,
    agent_fault_drills,
    agent_model_client,
    agent_policy,
    agent_price_observations,
    agent_shadow_store,
)
from tests.agent_test_helpers import complete_dual_momentum_history, fixed_etf_market

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


def test_readiness_is_shadow_only_and_exposes_concrete_blockers(con):
    fixed_etf_market(con)
    complete_dual_momentum_history(con)

    payload = agent_authority_read_models.readiness(con)

    assert payload["schema_version"] == 11
    assert payload["current_stage"] == "shadow"
    assert payload["authority_stages"] == [
        "shadow",
        "human_approved_paper",
        "automatic_paper",
    ]
    assert payload["human_approved_paper_eligible"] is False
    assert payload["automatic_paper_eligible"] is False
    assert payload["stage_projection"] == "separate_fail_closed_gates"
    assert payload["paper_order_route"] == "absent"
    assert payload["broker_route"] == "absent"
    assert payload["live_trading"] == "disabled"
    assert payload["execution_authority"] == "none"
    assert payload["evidence_pooling"] == "prohibited"
    body = {key: value for key, value in payload.items() if key != "readiness_sha256"}
    assert payload["readiness_sha256"] == canonical_sha256(body)
    assert {item["mode"] for item in payload["policies"]} == {
        "agent_only",
        "hybrid",
    }
    for policy in payload["policies"]:
        assert policy["current_stage"] == "shadow"
        assert policy["human_approved_paper_eligible"] is False
        assert policy["automatic_paper_eligible"] is False
        assert policy["paper_order_route"] == "absent"
        assert policy["execution_authority"] == "none"
        approved = policy["human_approved_paper"]
        automatic = policy["automatic_paper"]
        assert approved["stage"] == "human_approved_paper"
        assert approved["preconditions_passed"] is False
        assert approved["eligible"] is False
        assert approved["route"] == "absent"
        assert approved["execution_authority"] == "none"
        assert tuple(gate["name"] for gate in approved["gates"]) == (
            agent_authority_read_models.HUMAN_APPROVED_PAPER_GATE_NAMES
        )
        assert "human_order_approval" in approved["blockers"]
        assert "human_approved_paper_path" in approved["blockers"]
        assert "human_review_packet" not in approved["blockers"]
        assert "minimum_completed_market_sessions" not in approved["blockers"]
        assert "approved_paper_operation_evidence" not in approved["blockers"]
        assert "human_approval_lease" not in approved["blockers"]
        assert automatic["stage"] == "automatic_paper"
        assert automatic["preconditions_passed"] is False
        assert automatic["eligible"] is False
        assert automatic["route"] == "absent"
        assert automatic["execution_authority"] == "none"
        assert tuple(gate["name"] for gate in automatic["gates"]) == (
            agent_authority_read_models.AUTOMATIC_PAPER_GATE_NAMES
        )
        assert policy["blockers"] == automatic["blockers"]
        assert policy["gates"] == automatic["gates"]
        assert "point_in_time_data" in policy["blockers"]
        assert "provider_stable_model_revision" in policy["blockers"]
        assert "decision_contract_evidence" in policy["blockers"]
        assert "isolated_paper_portfolio" in policy["blockers"]
        assert "return_attribution" in policy["blockers"]
        assert "minimum_completed_market_sessions" in policy["blockers"]
        assert "fault_injection_and_restart_evidence" in policy["blockers"]
        assert "reviewed_release" in policy["blockers"]
        assert "human_approval_lease" in policy["blockers"]
        assert "approved_paper_operation_evidence" in policy["blockers"]
        assert "automatic_paper_path" in policy["blockers"]
        by_name = {gate["name"]: gate for gate in policy["gates"]}
        assert by_name["human_approval_lease"]["evidence"] == {
            "status": "candidate_contract_only",
            "candidate_contract": "server/broker_paper_lease.py",
            "activation_implemented": False,
            "startup_default": "disabled",
            "submission_authority": "none",
        }
        approved_by_name = {
            gate["name"]: gate for gate in approved["gates"]
        }
        assert approved_by_name["human_review_packet"] == {
            "name": "human_review_packet",
            "status": "pass",
            "evidence": {
                "status": "implemented_non_authorizing",
                "module": "server/broker_human_paper_review.py",
                "schema_version": 2,
                "scope": "one_exact_simulator_intent",
                "operator_cli": "tools.review_agent_paper_intent",
                "database_access": "read_only",
                "packet_output": "stdout_only",
                "packet_input": "bounded_strict_json_stdin",
                "maximum_ttl_seconds": 300,
                "supported_modes": ["agent_only", "hybrid"],
                "retained_evidence_revalidation": True,
                "approval_authentication": False,
                "submission_authority": "none",
            },
        }
        assert approved_by_name["human_order_approval"]["evidence"] == {
            "status": "approval_source_and_signer_policy_not_selected",
            "approval_scope": "one_exact_paper_intent",
            "contract": "server/broker_human_paper_approval.py",
            "contract_schema_version": 1,
            "source_neutral_envelope_implemented": True,
            "explicit_policy_contract_implemented": True,
            "strict_policy_parser": "bounded_duplicate_key_safe_json",
            "strict_envelope_parser": "bounded_duplicate_key_safe_json",
            "detached_authenticator_interface_implemented": True,
            "retained_evidence_authentication_composition": "read_only",
            "trust_source_loader_implemented": False,
            "selected_policy_present": False,
            "one_use_enforcement_implemented": False,
            "authenticated_evidence_replay_protection_implemented": True,
            "production_authority_consumption_implemented": False,
            "approval_observation_ledger": {
                "schema_version": 1,
                "status": "not_initialized",
                "observation_count": 0,
                "approve_observation_count": 0,
                "reject_observation_count": 0,
                "latest_recorded_at": None,
                "latest_observation_sha256": None,
                "authenticated_evidence_replay_protection_implemented": True,
                "production_authority_consumption_implemented": False,
                "trust_source_loader_implemented": False,
                "human_order_approval_granted": False,
                "paper_order_route": "absent",
                "submission_authority": "none",
            },
            "approval_verifier_implemented": False,
            "human_order_approval_granted": False,
            "submission_authority": "none",
        }
        assert approved_by_name["human_approved_paper_path"]["evidence"] == {
            "status": "not_implemented",
            "paper_order_route": "absent",
            "submission_authority": "none",
        }
        assert by_name["registered_shadow_policy"]["status"] == "pass"
        assert by_name["reviewed_release"]["evidence"] == {
            "schema_version": 1,
            "status": "unavailable",
            "manifest_schema_version": 8,
            "manifest_sha256": None,
            "identity_complete": False,
            "release_eligible": False,
            "manifest_reasons": ["release-readiness-not-supplied"],
            "git_commit": None,
            "git_tree": None,
            "git_branch": None,
            "working_tree_dirty": None,
            "changed_path_count": None,
            "required_files_tracked": None,
            "explicit_human_review_required": True,
            "review_evidence_status": "not_selected",
            "release_review_verifier_implemented": True,
            "reviewed_release": False,
            "paper_order_route": "absent",
            "execution_authority": "none",
            "release_readiness_sha256": (
                agent_authority_read_models.agent_release_readiness.unavailable(
                    "release-readiness-not-supplied"
                )["release_readiness_sha256"]
            ),
            "release_review_observation_ledger": {
                "schema_version": 1,
                "status": "not_initialized",
                "observation_count": 0,
                "approve_observation_count": 0,
                "reject_observation_count": 0,
                "latest_recorded_at": None,
                "latest_observation_sha256": None,
                "authenticated_evidence_replay_protection_implemented": True,
                "production_readiness_integration_implemented": False,
                "trust_source_loader_implemented": False,
                "reviewed_release_gate_passed": False,
                "paper_order_route": "absent",
                "submission_authority": "none",
            },
        }
        assert by_name["point_in_time_data"]["evidence"]["feature_complete"] is True
        assert (
            by_name["point_in_time_data"]["evidence"]["paper_ready_contract_count"]
            == 0
        )
        assert (
            by_name["point_in_time_data"]["evidence"][
                "immutable_normalized_contract_count"
            ]
            == 0
        )
        assert (
            by_name["point_in_time_data"]["evidence"][
                "later_raw_corroborated_contract_count"
            ]
            == 0
        )
        assert (
            by_name["point_in_time_data"]["evidence"][
                "original_raw_retained_contract_count"
            ]
            == 0
        )
        assert by_name["point_in_time_data"]["evidence"][
            "data_discrepancy_review"
        ] == {
            "status": "implemented_non_authorizing",
            "module": "server/agent_data_discrepancy_review.py",
            "operator_cli": "tools.review_agent_data_discrepancy",
            "review_scope": "one_exact_provider_source_cache_discrepancy",
            "maximum_ttl_seconds": 3600,
            "required_operator_decisions": [
                "accept_source_revision_via_separate_guarded_repair",
                "retain_current_cache_with_justification",
                "quarantine_ticker",
                "defer_pending_more_evidence",
            ],
            "automatic_recommendation": None,
            "cache_mutation_implemented": False,
            "quarantine_mutation_implemented": False,
            "execution_authority": "none",
        }
        assert by_name["point_in_time_data"]["evidence"][
            "data_discrepancy_adjudication"
        ] == {
            "schema_version": 1,
            "status": "not_initialized",
            "decision_count": 0,
            "decisions_by_disposition": {
                "accept_source_revision_via_separate_guarded_repair": 0,
                "retain_current_cache_with_justification": 0,
                "quarantine_ticker": 0,
                "defer_pending_more_evidence": 0,
            },
            "latest_decided_at": None,
            "latest_decision_sha256": None,
            "operational_effect": "record_only_separate_follow_up_required",
            "cache_mutation_implemented": False,
            "quarantine_mutation_implemented": False,
            "execution_authority": "none",
        }
        assert by_name["point_in_time_data"]["evidence"][
            "independent_price_evidence"
        ] == {
            "schema_version": 1,
            "status": "not_initialized",
            "response_count": 0,
            "observation_count": 0,
            "ticker_count": 0,
            "first_received_at": None,
            "last_received_at": None,
            "response_bytes": 0,
            "source_row_count": 0,
            "parse_error_count": 0,
            "incomplete_row_count": 0,
            "classification_counts": {
                "baseline_source_observation": 0,
                "source_value_revision": 0,
                "unchanged_source_observation": 0,
            },
            "raw_response_bodies_retained": False,
            "source_publication_time_available": False,
            "provider_dataset_version": None,
            "operational_price_mutation": False,
            "quarantine_mutation": False,
            "execution_authority": "none",
        }
        assert (
            by_name["provider_stable_model_revision"]["evidence"]["transport"]
            == "trae_cli_proxy"
        )
        assert (
            by_name["provider_stable_model_revision"]["evidence"]["model"]
            == "GPT-5.6-Sol:max"
        )
        assert (
            by_name["provider_stable_model_revision"]["evidence"]["model_version"]
            == "unversioned-catalog-alias"
        )
        assert by_name["provider_stable_model_revision"]["evidence"][
            "provider_model_revision"
        ] is None
        assert by_name["provider_stable_model_revision"]["evidence"][
            "provider_model_revision_available"
        ] is False
        assert by_name["provider_stable_model_revision"]["evidence"][
            "model_catalog_entry_sha256"
        ] == agent_model_client.MODEL_CATALOG_ENTRY_SHA256
        assert by_name["provider_stable_model_revision"]["evidence"][
            "required_traecli_runtime"
        ] == agent_model_client.REQUIRED_TRAECLI_RUNTIME
        assert by_name["provider_stable_model_revision"]["evidence"][
            "stable_revision"
        ] is False


def test_cadence_only_evidence_does_not_satisfy_decision_or_session_gate(con):
    fixed_etf_market(con)
    complete_dual_momentum_history(con)
    policy = agent_policy.get("dual_momentum_agent_shadow_v1")
    agent_shadow_store.init_schema(con)
    with engine_db.transaction(con):
        agent_shadow_store.insert_cadence_no_action(
            con,
            decision_window="agent-shadow-v2:" + "4" * 64,
            mode="agent_only",
            policy_id=policy["id"],
            policy_registration_sha256=policy["registration_sha256"],
            agent_id="paper-research-agent",
            strategy_id="dual_momentum",
            ticker="SPY",
            market_date=NOW.date(),
            started_at=NOW,
        )

    payload = agent_authority_read_models.readiness(con)
    readiness = next(
        item for item in payload["policies"] if item["policy_id"] == policy["id"]
    )
    gates = {gate["name"]: gate for gate in readiness["gates"]}

    assert gates["decision_contract_evidence"]["status"] == "blocked"
    assert gates["decision_contract_evidence"]["evidence"] == {
        "required_kind": "agent_proposal_or_model_no_action",
        "substantive_outcome_count": 0,
        "cadence_no_action_count": 1,
    }
    assert gates["minimum_completed_market_sessions"]["evidence"] == {
        "observed": 1,
        "required": 60,
        "evidence_scope": "shadow_and_human_approved_paper",
    }
    assert gates["minimum_completed_market_sessions"]["status"] == "blocked"
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


def test_later_provider_corroboration_is_visible_but_not_paper_ready(con):
    fixed_etf_market(con)
    market_date = complete_dual_momentum_history(con)
    agent_price_observations.capture_strategy_scope(
        con, "dual_momentum", market_date, observed_at=NOW
    )
    agent_corporate_action_observations.capture_strategy_scope(
        con, "dual_momentum", market_date, observed_at=NOW
    )
    payload = agent_context.build(con, "dual_momentum", "SPY")
    fact = payload["instrument"]["data_contract"]
    fact["provider_evidence"] = {
        "schema_version": 1,
        "relationship": "later_exact_value_corroboration",
        "receipt_sha256": "3" * 64,
        "response_sha256": "2" * 64,
        "response_size_bytes": 1,
        "received_at": "2026-09-13T12:00:00Z",
        "endpoint_api_version": "yahoo_finance_chart_v8",
        "source_library_version": "1.7.0",
        "observation_sha256": fact["revision"]["revision_id"],
        "value_sha256": fact["revision"]["value_sha256"],
        "raw_response_body_retained": True,
    }

    gate = agent_authority_read_models._data_gate(
        payload,
        None,
        provider_status={
            "cache_alignment_status": "current_cache_value_drift_detected",
            "cache_comparable_source_fact_count": 25,
            "cache_aligned_fact_count": 22,
            "cache_mismatched_fact_count": 3,
            "missing_cache_fact_count": 0,
        },
    )

    assert gate["status"] == "blocked"
    assert gate["evidence"]["immutable_normalized_contract_count"] == 8
    assert gate["evidence"]["later_raw_corroborated_contract_count"] == 1
    assert gate["evidence"]["original_raw_retained_contract_count"] == 0
    assert gate["evidence"]["paper_ready_contract_count"] == 0
    assert gate["evidence"]["provider_cache_alignment_status"] == (
        "current_cache_value_drift_detected"
    )
    assert gate["evidence"]["cache_comparable_source_fact_count"] == 25
    assert gate["evidence"]["cache_aligned_fact_count"] == 22
    assert gate["evidence"]["cache_mismatched_fact_count"] == 3
    assert gate["evidence"]["missing_cache_fact_count"] == 0
    assert gate["evidence"]["cache_alignment_error"] is None


def test_current_fault_drill_evidence_passes_only_its_readiness_gate(
    con, tmp_path, monkeypatch
):
    fixed_etf_market(con)
    complete_dual_momentum_history(con)
    suite = agent_fault_drills._suite_identity(
        agent_fault_drills.REPO_ROOT,
        agent_policy.REGISTRATION_PATH,
    )
    results = [
        {
            "id": case["id"],
            "mode": case["mode"],
            "property": case["property"],
            "status": "pass",
            "returncode": 0,
            "output_size_bytes": 1,
            "output_sha256": "a" * 64,
        }
        for case in agent_fault_drills.DRILL_CASES
    ]
    agent_fault_drills._persist(
        con,
        suite,
        results,
        started_at=NOW,
        completed_at=NOW,
    )

    payload = agent_authority_read_models.readiness(con)

    for policy in payload["policies"]:
        gates = {gate["name"]: gate for gate in policy["gates"]}
        drill = gates["fault_injection_and_restart_evidence"]
        assert drill["status"] == "pass"
        assert drill["evidence"]["status"] == "current_pass"
        assert drill["evidence"]["coverage_level"] == "application_state_machine"
        assert drill["evidence"]["run_count"] == 1
        assert drill["evidence"]["missing_coverage"] == []
        assert "minimum_completed_market_sessions" in policy["blockers"]
        assert policy["automatic_paper_eligible"] is False


def test_unavailable_context_is_a_blocker_not_an_exception(con):
    fixed_etf_market(con)
    complete_dual_momentum_history(con)
    con.execute("UPDATE portfolios SET active = FALSE WHERE id = 'dual_momentum'")

    payload = agent_authority_read_models.readiness(con)

    for policy in payload["policies"]:
        gates = {gate["name"]: gate for gate in policy["gates"]}
        assert gates["registered_shadow_policy"]["status"] == "blocked"
        assert "not active" in gates["registered_shadow_policy"]["evidence"][
            "live_registration_error"
        ]
        assert gates["point_in_time_data"]["status"] == "blocked"
        assert gates["point_in_time_data"]["evidence"]["context_available"] is False
        assert (
            gates["point_in_time_data"]["evidence"][
                "later_raw_corroborated_contract_count"
            ]
            == 0
        )
        assert "not active" in gates["point_in_time_data"]["evidence"]["reason"]
        assert gates["provider_stable_model_revision"]["status"] == "blocked"
        assert policy["execution_authority"] == "none"
