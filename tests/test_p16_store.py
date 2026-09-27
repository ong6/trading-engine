"""Append-only P16 evaluation-store tests."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import duckdb
import pytest

from server import p16_store

NOW = datetime(2026, 9, 27, 16, tzinfo=timezone.utc)
DAY = date(2026, 9, 25)
DIGEST = "a" * 64
REGISTRATION = "b" * 64
TRIAL = "c" * 64
EPOCH = date(2026, 9, 21)


@pytest.fixture
def con():
    connection = duckdb.connect(":memory:")
    p16_store.init_schema(connection)
    yield connection
    connection.close()


def test_artifacts_are_immutable_idempotent_and_as_of(con):
    first = p16_store.record_artifact(
        con, registration_sha256=REGISTRATION, artifact_kind="origin",
        artifact_key="p15-scoring-v1", market_date=DAY,
        information_cutoff_at=NOW - timedelta(hours=2), recorded_at=NOW,
        source_sha256=DIGEST, payload={"status": "available", "rows": [1, 2]},
    )
    assert p16_store.record_artifact(
        con, registration_sha256=REGISTRATION, artifact_kind="origin",
        artifact_key="p15-scoring-v1", market_date=DAY,
        information_cutoff_at=NOW - timedelta(hours=2), recorded_at=NOW,
        source_sha256=DIGEST, payload={"status": "available", "rows": [1, 2]},
    ) == first
    assert p16_store.artifacts_as_of(
        con, generated_at=NOW - timedelta(seconds=1)) == []
    visible = p16_store.artifacts_as_of(
        con, generated_at=NOW, registration_sha256=REGISTRATION, artifact_kind="origin",
        artifact_key="p15-scoring-v1", through_market_date=DAY,
    )
    assert visible[0]["artifact_sha256"] == first
    assert visible[0]["payload"] == {"rows": [1, 2], "status": "available"}
    with pytest.raises(ValueError, match="replayed differently"):
        p16_store.record_artifact(
            con, registration_sha256=REGISTRATION, artifact_kind="origin",
            artifact_key="p15-scoring-v1", market_date=DAY,
            information_cutoff_at=NOW - timedelta(hours=2), recorded_at=NOW,
            source_sha256=DIGEST, payload={"status": "changed"},
        )


def test_artifact_tampering_is_detected(con):
    p16_store.record_artifact(
        con, registration_sha256=REGISTRATION, artifact_kind="factor_report",
        artifact_key="origin-1", market_date=DAY,
        information_cutoff_at=NOW, recorded_at=NOW, source_sha256=DIGEST,
        payload={"status": "available"},
    )
    con.execute("UPDATE p16_evaluation_artifacts SET payload_json='{}'")
    with pytest.raises(ValueError, match="identity differs"):
        p16_store.artifacts_as_of(con, generated_at=NOW)


def _origin(index: int, market_date: date, **updates):
    value = {
        "registration_sha256": REGISTRATION, "family_id": "p16-family-v1",
        "comparison_id": "c-blind-v1", "trial_id": TRIAL,
        "epoch_session": EPOCH, "session_index": index,
        "market_date": market_date, "status": "scored", "reason": None,
        "decided_at": NOW - timedelta(hours=2),
        "forward_entry_at": NOW - timedelta(hours=1),
        "labels_available_at": NOW, "delta_ic": 0.2,
        "input_sha256": f"{index + 1:064x}", "source_sha256": DIGEST,
        "recorded_at": NOW,
    }
    value.update(updates)
    return value


def test_sequential_prefix_is_exact_and_immutable(con):
    days = [date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23)]
    for index, day in enumerate(days):
        p16_store.record_sequential_origin(con, **_origin(index, day))
    rows = p16_store.sequential_prefix(
        con, registration_sha256=REGISTRATION, family_id="p16-family-v1",
        comparison_id="c-blind-v1", trial_id=TRIAL, epoch_session=EPOCH,
        origin_endpoint=2, report_at=NOW,
    )
    assert [row["session_index"] for row in rows] == [0, 1, 2]
    assert all(row["delta_ic"] == 0.2 for row in rows)
    with pytest.raises(ValueError, match="replayed differently"):
        p16_store.record_sequential_origin(
            con, **_origin(1, days[1], delta_ic=-0.4),
        )


def test_sequential_prefix_projects_gaps_and_future_records_as_pending(con):
    p16_store.record_sequential_origin(con, **_origin(0, date(2026, 9, 21)))
    p16_store.record_sequential_origin(
        con, **_origin(2, date(2026, 9, 23), recorded_at=NOW + timedelta(minutes=1)),
    )
    prefix = p16_store.sequential_prefix(
        con, registration_sha256=REGISTRATION, family_id="p16-family-v1",
        comparison_id="c-blind-v1", trial_id=TRIAL, epoch_session=EPOCH,
        origin_endpoint=2, report_at=NOW,
    )
    assert [row["status"] for row in prefix] == ["scored", "pending", "pending"]
    con.execute("UPDATE p16_sequential_origins SET delta_ic=0.9 WHERE session_index=0")
    with pytest.raises(ValueError, match="stored P16 sequential origin differs"):
        p16_store.sequential_prefix(
            con, registration_sha256=REGISTRATION, family_id="p16-family-v1",
            comparison_id="c-blind-v1", trial_id=TRIAL, epoch_session=EPOCH,
            origin_endpoint=0, report_at=NOW,
        )


def test_sequential_origin_rules_fail_closed(con):
    with pytest.raises(ValueError, match="not pre-entry"):
        p16_store.record_sequential_origin(
            con, **_origin(0, EPOCH, decided_at=NOW, forward_entry_at=NOW),
        )
    with pytest.raises(ValueError, match="skipped"):
        p16_store.record_sequential_origin(
            con, **_origin(0, EPOCH, status="decision_unavailable", reason="late_label",
                           labels_available_at=None, delta_ic=None, input_sha256=None),
        )
    p16_store.record_sequential_origin(
        con, **_origin(0, EPOCH, status="decision_unavailable",
                       reason="constant_scores", labels_available_at=None,
                       delta_ic=None, input_sha256=None),
    )
    row = p16_store.sequential_prefix(
        con, registration_sha256=REGISTRATION, family_id="p16-family-v1",
        comparison_id="c-blind-v1", trial_id=TRIAL, epoch_session=EPOCH,
        origin_endpoint=0, report_at=NOW,
    )[0]
    assert row["status"] == "decision_unavailable"


def test_predictable_skip_is_retained_before_forward_entry(con):
    recorded = NOW - timedelta(hours=1)
    p16_store.record_sequential_origin(
        con, **_origin(
            0, EPOCH, status="decision_unavailable", reason="fewer_than_20_candidates",
            decided_at=NOW - timedelta(hours=2), forward_entry_at=NOW + timedelta(hours=1),
            labels_available_at=None, delta_ic=None, input_sha256=None, recorded_at=recorded,
        ),
    )
    row = p16_store.sequential_prefix(
        con, registration_sha256=REGISTRATION, family_id="p16-family-v1",
        comparison_id="c-blind-v1", trial_id=TRIAL, epoch_session=EPOCH,
        origin_endpoint=0, report_at=recorded,
    )[0]
    assert row["status"] == "decision_unavailable"
    assert row["recorded_at"] == recorded


def test_registration_and_trial_identity_isolate_sequential_series(con):
    p16_store.record_sequential_origin(con, **_origin(0, EPOCH))
    other = "d" * 64
    p16_store.record_sequential_origin(
        con, **_origin(0, EPOCH, registration_sha256=other, delta_ic=-0.1),
    )
    rows = p16_store.sequential_prefix(
        con, registration_sha256=other, family_id="p16-family-v1",
        comparison_id="c-blind-v1", trial_id=TRIAL, epoch_session=EPOCH,
        origin_endpoint=0, report_at=NOW,
    )
    assert rows[0]["delta_ic"] == -0.1


def test_artifact_time_and_payload_validation(con):
    with pytest.raises(ValueError, match="before its cutoff"):
        p16_store.record_artifact(
            con, registration_sha256=REGISTRATION, artifact_kind="origin",
            artifact_key="one", market_date=DAY,
            information_cutoff_at=NOW, recorded_at=NOW - timedelta(seconds=1),
            source_sha256=DIGEST, payload={},
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        p16_store.record_artifact(
            con, registration_sha256=REGISTRATION, artifact_kind="origin",
            artifact_key="one", market_date=DAY,
            information_cutoff_at=NOW.replace(tzinfo=None), recorded_at=NOW,
            source_sha256=DIGEST, payload={},
        )
