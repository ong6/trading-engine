"""Tests for recurring sweep evidence status."""

import json

import pytest

from server import read_model_utils, sweep_monitor


def test_sweep_evidence_status_is_explicitly_idle_without_open_charters(monkeypatch, con):
    monkeypatch.setattr(sweep_monitor, "recurring_charters", lambda: [])

    assert sweep_monitor.evidence_status(con) == {
        "status": "idle",
        "reason": "no-open-recurring-charters",
        "open_charters": 0,
        "current_charters": 0,
        "charters": [],
    }


def test_latest_sweep_jobs_stream_until_every_open_charter_is_found():
    class Cursor:
        def __init__(self):
            self.batches = [
                [
                    (
                        5,
                        '{"grid":"first","charter_version":"v1"}',
                        "done",
                        None,
                        None,
                        None,
                        None,
                    )
                ],
                [
                    (4, "not json", "failed", None, None, None, "bad params"),
                    (
                        3,
                        '{"grid":"second","charter_version":"v2"}',
                        "done",
                        None,
                        None,
                        None,
                        None,
                    ),
                    (
                        2,
                        '{"grid":"first","charter_version":"v1"}',
                        "failed",
                        None,
                        None,
                        None,
                        None,
                    ),
                ],
            ]
            self.batch_sizes = []

        def fetchmany(self, size):
            self.batch_sizes.append(size)
            if not self.batches:
                raise AssertionError("scan continued after every charter was found")
            return self.batches.pop(0)

    class Connection:
        def __init__(self):
            self.cursor = Cursor()

        def execute(self, query):
            assert "ORDER BY id DESC" in query
            return self.cursor

    con = Connection()

    latest = sweep_monitor._latest_jobs(con, [("first", "v1"), ("second", "v2")])

    assert {identity: row[0] for identity, row in latest.items()} == {
        ("first", "v1"): 5,
        ("second", "v2"): 3,
    }
    assert con.cursor.batch_sizes == [
        sweep_monitor.JOB_SCAN_BATCH_SIZE,
        sweep_monitor.JOB_SCAN_BATCH_SIZE,
    ]


def _setup_open_sweep_job(con, *, state="done", progress="complete", last_error=None):
    con.execute(
        "CREATE TABLE jobs (id BIGINT, kind VARCHAR, params VARCHAR, state VARCHAR, "
        "progress VARCHAR, created_at TIMESTAMP, updated_at TIMESTAMP, last_error VARCHAR)"
    )
    con.execute(
        "INSERT INTO jobs VALUES "
        '(1, \'sweep\', \'{"grid":"probe","charter_version":"charter-v1"}\', '
        "?, ?, TIMESTAMP '2026-09-05 06:00:00', TIMESTAMP '2026-09-05 07:00:00', ?)",
        [state, progress, last_error],
    )


def _write_sweep_ranking(root, **overrides):
    path = root / "probe" / "charters" / "charter-v1" / "ranking.json"
    path.parent.mkdir(parents=True)
    payload = {
        "sweep": "probe",
        "charter_version": "charter-v1",
        "n_trials": 2,
        "generated": "2026-09-05 07:00 UTC",
        "rows": [{"id": "one"}],
        "excluded": [{"id": "two"}],
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload))
    return path


def test_sweep_evidence_status_requires_matching_job_and_ranking(monkeypatch, con, tmp_path):
    _setup_open_sweep_job(con)
    _write_sweep_ranking(tmp_path)
    monkeypatch.setattr(
        sweep_monitor, "recurring_charters", lambda: [("probe", "charter-v1")]
    )
    monkeypatch.setattr(sweep_monitor.sweep_registry, "expand", lambda name: [{}, {}])

    result = sweep_monitor.evidence_status(con, tmp_path)

    assert result["status"] == "current"
    assert result["current_charters"] == result["open_charters"] == 1
    assert result["charters"] == [
        {
            "grid": "probe",
            "charter_version": "charter-v1",
            "status": "current",
            "job_id": 1,
            "job_state": "done",
            "job_updated_at": "2026-09-05T07:00:00",
            "generated_at": "2026-09-05T07:00:00+00:00",
            "n_trials": 2,
        }
    ]


def test_sweep_evidence_rejects_unsafe_job_identifier(monkeypatch, con):
    _setup_open_sweep_job(con)
    con.execute(
        "UPDATE jobs SET id = ?",
        [read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1],
    )
    monkeypatch.setattr(
        sweep_monitor, "recurring_charters", lambda: [("probe", "charter-v1")]
    )

    with pytest.raises(ValueError, match="public identifier is invalid"):
        sweep_monitor.evidence_status(con)


def test_sweep_evidence_nonterminal_job_omits_raw_worker_details(monkeypatch, con):
    _setup_open_sweep_job(
        con,
        state="failed",
        progress="read /private/research/input.json",
        last_error="traceback from /private/worker.py",
    )
    monkeypatch.setattr(
        sweep_monitor, "recurring_charters", lambda: [("probe", "charter-v1")]
    )

    result = sweep_monitor.evidence_status(con)

    assert result == {
        "status": "failed",
        "open_charters": 1,
        "current_charters": 0,
        "charters": [
            {
                "grid": "probe",
                "charter_version": "charter-v1",
                "status": "failed",
                "job_id": 1,
                "job_state": "failed",
                "job_updated_at": "2026-09-05T07:00:00",
                "reason": "latest-job-not-done",
            }
        ],
    }


@pytest.mark.parametrize(
    ("ranking_overrides", "reason"),
    [
        ({"charter_version": "wrong"}, "ranking-invalid"),
        ({"n_trials": 1}, "ranking-invalid"),
        ({"generated": "2026-09-05 05:00 UTC"}, "ranking-predates-latest-job"),
    ],
)
def test_sweep_evidence_status_rejects_bad_published_evidence(
    monkeypatch, con, tmp_path, ranking_overrides, reason
):
    _setup_open_sweep_job(con)
    _write_sweep_ranking(tmp_path, **ranking_overrides)
    monkeypatch.setattr(
        sweep_monitor, "recurring_charters", lambda: [("probe", "charter-v1")]
    )
    monkeypatch.setattr(sweep_monitor.sweep_registry, "expand", lambda name: [{}, {}])

    result = sweep_monitor.evidence_status(con, tmp_path)

    assert result["status"] in {"invalid", "stale"}
    assert result["charters"][0]["reason"] == reason


def test_sweep_evidence_rejects_duplicate_job_parameter_key(monkeypatch, con):
    _setup_open_sweep_job(con)
    con.execute(
        "UPDATE jobs SET params = ? WHERE id = 1",
        ['{"grid":"probe","grid":"probe","charter_version":"charter-v1"}'],
    )
    monkeypatch.setattr(
        sweep_monitor, "recurring_charters", lambda: [("probe", "charter-v1")]
    )

    result = sweep_monitor.evidence_status(con)

    assert result["status"] == "incomplete"
    assert result["charters"][0]["reason"] == "job-missing"


def test_sweep_evidence_rejects_duplicate_ranking_key(monkeypatch, con, tmp_path):
    _setup_open_sweep_job(con)
    path = _write_sweep_ranking(tmp_path)
    path.write_text(path.read_text().replace('"n_trials": 2', '"n_trials": 2, "n_trials": 2'))
    monkeypatch.setattr(
        sweep_monitor, "recurring_charters", lambda: [("probe", "charter-v1")]
    )
    monkeypatch.setattr(sweep_monitor.sweep_registry, "expand", lambda name: [{}, {}])

    result = sweep_monitor.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["charters"][0]["reason"] == "ranking-invalid"
