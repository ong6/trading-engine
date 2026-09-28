"""Contract tests for the P16 registration loader."""
from __future__ import annotations

import json
from copy import deepcopy

import pytest

from engine.lib.provenance import canonical_sha256
from farm import p16_sequential
from server import p16_registration


def _registration():
    members = [{
        "policy_id": policy_id, "comparison_id": policy_id,
        "trial_id": f"{index + 1:064x}", "control_trial_id": "f" * 64,
        "treatment_id": policy_id.removeprefix("c-"),
        "model_contract_sha256": None if policy_id == "c-ensemble" else "e" * 64,
    } for index, policy_id in enumerate(p16_registration.MEMBER_IDS)]
    body = {
        "schema_version": 1, "registration_id": "p16-challenger-lab-v1",
        "status": "registered_inactive",
        "authority": {
            "scope": "research_shadow_only", "broker_access": False,
            "real_capital": False, "execution_authority": "none",
            "promotion_authority": "owner_review_required",
        },
        "evaluation": {
            "policy_id": "p16-eval-v2", "family_id": "p16-challengers-f1",
            "epoch_session": "2026-10-02",
            "alpha_allocation": {
                "allocation_id": p16_sequential.ALPHA_ALLOCATION_ID,
                "family_alpha": 0.04, "future_family_reserve": 0.01,
                "lifetime_fwer": 0.05, "family_size": 8,
                "e_bonferroni_threshold": 200.0,
            },
            "prior_mixture": p16_sequential.mixing_from_pre_activation([], []),
            "prior_reason": "fewer_than_20_eligible_preactivation_origins",
        },
        "challengers": {
            "policy_id": "p16-challengers-v1", "universe_version": "p15-universe-v1",
            "members": members,
        },
    }
    return {**body, "registration_sha256": canonical_sha256(body)}


def _write(path, value):
    path.write_text(json.dumps(value, sort_keys=True))


def test_registration_loads_fixed_family_and_preentry_bindings(tmp_path):
    path = tmp_path / "registration.json"
    value = _registration()
    _write(path, value)

    assert p16_registration.load(path) == value
    assert [row["comparison_id"] for row in p16_registration.family_members(value)] \
        == list(p16_registration.MEMBER_IDS)


def test_registration_rejects_hash_roster_and_allocation_drift(tmp_path):
    for change in ("hash", "roster", "allocation"):
        value = deepcopy(_registration())
        if change == "hash":
            value["status"] = "active"
        elif change == "roster":
            value["challengers"]["members"].reverse()
            value["registration_sha256"] = canonical_sha256({
                key: item for key, item in value.items() if key != "registration_sha256"
            })
        else:
            value["evaluation"]["alpha_allocation"]["family_alpha"] = 0.05
            value["registration_sha256"] = canonical_sha256({
                key: item for key, item in value.items() if key != "registration_sha256"
            })
        path = tmp_path / f"{change}.json"
        _write(path, value)
        with pytest.raises(ValueError, match="differs"):
            p16_registration.load(path)


def test_missing_registration_is_optional_only_when_requested(tmp_path):
    path = tmp_path / "missing.json"
    assert p16_registration.load(path, required=False) is None
    with pytest.raises(ValueError, match="absent"):
        p16_registration.load(path)


def test_inert_w4_staging_does_not_claim_challenger_registration(tmp_path):
    path = tmp_path / "registration.json"
    historical = {
        "registration_id": "p16-w4-historical-labs-v1",
        "status": "registered_inactive",
        "real_data_producer_allowed": False,
    }
    historical["registration_sha256"] = canonical_sha256(historical)
    value = {
        "schema_version": 1,
        "registration_id": "p16-staging-v1",
        "status": "registered_inactive",
        "historical_labs": historical,
    }
    value["registration_sha256"] = canonical_sha256(value)
    _write(path, value)

    assert p16_registration.load(path, required=False) is None
    with pytest.raises(ValueError, match="challenger registration is absent"):
        p16_registration.load(path)


def test_committed_w4_registration_is_inert_while_w2_epoch_is_absent():
    value = json.loads(p16_registration.REGISTRATION_PATH.read_text())
    historical = value["historical_labs"]

    assert p16_registration.load(required=False) is None
    assert historical["status"] == "registered_inactive"
    assert historical["real_data_producer_allowed"] is False
    assert historical["replay_grids"]["GPT-5.6-Sol"]["development"]
    assert historical["replay_grids"]["GPT-5.6-Sol"]["lockbox"]
    assert historical["notes"] == {
        "filter_spec_sha256": "a6261d68aaf152b24524c02b9b9ed7650ec3d970bb38a070e5435a510f3b8efd",
        "lesson_corpus_sha256": "df038a79116ccb6faebb0ee63435b1afde54945968f7371b7ca1a6f45c64433c",
        "maximum_lessons": 12,
        "postmortem_schema": "schemas/postmortem-v1.json",
        "prompt": "prompts/notes-v1.txt",
    }
    execution = p16_registration.load_execution_realism()
    assert execution["status"] == "registered_inactive"
    assert execution["real_data_producer_allowed"] is False
    assert execution["v5_candidate"] == {
        "activatable_from_w6": False,
        "default_profile_unchanged": "baseline_v1",
        "execution_basis_verified": False,
        "future_cohorts_only": True,
        "profile_id": "p16-fill-v5-candidate",
        "requires_direct_paper_auction_evidence": True,
    }
    assert execution["session_split"] == {
        "rule": "first_80_exchange_sessions_after_w9_activation",
        "training_start_index": 0, "training_count": 60,
        "validation_start_index": 60, "validation_count": 20,
        "literal_dates_written_at_w9_activation": True,
    }
    assert execution["w9_activation_session"] is None
    assert "sessions" not in execution
