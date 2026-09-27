"""Validation and accessors for the frozen P16 registration."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from engine.lib.provenance import canonical_sha256
from engine.lib.settings import REPO_ROOT
from farm import p16_sequential
from sim import nyse

REGISTRATION_PATH = REPO_ROOT / "server" / "p16-registration.json"
FAMILY_ID = "p16-challengers-f1"
MEMBER_IDS = (
    "c-blind", "c-memory", "c-model-gpt-5.5-max",
    "c-model-gpt-5.6-terra-max", "c-ensemble", "c-price-only",
    "c-text-only", "c-prompt-v2",
)


def load(path: Path = REGISTRATION_PATH, *, required: bool = True) -> dict | None:
    """Load the self-hashed registration and validate its fixed family allocation."""
    if not path.exists():
        if required:
            raise ValueError("P16 registration is absent")
        return None
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("P16 registration is invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("P16 registration is invalid")
    digest = value.get("registration_sha256")
    if digest != canonical_sha256({
            key: item for key, item in value.items() if key != "registration_sha256"}):
        raise ValueError("P16 registration identity differs")
    evaluation, challengers, authority = (
        value.get("evaluation"), value.get("challengers"), value.get("authority"))
    members = challengers.get("members") if isinstance(challengers, dict) else None
    ids = [row.get("policy_id") for row in members] if isinstance(members, list) else []
    try:
        epoch = date.fromisoformat(evaluation["epoch_session"])
        allocation = evaluation["alpha_allocation"]
        valid = (
            value.get("schema_version") == 1
            and value.get("registration_id") == "p16-challenger-lab-v1"
            and value.get("status") in {"registered_inactive", "active"}
            and authority == {
                "scope": "research_shadow_only", "broker_access": False,
                "real_capital": False, "execution_authority": "none",
                "promotion_authority": "owner_review_required",
            }
            and evaluation["policy_id"] == "p16-eval-v2"
            and evaluation["family_id"] == FAMILY_ID
            and nyse.is_session(epoch)
            and allocation == {
                "allocation_id": p16_sequential.ALPHA_ALLOCATION_ID,
                "family_alpha": p16_sequential.FAMILY_ALPHA,
                "future_family_reserve": p16_sequential.FUTURE_FAMILY_ALPHA_RESERVE,
                "lifetime_fwer": p16_sequential.ALPHA,
                "family_size": len(MEMBER_IDS), "e_bonferroni_threshold": 200.0,
            }
            and evaluation["prior_mixture"]
            == p16_sequential.mixing_from_pre_activation([], [])
            and evaluation["prior_reason"]
            == "fewer_than_20_eligible_preactivation_origins"
            and challengers["policy_id"] == "p16-challengers-v1"
            and challengers["universe_version"] == "p15-universe-v1"
            and ids == list(MEMBER_IDS)
            and len(members) == len({row.get("trial_id") for row in members})
            and all(set(row) >= {
                "policy_id", "trial_id", "control_trial_id", "treatment_id",
                "model_contract_sha256",
            } for row in members)
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("P16 registration contract differs") from exc
    if not valid:
        raise ValueError("P16 registration contract differs")
    return value


def family_members(registration: dict) -> list[dict]:
    """Project only the identities accepted by the pre-entry store."""
    return [{key: row[key] for key in ("comparison_id", "trial_id", "control_trial_id")}
            for row in registration["challengers"]["members"]]
