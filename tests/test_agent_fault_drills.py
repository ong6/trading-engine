"""Fault-drill attestations are bounded, source-bound, and fail closed."""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone

import duckdb
import pytest

from server import agent_fault_drills

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


def _passed(_target: str):
    return subprocess.CompletedProcess(("drill",), 0, "passed\n", "")


def test_run_persists_current_all_pass_evidence_without_project_state(tmp_path):
    database = tmp_path / "drills.duckdb"
    times = iter((NOW, NOW + timedelta(seconds=1)))

    result = agent_fault_drills.run(
        database,
        lock_path=tmp_path / "drill.lock",
        runner=_passed,
        systemd_runner=_passed,
        now=lambda: next(times),
    )

    assert result["status"] == "pass"
    assert result["case_count"] == len(agent_fault_drills.DRILL_CASES)
    assert result["passed_count"] == len(agent_fault_drills.DRILL_CASES)
    assert result["failed_count"] == 0
    assert result["indeterminate_count"] == 0
    assert result["execution_authority"] == "none"
    con = duckdb.connect(str(database), read_only=True)
    try:
        status = agent_fault_drills.status(con)
        tables = {
            row[0]
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
    finally:
        con.close()
    assert status["status"] == "current_pass"
    assert status["current"] is True
    assert status["run_count"] == 1
    assert status["missing_coverage"] == []
    assert tables == {"agent_fault_drill_runs"}


def test_failed_and_indeterminate_cases_never_become_current(tmp_path):
    database = tmp_path / "drills.duckdb"
    calls = 0

    def mixed(_target: str):
        nonlocal calls
        calls += 1
        if calls == 1:
            return subprocess.CompletedProcess(("drill",), 7, "", "failed\n")
        return None

    times = iter((NOW, NOW + timedelta(seconds=1)))
    result = agent_fault_drills.run(
        database,
        lock_path=tmp_path / "drill.lock",
        runner=mixed,
        systemd_runner=mixed,
        now=lambda: next(times),
    )

    assert result["status"] == "fail"
    assert result["failed_count"] == 1
    assert result["indeterminate_count"] == len(agent_fault_drills.DRILL_CASES) - 1
    con = duckdb.connect(str(database), read_only=True)
    try:
        status = agent_fault_drills.status(con)
    finally:
        con.close()
    assert status["status"] == "fail"
    assert status["current"] is False


def test_status_marks_prior_pass_stale_when_current_suite_changes(tmp_path, monkeypatch):
    database = tmp_path / "drills.duckdb"
    times = iter((NOW, NOW + timedelta(seconds=1)))
    agent_fault_drills.run(
        database,
        lock_path=tmp_path / "drill.lock",
        runner=_passed,
        systemd_runner=_passed,
        now=lambda: next(times),
    )
    original = agent_fault_drills._suite_identity

    def changed(repo_root, registration_path):
        value = original(repo_root, registration_path)
        return {**value, "suite_sha256": "f" * 64}

    monkeypatch.setattr(agent_fault_drills, "_suite_identity", changed)
    con = duckdb.connect(str(database), read_only=True)
    try:
        status = agent_fault_drills.status(con)
    finally:
        con.close()

    assert status["status"] == "stale"
    assert status["current"] is False


def test_status_retains_verified_history_when_case_registry_expands(
    tmp_path, monkeypatch
):
    database = tmp_path / "drills.duckdb"
    current_cases = agent_fault_drills.DRILL_CASES
    earlier_cases = current_cases[:-1]
    times = iter(
        (
            NOW,
            NOW + timedelta(seconds=1),
            NOW + timedelta(seconds=2),
            NOW + timedelta(seconds=3),
        )
    )
    monkeypatch.setattr(agent_fault_drills, "DRILL_CASES", earlier_cases)
    earlier = agent_fault_drills.run(
        database,
        lock_path=tmp_path / "drill.lock",
        runner=_passed,
        systemd_runner=_passed,
        now=lambda: next(times),
    )
    monkeypatch.setattr(agent_fault_drills, "DRILL_CASES", current_cases)
    current = agent_fault_drills.run(
        database,
        lock_path=tmp_path / "drill.lock",
        runner=_passed,
        systemd_runner=_passed,
        now=lambda: next(times),
    )

    con = duckdb.connect(str(database), read_only=True)
    try:
        status = agent_fault_drills.status(con)
    finally:
        con.close()

    assert earlier["case_count"] == len(earlier_cases)
    assert current["case_count"] == len(current_cases)
    assert earlier["suite_sha256"] != current["suite_sha256"]
    assert status["status"] == "current_pass"
    assert status["current"] is True
    assert status["run_count"] == 2
    assert status["latest_run"]["run_sha256"] == current["run_sha256"]


def test_status_rejects_tampered_result_payload(tmp_path):
    database = tmp_path / "drills.duckdb"
    times = iter((NOW, NOW + timedelta(seconds=1)))
    agent_fault_drills.run(
        database,
        lock_path=tmp_path / "drill.lock",
        runner=_passed,
        systemd_runner=_passed,
        now=lambda: next(times),
    )
    con = duckdb.connect(str(database))
    try:
        con.execute(
            "UPDATE agent_fault_drill_runs SET results_payload = ?",
            ['{"tampered":true}'],
        )
    finally:
        con.close()
    con = duckdb.connect(str(database), read_only=True)
    try:
        with pytest.raises(
            agent_fault_drills.FaultDrillError,
            match="stored fault drill result is invalid",
        ):
            agent_fault_drills.status(con)
    finally:
        con.close()


def test_run_rejects_source_change_during_drill(tmp_path, monkeypatch):
    identities = iter(
        (
            {
                "suite_sha256": "a" * 64,
                "source_sha256": "b" * 64,
                "source_file_count": 1,
                "registry_sha256": "c" * 64,
            },
            {
                "suite_sha256": "d" * 64,
                "source_sha256": "e" * 64,
                "source_file_count": 1,
                "registry_sha256": "c" * 64,
            },
        )
    )
    monkeypatch.setattr(
        agent_fault_drills,
        "_suite_identity",
        lambda *_args: next(identities),
    )

    with pytest.raises(
        agent_fault_drills.FaultDrillError,
        match="source changed",
    ):
        agent_fault_drills.run(
            tmp_path / "drills.duckdb",
            lock_path=tmp_path / "drill.lock",
            runner=_passed,
            systemd_runner=_passed,
            now=lambda: NOW,
        )

    assert not (tmp_path / "drills.duckdb").exists()
