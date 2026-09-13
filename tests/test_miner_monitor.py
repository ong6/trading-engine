"""Tests for miner evidence monitoring."""

import json
from datetime import datetime

import pytest

from engine import queue_runner
from server import (
    miner_monitor,
    read_model_utils,
)


def _miner_meta(last_run="2026-09-07T23:00:00+00:00"):
    return {
        "intraday": {
            "last_run": last_run,
            "tickers_requested": 2,
            "tickers_with_data": 2,
            "failed_tickers": 0,
            "failed_batches": 0,
        },
        "signals_incremental": {
            "last_run": last_run,
            "rows_inserted": 1,
            "warnings": [],
            "sources": {"vix": {"status": "ok", "rows_fetched": 2, "rows_inserted": 1}},
        },
        "earnings": {
            "last_run": last_run,
            "pulled_this_run": 2,
            "with_upcoming_date": 1,
            "no_upcoming_date": 1,
            "failed_tickers": 0,
        },
        "fundamentals": {
            "last_run": last_run,
            "pulled_this_run": 2,
            "with_data": 2,
            "with_market_cap": 1,
            "failed_tickers": 0,
        },
    }


def _setup_miner_jobs(con, *, state="done", progress="complete", last_error=None):
    con.execute(
        "CREATE TABLE jobs (id BIGINT, kind VARCHAR, params VARCHAR, state VARCHAR, "
        "progress VARCHAR, created_at TIMESTAMP, updated_at TIMESTAMP, last_error VARCHAR)"
    )
    con.executemany(
        "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                job_id,
                kind,
                '{"mode": "incremental"}' if kind == "signals" else "{}",
                state,
                progress,
                datetime(2026, 9, 7, 22),
                datetime(2026, 9, 7, 23),
                last_error,
            )
            for job_id, kind in enumerate(
                ("intraday", "signals", "earnings", "fundamentals"), start=1
            )
        ],
    )


def test_miner_evidence_contract_matches_nightly_queue_plan():
    planned = {
        kind: json.loads(params)
        for kind, _priority, params in queue_runner.NIGHTLY_PLAN + queue_runner.NIGHTLY_FRIDAY_PLAN
    }

    assert miner_monitor._SCHEDULED_MINER_PARAMS == planned


def test_miner_evidence_status_requires_current_coherent_metadata(con):
    _setup_miner_jobs(con)

    result = miner_monitor.evidence_status(_miner_meta(), con)

    assert result["status"] == "current"
    assert result["current"] == result["expected"] == 4
    assert set(result["miners"]) == {"intraday", "signals", "earnings", "fundamentals"}
    assert all(item["status"] == "current" for item in result["miners"].values())


def test_miner_evidence_status_rejects_unsafe_scheduled_job_identifier(con):
    _setup_miner_jobs(con)
    con.execute(
        "UPDATE jobs SET id = ? WHERE kind = 'fundamentals'",
        [read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1],
    )

    with pytest.raises(ValueError, match="public identifier is invalid"):
        miner_monitor.evidence_status(_miner_meta(), con)


def test_miner_evidence_status_rejects_unsafe_published_count(con):
    _setup_miner_jobs(con)
    meta = _miner_meta()
    unsafe = read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1
    meta["intraday"].update(tickers_requested=unsafe, tickers_with_data=unsafe)

    result = miner_monitor.evidence_status(meta, con)

    assert result["status"] == "invalid"
    assert result["miners"]["intraday"]["reason"] == "evidence-invalid"


def test_miner_evidence_status_exposes_missing_weekly_block(con):
    _setup_miner_jobs(con)
    meta = _miner_meta()
    del meta["fundamentals"]

    result = miner_monitor.evidence_status(meta, con)

    assert result["status"] == "incomplete"
    assert result["current"] == 3
    assert result["miners"]["fundamentals"] == {
        "status": "missing",
        "job_id": 4,
        "job_state": "done",
        "job_updated_at": "2026-09-07T23:00:00",
        "reason": "evidence-missing",
    }


@pytest.mark.parametrize(
    ("mutate", "expected_status", "expected_reason"),
    [
        (
            lambda meta: meta["intraday"].update(last_run="2026-09-07T21:59:59+00:00"),
            "stale",
            "evidence-predates-latest-job",
        ),
        (
            lambda meta: meta["intraday"].update(last_run="20260907T230000+00:00"),
            "invalid",
            "evidence-invalid",
        ),
        (
            lambda meta: meta["earnings"].update(with_upcoming_date=2),
            "invalid",
            "evidence-invalid",
        ),
        (
            lambda meta: meta["fundamentals"].update(failed_tickers=1, with_data=1),
            "issues",
            "miner-reported-failures",
        ),
        (
            lambda meta: meta["signals_incremental"]["warnings"].append("source gap"),
            "issues",
            "miner-reported-failures",
        ),
    ],
)
def test_miner_evidence_status_fails_closed_on_bad_evidence(
    con, mutate, expected_status, expected_reason
):
    _setup_miner_jobs(con)
    meta = _miner_meta()
    mutate(meta)

    result = miner_monitor.evidence_status(meta, con)

    assert result["status"] == expected_status
    affected = [item for item in result["miners"].values() if item["status"] != "current"]
    assert len(affected) == 1
    assert affected[0]["reason"] == expected_reason


def test_miner_evidence_status_prioritizes_nonterminal_queue_state(con):
    _setup_miner_jobs(con)
    con.execute("UPDATE jobs SET state='running', progress='25/100' WHERE kind='earnings'")

    result = miner_monitor.evidence_status(_miner_meta(), con)

    assert result["status"] == "updating"
    assert result["miners"]["earnings"]["status"] == "running"
    assert result["miners"]["earnings"]["reason"] == "latest-job-not-done"
    assert result["miners"]["earnings"]["progress"] == "25/100"


def test_miner_evidence_status_ignores_later_ad_hoc_job(con):
    _setup_miner_jobs(con)
    con.execute(
        "INSERT INTO jobs VALUES "
        '(99, \'signals\', \'{"mode":"incremental","only":"vix"}\', '
        "'running', 'started', TIMESTAMP '2026-09-08 01:00:00', "
        "TIMESTAMP '2026-09-08 01:01:00', NULL)"
    )

    result = miner_monitor.evidence_status(_miner_meta(), con)

    assert result["status"] == "current"
    assert result["miners"]["signals"]["job_id"] == 2


def test_miner_evidence_status_ignores_ambiguous_scheduled_job_params(con):
    _setup_miner_jobs(con)
    con.execute(
        "UPDATE jobs SET params = ? WHERE kind = 'signals'",
        ['{"mode":"incremental","mode":"incremental"}'],
    )

    result = miner_monitor.evidence_status(_miner_meta(), con)

    assert result["status"] == "incomplete"
    assert result["miners"]["signals"] == {
        "status": "missing",
        "reason": "job-missing",
    }


def test_latest_scheduled_jobs_stream_until_all_miner_kinds_are_found():
    canonical = {
        "signals": '{"mode":"incremental"}',
        "intraday": "{}",
        "earnings": "{}",
        "fundamentals": "{}",
    }

    class Cursor:
        def __init__(self):
            self.batches = [
                [
                    (10, 10, "not json", "failed", None, None, None, None),
                    (
                        "signals",
                        9,
                        '{"mode":"incremental","only":"vix"}',
                        "done",
                        None,
                        None,
                        None,
                        None,
                    ),
                    ("signals", 8, canonical["signals"], "done", None, None, None, None),
                ],
                [
                    ("intraday", 7, canonical["intraday"], "done", None, None, None, None),
                    ("earnings", 6, canonical["earnings"], "done", None, None, None, None),
                    ("fundamentals", 5, canonical["fundamentals"], "done", None, None, None, None),
                    ("signals", 4, canonical["signals"], "failed", None, None, None, None),
                ],
            ]
            self.batch_sizes = []

        def fetchmany(self, size):
            self.batch_sizes.append(size)
            if not self.batches:
                raise AssertionError("scan continued after every miner kind was found")
            return self.batches.pop(0)

    class Connection:
        def __init__(self):
            self.cursor = Cursor()

        def execute(self, query):
            assert "ORDER BY id DESC" in query
            return self.cursor

    con = Connection()

    latest = miner_monitor._latest_scheduled_jobs(con)

    assert {kind: row[1] for kind, row in latest.items()} == {
        "signals": 8,
        "intraday": 7,
        "earnings": 6,
        "fundamentals": 5,
    }
    assert con.cursor.batch_sizes == [
        miner_monitor.JOB_SCAN_BATCH_SIZE,
        miner_monitor.JOB_SCAN_BATCH_SIZE,
    ]
