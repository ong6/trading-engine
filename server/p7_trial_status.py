"""Versioned P7 registration and bounded, non-authorizing trial status."""

from __future__ import annotations

import math
import re
from pathlib import Path

import duckdb

from engine.lib.provenance import canonical_sha256
from engine.lib.settings import REPO_ROOT
from sim.execution import PROFILES
from sim.strategies.configs import config_by_id

from . import (
    agent_authority_read_models,
    agent_model_client,
    agent_policy,
    p7_trial_attribution,
)
from .file_utils import read_bytes
from .json_utils import loads_object
from .status_validation import iso_date, iso_timestamp

SCHEMA_VERSION = 1
STATUS_SCHEMA_VERSION = 1
REGISTRATION_PATH = REPO_ROOT / "server" / "p7-trial-registration.json"
MAX_REGISTRATION_BYTES = 32_768
TRIAL_ID = "p7-autonomous-paper-trial"
ARM_IDS = ("algorithm_only", "ai_only", "algorithm_plus_ai")
ARM_CONTRACTS = {
    "algorithm_only": {
        "policy_id": "p7_algorithm_dual_momentum_v1",
        "behavior": "registered_deterministic_dual_momentum",
        "model_role": "none",
    },
    "ai_only": {
        "policy_id": "p7_ai_target_choice_v1",
        "behavior": "model_target_choice_deterministic_order_derivation",
        "model_role": "target_choice",
    },
    "algorithm_plus_ai": {
        "policy_id": "p7_hybrid_veto_v1",
        "behavior": "model_veto_only_on_eligible_buy",
        "model_role": "veto_only",
    },
}
REQUIREMENTS = (
    "manifest_dependencies_current",
    "trial_policy_implementations",
    "observable_model_identity",
    "model_transport_healthy",
    "shared_data_admission",
    "independent_fx_boundary",
    "three_isolated_books",
    "simulator_only_orchestrator",
    "complete_dry_run_window",
    "fault_drills_current",
    "trial_scheduler_current",
    "backup_restore_rehearsal",
    "validation_evidence",
    "prohibited_routes_absent",
    "future_activation_date",
    "immutable_cohort_identity",
)
MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "trial_id",
        "trial_version",
        "registration_status",
        "execution_authority",
        "live_trading",
        "arms",
        "capital",
        "cohort",
        "decision_contract",
        "legacy_bindings",
        "runtime_evidence",
        "activation_requirements",
        "manifest_sha256",
    }
)
ARM_FIELDS = frozenset(
    {
        "arm_id",
        "policy_id",
        "policy_version",
        "policy_sha256",
        "behavior",
        "model_role",
        "allowed_assets",
        "implementation_binding",
    }
)
BINDING_FIELDS = frozenset({"policy_registration_sha256", "portfolio_id", "runtime_source_sha256"})
RUNTIME_EVIDENCE_FIELDS = frozenset(
    {
        "backup_restore_rehearsal_sha256",
        "dry_run_window_sha256",
        "orchestrator_source_sha256",
        "scheduler_registration_sha256",
        "validation_evidence_sha256",
    }
)
CAPITAL_FIELDS = frozenset(
    {
        "accounting_currency",
        "counterfactual_book_count",
        "fx_observation_sha256",
        "fx_observed_at",
        "owner_envelope_currency",
        "owner_envelope_value",
        "usd_opening_balance",
    }
)
COHORT_FIELDS = frozenset(
    {
        "activation_market_date",
        "cohort_id",
        "minimum_calendar_days",
        "minimum_completed_sessions",
        "minimum_paired_windows_for_pilot",
        "minimum_paired_windows_for_verdict",
        "retrospective_backfill",
        "tuning_during_cohort",
    }
)
LEGACY_BINDING_FIELDS = frozenset(
    {
        "agent_policy_registry_sha256",
        "algorithm_strategy_config_sha256",
        "proposal_model_identity_sha256",
        "veto_model_identity_sha256",
    }
)
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class TrialStatusError(ValueError):
    """The P7 registration or its existing evidence is invalid."""


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise TrialStatusError(f"P7 {field} is invalid")
    return value


def _hash(value: object, field: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise TrialStatusError(f"P7 {field} is invalid")
    return value


def _positive_number(value: object, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise TrialStatusError(f"P7 {field} is invalid")
    return float(value)


def _validate_arm(raw: object) -> dict:
    if not isinstance(raw, dict) or set(raw) != ARM_FIELDS:
        raise TrialStatusError("P7 arm shape is invalid")
    arm = dict(raw)
    _identifier(arm["arm_id"], "arm identity")
    _identifier(arm["policy_id"], "policy identity")
    if arm["policy_version"] != 1 or isinstance(arm["policy_version"], bool):
        raise TrialStatusError("P7 policy version is invalid")
    if arm["model_role"] not in {"none", "target_choice", "veto_only"}:
        raise TrialStatusError("P7 model role is invalid")
    expected_contract = ARM_CONTRACTS.get(arm["arm_id"])
    if expected_contract is None or any(
        arm[field] != value for field, value in expected_contract.items()
    ):
        raise TrialStatusError("P7 arm contract is invalid")
    assets = arm["allowed_assets"]
    if assets != ["BIL", "CASH", "EFA", "SPY"]:
        raise TrialStatusError("P7 allowed assets are invalid")
    binding = arm["implementation_binding"]
    if not isinstance(binding, dict) or set(binding) != BINDING_FIELDS:
        raise TrialStatusError("P7 implementation binding is invalid")
    for field in ("policy_registration_sha256", "runtime_source_sha256"):
        _hash(binding[field], field, optional=True)
    if binding["portfolio_id"] is not None:
        _identifier(binding["portfolio_id"], "portfolio identity")
    expected = canonical_sha256(
        {key: value for key, value in arm.items() if key != "policy_sha256"}
    )
    if _hash(arm["policy_sha256"], "policy hash") != expected:
        raise TrialStatusError("P7 policy hash does not match its registration")
    return arm


def _load_registration(path: Path) -> dict:
    try:
        return loads_object(
            read_bytes(
                path,
                max_bytes=MAX_REGISTRATION_BYTES,
                label="P7 trial registration",
                allow_symlinked_parents=False,
            )
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise TrialStatusError("P7 trial registration is unavailable or invalid") from exc


def _validate_header(payload: dict) -> None:
    if (
        set(payload) != MANIFEST_FIELDS
        or payload["schema_version"] != SCHEMA_VERSION
        or payload["trial_id"] != TRIAL_ID
        or payload["trial_version"] != 1
        or payload["registration_status"] != "preregistered_inactive"
        or payload["execution_authority"] != "none"
        or payload["live_trading"] != "disabled"
        or payload["activation_requirements"] != list(REQUIREMENTS)
    ):
        raise TrialStatusError("P7 trial registration shape is invalid")


def _validate_capital(capital: object) -> None:
    if not isinstance(capital, dict):
        raise TrialStatusError("P7 capital contract is invalid")
    if (
        set(capital) != CAPITAL_FIELDS
        or capital.get("owner_envelope_currency") != "SGD"
        or _positive_number(capital.get("owner_envelope_value"), "capital") != 10_000.0
        or capital.get("accounting_currency") != "USD"
        or capital.get("counterfactual_book_count") != 3
    ):
        raise TrialStatusError("P7 capital contract is invalid")
    _hash(capital.get("fx_observation_sha256"), "FX identity", optional=True)
    fx_values = tuple(
        capital[field]
        for field in ("fx_observation_sha256", "fx_observed_at", "usd_opening_balance")
    )
    if any(value is None for value in fx_values) != all(value is None for value in fx_values):
        raise TrialStatusError("P7 FX boundary is incomplete")
    if capital["fx_observed_at"] is not None:
        try:
            iso_timestamp(capital["fx_observed_at"])
            _positive_number(capital["usd_opening_balance"], "USD opening balance")
        except (TypeError, ValueError) as exc:
            raise TrialStatusError("P7 FX boundary is invalid") from exc


def _validate_cohort(cohort: object) -> None:
    if not isinstance(cohort, dict):
        raise TrialStatusError("P7 cohort contract is invalid")
    expected = {
        "minimum_calendar_days": 90,
        "minimum_completed_sessions": 60,
        "minimum_paired_windows_for_pilot": 3,
        "minimum_paired_windows_for_verdict": 12,
        "retrospective_backfill": False,
        "tuning_during_cohort": False,
    }
    if set(cohort) != COHORT_FIELDS or any(
        cohort[field] != value for field, value in expected.items()
    ):
        raise TrialStatusError("P7 cohort contract is invalid")
    if cohort["activation_market_date"] is not None:
        try:
            iso_date(cohort["activation_market_date"])
        except (TypeError, ValueError) as exc:
            raise TrialStatusError("P7 activation date is invalid") from exc
    if cohort["cohort_id"] is not None:
        _identifier(cohort["cohort_id"], "cohort identity")


def _validate_hash_map(value: object, fields: frozenset[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != fields:
        raise TrialStatusError(f"P7 {label} shape is invalid")
    for field, item in value.items():
        _hash(item, field, optional=label == "runtime evidence")


def registration(path: Path = REGISTRATION_PATH) -> dict:
    """Load the exact preregistration and verify all nested identities."""
    payload = _load_registration(path)
    _validate_header(payload)
    arms = [_validate_arm(item) for item in payload["arms"]]
    if tuple(item["arm_id"] for item in arms) != ARM_IDS:
        raise TrialStatusError("P7 trial arms are invalid")
    _validate_capital(payload["capital"])
    _validate_cohort(payload["cohort"])
    _validate_hash_map(payload["legacy_bindings"], LEGACY_BINDING_FIELDS, "legacy bindings")
    _validate_hash_map(payload["runtime_evidence"], RUNTIME_EVIDENCE_FIELDS, "runtime evidence")
    if payload["decision_contract"] != {
        "cadence": "monthly",
        "execution_profile_id": "baseline_v1",
        "execution_profile_sha256": canonical_sha256(PROFILES["baseline_v1"].as_dict()),
        "fill_timing": "next_session_open",
        "gross_exposure_ceiling": "opening_capital",
        "leverage": False,
        "long_only": True,
        "margin": False,
        "options": False,
        "shorting": False,
    }:
        raise TrialStatusError("P7 execution contract is invalid")
    expected_manifest = canonical_sha256(
        {key: value for key, value in payload.items() if key != "manifest_sha256"}
    )
    if _hash(payload["manifest_sha256"], "manifest hash") != expected_manifest:
        raise TrialStatusError("P7 manifest hash does not match its registration")
    return {**payload, "arms": arms}


def _gate(name: str, passed: bool, evidence: dict) -> dict:
    return {"name": name, "status": "pass" if passed else "blocked", "evidence": evidence}


def _legacy_dependencies(manifest: dict) -> tuple[bool, dict]:
    bindings = manifest["legacy_bindings"]
    registry = agent_policy.registry()
    actual = {
        "agent_policy_registry_sha256": registry["registry_sha256"],
        "algorithm_strategy_config_sha256": canonical_sha256(config_by_id("dual_momentum")),
        "proposal_model_identity_sha256": canonical_sha256(agent_model_client.identity()),
        "veto_model_identity_sha256": canonical_sha256(agent_model_client.identity(role="veto")),
    }
    matching = sorted(key for key, value in actual.items() if bindings.get(key) == value)
    return len(matching) == len(actual), {
        "matching_binding_count": len(matching),
        "required_binding_count": len(actual),
        "mismatched_bindings": sorted(set(actual) - set(matching)),
    }


def _authority_gate(authority: dict, name: str) -> dict:
    policies = authority.get("policies")
    if not isinstance(policies, list) or not policies:
        raise TrialStatusError("existing authority projection is invalid")
    selected = []
    for policy in policies:
        gates = policy.get("automatic_paper", {}).get("gates", [])
        matches = [gate for gate in gates if gate.get("name") == name]
        if len(matches) != 1:
            raise TrialStatusError("existing authority gate is unavailable")
        selected.append(matches[0])
    return {
        "all_legacy_policies_pass": all(item.get("status") == "pass" for item in selected),
        "policy_statuses": [
            {"policy_id": policy["policy_id"], "status": item["status"]}
            for policy, item in zip(policies, selected, strict=True)
        ],
    }


def project(
    con: duckdb.DuckDBPyConnection,
    *,
    registration_path: Path = REGISTRATION_PATH,
) -> dict:
    """Project current P7 activation blockers without mutating any state."""
    manifest = registration(registration_path)
    try:
        authority = agent_authority_read_models.readiness(con)
        dependencies_pass, dependencies = _legacy_dependencies(manifest)
        data = _authority_gate(authority, "point_in_time_data")
        drills = _authority_gate(authority, "fault_injection_and_restart_evidence")
    except (ValueError, KeyError, TypeError, duckdb.Error) as exc:
        raise TrialStatusError("P7 existing-state evidence is invalid") from exc
    try:
        model_status = agent_model_client.status()
        model_transport_healthy = True
        model_transport_error = None
    except agent_model_client.ConnectorError:
        model_status = agent_model_client.identity()
        model_transport_healthy = False
        model_transport_error = "unavailable"
    arms = manifest["arms"]
    bound_arm_count = sum(
        all(value is not None for value in arm["implementation_binding"].values()) for arm in arms
    )
    portfolio_ids = [arm["implementation_binding"]["portfolio_id"] for arm in arms]
    existing_books = 0
    attribution_tables = {
        str(row[0])
        for row in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name IN "
            "('agent_paper_book_attribution', 'agent_paper_order_attribution')"
        ).fetchall()
    }
    if all(portfolio_id is not None for portfolio_id in portfolio_ids):
        existing_books = int(
            con.execute(
                "SELECT COUNT(*) FROM portfolios WHERE id IN (?, ?, ?) AND active = FALSE",
                portfolio_ids,
            ).fetchone()[0]
        )
    capital = manifest["capital"]
    runtime = manifest["runtime_evidence"]
    model_identity = agent_model_client.identity()
    prohibited_absent = (
        authority.get("broker_route") == "absent"
        and authority.get("live_trading") == "disabled"
        and authority.get("execution_authority") == "none"
    )
    gates = [
        _gate("manifest_dependencies_current", dependencies_pass, dependencies),
        _gate(
            "trial_policy_implementations",
            False,
            {
                "registered_binding_count": bound_arm_count,
                "required_arm_count": 3,
                "semantic_verifier_available": False,
                "verification_status": "unverified",
                "legacy_p5_initializer_usable_for_p7": False,
                "legacy_receipt_consumer_attribution_usable_for_p7": False,
                "reason": "legacy paths are bound to fixed USD 39000 P5 contracts and cannot represent one tri-arm cohort",
            },
        ),
        _gate(
            "observable_model_identity",
            model_transport_healthy,
            {
                "model": model_identity["model"],
                "model_version": model_identity["model_version"],
                "proxy_source_sha256": model_identity["required_proxy_source_sha256"],
                "catalog_sha256": model_identity["model_catalog_entry_sha256"],
                "upstream_model_family": agent_model_client.UPSTREAM_MODEL_FAMILY,
                "response_binding_required": True,
                "provider_model_revision_available": model_identity[
                    "provider_model_revision_available"
                ],
                "paper_authority_only": True,
            },
        ),
        _gate(
            "model_transport_healthy",
            model_transport_healthy,
            {
                "transport": model_status["transport"],
                "model": model_status["model"],
                "error": model_transport_error,
            },
        ),
        _gate(
            "shared_data_admission",
            False,
            {
                **data,
                "shared_fact_bundle_verified": False,
                "content_fingerprint_verified": False,
                "verification_status": "unverified",
            },
        ),
        _gate(
            "independent_fx_boundary",
            False,
            {
                "fx_observation_registered": capital["fx_observation_sha256"] is not None,
                "fx_observed_at": capital["fx_observed_at"],
                "usd_opening_balance": capital["usd_opening_balance"],
                "semantic_verifier_available": callable(p7_trial_attribution.verify),
                "verification_status": "unavailable_no_fx_evidence",
            },
        ),
        _gate(
            "three_isolated_books",
            False,
            {
                "matching_inactive_name_count": existing_books,
                "required_book_count": 3,
                "portfolio_bindings_complete": all(value is not None for value in portfolio_ids),
                "attribution_table_count": len(attribution_tables),
                "required_attribution_table_count": 2,
                "exact_attribution_balance_date_config_verified": False,
                "semantic_verifier_available": callable(p7_trial_attribution.verify),
                "verification_status": "unavailable_no_live_schema",
                "legacy_p5_initializer_usable_for_p7": False,
            },
        ),
        _gate(
            "simulator_only_orchestrator",
            False,
            {
                "orchestrator_source_sha256": runtime["orchestrator_source_sha256"],
                "semantic_verifier_available": False,
                "verification_status": "unverified",
            },
        ),
        _gate(
            "complete_dry_run_window",
            False,
            {
                "dry_run_window_sha256": runtime["dry_run_window_sha256"],
                "required_arm_count": 3,
                "exact_replay_required": True,
                "extra_model_calls_allowed": 0,
                "semantic_verifier_available": False,
                "verification_status": "unverified",
            },
        ),
        _gate(
            "fault_drills_current",
            False,
            {**drills, "p7_trial_drills_implemented": False, "verification_status": "unverified"},
        ),
        _gate(
            "trial_scheduler_current",
            False,
            {
                "scheduler_registration_sha256": runtime["scheduler_registration_sha256"],
                "semantic_verifier_available": False,
                "verification_status": "unverified",
            },
        ),
        _gate(
            "backup_restore_rehearsal",
            False,
            {
                "backup_restore_rehearsal_sha256": runtime["backup_restore_rehearsal_sha256"],
                "semantic_verifier_available": False,
                "verification_status": "unverified",
            },
        ),
        _gate(
            "validation_evidence",
            False,
            {
                "validation_evidence_sha256": runtime["validation_evidence_sha256"],
                "semantic_verifier_available": False,
                "verification_status": "unverified",
            },
        ),
        _gate(
            "prohibited_routes_absent",
            prohibited_absent,
            {
                "broker_route": authority.get("broker_route"),
                "live_trading": authority.get("live_trading"),
                "execution_authority": authority.get("execution_authority"),
            },
        ),
        _gate(
            "future_activation_date",
            False,
            {
                "activation_market_date": manifest["cohort"]["activation_market_date"],
                "retrospective_backfill": manifest["cohort"]["retrospective_backfill"],
                "calendar_verifier_available": False,
                "verification_status": "unverified",
            },
        ),
        _gate(
            "immutable_cohort_identity",
            False,
            {
                "cohort_id": manifest["cohort"]["cohort_id"],
                "shared_window_namespace_verified": False,
                "verification_status": "unverified",
            },
        ),
    ]
    blockers = [gate["name"] for gate in gates if gate["status"] == "blocked"]
    body = {
        "schema_version": STATUS_SCHEMA_VERSION,
        "trial_id": manifest["trial_id"],
        "trial_version": manifest["trial_version"],
        "cohort_id": manifest["cohort"]["cohort_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "status": "ready" if not blockers else "blocked",
        "activation_permitted": False,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "gates": gates,
        "execution_authority": "none",
        "broker_route": authority.get("broker_route"),
        "live_trading": authority.get("live_trading"),
    }
    return {**body, "status_sha256": canonical_sha256(body)}
