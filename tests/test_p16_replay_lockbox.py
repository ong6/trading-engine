"""W4 trial-set lockbox persistence and classification tests."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from farm.replay.lockbox import (
    ConfirmatoryArm,
    LockboxIntegrityError,
    LockboxLedger,
    append_lockbox_event,
    begin_lockbox_consumption,
    dispatch_lockbox,
    evaluation_tag,
    trial_set_sha256,
)

NOW = datetime(2026, 9, 27, 16, tzinfo=timezone.utc)
SESSIONS = (date(2026, 7, 1), date(2026, 7, 2))


def _arms():
    return (
        ConfirmatoryArm("trial-notes", "exec-notes", "a" * 64, "1" * 64, "initiating"),
        ConfirmatoryArm("trial-control", "exec-control", "a" * 64, "2" * 64, "paired"),
        ConfirmatoryArm("trial-astra", "exec-astra", "b" * 64, "3" * 64, "cross_model"),
    )


def _begin(ledger, *, arms=None, sessions=SESSIONS, registered=None):
    selected = _arms() if arms is None else arms
    registered_ids = {arm.trial_id for arm in selected} if registered is None else registered
    return begin_lockbox_consumption(
        ledger,
        experiment_id="replay-lockbox-v1",
        cohort_id="cohort-sol-v1",
        sessions=sessions,
        confirmatory_arms=selected,
        initiating_execution_id="exec-notes",
        expected_trial_set_sha256=trial_set_sha256(selected),
        committed_at=NOW,
        registration_as_of=lambda trial_id, _at: (
            {"trial_id": trial_id} if trial_id in registered_ids else None
        ),
    )


def _tag(ledger, arm, **changes):
    values = {
        "experiment_id": "replay-lockbox-v1",
        "cohort_id": "cohort-sol-v1",
        "trial_id": arm.trial_id,
        "execution_id": arm.execution_id,
        "model_identity_sha256": arm.model_identity_sha256,
        "execution_manifest_sha256": arm.execution_manifest_sha256,
        "sessions": SESSIONS,
        "evaluated_at": NOW + timedelta(hours=1),
    }
    values.update(changes)
    return evaluation_tag(ledger, **values)


def test_first_registered_trial_set_remains_confirmatory(tmp_path):
    ledger = LockboxLedger(tmp_path / "lockbox.duckdb")
    marker = _begin(ledger)
    assert marker == _begin(ledger)
    for arm in _arms():
        result = _tag(ledger, arm)
        assert result.tag == "confirmatory"
        assert result.reason == "registered_first_trial_set"
        assert result.marker_sha256 == marker

    append_lockbox_event(
        ledger,
        marker,
        execution_id="exec-notes",
        event_kind="partial",
        occurred_at=NOW + timedelta(minutes=1),
        source_sha256="4" * 64,
    )
    append_lockbox_event(
        ledger,
        marker,
        execution_id="exec-notes",
        event_kind="crashed",
        occurred_at=NOW + timedelta(minutes=2),
        source_sha256="5" * 64,
    )
    assert _tag(ledger, _arms()[0]).tag == "confirmatory"


def test_later_unregistered_or_substituted_execution_is_exploratory(tmp_path):
    ledger = LockboxLedger(tmp_path / "lockbox.duckdb")
    _begin(ledger)
    arm = _arms()[0]
    cases = (
        {"execution_id": "exec-later"},
        {"trial_id": "trial-unregistered", "execution_id": "exec-other"},
        {"model_identity_sha256": "c" * 64},
        {"execution_manifest_sha256": "9" * 64},
        {"sessions": (*SESSIONS, date(2026, 7, 6))},
    )
    for changed in cases:
        result = _tag(ledger, arm, **changed)
        assert result.tag == "post_lockbox_exploratory"


def test_marker_is_committed_and_visible_before_dispatch(tmp_path):
    path = tmp_path / "lockbox.duckdb"
    ledger = LockboxLedger(path)
    observed = []
    begin = dict(
        experiment_id="replay-lockbox-v1",
        cohort_id="cohort-sol-v1",
        sessions=SESSIONS,
        confirmatory_arms=_arms(),
        initiating_execution_id="exec-notes",
        expected_trial_set_sha256=trial_set_sha256(_arms()),
        committed_at=NOW,
        registration_as_of=lambda _trial, _at: {"registered": True},
    )

    def dispatch(marker_sha256):
        observed.append(LockboxLedger(path).marker("replay-lockbox-v1", "cohort-sol-v1"))
        return marker_sha256

    marker = dispatch_lockbox(ledger, dispatch=dispatch, begin=begin)
    assert observed[0]["trial_set_sha256"] == trial_set_sha256(_arms())
    assert observed[0]["committed_at"] == "2026-09-27T16:00:00Z"
    assert marker == observed[0]["marker_sha256"]


def test_marker_failure_prevents_dispatch_and_first_marker_cannot_change(tmp_path):
    ledger = LockboxLedger(tmp_path / "lockbox.duckdb")
    called = []
    begin = dict(
        experiment_id="replay-lockbox-v1",
        cohort_id="cohort-sol-v1",
        sessions=SESSIONS,
        confirmatory_arms=_arms(),
        initiating_execution_id="exec-notes",
        expected_trial_set_sha256=trial_set_sha256(_arms()),
        committed_at=NOW,
        registration_as_of=lambda _trial, _at: None,
    )
    with pytest.raises(LockboxIntegrityError, match="not_registered"):
        dispatch_lockbox(ledger, dispatch=lambda marker: called.append(marker), begin=begin)
    assert called == []
    assert ledger.marker("replay-lockbox-v1", "cohort-sol-v1") is None

    _begin(ledger)
    with pytest.raises(LockboxIntegrityError, match="first_marker_conflict"):
        _begin(ledger, sessions=(date(2026, 7, 1),))


def test_shared_ledger_survives_policy_store_reset(tmp_path):
    ledger = LockboxLedger(tmp_path / "shared-lockbox.duckdb")
    _begin(ledger)
    policy_store = tmp_path / "policy-replay.duckdb"
    policy_store.touch()
    policy_store.unlink()
    result = _tag(ledger, _arms()[0], execution_id="replacement-after-reset")
    assert result.tag == "post_lockbox_exploratory"


def test_cross_model_inspection_order_is_derived_from_events(tmp_path):
    unsafe = LockboxLedger(tmp_path / "unsafe.duckdb")
    marker = _begin(unsafe)
    append_lockbox_event(
        unsafe,
        marker,
        execution_id="exec-notes",
        event_kind="arm_artifact_frozen",
        occurred_at=NOW + timedelta(minutes=1),
        source_sha256="4" * 64,
    )
    append_lockbox_event(
        unsafe,
        marker,
        execution_id="development-review",
        event_kind="development_inspected",
        occurred_at=NOW + timedelta(minutes=2),
        source_sha256="5" * 64,
    )
    for index, arm in enumerate(_arms()[1:], start=3):
        append_lockbox_event(
            unsafe,
            marker,
            execution_id=arm.execution_id,
            event_kind="arm_artifact_frozen",
            occurred_at=NOW + timedelta(minutes=index),
            source_sha256=str(index + 3) * 64,
        )
    result = _tag(unsafe, _arms()[0])
    assert result.tag == "post_lockbox_exploratory"
    assert result.reason == "cross_model_inspection_before_both_frozen"

    safe = LockboxLedger(tmp_path / "safe.duckdb")
    marker = _begin(safe)
    for index, arm in enumerate(_arms(), start=1):
        append_lockbox_event(
            safe,
            marker,
            execution_id=arm.execution_id,
            event_kind="arm_artifact_frozen",
            occurred_at=NOW + timedelta(minutes=index),
            source_sha256=str(index + 6) * 64,
        )
    append_lockbox_event(
        safe,
        marker,
        execution_id="development-review",
        event_kind="development_inspected",
        occurred_at=NOW + timedelta(minutes=5),
        source_sha256="f" * 64,
    )
    assert _tag(safe, _arms()[2]).tag == "confirmatory"


def test_missing_marker_and_relative_path_fail_closed(tmp_path):
    with pytest.raises(LockboxIntegrityError, match="ledger_path"):
        LockboxLedger(tmp_path.relative_to(tmp_path.parent) / "relative.duckdb")
    ledger = LockboxLedger(tmp_path / "empty.duckdb")
    with pytest.raises(LockboxIntegrityError, match="marker_missing"):
        _tag(ledger, _arms()[0])
