"""Known-answer tests for W6 chronological calibration and v5 isolation."""
from __future__ import annotations

from datetime import date

import pytest

from engine.lib.provenance import canonical_sha256
from farm import p16_fill_calibration
from sim import execution, nyse, p16_fill_profile


def _registration():
    sessions = []
    current = date(2026, 10, 5)
    while len(sessions) < 80:
        if nyse.is_session(current):
            sessions.append(current.isoformat())
        current = nyse.next_session(current)
    body = {
        "registration_id": "p16-fills-v1", "sessions": sessions,
        "training_sessions": sessions[:60], "validation_sessions": sessions[60:],
        "calendar_sha256": canonical_sha256(sessions),
    }
    return {**body, "registration_sha256": canonical_sha256(body)}


def _observations(registration, *, validation_quote_shift=0.0):
    v4 = {"lt_5m": 25.0, "5m_20m": 15.0, "20m_50m": 10.0, "gte_50m": 5.0}
    rows = []
    for tier in p16_fill_calibration.TIERS:
        for index, session in enumerate(registration["sessions"]):
            for security in ("A", "B"):
                rows.append({
                    "session_date": session, "security_id": f"{tier}-{security}-{index}",
                    "sample_id": "p16-fills-v1:sample:1", "liquidity_tier": tier,
                    "quote_target_bp": v4[tier] + (validation_quote_shift if index >= 60 else 0),
                    "vwap_gap_bp": 5.0, "half_range_proxy_bp": v4[tier],
                    "hlc3_gap_bp": 5.0, "cross_source_open_gap_bp": 1.0,
                    "missing_reasons": [],
                })
    return rows


def test_full_fixture_calibration_passes_but_cannot_activate_v5():
    registration = _registration()
    report = p16_fill_calibration.build_report(
        registration, _observations(registration), generated_at="2027-01-28T17:05:00+00:00")

    assert report["status"] == "independent_targets_supported"
    assert report["independent_targets_verified"] is True
    assert report["execution_basis_verified"] is False
    assert report["v5_activation_eligible"] is False
    assert all(row["status"] == "independent_targets_supported" for row in report["tiers"])
    assert "does not activate fill model v5" in p16_fill_calibration.markdown(report)
    with pytest.raises(ValueError, match="not activation-eligible"):
        p16_fill_profile.validate_auction_artifact(report)
    assert execution.DEFAULT_PROFILE_ID == "baseline_v1"


def test_validation_rows_are_not_refit_into_frozen_training_estimate():
    registration = _registration()
    report = p16_fill_calibration.build_report(
        registration, _observations(registration, validation_quote_shift=20),
        generated_at="2027-01-28T17:05:00+00:00")
    highest = next(row for row in report["tiers"] if row["liquidity_tier"] == "gte_50m")

    assert highest["quote"]["estimate_bp"] == 5.0
    assert highest["quote"]["validation"]["mae_bp"] == 20.0
    assert highest["status"] == "independent_validation_failed"
    assert report["status"] == "independent_validation_failed"


def test_missing_independent_targets_stays_collecting_not_zero():
    registration = _registration()
    observations = _observations(registration)
    for row in observations:
        row["vwap_gap_bp"] = None
        row["missing_reasons"] = ["verified_vwap_unavailable"]
    report = p16_fill_calibration.build_report(
        registration, observations, generated_at="2027-01-28T17:05:00+00:00")

    assert report["status"] == "collecting"
    assert all(row["adverse_by_side"]["buy"]["estimate_bp"] is None
               for row in report["tiers"])
    assert all(row["missing_reasons"] == {"verified_vwap_unavailable": 160}
               for row in report["tiers"])


def test_future_v5_formula_uses_only_validated_auction_slippage():
    artifact = {
        "status": "validated", "independent_targets_verified": True,
        "execution_basis_verified": True,
        "execution_basis": "opening_auction_direct_paper_evidence",
        "auction_slippage_bp": {tier: 8.0 for tier in p16_fill_profile.TIERS},
    }
    assert p16_fill_profile.fill_price(100, "buy", "gte_50m", artifact) == pytest.approx(100.08)
    assert p16_fill_profile.fill_price(100, "sell", "gte_50m", artifact) == pytest.approx(99.92)
