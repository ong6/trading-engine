from __future__ import annotations

import json

import pytest

from tools import stage_timings


def _record(run_id: str, stage: str, seconds: float, ended: str, *, driver="daily", exit=0):
    return {
        "driver": driver,
        "run_id": run_id,
        "stage": stage,
        "started": ended,
        "ended": ended,
        "seconds": seconds,
        "exit": exit,
    }


def test_summarize_uses_last_n_runs_per_driver():
    records = [
        _record("old", "collect", 100, "2026-10-01T00:00:00Z"),
        _record("new-1", "collect", 1, "2026-10-02T00:00:00Z"),
        _record("new-1", "screen", 2, "2026-10-02T00:00:01Z"),
        _record("new-2", "collect", 3, "2026-10-03T00:00:00Z", exit=1),
    ]

    assert stage_timings.summarize(records, runs=2) == [
        {
            "driver": "daily", "stage": "collect", "runs": 2,
            "median_seconds": 2.0, "p90_seconds": 3.0, "failures": 1,
        },
        {
            "driver": "daily", "stage": "screen", "runs": 1,
            "median_seconds": 2.0, "p90_seconds": 2.0, "failures": 0,
        },
    ]


def test_load_timings_ignores_malformed_lines(tmp_path):
    path = tmp_path / "timings.jsonl"
    valid = _record("run", "collect", 1.25, "2026-10-02T00:00:00Z")
    path.write_text("not-json\n" + json.dumps(valid) + "\n{}\n")
    assert stage_timings.load_timings(path) == [valid]
    assert stage_timings.load_timings(tmp_path / "missing") == []


def test_summarize_rejects_nonpositive_run_count():
    with pytest.raises(ValueError, match="runs must be positive"):
        stage_timings.summarize([], runs=0)
