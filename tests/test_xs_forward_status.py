"""Tests for cross-sectional forward-evidence status."""

import json
import sys
from datetime import date

import pytest

from server import (
    xs_forward_status,
)


def _xs_waiting_payload(**override):
    payload = {
        "schema_version": 2,
        "status": "WAITING",
        "paper_only": True,
        "automatic_action": "none",
        "candidate": {
            "portfolio_id": xs_forward_status.xs_forward_monitor.CANDIDATE_ID,
            "config_sha256": xs_forward_status.xs_forward_monitor.EXPECTED_CONFIG_SHA256[
                xs_forward_status.xs_forward_monitor.CANDIDATE_ID
            ],
            "initial_cash": xs_forward_status.xs_forward_monitor.EXPECTED_INITIAL_CASH,
            "execution_profile": xs_forward_status.xs_forward_monitor.EXPECTED_EXECUTION_PROFILE,
        },
        "control": {
            "portfolio_id": xs_forward_status.xs_forward_monitor.CONTROL_ID,
            "config_sha256": xs_forward_status.xs_forward_monitor.EXPECTED_CONFIG_SHA256[
                xs_forward_status.xs_forward_monitor.CONTROL_ID
            ],
            "initial_cash": xs_forward_status.xs_forward_monitor.EXPECTED_INITIAL_CASH,
            "execution_profile": xs_forward_status.xs_forward_monitor.EXPECTED_EXECUTION_PROFILE,
        },
        "frozen_runtime": {
            "signal_date": xs_forward_status.xs_forward_monitor.SIGNAL_DATE.isoformat(),
            "observation_start": xs_forward_status.xs_forward_monitor.OBSERVATION_START.isoformat(),
            "fill_model": xs_forward_status.xs_forward_monitor.EXPECTED_FILL_MODEL_VERSION,
            "execution_profile_sha256": xs_forward_status.xs_forward_monitor.EXPECTED_PROFILE_SHA256,
            "runtime_contract_version": xs_forward_status.xs_forward_monitor.RUNTIME_CONTRACT_VERSION,
            "runtime_contract_sha256": (
                xs_forward_status.xs_forward_monitor.EXPECTED_RUNTIME_CONTRACT_SHA256
            ),
            "superseded_runtime_contract_sha256": (
                xs_forward_status.xs_forward_monitor.SUPERSEDED_RUNTIME_CONTRACT_SHA256
            ),
            "runtime_contract_migration": (
                xs_forward_status.xs_forward_monitor.RUNTIME_CONTRACT_MIGRATION
            ),
        },
        "observation": {
            "signal_date": xs_forward_status.xs_forward_monitor.SIGNAL_DATE.isoformat(),
            "observation_start": xs_forward_status.xs_forward_monitor.OBSERVATION_START.isoformat(),
            "eligible_after": "2031-10-01",
            "shared_sessions": 0,
            "paired_complete_months": 0,
            "mature": False,
            "signal_boundary_frozen": False,
        },
    }
    payload.update(override)
    return payload


def test_xs_forward_status_projects_pre_signal_waiting(tmp_path):
    path = tmp_path / "xs.json"
    path.write_text(json.dumps(_xs_waiting_payload()))
    assert xs_forward_status.status(path, date(2026, 9, 4)) == {
        "status": "WAITING",
        "paper_only": True,
        "automatic_action": "none",
        "report_schema_version": 2,
        "runtime_contract_version": xs_forward_status.xs_forward_monitor.RUNTIME_CONTRACT_VERSION,
        "runtime_contract_sha256": (
            xs_forward_status.xs_forward_monitor.EXPECTED_RUNTIME_CONTRACT_SHA256
        ),
        "signal_date": "2026-09-30",
        "observation_start": "2026-10-01",
        "eligible_after": "2031-10-01",
        "signal_boundary_frozen": False,
        "shared_sessions": 0,
        "paired_complete_months": 0,
        "minimum_paired_months": xs_forward_status.xs_forward_monitor.MIN_PAIRED_MONTHS,
        "mature": False,
    }


def test_xs_forward_status_matches_live_pre_signal_report(monkeypatch, tmp_path):
    payload = _xs_waiting_payload()
    path = tmp_path / "xs.json"
    path.write_text(json.dumps(payload))
    monkeypatch.setattr(
        xs_forward_status.xs_forward_monitor, "evaluate", lambda *_args, **_kwargs: payload
    )
    assert xs_forward_status.status(path, date(2026, 9, 4), object())["status"] == ("WAITING")


def test_xs_forward_status_rejects_live_report_mismatch(monkeypatch, tmp_path):
    payload = _xs_waiting_payload()
    path = tmp_path / "xs.json"
    path.write_text(json.dumps(payload))
    changed = _xs_waiting_payload(status="ACCUMULATING")
    monkeypatch.setattr(
        xs_forward_status.xs_forward_monitor, "evaluate", lambda *_args, **_kwargs: changed
    )
    assert xs_forward_status.status(path, date(2026, 9, 4), object()) == {
        "status": "INVALID",
        "paper_only": True,
        "automatic_action": "none",
    }


def test_xs_forward_status_fails_closed_for_deep_live_evaluation(monkeypatch, tmp_path):
    payload = _xs_waiting_payload()
    path = tmp_path / "xs.json"
    path.write_text(json.dumps(payload))
    live = _xs_waiting_payload()
    nested = live["observation"]
    for _ in range(sys.getrecursionlimit() * 2):
        nested["nested"] = {}
        nested = nested["nested"]
    monkeypatch.setattr(
        xs_forward_status.xs_forward_monitor,
        "evaluate",
        lambda *_args, **_kwargs: live,
    )

    assert xs_forward_status.status(path, date(2026, 9, 4), object()) == {
        "status": "INVALID",
        "paper_only": True,
        "automatic_action": "none",
    }


def test_xs_forward_status_rejects_duplicate_json_key(tmp_path):
    path = tmp_path / "xs.json"
    payload = json.dumps(_xs_waiting_payload()).replace(
        '"status": "WAITING"',
        '"status": "WAITING", "status": "ACCUMULATING"',
        1,
    )
    path.write_text(payload)

    assert xs_forward_status.status(path, date(2026, 9, 4)) == {
        "status": "INVALID",
        "paper_only": True,
        "automatic_action": "none",
    }


def test_xs_forward_status_rejects_noncanonical_eligibility_date(tmp_path):
    path = tmp_path / "xs.json"
    payload = _xs_waiting_payload()
    payload["observation"]["eligible_after"] = "20311001"
    path.write_text(json.dumps(payload))

    assert xs_forward_status.status(path, date(2026, 9, 4)) == {
        "status": "INVALID",
        "paper_only": True,
        "automatic_action": "none",
    }


@pytest.mark.parametrize(
    "override",
    [
        {"status": "PROMOTE"},
        {"paper_only": False},
        {"automatic_action": "activate"},
        {"schema_version": 1},
        {"observation": {"paired_complete_months": 1}},
    ],
)
def test_xs_forward_status_rejects_unsafe_or_malformed_payload(tmp_path, override):
    path = tmp_path / "xs.json"
    path.write_text(json.dumps(_xs_waiting_payload(**override)))
    assert xs_forward_status.status(path, date(2026, 9, 4)) == {
        "status": "INVALID",
        "paper_only": True,
        "automatic_action": "none",
    }
