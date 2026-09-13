"""Fail-closed API projection for prospective sector-momentum evidence."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import duckdb

from engine import forward_review as forward_monitor
from engine.lib.provenance import canonical_sha256

from .forward_contracts import (
    finite_metric,
    invalid_status,
    require_expected_fields,
    valid_nonnegative_int,
    validate_pair_registration,
    validate_report_envelope,
)
from .json_utils import load_object
from .status_validation import iso_date


def _validate_registration(payload: dict) -> None:
    common = {
        "initial_cash": forward_monitor.EXPECTED_INITIAL_CASH,
        "execution_profile": forward_monitor.EXPECTED_EXECUTION_PROFILE,
    }
    candidate = {
        "portfolio_id": forward_monitor.CANDIDATE_ID,
        "config_sha256": forward_monitor.EXPECTED_CONFIG_SHA256[forward_monitor.CANDIDATE_ID],
        **common,
    }
    control = {
        "portfolio_id": forward_monitor.CONTROL_ID,
        "config_sha256": forward_monitor.EXPECTED_CONFIG_SHA256[forward_monitor.CONTROL_ID],
        **common,
    }
    validate_pair_registration(
        payload,
        candidate,
        control,
        "forward report registration does not match frozen experiment",
    )


def _validate_runtime(payload: dict) -> dict:
    frozen = payload["frozen_runtime"]
    expected = {
        "observation_start": forward_monitor.OBSERVATION_START.isoformat(),
        "fill_model": forward_monitor.EXPECTED_FILL_MODEL_VERSION,
        "execution_profile_sha256": forward_monitor.EXPECTED_PROFILE_SHA256,
        "runtime_contract_version": forward_monitor.RUNTIME_CONTRACT_VERSION,
        "runtime_contract_sha256": forward_monitor.EXPECTED_RUNTIME_CONTRACT_SHA256,
        "superseded_runtime_contract_sha256": (forward_monitor.SUPERSEDED_RUNTIME_CONTRACT_SHA256),
        "runtime_contract_migration": forward_monitor.RUNTIME_CONTRACT_MIGRATION,
        "baseline_state": forward_monitor.EXPECTED_BASELINE_STATE,
        "baseline_state_sha256": forward_monitor.EXPECTED_BASELINE_STATE_SHA256,
    }
    require_expected_fields(
        frozen,
        expected,
        "forward report runtime does not match frozen experiment",
    )
    if (
        forward_monitor._runtime_contract_sha256()
        != forward_monitor.EXPECTED_RUNTIME_CONTRACT_SHA256
    ):
        raise ValueError("forward report runtime does not match frozen experiment")
    return frozen


def _validate_observation(
    payload: dict,
    latest_date: date | None,
) -> tuple[date, date, int, bool]:
    result_status = payload["status"]
    observation = payload["observation"]
    ledger_sha256 = observation["forward_ledger_sha256"]
    if not isinstance(ledger_sha256, str) or len(ledger_sha256) != 64:
        raise ValueError("forward ledger hash is invalid")
    as_of = iso_date(observation["as_of"], "forward as_of must be YYYY-MM-DD")
    eligible_after = iso_date(
        observation["eligible_after"], "forward eligible_after must be YYYY-MM-DD"
    )
    shared_sessions = observation["shared_sessions_available"]
    mature = observation["mature"]
    if not (
        valid_nonnegative_int(shared_sessions)
        and shared_sessions >= 1
        and isinstance(mature, bool)
    ):
        raise ValueError("invalid forward observation counts")
    expected_eligible_after = forward_monitor._plus_months(
        forward_monitor.OBSERVATION_START, forward_monitor.WINDOW_MONTHS
    )
    if eligible_after != expected_eligible_after:
        raise ValueError("forward eligibility date does not match frozen experiment")
    derived_mature = (
        as_of >= eligible_after and shared_sessions >= forward_monitor.MIN_SHARED_SESSIONS
    )
    if mature != derived_mature or (result_status == "ACCUMULATING") == mature:
        raise ValueError("forward status is inconsistent with maturity")
    if latest_date is not None and as_of != latest_date:
        raise ValueError("forward report is stale relative to latest prices")
    return as_of, eligible_after, shared_sessions, mature


def _reconcile_payload(
    payload: dict,
    latest_date: date | None,
    con: duckdb.DuckDBPyConnection | None,
) -> dict:
    if con is None:
        return payload
    if latest_date is None:
        raise ValueError("latest live price date is unavailable")
    authoritative = forward_monitor.evaluate(con)
    protected = (
        "schema_version",
        "status",
        "paper_only",
        "automatic_action",
        "candidate",
        "control",
        "criterion",
        "frozen_runtime",
        "observation",
        "metrics",
        "checks",
    )
    reported_contract = {key: payload[key] for key in protected}
    live_contract = {key: authoritative[key] for key in protected}
    live_contract = json.loads(json.dumps(live_contract, default=str))
    if canonical_sha256(reported_contract) != canonical_sha256(live_contract):
        raise ValueError("forward report does not match live frozen evaluation")
    return live_contract


def _project(payload: dict, frozen: dict, latest_date: date | None) -> dict:
    as_of, eligible_after, shared_sessions, mature = _validate_observation(payload, latest_date)
    metrics = payload["metrics"]
    excess_return = finite_metric(metrics, "excess_return", "forward metrics must be finite")
    drawdown_improvement = finite_metric(
        metrics,
        "drawdown_improvement",
        "forward metrics must be finite",
    )
    return {
        "status": payload["status"],
        "paper_only": True,
        "automatic_action": "none",
        "report_schema_version": payload["schema_version"],
        "runtime_contract_version": frozen["runtime_contract_version"],
        "runtime_contract_sha256": frozen["runtime_contract_sha256"],
        "as_of": as_of.isoformat(),
        "eligible_after": eligible_after.isoformat(),
        "shared_sessions": shared_sessions,
        "minimum_shared_sessions": forward_monitor.MIN_SHARED_SESSIONS,
        "mature": mature,
        "excess_return": excess_return,
        "drawdown_improvement": drawdown_improvement,
    }


def status(
    path: Path,
    latest_date: date | None = None,
    con: duckdb.DuckDBPyConnection | None = None,
) -> dict:
    """Project prospective sector-momentum evidence or fail closed."""
    if not path.exists():
        return invalid_status()
    try:
        payload = load_object(path)
        validate_report_envelope(
            payload,
            frozenset({"ACCUMULATING", "CONTINUE", "REVIEW-KILL"}),
            "sector",
        )
        _validate_registration(payload)
        frozen = _validate_runtime(payload)
        _validate_observation(payload, latest_date)
        payload = _reconcile_payload(payload, latest_date, con)
        return _project(payload, frozen, latest_date)
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        RecursionError,
        duckdb.Error,
    ):
        return invalid_status()
