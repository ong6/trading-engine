"""Pure contract for a future, short-lived automatic-paper authority lease.

This module validates a proposed lease against trusted runtime bindings. It
does not issue, sign, persist, activate, consume, renew, or revoke leases and
cannot submit an order. A successful assessment means only that the candidate
is admissible for a future activation mechanism that does not yet exist.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Literal

from engine.lib.provenance import canonical_sha256

from . import agent_model_client
from .broker_contract import require_identifier, require_symbol

LEASE_SCHEMA_VERSION = 1
ASSESSMENT_SCHEMA_VERSION = 1
MAX_LEASE_SECONDS = 300
MAX_LEASE_ORDERS = 16
CANDIDATE_GATE_NAMES = (
    "trusted_approval_reference",
    "lease_time_window",
    "immutable_runtime_bindings",
    "constrained_model_boundary",
    "bounded_risk_budget",
    "reviewed_release",
    "automatic_paper_readiness",
    "reconciled_halted_startup",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PaperLeaseError(ValueError):
    """A paper-lease contract or runtime binding is invalid."""


def _identifier(value: object, label: str) -> str:
    try:
        return require_identifier(value, label)
    except ValueError as exc:
        raise PaperLeaseError(str(exc)) from exc


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise PaperLeaseError(f"{label} must be a lowercase SHA-256")
    return value


def _positive(value: object, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise PaperLeaseError(f"{label} must be a positive finite number")
    return float(value)


def _utc(value: object, label: str) -> datetime:
    if (
        type(value) is not datetime
        or value.utcoffset() is None
        or value.utcoffset().total_seconds() != 0
    ):
        raise PaperLeaseError(f"{label} must be UTC")
    return value.astimezone(timezone.utc)


def _symbols(value: object, label: str) -> tuple[str, ...]:
    if (
        not isinstance(value, tuple)
        or not value
        or len(value) > 32
        or value != tuple(sorted(set(value)))
    ):
        raise PaperLeaseError(f"{label} must be a sorted unique tuple")
    try:
        for symbol in value:
            require_symbol(symbol)
    except ValueError as exc:
        raise PaperLeaseError(str(exc)) from exc
    return value


@dataclass(frozen=True, slots=True)
class PaperAuthorityLease:
    """One externally approved, bounded automatic-paper capability."""

    lease_id: str
    approval_id: str
    approved_by: str
    approval_evidence_sha256: str
    authority_stage: Literal["automatic_paper"]
    environment: Literal["simulator"]
    mode: Literal["agent_only", "hybrid"]
    policy_id: str
    policy_registration_sha256: str
    account_id: str
    strategy_id: str
    strategy_config_sha256: str
    data_snapshot_sha256: str
    transport: Literal["trae_cli_proxy"]
    endpoint: str
    model: str
    model_version: str
    required_proxy_version: str
    prompt_sha256: str
    toolset_sha256: str
    execution_profile_id: str
    execution_profile_sha256: str
    risk_policy_id: str
    risk_policy_sha256: str
    release_manifest_sha256: str
    authority_readiness_sha256: str
    decision_window_id: str
    allowed_symbols: tuple[str, ...]
    capital_ceiling: float
    max_order_notional: float
    max_orders: int
    approved_at: datetime
    not_before: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for value, label in (
            (self.lease_id, "paper lease identifier"),
            (self.approval_id, "paper approval identifier"),
            (self.approved_by, "paper approver identifier"),
            (self.policy_id, "paper policy identifier"),
            (self.account_id, "paper account identifier"),
            (self.strategy_id, "paper strategy identifier"),
            (self.execution_profile_id, "paper execution profile identifier"),
            (self.risk_policy_id, "paper risk policy identifier"),
            (self.decision_window_id, "paper decision-window identifier"),
        ):
            _identifier(value, label)
        for value, label in (
            (self.approval_evidence_sha256, "paper approval evidence identity"),
            (self.policy_registration_sha256, "policy registration identity"),
            (self.strategy_config_sha256, "strategy config identity"),
            (self.data_snapshot_sha256, "data snapshot identity"),
            (self.prompt_sha256, "prompt identity"),
            (self.toolset_sha256, "toolset identity"),
            (self.execution_profile_sha256, "execution profile identity"),
            (self.risk_policy_sha256, "risk policy identity"),
            (self.release_manifest_sha256, "release manifest identity"),
            (self.authority_readiness_sha256, "authority readiness identity"),
        ):
            _sha256(value, label)
        for value, label in (
            (self.model, "paper model identifier"),
            (self.model_version, "paper model-version identifier"),
            (self.required_proxy_version, "paper proxy-version identifier"),
        ):
            _identifier(value, label)
        if self.authority_stage != "automatic_paper":
            raise PaperLeaseError("paper lease authority stage is invalid")
        if self.environment != "simulator":
            raise PaperLeaseError("paper lease environment must be simulator")
        if self.mode not in {"agent_only", "hybrid"}:
            raise PaperLeaseError("paper lease mode is invalid")
        expected_model = agent_model_client.identity(
            role="proposal" if self.mode == "agent_only" else "veto"
        )
        if (
            self.transport != expected_model["transport"]
            or self.endpoint != expected_model["endpoint"]
            or self.model != expected_model["model"]
            or self.required_proxy_version != expected_model["required_proxy_version"]
            or self.prompt_sha256 != expected_model["instructions_sha256"]
            or self.toolset_sha256 != expected_model["toolset_sha256"]
        ):
            raise PaperLeaseError("paper lease model boundary is invalid")
        if self.model_version in {
            agent_model_client.MODEL_VERSION,
            "unversioned-catalog-alias",
        }:
            raise PaperLeaseError("paper lease requires a provider-stable model revision")
        object.__setattr__(
            self,
            "allowed_symbols",
            _symbols(self.allowed_symbols, "paper allowed symbols"),
        )
        object.__setattr__(
            self,
            "capital_ceiling",
            _positive(self.capital_ceiling, "paper capital ceiling"),
        )
        object.__setattr__(
            self,
            "max_order_notional",
            _positive(self.max_order_notional, "paper order-notional ceiling"),
        )
        if self.max_order_notional > self.capital_ceiling:
            raise PaperLeaseError(
                "paper order-notional ceiling exceeds capital ceiling"
            )
        if (
            isinstance(self.max_orders, bool)
            or not isinstance(self.max_orders, int)
            or not 1 <= self.max_orders <= MAX_LEASE_ORDERS
        ):
            raise PaperLeaseError(
                f"paper lease order count must be from 1 through {MAX_LEASE_ORDERS}"
            )
        approved_at = _utc(self.approved_at, "paper approval time")
        not_before = _utc(self.not_before, "paper lease start")
        expires_at = _utc(self.expires_at, "paper lease expiry")
        if not approved_at <= not_before < expires_at:
            raise PaperLeaseError("paper lease timestamps are out of order")
        if (expires_at - not_before).total_seconds() > MAX_LEASE_SECONDS:
            raise PaperLeaseError(
                f"paper lease duration exceeds {MAX_LEASE_SECONDS} seconds"
            )
        object.__setattr__(self, "approved_at", approved_at)
        object.__setattr__(self, "not_before", not_before)
        object.__setattr__(self, "expires_at", expires_at)

    def payload(self) -> dict:
        body = asdict(self)
        body["schema_version"] = LEASE_SCHEMA_VERSION
        body["allowed_symbols"] = list(self.allowed_symbols)
        for field in ("approved_at", "not_before", "expires_at"):
            body[field] = getattr(self, field).isoformat().replace("+00:00", "Z")
        return body

    def sha256(self) -> str:
        return canonical_sha256(self.payload())


@dataclass(frozen=True, slots=True)
class PaperAuthorityBindings:
    """Trusted current state against which a proposed lease is checked."""

    mode: Literal["agent_only", "hybrid"]
    policy_id: str
    policy_registration_sha256: str
    account_id: str
    strategy_id: str
    strategy_config_sha256: str
    data_snapshot_sha256: str
    transport: Literal["trae_cli_proxy"]
    endpoint: str
    model: str
    model_version: str
    required_proxy_version: str
    prompt_sha256: str
    toolset_sha256: str
    execution_profile_id: str
    execution_profile_sha256: str
    risk_policy_id: str
    risk_policy_sha256: str
    release_manifest_sha256: str
    authority_readiness_sha256: str
    decision_window_id: str
    allowed_symbols: tuple[str, ...]
    capital_ceiling: float
    max_order_notional: float
    max_orders: int
    release_eligible: bool
    automatic_paper_gate_passed: bool
    startup_assessment_sha256: str
    startup_status: Literal["reconciled_halted", "blocked"]
    startup_safe_halted: bool
    startup_submission_authority: Literal["none"]

    def __post_init__(self) -> None:
        if self.mode not in {"agent_only", "hybrid"}:
            raise PaperLeaseError("paper binding mode is invalid")
        if not isinstance(self.transport, str) or not self.transport:
            raise PaperLeaseError("paper binding transport is invalid")
        if not isinstance(self.endpoint, str) or not self.endpoint:
            raise PaperLeaseError("paper binding endpoint is invalid")
        for value, label in (
            (self.policy_id, "paper policy identifier"),
            (self.account_id, "paper account identifier"),
            (self.strategy_id, "paper strategy identifier"),
            (self.execution_profile_id, "paper execution profile identifier"),
            (self.risk_policy_id, "paper risk policy identifier"),
            (self.decision_window_id, "paper decision-window identifier"),
        ):
            _identifier(value, label)
        for value, label in (
            (self.policy_registration_sha256, "policy registration identity"),
            (self.strategy_config_sha256, "strategy config identity"),
            (self.data_snapshot_sha256, "data snapshot identity"),
            (self.prompt_sha256, "prompt identity"),
            (self.toolset_sha256, "toolset identity"),
            (self.execution_profile_sha256, "execution profile identity"),
            (self.risk_policy_sha256, "risk policy identity"),
            (self.release_manifest_sha256, "release manifest identity"),
            (self.authority_readiness_sha256, "authority readiness identity"),
            (self.startup_assessment_sha256, "startup assessment identity"),
        ):
            _sha256(value, label)
        for value, label in (
            (self.model, "paper model identifier"),
            (self.model_version, "paper model-version identifier"),
            (self.required_proxy_version, "paper proxy-version identifier"),
        ):
            _identifier(value, label)
        object.__setattr__(
            self,
            "allowed_symbols",
            _symbols(self.allowed_symbols, "paper allowed symbols"),
        )
        object.__setattr__(
            self,
            "capital_ceiling",
            _positive(self.capital_ceiling, "paper capital ceiling"),
        )
        object.__setattr__(
            self,
            "max_order_notional",
            _positive(self.max_order_notional, "paper order-notional ceiling"),
        )
        if self.max_order_notional > self.capital_ceiling:
            raise PaperLeaseError(
                "paper order-notional ceiling exceeds capital ceiling"
            )
        if (
            isinstance(self.max_orders, bool)
            or not isinstance(self.max_orders, int)
            or not 1 <= self.max_orders <= MAX_LEASE_ORDERS
        ):
            raise PaperLeaseError(
                f"paper binding order count must be from 1 through {MAX_LEASE_ORDERS}"
            )
        if type(self.release_eligible) is not bool:
            raise PaperLeaseError("paper release eligibility must be boolean")
        if type(self.automatic_paper_gate_passed) is not bool:
            raise PaperLeaseError("automatic-paper gate state must be boolean")
        if self.startup_status not in {"reconciled_halted", "blocked"}:
            raise PaperLeaseError("startup status is invalid")
        if type(self.startup_safe_halted) is not bool:
            raise PaperLeaseError("startup halted state must be boolean")
        if self.startup_submission_authority != "none":
            raise PaperLeaseError("startup submission authority must be none")


def _assessment_blockers(assessment: dict) -> list[str]:
    gates = assessment["gates"]
    if (
        not isinstance(gates, list)
        or tuple(gate.get("name") for gate in gates if isinstance(gate, dict))
        != CANDIDATE_GATE_NAMES
        or any(
            not isinstance(gate, dict)
            or set(gate) != {"name", "status"}
            or gate["status"] not in {"pass", "blocked"}
            for gate in gates
        )
    ):
        raise PaperLeaseError("paper candidate assessment gates are invalid")
    blocked = [gate["name"] for gate in gates if gate["status"] == "blocked"]
    if assessment["blockers"] != blocked:
        raise PaperLeaseError("paper candidate assessment outcome is inconsistent")
    return blocked


def verify_candidate_assessment(
    assessment: object,
    lease: PaperAuthorityLease,
    *,
    trusted_assessment_sha256: str,
) -> dict:
    """Verify one complete admissible candidate assessment."""
    if not isinstance(lease, PaperAuthorityLease):
        raise TypeError("lease must be a PaperAuthorityLease")
    trusted_assessment_sha256 = _sha256(
        trusted_assessment_sha256,
        "trusted paper assessment identity",
    )
    expected_fields = {
        "schema_version",
        "lease_id",
        "lease_sha256",
        "approval_evidence_sha256",
        "observed_at",
        "expires_at",
        "status",
        "candidate_admissible",
        "activation_implemented",
        "submission_authority",
        "startup_assessment_sha256",
        "gates",
        "blockers",
        "assessment_sha256",
    }
    if not isinstance(assessment, dict) or set(assessment) != expected_fields:
        raise PaperLeaseError("paper candidate assessment shape is invalid")
    for field in (
        "lease_sha256",
        "approval_evidence_sha256",
        "startup_assessment_sha256",
        "assessment_sha256",
    ):
        _sha256(assessment[field], field.replace("_", " "))
    blocked = _assessment_blockers(assessment)
    body = {
        key: value for key, value in assessment.items() if key != "assessment_sha256"
    }
    if canonical_sha256(body) != assessment["assessment_sha256"]:
        raise PaperLeaseError("paper candidate assessment hash does not match")
    if assessment["assessment_sha256"] != trusted_assessment_sha256:
        raise PaperLeaseError("paper candidate assessment is not externally trusted")
    expected_expiry = lease.expires_at.isoformat().replace("+00:00", "Z")
    if (
        type(assessment["schema_version"]) is not int
        or assessment["schema_version"] != ASSESSMENT_SCHEMA_VERSION
        or assessment["lease_id"] != lease.lease_id
        or assessment["lease_sha256"] != lease.sha256()
        or assessment["approval_evidence_sha256"]
        != lease.approval_evidence_sha256
        or assessment["expires_at"] != expected_expiry
        or assessment["status"] != "admissible_for_future_activation"
        or assessment["candidate_admissible"] is not True
        or assessment["activation_implemented"] is not False
        or assessment["submission_authority"] != "none"
        or blocked
    ):
        raise PaperLeaseError("paper candidate assessment is not admissible")
    observed_at = assessment["observed_at"]
    if not isinstance(observed_at, str) or not observed_at.endswith("Z"):
        raise PaperLeaseError("paper candidate assessment time is invalid")
    try:
        parsed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PaperLeaseError("paper candidate assessment time is invalid") from exc
    if (
        parsed.utcoffset() is None
        or parsed.utcoffset().total_seconds() != 0
        or parsed.isoformat().replace("+00:00", "Z") != observed_at
        or not lease.not_before <= parsed < lease.expires_at
    ):
        raise PaperLeaseError("paper candidate assessment time is invalid")
    return assessment


def assess_candidate(
    lease: PaperAuthorityLease,
    bindings: PaperAuthorityBindings,
    *,
    trusted_lease_sha256: str,
    approval_evidence_sha256: str,
    now: datetime,
) -> dict:
    """Assess a candidate without granting, persisting, or consuming authority."""
    if not isinstance(lease, PaperAuthorityLease):
        raise TypeError("lease must be a PaperAuthorityLease")
    if not isinstance(bindings, PaperAuthorityBindings):
        raise TypeError("bindings must be PaperAuthorityBindings")
    trusted_lease_sha256 = _sha256(
        trusted_lease_sha256,
        "trusted paper lease identity",
    )
    approval_evidence_sha256 = _sha256(
        approval_evidence_sha256,
        "paper approval evidence identity",
    )
    observed_at = _utc(now, "paper lease assessment time")
    lease_sha256 = lease.sha256()
    identity_fields = (
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
    )
    identity_matches = all(
        getattr(lease, field) == getattr(bindings, field)
        for field in identity_fields
    )
    budget_within_bounds = (
        lease.capital_ceiling <= bindings.capital_ceiling
        and lease.max_order_notional <= bindings.max_order_notional
        and lease.max_orders <= bindings.max_orders
    )
    startup_ready = (
        bindings.startup_status == "reconciled_halted"
        and bindings.startup_safe_halted
        and bindings.startup_submission_authority == "none"
    )
    expected_model_identity = agent_model_client.identity(
        role="proposal" if lease.mode == "agent_only" else "veto"
    )
    model_boundary_valid = (
        lease.transport == expected_model_identity["transport"]
        and lease.endpoint == expected_model_identity["endpoint"]
        and lease.model == expected_model_identity["model"]
        and lease.required_proxy_version
        == expected_model_identity["required_proxy_version"]
        and lease.prompt_sha256 == expected_model_identity["instructions_sha256"]
        and lease.toolset_sha256 == expected_model_identity["toolset_sha256"]
        and lease.model_version != agent_model_client.MODEL_VERSION
        and lease.model_version != "unversioned-catalog-alias"
    )
    gates = (
        {
            "name": "trusted_approval_reference",
            "status": (
                "pass"
                if lease_sha256 == trusted_lease_sha256
                and lease.approval_evidence_sha256 == approval_evidence_sha256
                else "blocked"
            ),
        },
        {
            "name": "lease_time_window",
            "status": (
                "pass"
                if lease.not_before <= observed_at < lease.expires_at
                else "blocked"
            ),
        },
        {
            "name": "immutable_runtime_bindings",
            "status": "pass" if identity_matches else "blocked",
        },
        {
            "name": "constrained_model_boundary",
            "status": "pass" if model_boundary_valid else "blocked",
        },
        {
            "name": "bounded_risk_budget",
            "status": "pass" if budget_within_bounds else "blocked",
        },
        {
            "name": "reviewed_release",
            "status": "pass" if bindings.release_eligible else "blocked",
        },
        {
            "name": "automatic_paper_readiness",
            "status": (
                "pass" if bindings.automatic_paper_gate_passed else "blocked"
            ),
        },
        {
            "name": "reconciled_halted_startup",
            "status": "pass" if startup_ready else "blocked",
        },
    )
    if tuple(gate["name"] for gate in gates) != CANDIDATE_GATE_NAMES:
        raise PaperLeaseError("paper candidate gate contract changed")
    blockers = [gate["name"] for gate in gates if gate["status"] == "blocked"]
    body = {
        "schema_version": ASSESSMENT_SCHEMA_VERSION,
        "lease_id": lease.lease_id,
        "lease_sha256": lease_sha256,
        "approval_evidence_sha256": approval_evidence_sha256,
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "expires_at": lease.expires_at.isoformat().replace("+00:00", "Z"),
        "status": "admissible_for_future_activation" if not blockers else "blocked",
        "candidate_admissible": not blockers,
        "activation_implemented": False,
        "submission_authority": "none",
        "startup_assessment_sha256": bindings.startup_assessment_sha256,
        "gates": list(gates),
        "blockers": blockers,
    }
    return {**body, "assessment_sha256": canonical_sha256(body)}
