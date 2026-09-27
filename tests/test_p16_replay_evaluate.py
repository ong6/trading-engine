"""W4 replay endpoint, registration, and count-only report tests."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from farm.replay import report as replay_report
from farm.replay.evaluate import paired_notes_endpoint
from farm.replay.registration import admitted_grid, w4_registration
from farm.replay.report import render_replay_report, write_replay_report


def test_paired_endpoint_uses_common_sessions_and_registered_bootstrap():
    rows = [
        {
            "session": f"2024-01-{day:02d}",
            "common_names": 20,
            "notes_factor_neutral_h5_ic": 0.2,
            "control_factor_neutral_h5_ic": 0.1,
        }
        for day in range(2, 12)
    ]
    rows.append({
        "session": "2024-01-12",
        "common_names": 9,
        "notes_factor_neutral_h5_ic": -1,
        "control_factor_neutral_h5_ic": 1,
    })
    result = paired_notes_endpoint(rows)
    assert result["status"] == "positive_evidence"
    assert result["estimate"] == 0.1
    assert result["eligible_sessions"] == 10
    assert result["excluded_sessions"] == ["2024-01-12"]
    assert result["block_sessions"] == 5 and result["resamples"] == 10_000
    assert result["zero_skill_unavailable_sensitivity"] == {
        "unavailable_sessions": 0, "estimate": 0.1
    }


def test_paired_endpoint_rejects_duplicate_sessions_and_counts_unavailable_as_zero():
    row = {
        "session": "2024-01-02", "common_names": 20,
        "notes_factor_neutral_h5_ic": 0.2, "control_factor_neutral_h5_ic": 0.1,
    }
    with pytest.raises(ValueError, match="duplicate"):
        paired_notes_endpoint([row, row])
    result = paired_notes_endpoint([
        row,
        {"session": "2024-01-03", "response_status": "unavailable"},
    ], resamples=100)
    assert result["zero_skill_unavailable_sensitivity"] == {
        "unavailable_sessions": 1, "estimate": 0.05
    }


def test_registration_is_inert_and_binds_all_w4_code_groups():
    hashes = {name: (str(index) * 64) for index, name in enumerate(
        ("collectors", "probes", "replay", "textlab", "reports"), start=1
    )}
    registration = w4_registration(
        hashes,
        plan_sha256="a" * 64,
        notes_filter_spec_sha256="b" * 64,
        lesson_corpus_sha256="c" * 64,
        activation_at=datetime(2026, 9, 29, 4, tzinfo=timezone.utc),
    )
    assert registration["status"] == "registered_inactive"
    assert registration["real_data_producer_allowed"] is False
    assert registration["primary_endpoint"]["bootstrap_resamples"] == 10_000
    assert registration["mandatory_acceptance_contract"]["schema_version"] == 1
    assert registration["notes"]["maximum_lessons"] == 12
    assert registration["model_cutoffs"] == {
        "GPT-5.6-Sol": "2026-02-16", "GPT-6-Astra": "2026-04-30"
    }
    assert registration["replay_grids"]["GPT-5.6-Sol"]["lockbox"]
    assert registration["future_split_quarantine"]["windows"] == {
        "GPT-5.6-Sol": {
            "window_start": "2026-04-17", "quarantined_rows": 59,
            "excluded_securities": 57,
        },
        "GPT-6-Astra": {
            "window_start": "2026-06-29", "quarantined_rows": 20,
            "excluded_securities": 20,
        },
    }
    assert len(registration["registration_sha256"]) == 64


def test_report_contains_counts_not_raw_text(tmp_path):
    snapshot = {
        "status": "unconfigured",
        "coverage": {"candidate_sessions": 12, "unavailable_chunks": 3},
        "primary_endpoint": {"status": "unavailable", "eligible_sessions": 0},
        "book_status": "fixture_passed",
        "raw_price_status": "pass",
        "lockbox_tag": "not_started",
    }
    rendered = render_replay_report(snapshot)
    assert "Status: **exploratory**" in rendered
    assert "Candidate sessions: 12" in rendered
    assert "Unavailable chunks: 3" in rendered
    assert "article body" not in rendered
    target = tmp_path / "replay.md"
    assert write_replay_report(target, snapshot) == target
    assert target.read_text() == rendered

    assert "Status: **exploratory**" in render_replay_report(snapshot)


def test_report_derives_confirmatory_complete_status_from_ledger(monkeypatch):
    seen = []

    def classify(ledger, **query):
        seen.append((ledger, query))
        return SimpleNamespace(tag="confirmatory")

    monkeypatch.setattr(replay_report, "evaluation_tag", classify)
    ledger = object()
    rendered = render_replay_report(
        {
            "status": "caller-value-is-ignored",
            "lockbox_tag": "caller-value-is-ignored",
            "coverage": {"candidate_sessions": 1, "unavailable_chunks": 0},
            "book_status": "completed", "raw_price_status": "pass",
        },
        lockbox_ledger=ledger, lockbox_query={"trial_id": "registered"},
    )
    assert seen == [(ledger, {"trial_id": "registered"})]
    assert "Status: **complete**" in rendered
    assert "Lockbox tag: confirmatory" in rendered


def test_post_cutoff_grid_uses_c_plus_60_decision_clock_and_fixed_two_thirds():
    activation = datetime(2024, 3, 20, 1, 59, tzinfo=timezone.utc)
    grid = admitted_grid("2024-01-01", activation)
    assert grid["c_plus_60_floor"] == "2024-03-01"
    assert grid["sessions"][0] == "2024-03-01"
    assert grid["sessions"][-1] == "2024-03-18"
    assert len(grid["development"]) == (2 * len(grid["sessions"])) // 3
    assert grid["lockbox"][0] == grid["first_lockbox_session"]
    assert set(grid["development"]).isdisjoint(grid["lockbox"])
    unknown = admitted_grid(None, activation)
    assert unknown["status"] == "unknown_cutoff" and unknown["sessions"] == []
