"""Tests for the P16 fixed-grid pre-entry evaluation adapter."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import duckdb
import pytest

from engine.lib.provenance import canonical_sha256
from engine.p16_features import EXPOSURES
from farm import p16_eval_inputs, p16_factors, p16_trials
from server import p16_preentry, p16_store, p16_trial_store

REGISTRATION = "a" * 64
EPOCH = date(2026, 9, 21)
NOW = datetime(2026, 9, 21, 21, tzinfo=timezone.utc)
IDENTITY = {key: "not_applicable" for key in p16_trials.IDENTITY_FIELDS}


def _trial(policy: str, registered_at: datetime) -> tuple[str, dict]:
    values = {
        "policy_id": policy, "policy_version": "v1", "plan_id": "P16",
        "registration_identity": IDENTITY | {"prompt": policy},
        "evidence_class": "prospective", "parent_trial_ids": [],
        "registered_at": registered_at, "identity_status": "verified",
        "trial_kind": "policy",
    }
    trial_id, _payload = p16_trials.registration(**values)
    return trial_id, values


@pytest.fixture
def family():
    registered = NOW - timedelta(days=1)
    control, control_values = _trial("p15-scoring", registered)
    members, registrations = [], [(control, control_values)]
    for policy in ("c-one", "c-two"):
        trial_id, values = _trial(policy, registered)
        registrations.append((trial_id, values))
        members.append({
            "comparison_id": policy, "trial_id": trial_id,
            "control_trial_id": control,
        })
    return members, registrations


@pytest.fixture
def con(family):
    connection = duckdb.connect(":memory:")
    p16_store.init_schema(connection)
    for expected, values in family[1]:
        registered_at = values.pop("registered_at")
        identity_status = values.pop("identity_status")
        actual = p16_trial_store.register(
            connection, **values, registered_at=registered_at,
            recorded_at=registered_at, identity_status=identity_status,
        )
        assert actual == expected
    yield connection
    connection.close()


def _origin(count: int = 20) -> dict:
    decision_rows = [{
        "ticker": f"T{index:02d}", "stratum": "mover",
        "champion_score": float(index), "champion_score_available": True,
        "rule_score": -index, "baseline_rank": index + 1,
        "baseline_score": count - index, "decision_sha256": f"{index + 1:064x}",
    } for index in range(count)]
    body = {
        "schema_version": 1, "policy_id": "p15-scoring-v1", "status": "pending",
        "market_date": EPOCH.isoformat(), "report_cutoff": NOW.isoformat(),
        "scoring_information_cutoff_at": (NOW - timedelta(minutes=30)).isoformat(),
        "source": {"run_id": 1, **{key: "b" * 64 for key in (
            "bundle_sha256", "universe_sha256", "context_sha256", "source_refs_sha256",
            "request_sha256", "input_sha256", "output_sha256", "trace_sha256")}},
        "p15_registration_sha256": "c" * 64, "scoring_completed_at": NOW.isoformat(),
        "frozen_candidate_count": count, "held_only_excluded_count": 0,
        "evaluation_candidate_count": count, "decision_rows": decision_rows,
        "terminal_h5_count": 0,
        "unresolved_h5_tickers": [row["ticker"] for row in decision_rows], "rows": [],
    }
    return {**body, "input_snapshot_sha256": canonical_sha256(body)}


def _exposure(origin: dict) -> dict:
    body = {
        "schema_version": 2, "policy_id": "p16-eval-v2",
        "market_date": origin["market_date"],
        "information_cutoff_at": origin["scoring_information_cutoff_at"],
        "price_basis": "split_adjusted_price_v1",
        "corporate_action_state": "retained_at_information_cutoff",
        "exposure_names": list(EXPOSURES), "source_bars_sha256": "d" * 64,
        "sector_snapshot_sha256": "e" * 64,
        "candidates": [{
            "ticker": row["ticker"], "status": "available", "missing_exposures": [],
            "exposures": dict.fromkeys(EXPOSURES, 0.0), "sector": "technology",
            "sector_source": None, "real_bar_count": 253,
        } for row in origin["decision_rows"]],
    }
    return {**body, "snapshot_sha256": canonical_sha256(body)}


def _scores(con, family, count: int = 20) -> list[str]:
    result = []
    for member_index, member in enumerate(family[0]):
        scores = {f"T{index:02d}": float(index + member_index) for index in range(count)}
        body = {
            "policy_id": member["comparison_id"], "market_date": EPOCH.isoformat(),
            "information_cutoff_at": (NOW - timedelta(minutes=30)).isoformat(),
            "scores": scores,
        }
        payload = {**body, "score_snapshot_sha256": canonical_sha256(body)}
        result.append(p16_store.record_policy_scores(
            con, registration_sha256=REGISTRATION, payload=payload,
            recorded_at=NOW - timedelta(minutes=20),
        ))
    return sorted(result)


def test_preentry_calls_full_origin_chain_and_records_every_family_member(
    con, family, monkeypatch,
):
    origin = _origin()
    exposure = _exposure(origin)
    calls = []
    monkeypatch.setattr(
        p16_eval_inputs, "load_origin",
        lambda _con, *, market_date, report_cutoff: calls.append(
            ("load_origin", market_date, report_cutoff)) or origin,
    )
    monkeypatch.setattr(
        p16_preentry.p16_features, "exposure_snapshot",
        lambda _con, tickers, market_date, *, information_cutoff_at: calls.append(
            ("exposure_snapshot", tickers, market_date, information_cutoff_at)) or exposure,
    )
    original_evaluate = p16_factors.evaluate_origin

    def evaluate(*args, **kwargs):
        calls.append(("evaluate_origin",))
        return original_evaluate(*args, **kwargs)

    monkeypatch.setattr(p16_factors, "evaluate_origin", evaluate)
    result = p16_preentry.record_preentry(
        con, registration_sha256=REGISTRATION, family_id="p16-family-v1",
        epoch_session=EPOCH, members=family[0], market_date=EPOCH,
        score_artifact_sha256s=_scores(con, family), recorded_at=NOW,
    )

    assert [call[0] for call in calls] == [
        "load_origin", "exposure_snapshot", "evaluate_origin",
    ]
    assert result["status"] == "recorded" and result["session_index"] == 0
    assert [row["status"] for row in result["decisions"]] == ["eligible", "eligible"]
    assert con.execute(
        "SELECT COUNT(*) FROM p16_sequential_origin_events WHERE event_kind='decision'"
    ).fetchone() == (2,)


def test_preentry_records_only_registered_pre_outcome_skip_reasons(con, family, monkeypatch):
    origin = _origin(19)
    monkeypatch.setattr(p16_eval_inputs, "load_origin", lambda *_args, **_kwargs: origin)
    monkeypatch.setattr(p16_preentry.p16_features, "exposure_snapshot",
                        lambda *_args, **_kwargs: _exposure(origin))

    result = p16_preentry.record_preentry(
        con, registration_sha256=REGISTRATION, family_id="p16-family-v1",
        epoch_session=EPOCH, members=family[0], market_date=EPOCH,
        score_artifact_sha256s=_scores(con, family, 19), recorded_at=NOW,
    )

    assert {(row["status"], row["reason"]) for row in result["decisions"]} == {
        ("decision_unavailable", "fewer_than_20_candidates")
    }


def test_missed_session_report_is_permanently_blocked_and_not_backfilled(con, family):
    after_forward_open = datetime(2026, 9, 22, 14, tzinfo=timezone.utc)

    report = p16_preentry.grid_report(
        con, registration_sha256=REGISTRATION, family_id="p16-family-v1",
        epoch_session=EPOCH, members=family[0], generated_at=after_forward_open,
    )

    assert report["status"] == "blocked_missing_origin_decision"
    assert report["first_permanently_missing_origin"] == "2026-09-21"
    assert all(row["missing_session_indices"] == [0] for row in report["comparisons"])
    assert report["grid_report_sha256"] == canonical_sha256({
        key: value for key, value in report.items() if key != "grid_report_sha256"
    })

    with pytest.raises(p16_preentry.PreentryError, match="after close and before next open"):
        p16_preentry.record_preentry(
            con, registration_sha256=REGISTRATION, family_id="p16-family-v1",
            epoch_session=EPOCH, members=family[0], market_date=EPOCH,
            score_artifact_sha256s=[], recorded_at=after_forward_open,
        )
