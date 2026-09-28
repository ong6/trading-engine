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
        "calendar_sha256": canonical_sha256(sessions),
        "session_split": {
            "rule": "first_80_exchange_sessions_after_w9_activation",
            "training_start_index": 0, "training_count": 60,
            "validation_start_index": 60, "validation_count": 20,
            "literal_dates_written_at_w9_activation": True,
        },
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
                    "half_range_proxy_bp": v4[tier], "hlc3_gap_bp": 5.0,
                    "cross_source_open_gap_bp": 1.0,
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
    assert all(row["adverse"]["status"] == "not_registered" for row in report["tiers"])
    proxy = report["tiers"][0]["proxy_stability"]
    assert proxy["adverse_stress_bp"] == {"buy": 5.0, "sell": 5.0}
    assert proxy["adverse_stress_validation"]["buy"]["pinball_loss_bp"] == 0.0
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


def test_overall_status_judges_only_tiers_with_registered_coverage():
    registration = _registration()
    observations = [row for row in _observations(registration)
                    if row["liquidity_tier"] == "gte_50m"]
    report = p16_fill_calibration.build_report(
        registration, observations, generated_at="2027-01-28T17:05:00+00:00")

    assert report["status"] == "independent_targets_supported"
    assert [row["status"] for row in report["tiers"]].count(
        "independent_targets_supported") == 1


def test_missing_quote_target_is_insufficient_after_collection_window():
    registration = _registration()
    observations = _observations(registration)
    for row in observations:
        row["quote_target_bp"] = None
        row["missing_reasons"] = ["quote_capture_failed"]
    report = p16_fill_calibration.build_report(
        registration, observations, generated_at="2027-01-28T17:05:00+00:00")

    assert report["status"] == "insufficient_data"
    assert all(row["adverse"]["status"] == "not_registered" for row in report["tiers"])
    assert all(row["missing_reasons"] == {"quote_capture_failed": 160}
               for row in report["tiers"])


def test_adverse_quantile_contract_uses_pinball_loss_and_median_bias():
    errors = p16_fill_calibration.quantile_errors([0.0, 2.0, 8.0, 10.0], 8.0, 5.0)

    assert errors["pinball_loss_bp"] == pytest.approx(1.25)
    assert errors["comparator_pinball_loss_bp"] == pytest.approx(2.0)
    assert errors["median_bias_bp"] == pytest.approx(3.0)


def test_future_v5_formula_uses_only_validated_auction_slippage():
    artifact = {
        "status": "validated", "independent_targets_verified": True,
        "execution_basis_verified": True,
        "execution_basis": "opening_auction_direct_paper_evidence",
        "auction_slippage_bp": {tier: 8.0 for tier in p16_fill_profile.TIERS},
    }
    assert p16_fill_profile.fill_price(100, "buy", "gte_50m", artifact) == pytest.approx(100.08)
    assert p16_fill_profile.fill_price(100, "sell", "gte_50m", artifact) == pytest.approx(99.92)
