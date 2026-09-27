"""Persistence contracts for versioned P16 construction books."""
from __future__ import annotations

import copy
import json
from datetime import date, datetime, timedelta, timezone

import duckdb
import pytest

from engine.lib.provenance import canonical_sha256
from server import p16_book_store
from tests.conftest import record_p16_calibration

NOW = datetime(2026, 9, 27, 16, tzinfo=timezone.utc)
REGISTRATION = "a" * 64


def test_contracts_require_a_retained_successful_calibration():
    con = duckdb.connect(":memory:")
    with pytest.raises(p16_book_store.P16BookError, match="calibration is absent"):
        p16_book_store.initialize_contracts(
            con, registration_sha256=REGISTRATION, activation_date=None,
            calibration_sha256="f" * 64, created_at=NOW,
        )


def test_contracts_use_full_registration_digest_and_remain_inactive():
    con = duckdb.connect(":memory:")
    calibration = record_p16_calibration(con, REGISTRATION, NOW)
    instances = p16_book_store.initialize_contracts(
        con, registration_sha256=REGISTRATION, activation_date=date(2026, 10, 5),
        calibration_sha256=calibration, created_at=NOW,
    )
    assert instances == [
        f"p16_construct_ai@sha256:{REGISTRATION}",
        f"p16_construct_rule@sha256:{REGISTRATION}",
    ]
    assert con.execute(
        "SELECT logical_portfolio_id,active,cash FROM p16_book_contracts c "
        "JOIN portfolios p ON p.id=c.portfolio_id ORDER BY logical_portfolio_id"
    ).fetchall() == [
        ("p16_construct_ai", False, 10_000.0),
        ("p16_construct_rule", False, 10_000.0),
    ]
    assert p16_book_store.initialize_contracts(
        con, registration_sha256=REGISTRATION, activation_date=date(2026, 10, 5),
        calibration_sha256=calibration, created_at=NOW,
    ) == instances

    projection = p16_book_store.status_projection(
        con, registration_sha256=REGISTRATION,
    )
    assert projection["status"] == "inactive"
    assert [row["book_id"] for row in projection["books"]] == [
        "p16_construct_ai", "p16_construct_rule",
    ]
    assert all(row["active"] is False for row in projection["books"])
    assert all(row["latest_target"] is None for row in projection["books"])
    assert projection["execution_authority"] == "none"


def test_calibration_store_recomputes_selection_cases_and_cost_evidence():
    source = duckdb.connect(":memory:")
    digest = record_p16_calibration(source, REGISTRATION, NOW)
    payload = json.loads(source.execute(
        "SELECT payload_json FROM p16_calibrations WHERE calibration_sha256=?", [digest],
    ).fetchone()[0])
    source.close()

    mutations = []
    changed_case = copy.deepcopy(payload)
    changed_case["curve"][0]["cases"][0]["tracking_error"] = 9.0
    mutations.append(changed_case)
    changed_cost = copy.deepcopy(payload)
    changed_cost["cost_per_turnover"] = 0.987
    mutations.append(changed_cost)
    changed_ic = copy.deepcopy(payload)
    changed_ic["assumed_ic"] = 0.9
    mutations.append(changed_ic)
    changed_alpha = copy.deepcopy(payload)
    changed_alpha["snapshots"][0]["solver_inputs"]["champion"]["alpha_h5"] = [0.008] * 6
    snapshot_body = {
        key: value for key, value in changed_alpha["snapshots"][0].items()
        if key != "snapshot_sha256"
    }
    changed_alpha["snapshots"][0]["snapshot_sha256"] = canonical_sha256(snapshot_body)
    mutations.append(changed_alpha)
    future_cutoff = copy.deepcopy(payload)
    future_cutoff["snapshots"][0]["scoring_information_cutoff_at"] = (
        "2026-09-28T16:00:00+00:00"
    )
    snapshot_body = {
        key: value for key, value in future_cutoff["snapshots"][0].items()
        if key != "snapshot_sha256"
    }
    future_cutoff["snapshots"][0]["snapshot_sha256"] = canonical_sha256(snapshot_body)
    mutations.append(future_cutoff)
    missing_case = copy.deepcopy(payload)
    missing_case["curve"][0]["cases"].pop()
    mutations.append(missing_case)

    for mutated in mutations:
        body = {key: value for key, value in mutated.items() if key != "calibration_sha256"}
        mutated["calibration_sha256"] = canonical_sha256(body)
        target = duckdb.connect(":memory:")
        with pytest.raises(p16_book_store.P16BookError, match="calibration"):
            p16_book_store.record_calibration(
                target, registration_sha256=REGISTRATION,
                payload=mutated, recorded_at=NOW,
            )
        target.close()


def test_contracts_reject_calibration_not_strictly_before_activation():
    con = duckdb.connect(":memory:")
    calibration = record_p16_calibration(con, REGISTRATION, NOW)
    with pytest.raises(p16_book_store.P16BookError, match="not preactivation"):
        p16_book_store.initialize_contracts(
            con, registration_sha256=REGISTRATION, activation_date=NOW.date(),
            calibration_sha256=calibration, created_at=NOW,
        )


def test_contracts_reject_calibration_recorded_after_activation():
    source = duckdb.connect(":memory:")
    digest = record_p16_calibration(source, REGISTRATION, NOW)
    payload = json.loads(source.execute(
        "SELECT payload_json FROM p16_calibrations WHERE calibration_sha256=?", [digest],
    ).fetchone()[0])
    source.close()
    con = duckdb.connect(":memory:")
    late = NOW + timedelta(days=10)
    p16_book_store.record_calibration(
        con, registration_sha256=REGISTRATION, payload=payload, recorded_at=late,
    )

    with pytest.raises(p16_book_store.P16BookError, match="not preactivation"):
        p16_book_store.initialize_contracts(
            con, registration_sha256=REGISTRATION,
            activation_date=NOW.date() + timedelta(days=8),
            calibration_sha256=digest, created_at=NOW,
        )


def test_calibration_rejects_non_exchange_session_history():
    source = duckdb.connect(":memory:")
    digest = record_p16_calibration(source, REGISTRATION, NOW)
    payload = json.loads(source.execute(
        "SELECT payload_json FROM p16_calibrations WHERE calibration_sha256=?", [digest],
    ).fetchone()[0])
    source.close()
    payload["snapshots"][0]["sessions"][0] = (
        date.fromisoformat(payload["snapshots"][0]["sessions"][0]) + timedelta(days=1)
    ).isoformat()
    body = {
        key: value for key, value in payload["snapshots"][0].items()
        if key != "snapshot_sha256"
    }
    payload["snapshots"][0]["snapshot_sha256"] = canonical_sha256(body)
    payload_body = {key: value for key, value in payload.items() if key != "calibration_sha256"}
    payload["calibration_sha256"] = canonical_sha256(payload_body)

    with pytest.raises((p16_book_store.P16BookError, ValueError), match="calibration|session"):
        p16_book_store.record_calibration(
            duckdb.connect(":memory:"), registration_sha256=REGISTRATION,
            payload=payload, recorded_at=NOW,
        )


def test_attempts_and_horizon_labels_are_separate_tables_with_p15_parity_columns():
    con = duckdb.connect(":memory:")
    p16_book_store.init_schema(con)
    attempts = [
        row[1] for row in con.execute("PRAGMA table_info('p16_limit_attempts')").fetchall()
    ]
    labels = [
        row[1] for row in con.execute("PRAGMA table_info('p16_limit_labels')").fetchall()
    ]
    assert attempts == [
        "intent_id", "attempt_date", "limit_px", "open_px",
        "counterfactual_fill_px", "outcome", "reject_reason",
    ]
    assert labels == [
        "intent_id", "attempt_date", "horizon_sessions", "entry_px", "exit_date",
        "exit_close", "net_return", "spy_net_return", "net_excess_return",
        "price_prefix_sha256", "labeled_at", "label_sha256",
    ]


def test_intent_and_attempt_exact_retries_are_idempotent_but_drift_is_rejected():
    con = duckdb.connect(":memory:")
    calibration = record_p16_calibration(con, REGISTRATION, NOW)
    [instance, _] = p16_book_store.initialize_contracts(
        con, registration_sha256=REGISTRATION, activation_date=None,
        calibration_sha256=calibration, created_at=NOW,
    )
    arguments = dict(
        book_instance_id=instance, signal_date=date(2026, 9, 25), ticker="AAA",
        side="buy", order_role="rebalance", target_weight=0.1, rounded_qty=10,
        source_sha256="b" * 64, limit_px=9.95,
        expected_session=date(2026, 9, 28), created_at=NOW,
    )
    intent_id, created = p16_book_store.add_intent(con, **arguments)
    assert created is True
    assert p16_book_store.add_intent(con, **arguments) == (intent_id, False)
    with pytest.raises(p16_book_store.P16BookError, match="replay differs"):
        p16_book_store.add_intent(con, **(arguments | {"rounded_qty": 11}))
    attempt = dict(
        intent_id=intent_id, attempt_date=date(2026, 9, 28), limit_px=9.95,
        open_px=10.0, counterfactual_fill_px=10.01,
        outcome="limit_not_reached", reject_reason="limit_not_reached",
    )
    assert p16_book_store.record_limit_attempt(con, **attempt) is True
    assert p16_book_store.record_limit_attempt(con, **attempt) is False
    with pytest.raises(p16_book_store.P16BookError, match="replay differs"):
        p16_book_store.record_limit_attempt(
            con, **(attempt | {"counterfactual_fill_px": 10.02}),
        )
    label = dict(
        intent_id=intent_id, attempt_date=date(2026, 9, 28), horizon_sessions=5,
        entry_px=10.01, exit_date=date(2026, 10, 2), exit_close=10.5,
        net_return=0.0479, spy_net_return=0.01, net_excess_return=0.0379,
        price_prefix_sha256="c" * 64, labeled_at=NOW,
    )
    assert p16_book_store.record_limit_label(con, **label) is True
    assert p16_book_store.record_limit_label(con, **label) is False
    with pytest.raises(p16_book_store.P16BookError, match="replay differs"):
        p16_book_store.record_limit_label(
            con, **(label | {"net_excess_return": 0.02}),
        )
