"""Append-only P16 evaluation-store tests."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import duckdb
import pytest

from engine.lib.provenance import canonical_sha256
from farm import p16_trials
from server import p16_store
from server import p16_trial_store

NOW = datetime(2026, 9, 27, 16, tzinfo=timezone.utc)
DAY = date(2026, 9, 25)
DIGEST = "a" * 64
REGISTRATION = "b" * 64
EPOCH = date(2026, 9, 21)
REGISTERED = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
IDENTITY = {key: "not_applicable" for key in p16_trials.IDENTITY_FIELDS}


def _trial_id(policy: str, version: str, kind: str) -> str:
    trial_id, _ = p16_trials.registration(
        policy_id=policy, policy_version=version, plan_id="P16",
        registration_identity=IDENTITY | {"prompt": policy},
        evidence_class="prospective", parent_trial_ids=[], registered_at=REGISTERED,
        identity_status="verified", trial_kind=kind,
    )
    return trial_id


TRIAL = _trial_id("c-blind", "v1", "policy")
CONTROL = _trial_id("p15-scoring", "v1", "deterministic_baseline")


def _evaluation_payload(**updates):
    body = {
        "schema_version": 1, "policy_id": "p15-scoring-v1", "status": "available",
        "market_date": DAY.isoformat(), "report_cutoff": NOW.isoformat(),
        "scoring_information_cutoff_at": (NOW - timedelta(days=2)).isoformat(),
        "source": {"run_id": 1, **{key: DIGEST for key in (
            "bundle_sha256", "universe_sha256", "context_sha256", "source_refs_sha256",
            "request_sha256", "input_sha256", "output_sha256", "trace_sha256")}},
        "p15_registration_sha256": REGISTRATION, "rows": [],
    }
    body.update(updates)
    return {**body, "input_snapshot_sha256": canonical_sha256(body)}


def _exposure_payload(**updates):
    body = {
        "schema_version": 2, "policy_id": "p16-eval-v2", "market_date": DAY.isoformat(),
        "information_cutoff_at": (NOW - timedelta(days=2)).isoformat(),
        "price_basis": "split_adjusted_price_v1",
        "corporate_action_state": "retained_at_information_cutoff",
        "exposure_names": list(p16_store.EXPOSURES), "source_bars_sha256": DIGEST,
        "sector_snapshot_sha256": "e" * 64,
        "candidates": [{"ticker": "AAA", "status": "available"}],
    }
    body.update(updates)
    return {**body, "snapshot_sha256": canonical_sha256(body)}


@pytest.fixture
def con():
    connection = duckdb.connect(":memory:")
    p16_store.init_schema(connection)
    for policy, version, kind, expected in (
        ("c-blind", "v1", "policy", TRIAL),
        ("p15-scoring", "v1", "deterministic_baseline", CONTROL),
    ):
        actual = p16_trial_store.register(
            connection, policy_id=policy, policy_version=version, plan_id="P16",
            registration_identity=IDENTITY | {"prompt": policy},
            evidence_class="prospective", parent_trial_ids=[], registered_at=REGISTERED,
            recorded_at=REGISTERED, trial_kind=kind,
        )
        assert actual == expected
    yield connection
    connection.close()


def test_artifacts_are_immutable_idempotent_and_as_of(con):
    payload = _evaluation_payload()
    first = p16_store.record_evaluation_input(
        con, registration_sha256=REGISTRATION, payload=payload, recorded_at=NOW)
    assert p16_store.record_evaluation_input(
        con, registration_sha256=REGISTRATION, payload=payload,
        recorded_at=NOW + timedelta(seconds=1)) == first
    assert p16_store._artifacts_as_of(
        con, generated_at=NOW - timedelta(seconds=1)) == []
    visible = p16_store._artifacts_as_of(
        con, generated_at=NOW, registration_sha256=REGISTRATION,
        artifact_kind="evaluation_input",
        artifact_key="p15-scoring-v1", through_market_date=DAY,
    )
    assert visible[0]["artifact_sha256"] == first
    assert visible[0]["payload"] == payload
    changed = _evaluation_payload(rows=[{"ticker": "AAA"}])
    with pytest.raises(ValueError, match="replayed differently"):
        p16_store.record_evaluation_input(
            con, registration_sha256=REGISTRATION, payload=changed, recorded_at=NOW)


def test_artifact_tampering_is_detected(con):
    p16_store.record_evaluation_input(
        con, registration_sha256=REGISTRATION, payload=_evaluation_payload(), recorded_at=NOW)
    con.execute("UPDATE p16_evaluation_artifacts SET payload_json='{}'")
    with pytest.raises(ValueError, match="identity differs"):
        p16_store._artifacts_as_of(con, generated_at=NOW)


def test_typed_exposure_score_and_factor_dependencies(con):
    origin_payload, exposure_payload = _evaluation_payload(), _exposure_payload()
    origin = p16_store.record_evaluation_input(
        con, registration_sha256=REGISTRATION, payload=origin_payload, recorded_at=NOW)
    exposure = p16_store.record_exposure_snapshot(
        con, registration_sha256=REGISTRATION, payload=exposure_payload,
        recorded_at=NOW - timedelta(hours=1))
    scores_body = {"policy_id": "challenger", "market_date": DAY.isoformat(),
                   "information_cutoff_at": (NOW - timedelta(days=2)).isoformat(),
                   "scores": {"AAA": 1.0}}
    scores = {**scores_body, "score_snapshot_sha256": canonical_sha256(scores_body)}
    score_id = p16_store.record_policy_scores(
        con, registration_sha256=REGISTRATION, payload=scores,
        recorded_at=NOW - timedelta(minutes=30))
    factor_body = {
        "status": "available", "reason": None, "market_date": DAY.isoformat(),
        "report_cutoff": NOW.isoformat(),
        "input_snapshot_sha256": origin_payload["input_snapshot_sha256"],
        "exposure_snapshot_sha256": exposure_payload["snapshot_sha256"],
        "score_snapshot_sha256": {
            "p15-scoring-v1": DIGEST, "p15_rule_control": DIGEST,
            "challenger": scores["score_snapshot_sha256"],
        }, "comparisons": {},
    }
    factor = {**factor_body, "factor_report_sha256": canonical_sha256(factor_body)}
    stored = p16_store.record_factor_report(
        con, registration_sha256=REGISTRATION, payload=factor,
        origin_artifact_sha256=origin, exposure_artifact_sha256=exposure,
        score_artifact_sha256s=[score_id], recorded_at=NOW)
    assert p16_store._artifact_by_id(con, stored)["payload"] == factor
    factor["factor_report_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="factor report sha256 differs"):
        p16_store.record_factor_report(
            con, registration_sha256=REGISTRATION, payload=factor,
            origin_artifact_sha256=origin, exposure_artifact_sha256=exposure,
            score_artifact_sha256s=[score_id], recorded_at=NOW)


def _origin(index: int, market_date: date, **updates):
    decided = datetime.combine(market_date, datetime.min.time(), tzinfo=timezone.utc) \
        + timedelta(hours=20)
    entry = decided + timedelta(hours=12)
    value = {
        "registration_sha256": REGISTRATION, "family_id": "p16-family-v1",
        "comparison_id": "c-blind-v1", "trial_id": TRIAL,
        "control_trial_id": CONTROL,
        "epoch_session": EPOCH, "session_index": index,
        "market_date": market_date, "status": "pending", "reason": "label_pending",
        "decided_at": decided, "forward_entry_at": entry,
        "labels_available_at": None, "delta_ic": None, "input_sha256": None,
        "source_sha256": DIGEST, "recorded_at": decided + timedelta(minutes=1),
    }
    value.update(updates)
    return value


def _record_scored(con, index: int, market_date: date, **updates):
    pending = _origin(index, market_date)
    pending.update({key: value for key, value in updates.items() if key not in {
        "status", "reason", "labels_available_at", "delta_ic", "input_sha256", "recorded_at",
    }})
    p16_store.record_sequential_origin(con, **pending)
    scored = {
        **pending, "status": "scored", "reason": None,
        "labels_available_at": NOW, "delta_ic": 0.2,
        "input_sha256": f"{index + 1:064x}", "recorded_at": NOW,
    }
    scored.update(updates)
    return p16_store.record_sequential_origin(con, **scored)


def test_sequential_prefix_is_exact_and_immutable(con):
    days = [date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23)]
    for index, day in enumerate(days):
        _record_scored(con, index, day)
    rows = p16_store.sequential_prefix(
        con, registration_sha256=REGISTRATION, family_id="p16-family-v1",
        comparison_id="c-blind-v1", trial_id=TRIAL, control_trial_id=CONTROL,
        epoch_session=EPOCH,
        origin_endpoint=2, report_at=NOW,
    )
    assert [row["session_index"] for row in rows] == [0, 1, 2]
    assert all(row["delta_ic"] == 0.2 for row in rows)
    with pytest.raises(ValueError, match="replayed differently"):
        _record_scored(con, 1, days[1], delta_ic=-0.4)


def test_sequential_event_retry_keeps_first_seen_time(con):
    value = _origin(0, EPOCH)
    first = p16_store.record_sequential_origin(con, **value)
    assert p16_store.record_sequential_origin(
        con, **(value | {"recorded_at": value["recorded_at"] + timedelta(seconds=1)}),
    ) == first
    row = p16_store.sequential_prefix(
        con, registration_sha256=REGISTRATION, family_id="p16-family-v1",
        comparison_id="c-blind-v1", trial_id=TRIAL, control_trial_id=CONTROL,
        epoch_session=EPOCH, origin_endpoint=0, report_at=NOW,
    )[0]
    assert row["recorded_at"] == value["recorded_at"]


def test_sequential_prefix_rejects_missing_retained_decisions_and_tampering(con):
    _record_scored(con, 0, date(2026, 9, 21))
    p16_store.record_sequential_origin(
        con, **_origin(2, date(2026, 9, 23)),
    )
    with pytest.raises(ValueError, match="missing a retained decision"):
        p16_store.sequential_prefix(
            con, registration_sha256=REGISTRATION, family_id="p16-family-v1",
            comparison_id="c-blind-v1", trial_id=TRIAL, control_trial_id=CONTROL,
            epoch_session=EPOCH, origin_endpoint=2, report_at=NOW,
        )
    con.execute("UPDATE p16_sequential_origin_events SET delta_ic=0.9 "
                "WHERE session_index=0 AND event_kind='scored'")
    with pytest.raises(ValueError, match="stored P16 sequential origin event differs"):
        p16_store.sequential_prefix(
            con, registration_sha256=REGISTRATION, family_id="p16-family-v1",
            comparison_id="c-blind-v1", trial_id=TRIAL, control_trial_id=CONTROL,
            epoch_session=EPOCH,
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
        comparison_id="c-blind-v1", trial_id=TRIAL, control_trial_id=CONTROL,
        epoch_session=EPOCH,
        origin_endpoint=0, report_at=NOW,
    )[0]
    assert row["status"] == "decision_unavailable"


def test_predictable_skip_is_retained_before_forward_entry(con):
    recorded = REGISTERED + timedelta(days=1)
    p16_store.record_sequential_origin(
        con, **_origin(
            0, EPOCH, status="decision_unavailable", reason="fewer_than_20_candidates",
            decided_at=recorded - timedelta(minutes=1),
            forward_entry_at=recorded + timedelta(hours=1),
            labels_available_at=None, delta_ic=None, input_sha256=None, recorded_at=recorded,
        ),
    )
    row = p16_store.sequential_prefix(
        con, registration_sha256=REGISTRATION, family_id="p16-family-v1",
        comparison_id="c-blind-v1", trial_id=TRIAL, control_trial_id=CONTROL,
        epoch_session=EPOCH,
        origin_endpoint=0, report_at=recorded,
    )[0]
    assert row["status"] == "decision_unavailable"
    assert row["recorded_at"] == recorded


def test_registration_and_trial_identity_isolate_sequential_series(con):
    _record_scored(con, 0, EPOCH)
    other = "e" * 64
    _record_scored(con, 0, EPOCH, registration_sha256=other, delta_ic=-0.1)
    rows = p16_store.sequential_prefix(
        con, registration_sha256=other, family_id="p16-family-v1",
        comparison_id="c-blind-v1", trial_id=TRIAL, control_trial_id=CONTROL,
        epoch_session=EPOCH,
        origin_endpoint=0, report_at=NOW,
    )
    assert rows[0]["delta_ic"] == -0.1


def test_tampered_trial_registration_cannot_authorize_origin(con):
    con.execute(f"UPDATE {p16_trial_store.TABLE} SET payload='{{}}' WHERE trial_id=?", [TRIAL])
    with pytest.raises(ValueError, match="trial record differs"):
        p16_store.record_sequential_origin(con, **_origin(0, EPOCH))


def test_artifact_time_and_payload_validation(con):
    payload = _evaluation_payload()
    with pytest.raises(ValueError, match="before its cutoff"):
        p16_store.record_evaluation_input(
            con, registration_sha256=REGISTRATION, payload=payload,
            recorded_at=NOW - timedelta(seconds=1))
    with pytest.raises(ValueError, match="timezone-aware"):
        p16_store.record_evaluation_input(
            con, registration_sha256=REGISTRATION,
            payload=_evaluation_payload(report_cutoff=NOW.replace(tzinfo=None).isoformat()),
            recorded_at=NOW)
