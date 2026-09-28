"""Tests for the W7 weekly operator digest."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from engine.lib import db
from farm import p16_operator_digest as digest

NOW = datetime(2026, 9, 27, 6, tzinfo=timezone.utc)


def _sources():
    comparison = {
        "challenger": "p15_ai_ranked", "paired_return_count": 22,
        "positive_lower_bound": True,
    }
    family_comparison = {
        "comparison_id": "c-blind", "candidate_for_promotion": False,
        "deflated_sharpe": {"probability": 0.71},
        "sequential": {"primary": {"max_log_e": 1.4}},
    }
    return {
        "generated_at": NOW.isoformat(),
        "evaluation": {
            "cohorts": [{"model": "GPT-5.6-Sol:max",
                         "model_version": "unversioned-catalog-alias"}],
            "p15": {
                "status": "collecting",
                "primary": {"scored_session_count": 12, "next_look": 60,
                            "earliest_next_look_date": "2026-12-29"},
                "books": {"status": "collecting", "comparisons": [comparison]},
                "events": {"status": "collecting", "window_count": 4,
                           "decision_count": 9},
            },
            "p8_evaluation": {"status": "collecting", "completed_session_count": 3},
        },
        "p16": {"status": "available", "family_report": {
            "comparisons": [family_comparison]}, "promotion_candidate_ids": []},
        "filings": {"status": "unconfigured", "scan_count": 0,
                    "accession_count": 0, "scored_count": 0,
                    "unavailable_count": 0},
        "fills": {"status": "available", "measurement_count": 200,
                  "session_count": 10, "latest_median_abs_vwap_gap_bp": 8.0,
                  "prior_median_abs_vwap_gap_bp": 6.0, "drift_bp": 2.0},
        "health": {key: {"status": "ok"} for key in (
            "nightly", "weekly_walkforward", "walkforward_evidence", "scheduler",
            "source_control", "queue")},
    }


def test_complete_digest_is_compact_and_covers_every_required_section():
    text = digest.markdown(_sources())

    assert text.startswith("# Weekly operator digest — 2026-09-27")
    assert "**MODEL IDENTITY WARNING — `unversioned-catalog-alias`.**" in text
    assert "not eligible for real-capital authority" in text
    for section in ("Gates and next looks", "Books against controls",
                    "Challenger leaderboard (deflated)",
                    "Filing, event, and fill activity", "Producer health", "Owner needed"):
        assert f"## {section}" in text
    assert "| 1 | c-blind | 0.71 | 1.4 | no |" in text
    assert "latest/prior median |VWAP-open| 8/6 bp; drift 2 bp" in text
    assert len(text.splitlines()) <= 65


def test_unavailable_sources_are_explicit():
    report = _sources()
    report.update({"evaluation": {"status": "unavailable"},
                   "p16": {"status": "unavailable"},
                   "filings": {"status": "unavailable"},
                   "fills": {"status": "collecting"}, "health": {}})
    text = digest.markdown(report)

    assert "| P15 primary | unavailable |" in text
    assert "| — | unavailable | unavailable | unavailable | no |" in text
    assert "P16 filing reader: **unavailable**" in text
    assert "Fill quality: **collecting**" in text
    assert text.count("| unavailable |") >= 6


def test_fill_quality_reports_descriptive_weekly_drift(con):
    con.execute("CREATE TABLE p16_fill_measurements ("
                "measurement_sha256 VARCHAR,session_date DATE,payload_json VARCHAR)")
    days = [f"2026-09-{day:02d}" for day in range(1, 11)]
    con.executemany(
        "INSERT INTO p16_fill_measurements VALUES (?,?,?)",
        [(str(index), day, json.dumps({"vwap_gap_bp": 5 if index < 5 else 8}))
         for index, day in enumerate(days)],
    )

    result = digest.fill_quality(con)

    assert result["status"] == "available"
    assert result["session_count"] == 10
    assert result["prior_median_abs_vwap_gap_bp"] == 5
    assert result["latest_median_abs_vwap_gap_bp"] == 8
    assert result["drift_bp"] == 3


def test_fixture_command_writes_report_with_graceful_unavailable_states(tmp_path):
    database = tmp_path / "fixture.duckdb"
    con = db.connect(database)
    db.init_schema(con)
    con.close()
    evaluation = tmp_path / "missing-evaluation.json"
    output = tmp_path / "weekly" / "2026-09-27.md"

    assert digest.main([
        "--database", str(database), "--evaluation", str(evaluation),
        "--meta-path", str(tmp_path / "missing-meta.json"),
        "--data-dir", str(tmp_path), "--output", str(output),
        "--generated-at", NOW.isoformat(),
    ]) == 0

    text = output.read_text()
    assert "Weekly operator digest — 2026-09-27" in text
    assert "unversioned-catalog-alias" in text
    assert "P16 filing reader: **unconfigured**" in text
    assert "Execution authority: **none**" in text
