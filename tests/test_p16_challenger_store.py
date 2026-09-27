from datetime import date, datetime, timedelta, timezone

import duckdb
import pytest

from engine.lib.provenance import canonical_sha256
from farm import p16_trials
from server import p16_challenger_store as store, p16_trial_store

NOW = datetime(2026, 9, 29, 2, 45, tzinfo=timezone.utc)
REGISTRATION = "a" * 64
MODEL = "c" * 64
REGISTERED = NOW - timedelta(days=1)
IDENTITY = {key: "not_applicable" for key in p16_trials.IDENTITY_FIELDS}


def _trial(policy_id):
    return p16_trials.registration(
        policy_id=policy_id, policy_version="v1", plan_id="P16",
        registration_identity=IDENTITY | {"prompt": policy_id},
        evidence_class="prospective", parent_trial_ids=[], registered_at=REGISTERED,
        identity_status="verified", trial_kind="policy",
    )[0]


TRIAL = _trial("c-blind")
ENSEMBLE_TRIAL = _trial("c-ensemble")


@pytest.fixture
def con():
    value = duckdb.connect(":memory:")
    store.init_schema(value)
    for policy_id, trial_id in (("c-blind", TRIAL), ("c-ensemble", ENSEMBLE_TRIAL)):
        actual = p16_trial_store.register(
            value, policy_id=policy_id, policy_version="v1", plan_id="P16",
            registration_identity=IDENTITY | {"prompt": policy_id},
            evidence_class="prospective", parent_trial_ids=[], registered_at=REGISTERED,
            recorded_at=REGISTERED, identity_status="verified", trial_kind="policy",
        )
        assert actual == trial_id
    yield value
    value.close()


def _run(con, **overrides):
    values = {
        "registration_sha256": REGISTRATION, "family_id": "p16-challengers-v1",
        "policy_id": "c-blind", "trial_id": TRIAL,
        "window_id": "c-blind:2026-09-28", "market_date": date(2026, 9, 28),
        "information_cutoff_at": NOW - timedelta(minutes=15), "started_at": NOW,
        "tickers": ["AAA", "BBB"],
        "source_identity": {"p15_run_sha256": "d" * 64},
        "treatment_id": "blind", "model_contract_sha256": MODEL,
        "attempt_manifest": [{
            "chunk_index": 0, "sample_index": 0,
            "source_request_sha256": "a" * 64,
            "source_input_sha256": "e" * 64,
        }],
        "run_mode": "prospective",
    }
    values.update(overrides)
    if "attempt_manifest" not in overrides and values["model_contract_sha256"] is None:
        values["attempt_manifest"] = []
    return store.start_run(con, **values)


def _attempt(con, run, *, started_at=NOW):
    request = {"model": "fixture", "input": "{}"}
    treatment = {"treatment": "blind", "payload_sha256": "e" * 64,
                 "original_sha256": "e" * 64}
    return store.start_attempt(
        con, run["record_id"], chunk_index=0, sample_index=0,
        request_payload=request, treatment=treatment, started_at=started_at,
    )


def _receipt(attempt):
    request = attempt["data"]["request"]
    response = {"id": "response-1"}
    return {
        "request": request, "request_sha256": canonical_sha256(request),
        "response": response, "response_sha256": canonical_sha256(response),
        "output": {"schema_version": 1, "assessments": [{
            key: row[key] for key in (
                "ticker", "p_outperform_5", "expected_excess_bp_5",
                "expected_excess_bp_10", "action", "thesis", "invalidation",
                "evidence_ids",
            )
        } for row in _rows()]},
        "model_contract_sha256": MODEL,
    }


def _rows():
    return [{
        "ticker": ticker, "p_outperform_5": 0.6,
        "expected_excess_bp_5": 50.0, "expected_excess_bp_10": 70.0,
        "action": "buy_candidate", "thesis": "Fixture thesis.",
        "invalidation": "Fixture invalidation.", "evidence_ids": ["f" * 64],
        "scoring_status": "available",
    } for ticker in ("AAA", "BBB")]


def test_append_only_run_attempt_receipt_and_output_are_idempotent(con):
    run = _run(con)
    assert _run(con, started_at=NOW + timedelta(seconds=1)) == run
    attempt = _attempt(con, run)
    receipt = store.finish_attempt(
        con, attempt["record_id"], status="available", receipt=_receipt(attempt),
        completed_at=NOW + timedelta(minutes=1),
    )
    output = store.finish_run(
        con, run["record_id"], rows=_rows(),
        completed_at=NOW + timedelta(minutes=2),
    )
    assert store.get(con, "p16_challenger_receipts", receipt["record_id"]) == receipt
    assert store.output_for_run(con, run["record_id"]) == output
    assert store.finish_run(
        con, run["record_id"], rows=_rows(),
        completed_at=NOW + timedelta(minutes=3),
    ) == output
    assert store.find_run(
        con, registration_sha256=REGISTRATION, family_id="p16-challengers-v1",
        policy_id="c-blind", market_date=date(2026, 9, 28), run_mode="prospective",
    )["output"] == output


def test_conflicting_replay_and_unresolved_attempt_are_rejected(con):
    run = _run(con)
    with pytest.raises(ValueError, match="replay differs"):
        _run(con, tickers=["AAA", "CCC"])
    _attempt(con, run)
    with pytest.raises(ValueError, match="unresolved"):
        store.finish_run(
            con, run["record_id"], rows=_rows(),
            completed_at=NOW + timedelta(minutes=2),
        )


def test_failed_receipt_and_explicit_unavailable_rows_are_retained(con):
    run = _run(con)
    attempt = _attempt(con, run)
    request = attempt["data"]["request"]
    receipt = {
        "request": request, "request_sha256": canonical_sha256(request),
        "response": {"bad": True},
        "response_sha256": canonical_sha256({"bad": True}),
    }
    store.finish_attempt(
        con, attempt["record_id"], status="unavailable", receipt=receipt,
        reason="invalid response", completed_at=NOW + timedelta(minutes=1),
    )
    rows = [{
        **row, "p_outperform_5": None, "expected_excess_bp_5": None,
        "expected_excess_bp_10": None, "action": "unavailable",
        "thesis": None, "invalidation": None, "scoring_status": "unavailable",
        "unavailable_reason": "invalid response",
    } for row in _rows()]
    output = store.finish_run(
        con, run["record_id"], rows=rows, reason="invalid response",
        completed_at=NOW + timedelta(minutes=2),
    )
    assert output["data"]["unavailable_count"] == 2
    assert output["data"]["attempt_sources"]


def test_ensemble_output_binds_exact_component_outputs(con):
    first = _run(con, model_contract_sha256=None)
    first_output = store.finish_run(
        con, first["record_id"], rows=_rows(), completed_at=NOW + timedelta(minutes=1))
    second = _run(
        con, policy_id="c-ensemble", trial_id=ENSEMBLE_TRIAL,
        window_id="c-ensemble:2026-09-28", treatment_id="ensemble_mean",
        model_contract_sha256=None,
    )
    output = store.finish_run(
        con, second["record_id"], rows=_rows(),
        dependency_output_ids=[first_output["record_id"]],
        completed_at=NOW + timedelta(minutes=2),
    )
    assert output["data"]["dependency_output_ids"] == [first_output["record_id"]]


def test_available_scores_require_finite_bounds(con):
    run = _run(con, model_contract_sha256=None)
    rows = _rows()
    rows[0]["p_outperform_5"] = float("nan")
    with pytest.raises(ValueError, match="available output"):
        store.finish_run(con, run["record_id"], rows=rows, completed_at=NOW)


def test_trial_binding_terminal_attempt_and_output_schema_are_enforced(con):
    with pytest.raises(ValueError, match="trial identity differs"):
        _run(con, trial_id="9" * 64)
    run = _run(con, model_contract_sha256=None)
    output = store.finish_run(con, run["record_id"], rows=_rows(), completed_at=NOW)
    with pytest.raises(ValueError, match="invalid or uncatalogued"):
        _attempt(con, run, started_at=NOW + timedelta(minutes=1))
    assert output["data"]["unavailable_count"] == 0

    other = _run(
        con, policy_id="c-ensemble", trial_id=ENSEMBLE_TRIAL,
        window_id="c-ensemble:2026-09-28", treatment_id="ensemble_mean",
        model_contract_sha256=None,
    )
    malformed = _rows()
    malformed[0]["action"] = "teleport"
    with pytest.raises(ValueError, match="available output"):
        store.finish_run(con, other["record_id"], rows=malformed, completed_at=NOW)


def test_ensemble_dependency_must_share_the_exact_origin(con):
    source = _run(con, model_contract_sha256=None)
    source_output = store.finish_run(con, source["record_id"], rows=_rows(), completed_at=NOW)
    ensemble = _run(
        con, policy_id="c-ensemble", trial_id=ENSEMBLE_TRIAL,
        window_id="c-ensemble:2026-09-29", market_date=date(2026, 9, 29),
        treatment_id="ensemble_mean", model_contract_sha256=None,
    )
    with pytest.raises(ValueError, match="dependency differs"):
        store.finish_run(
            con, ensemble["record_id"], rows=_rows(),
            dependency_output_ids=[source_output["record_id"]], completed_at=NOW,
        )


def test_unavailable_receipt_cannot_support_available_output(con):
    run = _run(con)
    attempt = _attempt(con, run)
    request = attempt["data"]["request"]
    store.finish_attempt(
        con, attempt["record_id"], status="unavailable",
        receipt={"request": request, "request_sha256": canonical_sha256(request)},
        reason="connector failure", completed_at=NOW + timedelta(minutes=1),
    )
    with pytest.raises(ValueError, match="cannot support"):
        store.finish_run(
            con, run["record_id"], rows=_rows(), completed_at=NOW + timedelta(minutes=2),
        )


def test_model_output_requires_the_complete_frozen_attempt_grid(con):
    run = _run(con, attempt_manifest=[
        {"chunk_index": 0, "sample_index": index,
         "source_request_sha256": f"{index + 1:064x}",
         "source_input_sha256": "e" * 64}
        for index in range(2)
    ])
    attempt = _attempt(con, run)
    store.finish_attempt(
        con, attempt["record_id"], status="available", receipt=_receipt(attempt),
        completed_at=NOW + timedelta(minutes=1),
    )
    with pytest.raises(ValueError, match="attempt grid is incomplete"):
        store.finish_run(
            con, run["record_id"], rows=_rows(), completed_at=NOW + timedelta(minutes=2),
        )


def test_prospective_output_publishes_exact_w1_score_snapshot(con):
    run = _run(con, model_contract_sha256=None)
    output = store.finish_run(con, run["record_id"], rows=_rows(), completed_at=NOW)
    artifact_id, payload = store.publish_score_snapshot(
        con, output["record_id"], evaluation_tickers=["AAA"],
        recorded_at=NOW + timedelta(seconds=1),
    )
    assert payload["scores"] == {"AAA": 50.0}
    assert payload["score_snapshot_sha256"] == canonical_sha256({
        key: value for key, value in payload.items() if key != "score_snapshot_sha256"
    })
    assert artifact_id

    dry = _run(
        con, window_id="c-blind:dry-run:2026-09-28", run_mode="dry_run",
        model_contract_sha256=None,
    )
    dry_output = store.finish_run(con, dry["record_id"], rows=_rows(), completed_at=NOW)
    with pytest.raises(ValueError, match="only prospective"):
        store.publish_score_snapshot(
            con, dry_output["record_id"], evaluation_tickers=["AAA"],
            recorded_at=NOW + timedelta(seconds=1),
        )
