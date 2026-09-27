"""Tests for the read-only P16 evaluation projection."""
from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest

from farm import p16_evaluation_report
from server import p16_reporting
from tests.test_p16_evaluation_report import _build

NOW = datetime(2027, 1, 4, 21, tzinfo=timezone.utc)


def test_project_reports_not_initialized_without_family_evidence(monkeypatch):
    monkeypatch.setattr(p16_reporting.p16_store, "family_report_as_of",
                        lambda con, *, generated_at: None)
    assert p16_reporting.project(object(), generated_at=NOW) == {
        "schema_version": 1, "status": "not_initialized",
        "evaluation_policy_id": "p16-eval-v2", "family_report": None,
        "origin_grid": None, "promotion_candidate_ids": [],
        "promotion_authority": "owner_review_required", "execution_authority": "none",
    }


def test_project_validates_and_exposes_complete_family(monkeypatch):
    family = _build()
    monkeypatch.setattr(p16_reporting.p16_store, "family_report_as_of",
                        lambda con, *, generated_at: {"payload": family})
    result = p16_reporting.project(object(), generated_at=NOW)
    assert result["status"] == "available"
    assert result["family_report"] is family
    text = p16_reporting.markdown(result)
    assert "Status: **available**" in text
    assert "| c0 |" in text and "## Transfer coefficient" in text
    assert "Execution authority: **none**" in text


def test_project_refuses_tampered_or_unknown_status(monkeypatch):
    family = _build()
    family["promotion_candidate_ids"] = []
    monkeypatch.setattr(p16_reporting.p16_store, "family_report_as_of",
                        lambda con, *, generated_at: {"payload": family})
    with pytest.raises(ValueError, match="hash differs"):
        p16_reporting.project(object(), generated_at=NOW)

    family = _build()
    family["status"] = "unknown"
    body = {key: value for key, value in family.items() if key != "report_sha256"}
    family["report_sha256"] = p16_evaluation_report.canonical_sha256(body)
    with pytest.raises(ValueError, match="status is invalid"):
        p16_reporting.project(object(), generated_at=NOW)


def test_markdown_rejects_projection_family_mismatch():
    family = _build()
    projection = {
        "schema_version": 1, "status": "incomplete",
        "evaluation_policy_id": "p16-eval-v2", "family_report": copy.deepcopy(family),
        "promotion_authority": "owner_review_required", "execution_authority": "none",
    }
    with pytest.raises(ValueError, match="status differs"):
        p16_reporting.markdown(projection)


def test_missed_origin_is_publicly_incomplete_and_blocks_promotion(monkeypatch):
    family = _build()
    body = {
        "schema_version": 1, "registration_sha256": "b" * 64,
        "family_id": "p16-challengers-f1", "epoch_session": "2026-10-01",
        "report_at": NOW.isoformat(), "expected_through_session_index": 5,
        "status": "blocked_missing_origin_decision",
        "first_permanently_missing_session_index": 5,
        "first_permanently_missing_origin": "2026-10-08",
        "comparisons": [], "execution_authority": "none",
    }
    grid = {**body, "grid_report_sha256": p16_reporting.canonical_sha256(body)}
    monkeypatch.setattr(p16_reporting.p16_registration, "load", lambda *_args, **_kwargs: {
        "registration_sha256": "b" * 64,
        "evaluation": {"family_id": "p16-challengers-f1", "epoch_session": "2026-10-01"},
    })
    monkeypatch.setattr(p16_reporting.p16_registration, "family_members", lambda _value: [{
        "comparison_id": "c0", "trial_id": "1" * 64, "control_trial_id": "f" * 64,
    }])
    monkeypatch.setattr(p16_reporting.p16_preentry, "grid_report",
                        lambda *_args, **_kwargs: grid)
    monkeypatch.setattr(p16_reporting.p16_store, "family_report_as_of",
                        lambda con, *, generated_at: {"payload": family})

    result = p16_reporting.project(object(), generated_at=NOW)
    text = p16_reporting.markdown(result)

    assert result["status"] == "incomplete"
    assert result["origin_grid"] == grid
    assert result["promotion_candidate_ids"] == []
    assert "Status: **incomplete**" in text
    assert "origin index 5 (2026-10-08)" in text
    assert "were not backfilled into this slot" in text
