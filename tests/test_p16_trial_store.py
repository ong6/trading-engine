from datetime import datetime, timedelta, timezone

import pytest

from farm import p16_trials
from server import p16_trial_store as trials

NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
IDENTITY = {key: "not_applicable" for key in p16_trials.IDENTITY_FIELDS}


def _register(con, version="v1", **kwargs):
    trials.init_schema(con)
    identity = kwargs.pop("registration_identity", IDENTITY | {"prompt": version})
    return trials.register(
        con, policy_id="test-policy", policy_version=version, plan_id="P16",
        registration_identity=identity,
        evidence_class="prospective", parent_trial_ids=[], registered_at=NOW,
        recorded_at=NOW, trial_kind="deterministic_baseline", **kwargs)


def _event(con, trial_id, kind="evaluated", source="attempt", **kwargs):
    return trials.record_event(con, trial_id, kind, event_at=kwargs.get("event_at", NOW),
                               recorded_at=kwargs.get("recorded_at", NOW),
                               source_ref={"run": source})


def _reconciliation(con, trial_ids, *, digest=None):
    entries = []
    for trial_id in trial_ids:
        source = f"source-{trial_id}"
        _event(con, trial_id, "alias", source)
        entries.append({"source": "plans", "source_key_sha256": p16_trials.canonical_sha256(
            {"run": source}), "trial_id": trial_id, "disposition": "alias", "reason": None})
    current = trials.project(con, generated_at=NOW + timedelta(days=30))
    plans = [f"P{number}" for number in range(5, 17)]
    records = trials._records(con, NOW + timedelta(days=30))
    return {"scope": "all_plans_and_deterministic_baselines_through_p16",
            "covered_plans": plans,
            "deterministic_baseline_trial_ids": trial_ids,
            "sources": [{"source": f"plan-{plan}", "plan_id": plan,
                         "row_count": len(entries) if plan == "P16" else 0,
                         "snapshot_sha256": p16_trials.canonical_sha256({"plan": plan})}
                        for plan in plans],
            "entries": [{**entry, "source": "plan-P16"} for entry in entries],
            "trial_redirects": {}, "register_sha256": digest or current["register_sha256"],
            "sealed_through_sequence": max(
                (row["append_sequence"] for row in records), default=0),
            "sealed_row_sha256s": sorted(row["row_sha256"] for row in records)}


def test_attempts_aliases_retirement_and_replay_count_once(con):
    trial_id = _register(con)
    assert _register(con) == trial_id
    _register(con, "unused")
    first = _event(con, trial_id, "evaluation_started", "attempt-1")
    assert _event(con, trial_id, "evaluation_started", "attempt-1") == first
    _event(con, trial_id, "failed", "attempt-2", recorded_at=NOW + timedelta(minutes=1))
    _event(con, trial_id, "retired", "retired", recorded_at=NOW + timedelta(minutes=2))
    reconciliation = _reconciliation(con, [trial_id])
    trials.record_reconciliation(con, recorded_at=NOW + timedelta(minutes=3),
                                 reconciliation=reconciliation)
    result = trials.project(con, generated_at=NOW + timedelta(minutes=3))
    row = next(item for item in result["versions"] if item["trial_id"] == trial_id)
    assert result["status"] == "complete" and result["selection_trial_count"] == 1
    assert result["registered_trial_count"] == 2 and row["status"] == "retired"
    assert row["alias_count"] == 1 and row["first_evaluated_at"] == NOW.replace(
        tzinfo=None).isoformat()


def test_registration_metadata_is_immutable_and_recipe_changes_id(con):
    first = _register(con)
    assert _register(con, "v2") != first
    with pytest.raises(ValueError, match="registration replay"):
        trials.register(
            con, policy_id="test-policy", policy_version="v1",
            plan_id="P15", registration_identity=IDENTITY | {"prompt": "v1"},
            evidence_class="prospective", parent_trial_ids=[], registered_at=NOW,
            recorded_at=NOW)
    for field in p16_trials.IDENTITY_FIELDS:
        with pytest.raises(ValueError, match="registration is invalid"):
            _register(con, f"missing-{field}", registration_identity={
                key: value for key, value in IDENTITY.items() if key != field})


def test_registration_as_of_validates_visible_row(con):
    trial_id = _register(con)
    assert trials.registration_as_of(
        con, trial_id=trial_id, generated_at=NOW)["trial_id"] == trial_id
    assert trials.registration_as_of(
        con, trial_id=trial_id, generated_at=NOW - timedelta(seconds=1)) is None
    con.execute(f"UPDATE {trials.TABLE} SET payload='{{}}' WHERE trial_id=?", [trial_id])
    with pytest.raises(ValueError, match="trial record differs"):
        trials.registration_as_of(con, trial_id=trial_id, generated_at=NOW)


def test_alias_source_cannot_identify_two_trials_but_batch_sources_can(con):
    first, second = _register(con), _register(con, "v2")
    _event(con, first, "alias", "shared")
    with pytest.raises(ValueError, match="cannot identify two trials"):
        _event(con, second, "alias", "shared")
    _event(con, first, "retired", "batch")
    _event(con, second, "retired", "batch")


def test_reconciliation_is_required_and_becomes_stale(con):
    trial_id = _register(con)
    _event(con, trial_id)
    assert trials.project(con, generated_at=NOW)["status"] == "unreconciled"
    reconciliation = _reconciliation(con, [trial_id])
    trials.record_reconciliation(con, recorded_at=NOW, reconciliation=reconciliation)
    assert trials.project(con, generated_at=NOW)["status"] == "complete"
    _event(con, trial_id, "evaluated", "later", recorded_at=NOW + timedelta(minutes=1))
    assert trials.project(con, generated_at=NOW + timedelta(minutes=1))["status"] == "stale"


def test_partial_reconciliation_reports_missing_inventory_and_exact_aliases(con):
    mapped, unmapped = _register(con), _register(con, "v2")
    _event(con, mapped)
    _event(con, unmapped)
    reconciliation = _reconciliation(con, [mapped])
    reconciliation["covered_plans"] = ["P16"]
    reconciliation["sources"] = [item for item in reconciliation["sources"]
                                 if item["plan_id"] == "P16"]
    reconciliation["register_sha256"] = trials.project(
        con, generated_at=NOW)["register_sha256"]
    trials.record_reconciliation(con, recorded_at=NOW, reconciliation=reconciliation)
    result = trials.project(con, generated_at=NOW)
    assert result["status"] == "incomplete" and "P5" in result["missing_plans"]
    assert result["unmapped_trial_ids"] == [unmapped]
    _event(con, mapped, "alias", "unlisted")
    reconciliation["register_sha256"] = trials.project(
        con, generated_at=NOW)["register_sha256"]
    with pytest.raises(ValueError, match="reconciliation is invalid"):
        trials.record_reconciliation(
            con, recorded_at=NOW + timedelta(minutes=1), reconciliation=reconciliation)


def test_provisional_identity_can_be_verified_in_place(con):
    trial_id = _register(con, identity_status="provisional")
    _event(con, trial_id)
    identity_sha = p16_trials.canonical_sha256(IDENTITY | {"prompt": "v1"})
    trials.record_event(
        con, trial_id, "identity_verified", event_at=NOW, recorded_at=NOW,
        source_ref={"registration_identity_sha256": identity_sha,
                    "evidence_sha256": "c" * 64, "reason": "registration recovered"})
    reconciliation = _reconciliation(con, [trial_id])
    trials.record_reconciliation(con, recorded_at=NOW, reconciliation=reconciliation)
    row = trials.project(con, generated_at=NOW)["versions"][0]
    assert row["identity_verified"] is True and row["reconciled_to"] is None
    with pytest.raises(ValueError, match="verification is invalid"):
        trials.record_event(
            con, trial_id, "identity_verified", event_at=NOW, recorded_at=NOW,
            source_ref={"registration_identity_sha256": "d" * 64,
                        "evidence_sha256": "c" * 64, "reason": "wrong recipe"})


def test_provisional_redirect_deduplicates_without_deleting_history(con):
    old = _register(con, "v2", identity_status="provisional",
                    registration_identity=IDENTITY | {"prompt": "unresolved:prompt"})
    new = _register(con, "v2")
    _event(con, old, source="old")
    _event(con, new, "failed", source="new")
    reconciliation = _reconciliation(con, [old])
    reconciliation["deterministic_baseline_trial_ids"] = [new]
    reconciliation["trial_redirects"] = {old: {
        "canonical_trial_id": new, "evidence_sha256": "b" * 64,
        "reason": "historical placeholder resolved from the frozen registration"}}
    reconciliation_sha = trials.record_reconciliation(
        con, recorded_at=NOW, reconciliation=reconciliation)
    result = trials.project(con, generated_at=NOW)
    sealed = trials.project_sealed(
        con, reconciliation_sha256=reconciliation_sha)
    assert result["selection_trial_count"] == 1
    assert result["unresolved_identity_count"] == 0 and len(result["versions"]) == 2
    assert next(row for row in result["versions"] if row["trial_id"] == old)[
        "reconciled_to"] == new
    canonical = next(row for row in result["versions"] if row["trial_id"] == new)
    assert canonical["status"] == "failed"
    assert canonical["first_evaluated_at"] == NOW.replace(tzinfo=None).isoformat()
    assert canonical["alias_count"] == 1
    assert result["unmapped_trial_ids"] == []
    _event(con, old, "retired", "retirement", recorded_at=NOW)
    stale = trials.project(con, generated_at=NOW)
    assert stale["status"] == "stale" and stale["selection_trial_count"] == 1
    assert stale["unresolved_identity_count"] == 0
    canonical = next(row for row in stale["versions"] if row["trial_id"] == new)
    assert canonical["status"] == "retired" and canonical["alias_count"] == 1
    assert trials.project_sealed(
        con, reconciliation_sha256=reconciliation_sha) == sealed


def test_reconciliation_cannot_merge_distinct_evaluated_recipes(con):
    old = _register(con, "v2", identity_status="provisional",
                    registration_identity=IDENTITY | {"prompt": "different"})
    new = _register(con, "v2")
    _event(con, old, source="old")
    _event(con, new, source="new")
    reconciliation = _reconciliation(con, [old, new])
    reconciliation["deterministic_baseline_trial_ids"] = [new]
    reconciliation["trial_redirects"] = {old: {
        "canonical_trial_id": new, "evidence_sha256": "b" * 64,
        "reason": "unsupported merge"}}
    with pytest.raises(ValueError, match="reconciliation is invalid"):
        trials.record_reconciliation(con, recorded_at=NOW, reconciliation=reconciliation)


def test_future_ingest_truncation_and_tampering_do_not_change_old_projection(con):
    for index in range(4):
        trial_id = _register(con, f"v{index}")
        _event(con, trial_id, source=index, recorded_at=NOW + timedelta(days=index))
    old = trials.project(con, generated_at=NOW, limit=1)
    assert old["selection_trial_count"] == 1 and old["versions_truncated"] is True
    con.execute(f"UPDATE {trials.TABLE} SET payload='{{}}' WHERE record_kind='registration'")
    with pytest.raises(ValueError, match="record differs"):
        trials.project(con, generated_at=NOW + timedelta(days=4))


def test_register_digest_binds_ingest_time():
    first = p16_trials.decode(p16_trials.encoded_record(
        "evaluated", "a" * 64, NOW, NOW, {"source_ref": {"run": "same"}},
        p16_trials.canonical_sha256({"run": "same"}), 1))
    second = p16_trials.decode(p16_trials.encoded_record(
        "evaluated", "a" * 64, NOW, NOW + timedelta(seconds=1),
        {"source_ref": {"run": "same"}}, p16_trials.canonical_sha256({"run": "same"}), 1))
    assert first["record_sha256"] == second["record_sha256"]
    assert p16_trials.register_digest([first]) != p16_trials.register_digest([second])


def test_reconciliation_requires_an_exact_append_prefix(con):
    trial_id = _register(con)
    _event(con, trial_id)
    reconciliation = _reconciliation(con, [trial_id])
    reconciliation["sealed_row_sha256s"] = reconciliation["sealed_row_sha256s"][1:]
    with pytest.raises(ValueError, match="reconciliation is invalid"):
        trials.record_reconciliation(con, recorded_at=NOW, reconciliation=reconciliation)
    reconciliation = _reconciliation(con, [trial_id])
    reconciliation["sealed_through_sequence"] -= 1
    with pytest.raises(ValueError, match="reconciliation is invalid"):
        trials.record_reconciliation(con, recorded_at=NOW, reconciliation=reconciliation)


def test_append_sequence_is_stable_on_replay_and_tamper_evident(con):
    trial_id = _register(con)
    before = trials._records(con)
    assert _register(con) == trial_id
    assert trials._records(con) == before
    con.execute(f"UPDATE {trials.TABLE} SET append_sequence=10 WHERE trial_id=?", [trial_id])
    with pytest.raises(ValueError, match="trial record differs"):
        trials.project(con, generated_at=NOW)
