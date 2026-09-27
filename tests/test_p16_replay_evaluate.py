"""W4 replay endpoint, registration, and count-only report tests."""
from farm.replay.evaluate import paired_notes_endpoint
from farm.replay.registration import w4_registration
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


def test_registration_is_inert_and_binds_all_w4_code_groups():
    hashes = {name: (str(index) * 64) for index, name in enumerate(
        ("collectors", "probes", "replay", "textlab", "reports"), start=1
    )}
    registration = w4_registration(hashes)
    assert registration["status"] == "registered_inactive"
    assert registration["real_data_producer_allowed"] is False
    assert registration["primary_endpoint"]["bootstrap_resamples"] == 10_000
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
    assert "Candidate sessions: 12" in rendered
    assert "Unavailable chunks: 3" in rendered
    assert "article body" not in rendered
    target = tmp_path / "replay.md"
    assert write_replay_report(target, snapshot) == target
    assert target.read_text() == rendered
