"""W4 trial-set lockbox persistence and classification tests."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

import duckdb
import pytest

from engine.lib.provenance import canonical_sha256
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


def _ledger(tmp_path, name="lockbox.duckdb"):
    root = tmp_path / "research"
    root.mkdir(exist_ok=True)
    return LockboxLedger(
        root / name, research_root=root, live_db_path=tmp_path / "live.duckdb"
    )


def _arms():
    return (
        ConfirmatoryArm("trial-notes", "exec-notes", "a" * 64, "1" * 64, "4" * 64, "5" * 64, "initiating"),
        ConfirmatoryArm("trial-control", "exec-control", "a" * 64, "2" * 64, "4" * 64, "6" * 64, "paired"),
        ConfirmatoryArm("trial-astra", "exec-astra", "b" * 64, "3" * 64, "4" * 64, "7" * 64, "cross_model"),
    )


def _registrations(arms, sessions):
    trial_set = trial_set_sha256(arms, sessions)
    rows = {}
    for arm in arms:
        payload = {
            **asdict(arm),
            "status": "registered",
            "sessions": [session.isoformat() for session in sessions],
            "trial_set_sha256": trial_set,
            "registered_at": "2026-09-27T15:00:00Z",
            "authority": "historical_research_only",
        }
        rows[arm.trial_id] = {
            **payload,
            "registration_sha256": canonical_sha256(payload),
        }
    return rows


def _begin(
    ledger,
    *,
    arms=None,
    sessions=SESSIONS,
    experiment_id="replay-lockbox-v1",
    cohort_id="cohort-sol-v1",
    registrations=None,
    committed_at=NOW,
):
    selected = _arms() if arms is None else arms
    registered = _registrations(selected, sessions) if registrations is None else registrations
    return begin_lockbox_consumption(
        ledger,
        experiment_id=experiment_id,
        cohort_id=cohort_id,
        sessions=sessions,
        confirmatory_arms=selected,
        initiating_execution_id="exec-notes",
        expected_trial_set_sha256=trial_set_sha256(selected, sessions),
        committed_at=committed_at,
        registration_as_of=lambda trial_id, _at: registered.get(trial_id),
    )


def _tag(ledger, arm, **changes):
    values = {
        "experiment_id": "replay-lockbox-v1",
        "cohort_id": "cohort-sol-v1",
        "trial_id": arm.trial_id,
        "execution_id": arm.execution_id,
        "model_identity_sha256": arm.model_identity_sha256,
        "execution_manifest_sha256": arm.execution_manifest_sha256,
        "endpoint_sha256": arm.endpoint_sha256,
        "development_artifact_sha256": arm.development_artifact_sha256,
        "sessions": SESSIONS,
        "evaluated_at": NOW + timedelta(hours=1),
    }
    values.update(changes)
    return evaluation_tag(ledger, **values)


def test_first_registered_trial_set_and_exact_receipt_resume_are_confirmatory(tmp_path):
    ledger = _ledger(tmp_path)
    marker = _begin(ledger)
    assert marker == _begin(ledger)
    assert all(_tag(ledger, arm).tag == "confirmatory" for arm in _arms())

    for kind, minute in (("partial", 1), ("crashed", 2)):
        append_lockbox_event(
            ledger, marker, execution_id="exec-notes", event_kind=kind,
            occurred_at=NOW + timedelta(minutes=minute), source_sha256="5" * 64,
        )
    assert _tag(ledger, _arms()[0]).reason == "interrupted_receipt_not_reconciled"
    append_lockbox_event(
        ledger, marker, execution_id="exec-notes", event_kind="completed",
        occurred_at=NOW + timedelta(minutes=3), source_sha256="5" * 64,
    )
    assert _tag(ledger, _arms()[0]).tag == "confirmatory"


def test_subsets_later_identities_and_prior_consumed_sessions_are_exploratory(tmp_path):
    ledger = _ledger(tmp_path)
    _begin(ledger)
    arm = _arms()[0]
    cases = (
        {"execution_id": "exec-later"},
        {"trial_id": "trial-unregistered", "execution_id": "exec-other"},
        {"model_identity_sha256": "c" * 64},
        {"execution_manifest_sha256": "9" * 64},
        {"endpoint_sha256": "8" * 64},
        {"development_artifact_sha256": "7" * 64},
        {"sessions": SESSIONS[:1]},
        {"sessions": (*SESSIONS, date(2026, 7, 6))},
    )
    assert all(_tag(ledger, arm, **changed).tag == "post_lockbox_exploratory" for changed in cases)

    later_marker = _begin(
        ledger, experiment_id="later", cohort_id="other",
        committed_at=NOW + timedelta(seconds=1),
    )
    result = _tag(ledger, arm, experiment_id="later", cohort_id="other")
    assert result.reason == "sessions_consumed_by_prior_marker"
    with duckdb.connect(str(ledger.path)) as con:
        con.execute(
            "UPDATE w4_lockbox_first_sessions SET marker_sha256=?", [later_marker]
        )
    with pytest.raises(LockboxIntegrityError, match="children_tampered"):
        _tag(ledger, arm, experiment_id="later", cohort_id="other")


def test_registration_must_bind_every_arm_field_sessions_and_own_digest(tmp_path):
    ledger = _ledger(tmp_path)
    for field, value in (
        ("model_identity_sha256", "9" * 64),
        ("execution_manifest_sha256", "8" * 64),
        ("endpoint_sha256", "7" * 64),
        ("development_artifact_sha256", "6" * 64),
        ("role", "paired"),
        ("authority", "producer"),
        ("sessions", ["2026-07-01"]),
        ("trial_set_sha256", "6" * 64),
    ):
        rows = _registrations(_arms(), SESSIONS)
        rows["trial-notes"][field] = value
        with pytest.raises(LockboxIntegrityError, match="identity_mismatch|digest_mismatch"):
            _begin(ledger, registrations=rows)

    rows = _registrations(_arms(), SESSIONS)
    rows["trial-notes"]["registration_sha256"] = "0" * 64
    with pytest.raises(LockboxIntegrityError, match="digest_mismatch"):
        _begin(ledger, registrations=rows)


def test_marker_is_visible_before_dispatch_and_failure_prevents_call(tmp_path):
    ledger = _ledger(tmp_path)
    observed = []
    selected = _arms()
    begin = dict(
        experiment_id="replay-lockbox-v1", cohort_id="cohort-sol-v1",
        sessions=SESSIONS, confirmatory_arms=selected,
        initiating_execution_id="exec-notes",
        expected_trial_set_sha256=trial_set_sha256(selected, SESSIONS), committed_at=NOW,
        registration_as_of=lambda trial_id, _at: _registrations(selected, SESSIONS).get(trial_id),
    )

    def dispatch(marker_sha256):
        observed.append(ledger.marker("replay-lockbox-v1", "cohort-sol-v1"))
        return marker_sha256

    marker = dispatch_lockbox(ledger, dispatch=dispatch, begin=begin)
    assert observed[0]["trial_set_sha256"] == trial_set_sha256(selected, SESSIONS)
    assert marker == observed[0]["marker_sha256"]
    with pytest.raises(LockboxIntegrityError, match="already_dispatched"):
        dispatch_lockbox(ledger, dispatch=lambda value: pytest.fail(value), begin=begin)

    other = _ledger(tmp_path, "failed.duckdb")
    begin["registration_as_of"] = lambda _trial, _at: None
    with pytest.raises(LockboxIntegrityError, match="not_registered"):
        dispatch_lockbox(other, dispatch=lambda value: pytest.fail(value), begin=begin)


def test_first_marker_conflict_and_policy_store_reset_do_not_restore_holdout(tmp_path):
    ledger = _ledger(tmp_path)
    _begin(ledger)
    with pytest.raises(LockboxIntegrityError, match="first_marker_conflict"):
        _begin(ledger, sessions=SESSIONS[:1])
    policy_store = tmp_path / "policy-replay.duckdb"
    policy_store.touch()
    policy_store.unlink()
    assert _tag(ledger, _arms()[0], execution_id="replacement").tag == "post_lockbox_exploratory"


def test_event_membership_clocks_and_cross_model_freeze_order_fail_closed(tmp_path):
    unsafe = _ledger(tmp_path, "unsafe.duckdb")
    marker = _begin(unsafe)
    for execution, kind, when in (
        ("fake", "arm_artifact_frozen", NOW + timedelta(minutes=1)),
        ("exec-notes", "partial", NOW - timedelta(minutes=1)),
    ):
        with pytest.raises(LockboxIntegrityError, match="not_registered|before_lockbox"):
            append_lockbox_event(
                unsafe, marker, execution_id=execution, event_kind=kind,
                occurred_at=when, source_sha256="4" * 64,
            )
    append_lockbox_event(
        unsafe, marker, execution_id="exec-notes", event_kind="arm_artifact_frozen",
        occurred_at=NOW + timedelta(minutes=1), source_sha256=_arms()[0].development_artifact_sha256,
    )
    append_lockbox_event(
        unsafe, marker, execution_id="development-review", event_kind="development_inspected",
        occurred_at=NOW + timedelta(minutes=2), source_sha256="5" * 64,
    )
    for index, arm in enumerate(_arms()[1:], start=3):
        append_lockbox_event(
            unsafe, marker, execution_id=arm.execution_id, event_kind="arm_artifact_frozen",
            occurred_at=NOW + timedelta(minutes=index), source_sha256=arm.development_artifact_sha256,
        )
    assert _tag(unsafe, _arms()[0]).reason == "cross_model_inspection_before_both_frozen"

    safe = _ledger(tmp_path, "safe.duckdb")
    marker = _begin(safe)
    for index, arm in enumerate(_arms(), start=1):
        append_lockbox_event(
            safe, marker, execution_id=arm.execution_id, event_kind="arm_artifact_frozen",
            occurred_at=NOW + timedelta(minutes=index), source_sha256=arm.development_artifact_sha256,
        )
    append_lockbox_event(
        safe, marker, execution_id="development-review", event_kind="development_inspected",
        occurred_at=NOW + timedelta(minutes=5), source_sha256="f" * 64,
    )
    assert _tag(safe, _arms()[2]).tag == "confirmatory"


def test_marker_tamper_and_evaluation_before_marker_fail_closed(tmp_path):
    ledger = _ledger(tmp_path)
    marker = _begin(ledger)
    with pytest.raises(LockboxIntegrityError, match="evaluation_before"):
        _tag(ledger, _arms()[0], evaluated_at=NOW - timedelta(seconds=1))
    with duckdb.connect(str(ledger.path)) as con:
        payload = json.loads(con.execute(
            "SELECT payload_json FROM w4_lockbox_markers WHERE marker_sha256=?", [marker]
        ).fetchone()[0])
        payload["cohort_id"] = "tampered"
        con.execute(
            "UPDATE w4_lockbox_markers SET payload_json=? WHERE marker_sha256=?",
            [json.dumps(payload, sort_keys=True, separators=(",", ":")), marker],
        )
    with pytest.raises(LockboxIntegrityError, match="payload_tampered"):
        _tag(ledger, _arms()[0])


def test_deleted_session_or_event_and_conflicting_completion_fail_closed(tmp_path):
    sessions = _ledger(tmp_path, "sessions.duckdb")
    _begin(sessions)
    with duckdb.connect(str(sessions.path)) as con:
        con.execute("DELETE FROM w4_lockbox_first_sessions WHERE session=?", [SESSIONS[0]])
    with pytest.raises(LockboxIntegrityError, match="children_tampered"):
        _tag(sessions, _arms()[0])

    events = _ledger(tmp_path, "events.duckdb")
    marker = _begin(events)
    for kind, minute in (("crashed", 1), ("completed", 2)):
        append_lockbox_event(
            events, marker, execution_id="exec-notes", event_kind=kind,
            occurred_at=NOW + timedelta(minutes=minute), source_sha256="5" * 64,
        )
    with duckdb.connect(str(events.path)) as con:
        con.execute("DELETE FROM w4_lockbox_events WHERE event_kind='crashed'")
    with pytest.raises(LockboxIntegrityError, match="history_tampered"):
        _tag(events, _arms()[0])

    conflict = _ledger(tmp_path, "conflict.duckdb")
    marker = _begin(conflict)
    for minute, digest in ((1, "5" * 64), (2, "6" * 64)):
        append_lockbox_event(
            conflict, marker, execution_id="exec-notes", event_kind="completed",
            occurred_at=NOW + timedelta(minutes=minute), source_sha256=digest,
        )
    assert _tag(conflict, _arms()[0]).reason == "conflicting_completed_receipts"


def test_dispatch_and_marker_children_cannot_be_restored_by_deleting_rows(tmp_path):
    ledger = _ledger(tmp_path)
    selected = _arms()
    begin = dict(
        experiment_id="replay-lockbox-v1", cohort_id="cohort-sol-v1",
        sessions=SESSIONS, confirmatory_arms=selected,
        initiating_execution_id="exec-notes",
        expected_trial_set_sha256=trial_set_sha256(selected, SESSIONS), committed_at=NOW,
        registration_as_of=lambda trial_id, _at: _registrations(selected, SESSIONS).get(trial_id),
    )
    calls = []
    marker = dispatch_lockbox(
        ledger, dispatch=lambda value: (calls.append(value), value)[1], begin=begin
    )
    with duckdb.connect(str(ledger.path)) as con:
        con.execute("DELETE FROM w4_lockbox_events WHERE event_kind='dispatched'")
        genesis = canonical_sha256({"marker_sha256": marker, "events": []})
        con.execute(
            "UPDATE w4_lockbox_event_state SET event_count=0,chain_sha256=? WHERE marker_sha256=?",
            [genesis, marker],
        )
    with pytest.raises(LockboxIntegrityError, match="history_tampered"):
        dispatch_lockbox(ledger, dispatch=lambda value: calls.append(value), begin=begin)
    assert calls == [marker]

    children = _ledger(tmp_path, "children.duckdb")
    _begin(children)
    with duckdb.connect(str(children.path)) as con:
        con.execute("DELETE FROM w4_lockbox_arms WHERE marker_sha256=?", [marker])
    with pytest.raises(LockboxIntegrityError, match="children_tampered"):
        _begin(children)

    owners = _ledger(tmp_path, "owners.duckdb")
    _begin(owners)
    with duckdb.connect(str(owners.path)) as con:
        con.execute("DELETE FROM w4_lockbox_first_sessions")
        con.execute("DELETE FROM w4_lockbox_sessions")
    later = {
        **begin, "experiment_id": "later", "cohort_id": "later",
        "committed_at": NOW + timedelta(seconds=1),
    }
    with pytest.raises(LockboxIntegrityError, match="history_tampered"):
        dispatch_lockbox(owners, dispatch=lambda value: calls.append(value), begin=later)


def test_subsecond_timestamp_after_marker_is_accepted(tmp_path):
    ledger = _ledger(tmp_path)
    marker = _begin(ledger)
    append_lockbox_event(
        ledger, marker, execution_id="exec-notes", event_kind="viewed",
        occurred_at=NOW + timedelta(microseconds=1), source_sha256="5" * 64,
    )


def test_ledger_rejects_relative_checkout_live_and_symlink_paths(tmp_path):
    root = tmp_path / "research"
    root.mkdir()
    live = tmp_path / "live.duckdb"
    live.touch()
    with pytest.raises(LockboxIntegrityError, match="ledger_path"):
        LockboxLedger(root.relative_to(tmp_path) / "relative.duckdb", research_root=root, live_db_path=live)
    with pytest.raises(LockboxIntegrityError, match="ledger_path"):
        LockboxLedger(live, research_root=root, live_db_path=live)
    checkout_target = __import__("pathlib").Path(__file__).resolve().parents[1] / "lockbox.duckdb"
    with pytest.raises(LockboxIntegrityError, match="ledger_path"):
        LockboxLedger(checkout_target, research_root=checkout_target.parent, live_db_path=live)
    link = root / "linked.duckdb"
    link.symlink_to(live)
    with pytest.raises(LockboxIntegrityError, match="ledger_path"):
        LockboxLedger(link, research_root=root, live_db_path=live)
    replay_path = root / "replay.duckdb"
    with open(replay_path, "wb"):
        pass
    replay_path.unlink()
    from farm.replay.store import open_store
    with open_store(replay_path, research_root=root, live_db_path=live, kind="replay"):
        pass
    with pytest.raises(LockboxIntegrityError, match="ledger_store"):
        LockboxLedger(replay_path, research_root=root, live_db_path=live)


def test_missing_marker_is_exploratory(tmp_path):
    result = _tag(_ledger(tmp_path), _arms()[0])
    assert result.tag == "post_lockbox_exploratory"
    assert result.reason == "lockbox_marker_missing"
    assert result.marker_sha256 == ""
