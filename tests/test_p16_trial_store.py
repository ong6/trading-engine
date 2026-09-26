from datetime import datetime, timedelta, timezone

import pytest

from server import p16_trial_store as trials

NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)


def _register(con, version="v1", **kwargs):
    trials.init_schema(con)
    return trials.register(con, policy_id="test-policy", plan_id="P16",
                           registration_identity={"version": version, "prompt_sha256": "a" * 64},
                           catalogued_at=NOW, **kwargs)


def _attempt(con, trial_id, source, event_at=NOW, recorded_at=NOW):
    return trials.record_event(con, trial_id, "evaluated", event_at=event_at,
                               recorded_at=recorded_at, source_ref={"run": source})


def test_aliases_and_retries_count_once_but_unused_versions_do_not(con):
    first = _register(con)
    assert _register(con) == first
    _register(con, "unused-v2")
    one = _attempt(con, first, "failed-attempt")
    assert _attempt(con, first, "failed-attempt", recorded_at=NOW + timedelta(hours=1)) == one
    _attempt(con, first, "second-attempt")
    result = trials.project(con, generated_at=NOW + timedelta(hours=2), inventory_complete=True)
    assert result["selection_trial_count"] == 1
    assert result["versions"][0]["evidence_alias_count"] == 2


def test_retired_and_provisional_versions_remain_in_the_count(con):
    first = _register(con, identity_status="provisional")
    _attempt(con, first, "legacy", event_at=NOW - timedelta(days=30))
    trials.record_event(con, first, "retired", event_at=NOW, recorded_at=NOW,
                        source_ref={"retirement": "sealed-negative-result"})
    result = trials.project(con, generated_at=NOW, inventory_complete=True)
    assert result["selection_trial_count"] == 1 and result["status"] == "incomplete"
    assert result["unresolved_identity_count"] == 1 and result["versions"][0]["retired"]


def test_future_ingest_and_conflicting_identity_do_not_change_old_counts(con):
    first, second = _register(con), _register(con, "v2")
    _attempt(con, first, "first", recorded_at=NOW + timedelta(days=1))
    assert trials.project(con, generated_at=NOW, inventory_complete=True)["selection_trial_count"] == 0
    with pytest.raises(ValueError, match="two trials"):
        _attempt(con, second, "first")
    con.execute("UPDATE p16_trials SET registration_identity='{}' WHERE trial_id=?", [first])
    with pytest.raises(ValueError, match="registration differs"):
        trials.project(con, generated_at=NOW + timedelta(days=2), inventory_complete=True)


def test_display_cap_never_truncates_trial_count(con):
    for index in range(105):
        trial_id = _register(con, f"v{index}")
        _attempt(con, trial_id, index)
    result = trials.project(con, generated_at=NOW, inventory_complete=True, limit=3)
    assert result["selection_trial_count"] == 105 and len(result["versions"]) == 3
    assert result["versions_truncated"] is True


def test_ingest_time_is_bound_and_event_clock_cannot_be_rewritten(con):
    trial_id = _register(con)
    _attempt(con, trial_id, "first", recorded_at=NOW + timedelta(days=1))
    with pytest.raises(ValueError, match="replay differs"):
        _attempt(con, trial_id, "first", event_at=NOW - timedelta(days=1))
    con.execute("UPDATE p16_trial_events SET recorded_at=?", [NOW.replace(tzinfo=None)])
    with pytest.raises(ValueError, match="lifecycle evidence differs"):
        trials.project(con, generated_at=NOW, inventory_complete=True)
