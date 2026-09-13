"""Tests for research queue monitoring."""

from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from server import (
    queue_monitor,
    read_model_utils,
)


def test_queue_status_summarizes_and_returns_latest_research_job(con):
    con.execute("""
        CREATE TABLE jobs (
            id INTEGER, kind VARCHAR, params VARCHAR, state VARCHAR, progress VARCHAR,
            updated_at TIMESTAMP, last_error VARCHAR
        )
    """)
    con.executemany(
        "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (1, "walkforward", "{}", "failed", "enqueue", datetime(2026, 9, 6, 6), "boom"),
            (2, "signals", "{}", "done", "done", datetime(2026, 9, 6, 7), None),
            (
                3,
                "sweep",
                '{"grid":"open","charter_version":"v1"}',
                "pending",
                "queued",
                datetime(2026, 9, 6, 8),
                None,
            ),
        ],
    )
    status = queue_monitor.status(con)
    assert status["counts"] == {"done": 1, "failed": 1, "pending": 1}
    assert status["actionable_failure_count"] == 1
    assert status["actionable_failures"] == [
        {
            "id": 1,
            "kind": "walkforward",
            "updated_at": "2026-09-06T06:00:00+00:00",
        }
    ]
    assert status["actionable_failures_limit"] == queue_monitor.FAILURE_DETAIL_LIMIT
    assert status["actionable_failures_truncated"] is False
    assert status["historical_failure_count"] == 0
    assert status["historical_failures_limit"] == queue_monitor.FAILURE_DETAIL_LIMIT
    assert status["historical_failures_truncated"] is False
    assert status["latest_research_job"]["id"] == 3
    assert status["latest_research_job"]["state"] == "pending"
    assert status["latest_research_job"]["updated_at"] == "2026-09-06T08:00:00+00:00"
    assert status["latest_research_job"] == {
        "id": 3,
        "kind": "sweep",
        "state": "pending",
        "updated_at": "2026-09-06T08:00:00+00:00",
    }


@pytest.mark.parametrize("state", ["failed", "pending"])
def test_queue_status_rejects_unsafe_public_job_identifier(con, state):
    con.execute(
        "CREATE TABLE jobs (id BIGINT, kind VARCHAR, params VARCHAR, state VARCHAR, "
        "progress VARCHAR, updated_at TIMESTAMP, last_error VARCHAR)"
    )
    con.execute(
        "INSERT INTO jobs VALUES (?, 'walkforward', '{}', ?, NULL, now(), NULL)",
        [read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1, state],
    )

    with pytest.raises(ValueError, match="public identifier is invalid"):
        queue_monitor.status(con)


def test_queue_status_rejects_unsafe_grouped_count(con):
    con.execute(
        "CREATE TABLE jobs (id BIGINT, kind VARCHAR, params VARCHAR, state VARCHAR, "
        "progress VARCHAR, updated_at TIMESTAMP, last_error VARCHAR)"
    )

    class UnsafeCountConnection:
        def execute(self, query, parameters=None):
            if query.startswith("SELECT state, COUNT(*)"):
                return self
            return con.execute(query, parameters) if parameters is not None else con.execute(query)

        def fetchall(self):
            return [("done", read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1)]

    with pytest.raises(ValueError, match="public count is invalid"):
        queue_monitor.status(UnsafeCountConnection())


def test_queue_public_job_kinds_are_bounded_without_exposing_worker_text(con):
    long_kind = "💥" * 100
    _setup_queue_failures(
        con,
        [
            (
                1,
                long_kind,
                "/private/input.json",
                "failed",
                "/private/progress.log",
                datetime(2026, 9, 7, 6),
                "traceback from /private/worker.py",
            )
        ],
    )

    status = queue_monitor.status(con)

    assert status["actionable_failures"] == [
        {
            "id": 1,
            "kind": "💥" * queue_monitor.FAILURE_KIND_MAX_CHARS,
            "updated_at": "2026-09-07T06:00:00+00:00",
        }
    ]


@pytest.mark.parametrize("kind", [None, "   "])
def test_queue_rejects_malformed_failure_kind_without_rewriting(con, kind):
    _setup_queue_failures(
        con,
        [(1, kind, "{}", "failed", "failed", datetime(2026, 9, 7, 6), "boom")],
    )

    with pytest.raises(ValueError, match="public queue job kind is invalid"):
        queue_monitor.status(con)
    assert con.execute("SELECT kind FROM jobs WHERE id = 1").fetchone() == (kind,)


def test_queue_final_projection_rejects_false_limits_duplicates_and_order(con):
    payload = queue_monitor.status(con)
    row = {
        "id": 2,
        "kind": "signals",
        "updated_at": "2026-09-07T06:00:00+00:00",
    }
    payload.update(
        {
            "counts": {"failed": 2},
            "actionable_failure_count": 2,
            "actionable_failures": [row, {**row, "id": 1}],
        }
    )
    queue_monitor._validate_queue_status(payload)

    false_limit = deepcopy(payload)
    false_limit["actionable_failures_limit"] = 2
    with pytest.raises(ValueError, match="collection is inconsistent"):
        queue_monitor._validate_queue_status(false_limit)

    duplicated = deepcopy(payload)
    duplicated["actionable_failures"][1]["id"] = 2
    with pytest.raises(ValueError, match="identifier is duplicated"):
        queue_monitor._validate_queue_status(duplicated)

    unordered = deepcopy(payload)
    unordered["actionable_failures"].reverse()
    with pytest.raises(ValueError, match="not ordered"):
        queue_monitor._validate_queue_status(unordered)

    noncanonical_timestamp = deepcopy(payload)
    noncanonical_timestamp["actionable_failures"][0]["updated_at"] = "2026-09-07T06:00:00Z"
    with pytest.raises(ValueError, match="public queue timestamp is invalid"):
        queue_monitor._validate_queue_status(noncanonical_timestamp)


def _setup_queue_failures(con, rows):
    con.execute("""
        CREATE TABLE jobs (
            id INTEGER, kind VARCHAR, params VARCHAR, state VARCHAR, progress VARCHAR,
            updated_at TIMESTAMP, last_error VARCHAR
        )
    """)
    con.executemany("INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?)", rows)


def test_closed_sweep_failure_is_preserved_as_non_actionable_history(monkeypatch, con):
    monkeypatch.setattr(queue_monitor.sweep_monitor, "recurring_charters", lambda: [])
    _setup_queue_failures(
        con,
        [
            (
                315,
                "sweep",
                '{"grid":"meanrev"}',
                "failed",
                "timeout",
                datetime(2026, 9, 5, 20),
                "timeout: killed after 50400s",
            ),
        ],
    )

    status = queue_monitor.status(con)

    assert status["counts"]["failed"] == 1
    assert status["actionable_failure_count"] == 0
    assert status["historical_failure_count"] == 1
    assert status["historical_failures"][0]["id"] == 315
    assert status["historical_failures"][0]["classification"] == (
        "recurring sweep charter is closed"
    )


def test_open_recurring_sweep_failure_remains_actionable(monkeypatch, con):
    monkeypatch.setattr(
        queue_monitor.sweep_monitor, "recurring_charters", lambda: [("meanrev", "v2")]
    )
    _setup_queue_failures(
        con,
        [
            (
                1,
                "sweep",
                '{"grid":"meanrev","charter_version":"v2"}',
                "failed",
                "timeout",
                datetime(2026, 9, 7, 6),
                "timeout",
            ),
        ],
    )

    status = queue_monitor.status(con)

    assert status["actionable_failure_count"] == 1
    assert status["actionable_failures"][0]["id"] == 1
    assert status["historical_failure_count"] == 0


def test_closed_sweep_failure_with_active_equivalent_remains_actionable(monkeypatch, con):
    monkeypatch.setattr(queue_monitor.sweep_monitor, "recurring_charters", lambda: [])
    _setup_queue_failures(
        con,
        [
            (
                1,
                "sweep",
                '{"grid":"meanrev","charter_version":"v1"}',
                "failed",
                "timeout",
                datetime(2026, 9, 7, 6),
                "timeout",
            ),
            (
                2,
                "sweep",
                '{ "charter_version": "v1", "grid": "meanrev" }',
                "running",
                "started",
                datetime(2026, 9, 7, 7),
                None,
            ),
        ],
    )

    status = queue_monitor.status(con)

    assert status["actionable_failure_count"] == 1
    assert status["historical_failure_count"] == 0


def test_unversioned_failure_for_currently_open_sweep_is_actionable(monkeypatch, con):
    monkeypatch.setattr(
        queue_monitor.sweep_monitor, "recurring_charters", lambda: [("meanrev", "v2")]
    )
    _setup_queue_failures(
        con,
        [
            (
                1,
                "sweep",
                '{"grid":"meanrev"}',
                "failed",
                "failed",
                datetime(2026, 9, 7, 6),
                "missing charter",
            ),
        ],
    )

    status = queue_monitor.status(con)

    assert status["actionable_failure_count"] == 1
    assert status["historical_failure_count"] == 0


@pytest.mark.parametrize("params", ["not json", "[]", '{"charter_version":"v1"}'])
def test_malformed_sweep_failure_remains_actionable(monkeypatch, con, params):
    monkeypatch.setattr(queue_monitor.sweep_monitor, "recurring_charters", lambda: [])
    _setup_queue_failures(
        con,
        [
            (1, "sweep", params, "failed", "failed", datetime(2026, 9, 7, 6), "bad params"),
        ],
    )

    status = queue_monitor.status(con)

    assert status["actionable_failure_count"] == 1
    assert status["historical_failure_count"] == 0


def test_invalid_recurring_sweep_registry_fails_closed(monkeypatch, con):
    def invalid_registry():
        raise ValueError("invalid recurring sweep registry")

    monkeypatch.setattr(queue_monitor.sweep_monitor, "recurring_charters", invalid_registry)
    _setup_queue_failures(
        con,
        [
            (
                1,
                "sweep",
                '{"grid":"meanrev","charter_version":"v1"}',
                "failed",
                "timeout",
                datetime(2026, 9, 7, 6),
                "timeout",
            ),
        ],
    )

    status = queue_monitor.status(con)

    assert status["actionable_failure_count"] == 1
    assert status["historical_failure_count"] == 0


@pytest.mark.parametrize("kind", ["walkforward", "signals", "earnings", "backtest"])
def test_non_sweep_failure_remains_actionable(monkeypatch, con, kind):
    monkeypatch.setattr(queue_monitor.sweep_monitor, "recurring_charters", lambda: [])
    _setup_queue_failures(
        con,
        [
            (1, kind, "{}", "failed", "failed", datetime(2026, 9, 7, 6), "boom"),
        ],
    )

    status = queue_monitor.status(con)

    assert status["actionable_failure_count"] == 1
    assert status["historical_failure_count"] == 0


def test_failure_details_are_bounded_without_weakening_totals_or_order(monkeypatch, con):
    monkeypatch.setattr(queue_monitor.sweep_monitor, "recurring_charters", lambda: [])
    limit = queue_monitor.FAILURE_DETAIL_LIMIT
    failures_per_class = limit + 3
    rows = []
    for index in range(failures_per_class):
        actionable_id = 2 * index + 1
        historical_id = actionable_id + 1
        updated_at = datetime(2026, 1, 1) + timedelta(minutes=index)
        rows.extend(
            [
                (
                    actionable_id,
                    "signals",
                    "{}",
                    "failed",
                    "failed",
                    updated_at,
                    "boom",
                ),
                (
                    historical_id,
                    "sweep",
                    '{"grid":"closed","charter_version":"v1"}',
                    "failed",
                    "failed",
                    updated_at,
                    "boom",
                ),
            ]
        )
    _setup_queue_failures(con, rows)

    status = queue_monitor.status(con)

    assert status["counts"]["failed"] == 2 * failures_per_class
    assert status["actionable_failure_count"] == failures_per_class
    assert len(status["actionable_failures"]) == limit
    assert status["actionable_failures_truncated"] is True
    assert status["historical_failure_count"] == failures_per_class
    assert len(status["historical_failures"]) == limit
    assert status["historical_failures_truncated"] is True
    assert [row["id"] for row in status["actionable_failures"]] == sorted(
        (row[0] for row in rows if row[1] == "signals"), reverse=True
    )[:limit]
    assert [row["id"] for row in status["historical_failures"]] == sorted(
        (row[0] for row in rows if row[1] == "sweep"), reverse=True
    )[:limit]


def test_missing_jobs_table_returns_complete_empty_failure_windows(con):
    status = queue_monitor.status(con)

    assert status["actionable_failure_count"] == 0
    assert status["actionable_failures"] == []
    assert status["actionable_failures_limit"] == queue_monitor.FAILURE_DETAIL_LIMIT
    assert status["actionable_failures_truncated"] is False
    assert status["historical_failure_count"] == 0
    assert status["historical_failures"] == []
    assert status["historical_failures_limit"] == queue_monitor.FAILURE_DETAIL_LIMIT
    assert status["historical_failures_truncated"] is False


def test_queue_public_details_omit_raw_text_after_complete_sweep_classification(monkeypatch, con):
    monkeypatch.setattr(queue_monitor.sweep_monitor, "recurring_charters", lambda: [])
    params = '{"grid":"' + "x" * 5_000 + '","charter_version":"v1"}'
    progress = "p" * 5_000
    last_error = "e" * 5_000
    _setup_queue_failures(
        con,
        [
            (
                1,
                "sweep",
                params,
                "failed",
                progress,
                datetime(2026, 9, 7, 6),
                last_error,
            )
        ],
    )

    status = queue_monitor.status(con)
    failure = status["historical_failures"][0]

    assert status["historical_failure_count"] == 1
    assert failure == {
        "id": 1,
        "kind": "sweep",
        "updated_at": "2026-09-07T06:00:00+00:00",
        "classification": "recurring sweep charter is closed",
    }
