"""Resolutions preserve the failed job and require exact replacement evidence."""
import json

import pytest

from engine import job_resolutions
from server import queue_monitor


def _setup(con):
    con.execute("CREATE TABLE jobs(id BIGINT,kind VARCHAR,params VARCHAR,state VARCHAR,"
                "progress VARCHAR,updated_at TIMESTAMP,last_error VARCHAR)")
    con.execute("INSERT INTO jobs VALUES (1,'history','{\"slice\":1}','failed',"
                "'1/3','2026-10-01','worker exited 1'),"
                "(2,'history','{\"slice\":2}','done','3/3','2026-10-02',NULL),"
                "(3,'history','{\"slice\":1}','done','3/3','2026-10-03',NULL)")


def test_cancellation_preserves_failure_and_replays_idempotently(con):
    _setup(con)
    before = con.execute("SELECT * FROM jobs ORDER BY id").fetchall()
    kwargs = dict(job_id=1, kind="cancelled", reason="operator stopped non-scheduled work",
                  evidence="retained operator log identifies job 1")
    job_resolutions.record(con, **kwargs)
    job_resolutions.record(con, **kwargs)
    assert con.execute("SELECT * FROM jobs ORDER BY id").fetchall() == before
    result = queue_monitor.status(con)
    assert result["counts"]["failed"] == result["historical_failure_count"] == 1
    assert result["actionable_failure_count"] == 0
    assert con.execute("SELECT COUNT(*) FROM job_resolutions").fetchone() == (1,)
    with pytest.raises(ValueError, match="different immutable"):
        job_resolutions.record(con, **{**kwargs, "reason": "different"})


def test_completion_requires_exact_successor_and_tamper_restores_warning(con):
    _setup(con)
    kwargs = dict(job_id=1, kind="completed", reason="same window recovered",
                  evidence="retained successful archive coverage receipt")
    with pytest.raises(ValueError, match="same work"):
        job_resolutions.record(con, **kwargs, replacement_job=2)
    job_resolutions.record(con, **kwargs, replacement_job=3)
    assert job_resolutions.classifications(con) == {1: job_resolutions.CLASSIFICATIONS["completed"]}
    con.execute("UPDATE jobs SET progress='changed' WHERE id=3")
    assert queue_monitor.status(con)["actionable_failure_count"] == 1


def test_modified_resolution_payload_cannot_hide_failure(con):
    _setup(con)
    job_resolutions.record(con, job_id=1, kind="cancelled", reason="intentional",
                           evidence="retained receipt")
    raw = con.execute("SELECT payload FROM job_resolutions").fetchone()[0]
    body = json.loads(raw)
    body["reason"] = "rewritten"
    con.execute("UPDATE job_resolutions SET payload=?", [json.dumps(body)])
    assert job_resolutions.classifications(con) == {}
