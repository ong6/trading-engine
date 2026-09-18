"""Fail-closed readiness projection for later agent paper authority stages."""

from __future__ import annotations

from pathlib import Path

import duckdb

from engine.lib.provenance import canonical_sha256
from engine.lib.settings import REPO_ROOT

from . import (
    agent_attribution_read_models,
    agent_context,
    agent_data_discrepancy_adjudication,
    agent_data_discrepancy_review,
    agent_fault_drills,
    agent_independent_price_evidence,
    agent_model_client,
    agent_policy,
    agent_provider_responses,
    agent_release_readiness,
    agent_release_review_store,
    broker_human_paper_approval,
    broker_human_paper_approval_store,
    broker_human_paper_review,
)

CURRENT_STAGE = "shadow"
AUTHORITY_STAGES = ("shadow", "human_approved_paper", "automatic_paper")
HUMAN_APPROVED_PAPER_GATE_NAMES = (
    "registered_shadow_policy",
    "point_in_time_data",
    "provider_stable_model_revision",
    "decision_contract_evidence",
    "isolated_paper_portfolio",
    "return_attribution",
    "zero_integrity_failures",
    "fault_injection_and_restart_evidence",
    "reviewed_release",
    "human_review_packet",
    "human_order_approval",
    "human_approved_paper_path",
)
AUTOMATIC_PAPER_GATE_NAMES = (
    "registered_shadow_policy",
    "point_in_time_data",
    "provider_stable_model_revision",
    "decision_contract_evidence",
    "isolated_paper_portfolio",
    "return_attribution",
    "zero_integrity_failures",
    "fault_injection_and_restart_evidence",
    "reviewed_release",
    "minimum_completed_market_sessions",
    "approved_paper_operation_evidence",
    "human_approval_lease",
    "automatic_paper_path",
)
STABLE_MODEL_VERSION_BLOCKLIST = frozenset({"unversioned-catalog-alias"})
FAILURE_OUTCOMES = frozenset(
    {
        "malformed_output",
        "transport_failure",
        "proposal_failure",
        "uncertain",
        "hybrid_fallback_allow",
    }
)


def _gate(name: str, passed: bool, evidence: dict) -> dict:
    return {
        "name": name,
        "status": "pass" if passed else "blocked",
        "evidence": evidence,
    }


def _contracts(value: object) -> list[dict]:
    """Collect only explicit agent data-contract envelopes from a context."""
    found = []
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            if (
                item.get("dataset") in {"daily_price", "cash_dividend"}
                and "quality_status" in item
                and "usage_authority" in item
            ):
                found.append(item)
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return found


def _data_gate(
    context: dict | None,
    context_error: str | None,
    *,
    provider_status: dict | None = None,
    adjudication_status: dict | None = None,
    independent_status: dict | None = None,
) -> dict:
    alignment = {
        "provider_cache_alignment_status": (
            "unavailable"
            if provider_status is None
            else provider_status["cache_alignment_status"]
        ),
        "cache_comparable_source_fact_count": (
            0
            if provider_status is None
            else provider_status["cache_comparable_source_fact_count"]
        ),
        "cache_aligned_fact_count": (
            0
            if provider_status is None
            else provider_status["cache_aligned_fact_count"]
        ),
        "cache_mismatched_fact_count": (
            0
            if provider_status is None
            else provider_status["cache_mismatched_fact_count"]
        ),
        "missing_cache_fact_count": (
            0
            if provider_status is None
            else provider_status["missing_cache_fact_count"]
        ),
        "cache_alignment_error": (
            None if provider_status is None else provider_status.get("error")
        ),
        "data_discrepancy_review": {
            "status": "implemented_non_authorizing",
            "module": "server/agent_data_discrepancy_review.py",
            "operator_cli": "tools.review_agent_data_discrepancy",
            "review_scope": agent_data_discrepancy_review.REVIEW_SCOPE,
            "maximum_ttl_seconds": (
                agent_data_discrepancy_review.REVIEW_TTL_SECONDS
            ),
            "required_operator_decisions": list(
                agent_data_discrepancy_review.OPERATOR_DECISIONS
            ),
            "automatic_recommendation": None,
            "cache_mutation_implemented": False,
            "quarantine_mutation_implemented": False,
            "execution_authority": "none",
        },
        "data_discrepancy_adjudication": (
            {
                "status": "invalid",
                "decision_count": 0,
                "error": "adjudication status unavailable",
                "operational_effect": "record_only_separate_follow_up_required",
                "cache_mutation_implemented": False,
                "quarantine_mutation_implemented": False,
                "execution_authority": "none",
            }
            if adjudication_status is None
            else adjudication_status
        ),
        "independent_price_evidence": (
            {
                "schema_version": 1,
                "status": "unavailable",
                "response_count": 0,
                "observation_count": 0,
                "raw_response_bodies_retained": False,
                "source_publication_time_available": False,
                "provider_dataset_version": None,
                "operational_price_mutation": False,
                "quarantine_mutation": False,
                "execution_authority": "none",
            }
            if independent_status is None
            else independent_status
        ),
    }
    cache_aligned = (
        provider_status is not None
        and provider_status["cache_alignment_status"] == "current_cache_aligned"
        and provider_status["cache_comparable_source_fact_count"] > 0
        and provider_status["cache_mismatched_fact_count"] == 0
        and provider_status["missing_cache_fact_count"] == 0
    )
    if context is None:
        return _gate(
            "point_in_time_data",
            False,
            {
                "context_available": False,
                "reason": context_error,
                "contract_count": 0,
                "immutable_normalized_contract_count": 0,
                "later_raw_corroborated_contract_count": 0,
                "original_raw_retained_contract_count": 0,
                "paper_ready_contract_count": 0,
                **alignment,
            },
        )
    contracts = _contracts(context)
    immutable_normalized = [
        contract
        for contract in contracts
        if contract.get("revision", {}).get("history_retained") is True
        and contract.get("revision", {}).get("point_in_time_replayable") is True
    ]
    later_corroborated = [
        contract
        for contract in contracts
        if (contract.get("provider_evidence") or {}).get("relationship")
        == "later_exact_value_corroboration"
        and (contract.get("provider_evidence") or {}).get(
            "raw_response_body_retained"
        )
        is True
    ]
    original_raw_retained = [
        contract
        for contract in contracts
        if (contract.get("provider_evidence") or {}).get("relationship")
        == "exact_response_source_observation"
        and contract.get("record", {}).get("raw_retained") is True
        and contract.get("record", {}).get("raw_sha256") is not None
    ]
    paper_ready = [
        contract
        for contract in contracts
        if contract.get("quality_status") == "verified"
        and contract.get("usage_authority") == "paper_decision"
        and contract.get("revision", {}).get("history_retained") is True
        and contract.get("revision", {}).get("point_in_time_replayable") is True
        and contract.get("record", {}).get("raw_retained") is True
        and contract.get("record", {}).get("raw_sha256") is not None
        and contract.get("availability", {}).get("source_published_at") is not None
        and contract.get("source", {}).get("provider_version") is not None
    ]
    features = context["decision_features"]
    feature_complete = (
        features["complete_tickers"] == features["required_tickers"]
        and bool(features["required_tickers"])
    )
    passed = (
        bool(contracts)
        and len(paper_ready) == len(contracts)
        and feature_complete
        and cache_aligned
    )
    return _gate(
        "point_in_time_data",
        passed,
        {
            "context_available": True,
            "context_sha256": context["context_sha256"],
            "feature_complete": feature_complete,
            "required_tickers": features["required_tickers"],
            "complete_tickers": features["complete_tickers"],
            "contract_count": len(contracts),
            "immutable_normalized_contract_count": len(immutable_normalized),
            "later_raw_corroborated_contract_count": len(later_corroborated),
            "original_raw_retained_contract_count": len(original_raw_retained),
            "paper_ready_contract_count": len(paper_ready),
            **alignment,
            "required_quality_status": "verified",
            "required_usage_authority": "paper_decision",
            "requires_revision_history": True,
            "requires_raw_retention": True,
            "requires_source_publication_time": True,
            "requires_provider_version": True,
        },
    )


def _model_gate(context: dict | None, context_error: str | None) -> dict:
    identity = (
        agent_model_client.identity()
        if context is None
        else context["decision_model"]
    )
    stable = (
        identity["model_version"] not in STABLE_MODEL_VERSION_BLOCKLIST
        and identity["provider_model_revision_available"] is True
        and identity["provider_model_revision"] is not None
    )
    return _gate(
        "provider_stable_model_revision",
        stable and context is not None,
        {
            "context_available": context is not None,
            "context_error": context_error,
            "transport": identity["transport"],
            "model": identity["model"],
            "model_version": identity["model_version"],
            "provider_model_revision": identity["provider_model_revision"],
            "provider_model_revision_available": identity[
                "provider_model_revision_available"
            ],
            "model_catalog_entry_sha256": identity[
                "model_catalog_entry_sha256"
            ],
            "required_traecli_runtime": identity["required_traecli_runtime"],
            "stable_revision": stable,
            "tools": identity["tools"],
            "execution_authority": identity["execution_authority"],
        },
    )


def _decision_evidence_gate(summary: dict) -> dict:
    outcomes = summary["terminal_outcomes"]
    if summary["mode"] == "agent_only":
        substantive = outcomes["proposal_result"] + outcomes["no_action"]
        kind = "agent_proposal_or_model_no_action"
    else:
        substantive = sum(
            outcomes[name]
            for name in (
                "hybrid_no_veto_candidate",
                "hybrid_allow",
                "hybrid_veto",
                "hybrid_fallback_allow",
            )
        )
        kind = "candidate_bound_hybrid_outcome"
    return _gate(
        "decision_contract_evidence",
        substantive > 0,
        {
            "required_kind": kind,
            "substantive_outcome_count": substantive,
            "cadence_no_action_count": outcomes["cadence_no_action"],
        },
    )


def _stage(
    stage: str,
    gates: list[dict],
    *,
    route: str,
) -> dict:
    blockers = [gate["name"] for gate in gates if gate["status"] == "blocked"]
    return {
        "stage": stage,
        "preconditions_passed": not blockers,
        "eligible": False,
        "route": route,
        "execution_authority": "none",
        "blockers": blockers,
        "gates": gates,
    }


def _policy_readiness(
    con: duckdb.DuckDBPyConnection,
    policy: dict,
    summary: dict,
    *,
    ticker: str,
    repo_root: Path,
    registration_path: Path,
    fault_drill_status: dict,
    provider_status: dict,
    adjudication_status: dict,
    independent_status: dict,
    approval_observation_status: dict,
    release_status: dict,
    release_review_observation_status: dict,
) -> dict:
    try:
        agent_policy.validate_live_registration(
            con,
            policy,
            allow_reserved_portfolio=True,
        )
        registration_error = None
    except agent_policy.PolicyError as exc:
        registration_error = str(exc)
    try:
        context = agent_context.build(
            con,
            policy["strategy_id"],
            ticker,
            policy_id=policy["id"],
            repo_root=repo_root,
            policy_path=registration_path,
            allow_reserved_portfolio=True,
        )
        context_error = None
    except agent_context.ContextError as exc:
        context = None
        context_error = str(exc)
    failures = sum(summary["terminal_outcomes"][name] for name in FAILURE_OUTCOMES)
    common_gates = [
        _gate(
            "registered_shadow_policy",
            registration_error is None,
            {
                "policy_registration_sha256": policy["registration_sha256"],
                "authority_stage": policy["authority_stage"],
                "execution_authority": policy["execution_authority"],
                "live_registration_error": registration_error,
            },
        ),
        _data_gate(
            context,
            context_error,
            provider_status=provider_status,
            adjudication_status=adjudication_status,
            independent_status=independent_status,
        ),
        _model_gate(context, context_error),
        _decision_evidence_gate(summary),
        _gate(
            "isolated_paper_portfolio",
            summary["reserved_portfolio_created"],
            {
                "reserved_portfolio_id": policy["reserved_portfolio_id"],
                "created": summary["reserved_portfolio_created"],
            },
        ),
        _gate(
            "return_attribution",
            summary["return_attribution_status"] == "available",
            {"status": summary["return_attribution_status"]},
        ),
        _gate(
            "zero_integrity_failures",
            failures == 0 and summary["completed_attempt_count"] > 0,
            {
                "completed_attempt_count": summary["completed_attempt_count"],
                "failure_outcomes": {
                    name: summary["terminal_outcomes"][name]
                    for name in sorted(FAILURE_OUTCOMES)
                },
            },
        ),
        _gate(
            "fault_injection_and_restart_evidence",
            fault_drill_status.get("current") is True
            and not fault_drill_status.get("missing_coverage"),
            {
                "status": fault_drill_status["status"],
                "suite_id": fault_drill_status.get("suite_id"),
                "suite_sha256": fault_drill_status.get("suite_sha256"),
                "coverage_level": fault_drill_status.get("coverage_level"),
                "run_count": fault_drill_status.get("run_count", 0),
                "missing_coverage": fault_drill_status.get(
                    "missing_coverage", ["unavailable"]
                ),
                "error": fault_drill_status.get("error"),
            },
        ),
        _gate(
            "reviewed_release",
            False,
            {
                **release_status,
                "release_review_observation_ledger": (
                    release_review_observation_status
                ),
            },
        ),
    ]
    human_approved_gates = [
        *common_gates,
        _gate(
            "human_review_packet",
            True,
            {
                "status": "implemented_non_authorizing",
                "module": "server/broker_human_paper_review.py",
                "schema_version": (
                    broker_human_paper_review.REVIEW_SCHEMA_VERSION
                ),
                "scope": broker_human_paper_review.REVIEW_SCOPE,
                "operator_cli": "tools.review_agent_paper_intent",
                "database_access": "read_only",
                "packet_output": "stdout_only",
                "packet_input": "bounded_strict_json_stdin",
                "maximum_ttl_seconds": (
                    broker_human_paper_review.REVIEW_TTL_SECONDS
                ),
                "supported_modes": ["agent_only", "hybrid"],
                "retained_evidence_revalidation": True,
                "approval_authentication": False,
                "submission_authority": "none",
            },
        ),
        _gate(
            "human_order_approval",
            False,
            {
                "status": "approval_source_and_signer_policy_not_selected",
                "approval_scope": "one_exact_paper_intent",
                "contract": "server/broker_human_paper_approval.py",
                "contract_schema_version": (
                    broker_human_paper_approval.ENVELOPE_SCHEMA_VERSION
                ),
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
                "approval_observation_ledger": approval_observation_status,
                "approval_verifier_implemented": False,
                "human_order_approval_granted": False,
                "submission_authority": "none",
            },
        ),
        _gate(
            "human_approved_paper_path",
            False,
            {
                "status": "not_implemented",
                "paper_order_route": "absent",
                "submission_authority": "none",
            },
        ),
    ]
    automatic_gates = [
        *common_gates,
        _gate(
            "minimum_completed_market_sessions",
            summary["automatic_paper_session_gate_passed"],
            {
                "observed": summary["completed_market_sessions"],
                "required": summary["automatic_paper_minimum_sessions"],
                "evidence_scope": "shadow_and_human_approved_paper",
            },
        ),
        _gate(
            "approved_paper_operation_evidence",
            False,
            {
                "status": "unavailable_no_human_approved_paper_path",
                "required_before": "automatic_paper",
            },
        ),
        _gate(
            "human_approval_lease",
            False,
            {
                "status": "candidate_contract_only",
                "candidate_contract": "server/broker_paper_lease.py",
                "activation_implemented": False,
                "startup_default": "disabled",
                "submission_authority": "none",
            },
        ),
        _gate(
            "automatic_paper_path",
            False,
            {
                "status": "not_implemented",
                "paper_order_route": "absent",
                "submission_authority": "none",
            },
        ),
    ]
    if tuple(gate["name"] for gate in human_approved_gates) != (
        HUMAN_APPROVED_PAPER_GATE_NAMES
    ):
        raise ValueError("human-approved paper gate contract changed")
    if tuple(gate["name"] for gate in automatic_gates) != (
        AUTOMATIC_PAPER_GATE_NAMES
    ):
        raise ValueError("automatic-paper gate contract changed")
    human_approved = _stage(
        "human_approved_paper",
        human_approved_gates,
        route="absent",
    )
    automatic = _stage(
        "automatic_paper",
        automatic_gates,
        route="absent",
    )
    return {
        "policy_id": policy["id"],
        "policy_registration_sha256": policy["registration_sha256"],
        "mode": policy["mode"],
        "strategy_id": policy["strategy_id"],
        "ticker": ticker,
        "current_stage": CURRENT_STAGE,
        "human_approved_paper_eligible": False,
        "automatic_paper_eligible": False,
        "promotion_sequence": [
            "shadow",
            "human_approved_paper",
            "automatic_paper",
        ],
        "paper_order_route": "absent",
        "execution_authority": "none",
        "human_approved_paper": human_approved,
        "automatic_paper": automatic,
        "blockers": automatic["blockers"],
        "gates": automatic["gates"],
    }


def readiness(
    con: duckdb.DuckDBPyConnection,
    *,
    repo_root: Path = REPO_ROOT,
    registration_path: Path = agent_policy.REGISTRATION_PATH,
    release_status: dict | None = None,
) -> dict:
    """Report why later paper authority remains unavailable; never grant it."""
    registry = agent_policy.registry(registration_path)
    if release_status is None:
        release_status = agent_release_readiness.unavailable(
            "release-readiness-not-supplied"
        )
    release_status = agent_release_readiness.verify_projection(release_status)
    try:
        release_review_observation_status = (
            agent_release_review_store.status(con)
        )
    except agent_release_review_store.ReleaseReviewStoreError as exc:
        release_review_observation_status = {
            "schema_version": agent_release_review_store.SCHEMA_VERSION,
            "status": "invalid",
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
            "error": str(exc),
        }
    attribution = agent_attribution_read_models.attribution(
        con,
        registration_path=registration_path,
        require_live_registration=False,
    )
    summaries = {
        summary["policy_id"]: summary
        for summary in attribution["policy_summaries"]
    }
    try:
        fault_drill_status = agent_fault_drills.status(
            con,
            repo_root=repo_root,
            registration_path=registration_path,
        )
    except agent_fault_drills.FaultDrillError as exc:
        fault_drill_status = {
            "status": "invalid",
            "current": False,
            "run_count": 0,
            "missing_coverage": ["unavailable"],
            "error": str(exc),
        }
    try:
        provider_status = agent_provider_responses.status(con)
    except agent_provider_responses.ProviderResponseError as exc:
        provider_status = {
            "cache_alignment_status": "invalid",
            "cache_comparable_source_fact_count": 0,
            "cache_aligned_fact_count": 0,
            "cache_mismatched_fact_count": 0,
            "missing_cache_fact_count": 0,
            "error": str(exc),
        }
    try:
        adjudication_status = agent_data_discrepancy_adjudication.status(con)
    except agent_data_discrepancy_adjudication.DataDiscrepancyAdjudicationError as exc:
        adjudication_status = {
            "schema_version": (
                agent_data_discrepancy_adjudication.SCHEMA_VERSION
            ),
            "status": "invalid",
            "decision_count": 0,
            "decisions_by_disposition": {
                disposition: 0
                for disposition in agent_data_discrepancy_adjudication.DISPOSITIONS
            },
            "latest_decided_at": None,
            "latest_decision_sha256": None,
            "operational_effect": "record_only_separate_follow_up_required",
            "cache_mutation_implemented": False,
            "quarantine_mutation_implemented": False,
            "execution_authority": "none",
            "error": str(exc),
        }
    try:
        independent_status = agent_independent_price_evidence.status(con)
    except agent_independent_price_evidence.IndependentPriceEvidenceError as exc:
        independent_status = {
            "schema_version": 1,
            "status": "invalid",
            "response_count": 0,
            "observation_count": 0,
            "raw_response_bodies_retained": False,
            "source_publication_time_available": False,
            "provider_dataset_version": None,
            "operational_price_mutation": False,
            "quarantine_mutation": False,
            "execution_authority": "none",
            "error": str(exc),
        }
    try:
        approval_observation_status = broker_human_paper_approval_store.status(con)
    except broker_human_paper_approval_store.HumanPaperApprovalStoreError as exc:
        approval_observation_status = {
            "schema_version": broker_human_paper_approval_store.SCHEMA_VERSION,
            "status": "invalid",
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
            "error": str(exc),
        }
    ticker = registry["scheduled_ticker"]
    policies = [
        _policy_readiness(
            con,
            agent_policy.get(raw["id"], path=registration_path),
            summaries[raw["id"]],
            ticker=ticker,
            repo_root=repo_root,
            registration_path=registration_path,
            fault_drill_status=fault_drill_status,
            provider_status=provider_status,
            adjudication_status=adjudication_status,
            independent_status=independent_status,
            approval_observation_status=approval_observation_status,
            release_status=release_status,
            release_review_observation_status=(
                release_review_observation_status
            ),
        )
        for raw in registry["policies"]
    ]
    body = {
        "schema_version": 11,
        "current_stage": CURRENT_STAGE,
        "authority_stages": list(AUTHORITY_STAGES),
        "human_approved_paper_eligible": False,
        "automatic_paper_eligible": False,
        "stage_projection": "separate_fail_closed_gates",
        "paper_order_route": "absent",
        "broker_route": "absent",
        "live_trading": "disabled",
        "execution_authority": "none",
        "registry_sha256": registry["registry_sha256"],
        "attribution_scope": attribution["attribution_scope"],
        "evidence_pooling": "prohibited",
        "policies": policies,
    }
    return {**body, "readiness_sha256": canonical_sha256(body)}
