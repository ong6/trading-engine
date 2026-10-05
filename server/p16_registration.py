"""Validation and accessors for the frozen P16 registration."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

from engine import p16_fill_capture
from engine.lib.provenance import canonical_sha256
from engine.lib.settings import REPO_ROOT
from farm import p16_fill_calibration, p16_sequential
from sim import nyse

REGISTRATION_PATH = REPO_ROOT / "server" / "p16-registration.json"
FAMILY_ID = "p16-challengers-f1"
MEMBER_IDS = (
    "c-blind", "c-memory", "c-model-gpt-5.5-max",
    "c-model-gpt-5.6-terra-max", "c-ensemble", "c-price-only",
    "c-text-only", "c-prompt-v2",
)


def _execution_realism_valid(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    digest = value.get("registration_sha256")
    if digest != canonical_sha256({
            key: item for key, item in value.items() if key != "registration_sha256"}):
        return False
    paths = {
        "capture": REPO_ROOT / "engine" / "p16_fill_capture.py",
        "calibration": REPO_ROOT / "farm" / "p16_fill_calibration.py",
        "runner": REPO_ROOT / "farm" / "p16_fill_runner.py",
        "store": REPO_ROOT / "server" / "p16_fill_store.py",
        "quote_capture": REPO_ROOT / "server" / "p16_quote_capture.py",
        "tradingview_5m": REPO_ROOT / "server" / "p16_tradingview_intraday.py",
        "yfinance_5m": REPO_ROOT / "server" / "p16_yfinance_intraday.py",
        "future_profile_guard": REPO_ROOT / "sim" / "p16_fill_profile.py",
    }
    code = value.get("code_sha256")
    return bool(
        value.get("registration_id") == p16_fill_capture.POLICY_ID
        and value.get("status") == "registered_inactive"
        and value.get("authority") == "research_measurement_only"
        and value.get("real_data_producer_allowed") is False
        and value.get("sample", {}).get("sample_id") == p16_fill_capture.SAMPLE_ID
        and value.get("calibration", {}).get("adverse_quantile")
        == p16_fill_calibration.ADVERSE_QUANTILE
        and value.get("calibration", {}).get("targets", {}).get("adverse")
        == {"status": "not_registered", "reason": "no_admitted_vwap_or_trades_source"}
        and value.get("session_split") == {
            "rule": "first_80_exchange_sessions_after_w9_activation",
            "training_start_index": 0, "training_count": 60,
            "validation_start_index": 60, "validation_count": 20,
            "literal_dates_written_at_w9_activation": True,
        }
        and value.get("w9_activation_session") is None
        and all(key not in value for key in (
            "sessions", "training_sessions", "validation_sessions", "calendar_sha256"))
        and value.get("v5_candidate", {}).get("activatable_from_w6") is False
        and value.get("v5_candidate", {}).get("default_profile_unchanged") == "baseline_v1"
        and code == {key: hashlib.sha256(path.read_bytes()).hexdigest()
                     for key, path in paths.items()}
    )


def load_execution_realism(path: Path = REGISTRATION_PATH) -> dict:
    """Load the separately inert W6 section while the challenger epoch is pending."""
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("P16 registration is invalid") from exc
    if (not isinstance(value, dict)
            or value.get("registration_sha256") != canonical_sha256({
                key: item for key, item in value.items() if key != "registration_sha256"})
            or not _execution_realism_valid(value.get("execution_realism"))):
        raise ValueError("P16 execution-realism registration differs")
    return value["execution_realism"]


def _validate_staging_registration(value: dict) -> None:
    historical = value.get("historical_labs")
    valid_historical = (
        value.get("schema_version") == 1
        and value.get("status") == "registered_inactive"
        and isinstance(historical, dict)
        and historical.get("registration_id") == "p16-w4-historical-labs-v1"
        and historical.get("status") == "registered_inactive"
        and historical.get("real_data_producer_allowed") is False
        and historical.get("registration_sha256")
        == canonical_sha256(
            {key: item for key, item in historical.items() if key != "registration_sha256"}
        )
        and (
            value.get("execution_realism") is None
            or _execution_realism_valid(value.get("execution_realism"))
        )
    )
    if not valid_historical:
        raise ValueError("P16 registration contract differs")


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
    if value.get("registration_id") == "p16-staging-v1":
        _validate_staging_registration(value)
        if required:
            raise ValueError("P16 challenger registration is absent")
        return None
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
