from datetime import date, datetime, timedelta, timezone

import duckdb
import pytest

from engine.lib.provenance import canonical_sha256
from server import p16_challenger_store as store

NOW = datetime(2026, 9, 29, 2, 45, tzinfo=timezone.utc)
REGISTRATION = "a" * 64
POLICY = "b" * 64
MODEL = "c" * 64


@pytest.fixture
def con():
    value = duckdb.connect(":memory:")
    store.init_schema(value)
    yield value
    value.close()


def _run(con, **overrides):
    values = {
        "registration_sha256": REGISTRATION, "family_id": "p16-challengers-v1",
        "policy_id": "c-blind", "policy_sha256": POLICY,
        "window_id": "c-blind:2026-09-28", "market_date": date(2026, 9, 28),
        "information_cutoff_at": NOW - timedelta(minutes=15), "started_at": NOW,
        "tickers": ["AAA", "BBB"],
        "source_identity": {"p15_run_sha256": "d" * 64},
        "treatment_id": "blind", "model_contract_sha256": MODEL,
    }
    values.update(overrides)
    return store.start_run(con, **values)


def _attempt(con, run, *, started_at=NOW):
    request = {"model": "fixture", "input": "{}"}
    treatment = {"treatment": "blind", "payload_sha256": "e" * 64}
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
        "output": {"schema_version": 1, "assessments": []},
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
    assert _run(con) == run
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
        completed_at=NOW + timedelta(minutes=2),
    ) == output


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
        "scoring_status": "unavailable",
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
        con, policy_id="c-ensemble", policy_sha256="9" * 64,
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
    with pytest.raises(ValueError, match="available score"):
        store.finish_run(con, run["record_id"], rows=rows, completed_at=NOW)
