"""Fail-closed API projection for prospective cross-sectional momentum evidence."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import duckdb

from engine import xs_forward_review as xs_forward_monitor
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
        "initial_cash": xs_forward_monitor.EXPECTED_INITIAL_CASH,
        "execution_profile": xs_forward_monitor.EXPECTED_EXECUTION_PROFILE,
    }
    candidate = {
        "portfolio_id": xs_forward_monitor.CANDIDATE_ID,
        "config_sha256": xs_forward_monitor.EXPECTED_CONFIG_SHA256[xs_forward_monitor.CANDIDATE_ID],
        **common,
    }
    control = {
        "portfolio_id": xs_forward_monitor.CONTROL_ID,
        "config_sha256": xs_forward_monitor.EXPECTED_CONFIG_SHA256[xs_forward_monitor.CONTROL_ID],
        **common,
    }
    validate_pair_registration(
        payload,
        candidate,
        control,
        "XS forward registration does not match frozen experiment",
    )


def _validate_runtime(payload: dict) -> dict:
    frozen = payload["frozen_runtime"]
    expected = {
        "signal_date": xs_forward_monitor.SIGNAL_DATE.isoformat(),
        "observation_start": xs_forward_monitor.OBSERVATION_START.isoformat(),
        "fill_model": xs_forward_monitor.EXPECTED_FILL_MODEL_VERSION,
        "execution_profile_sha256": xs_forward_monitor.EXPECTED_PROFILE_SHA256,
        "runtime_contract_version": xs_forward_monitor.RUNTIME_CONTRACT_VERSION,
        "runtime_contract_sha256": xs_forward_monitor.EXPECTED_RUNTIME_CONTRACT_SHA256,
        "superseded_runtime_contract_sha256": (
            xs_forward_monitor.SUPERSEDED_RUNTIME_CONTRACT_SHA256
        ),
        "runtime_contract_migration": xs_forward_monitor.RUNTIME_CONTRACT_MIGRATION,
    }
    require_expected_fields(
        frozen,
        expected,
        "XS forward runtime does not match frozen experiment",
    )
    if (
        xs_forward_monitor._runtime_contract_sha256()
        != xs_forward_monitor.EXPECTED_RUNTIME_CONTRACT_SHA256
    ):
        raise ValueError("XS forward runtime does not match frozen experiment")
    return frozen


def _validate_observation(payload: dict, latest_date: date | None) -> dict:
    result_status = payload["status"]
    observation = payload["observation"]
    paired_months = observation["paired_complete_months"]
    shared_sessions = observation["shared_sessions"]
    mature = observation["mature"]
    boundary_frozen = observation["signal_boundary_frozen"]
    eligible_after = iso_date(
        observation["eligible_after"], "XS eligible_after must be YYYY-MM-DD"
    )
    if not (
        valid_nonnegative_int(paired_months)
        and valid_nonnegative_int(shared_sessions)
        and isinstance(mature, bool)
        and isinstance(boundary_frozen, bool)
    ):
        raise ValueError("invalid XS forward observation counts")
    expected_eligible_after = xs_forward_monitor._plus_months(
        xs_forward_monitor.OBSERVATION_START, xs_forward_monitor.WINDOW_MONTHS
    )
    if eligible_after != expected_eligible_after:
        raise ValueError("XS forward eligibility date does not match frozen experiment")
    if result_status == "WAITING":
        if mature or paired_months or shared_sessions or "as_of" in observation:
            raise ValueError("XS waiting status has accrued observations")
        return observation
    as_of = iso_date(observation["as_of"], "XS as_of must be YYYY-MM-DD")
    derived_mature = (
        as_of >= eligible_after and paired_months >= xs_forward_monitor.MIN_PAIRED_MONTHS
    )
    if mature != derived_mature or (result_status == "ACCUMULATING") == mature:
        raise ValueError("XS forward status is inconsistent with maturity")
    if latest_date is not None and as_of != latest_date:
        raise ValueError("XS forward report is stale relative to latest prices")
    return observation


def _reconcile_payload(
    payload: dict,
    latest_date: date | None,
    con: duckdb.DuckDBPyConnection | None,
) -> dict:
    if con is None:
        return payload
    if latest_date is None:
        raise ValueError("latest live price date is unavailable")
    authoritative = xs_forward_monitor.evaluate(con, prior_result=payload)
    live_payload = json.loads(json.dumps(authoritative, default=str))
    if canonical_sha256(payload) != canonical_sha256(live_payload):
        raise ValueError("XS forward report does not match live frozen evaluation")
    return live_payload


def _project(payload: dict, frozen: dict) -> dict:
    observation = payload["observation"]
    projected = {
        "status": payload["status"],
        "paper_only": True,
        "automatic_action": "none",
        "report_schema_version": payload["schema_version"],
        "runtime_contract_version": frozen["runtime_contract_version"],
        "runtime_contract_sha256": frozen["runtime_contract_sha256"],
        "signal_date": observation["signal_date"],
        "observation_start": observation["observation_start"],
        "eligible_after": observation["eligible_after"],
        "signal_boundary_frozen": observation["signal_boundary_frozen"],
        "shared_sessions": observation["shared_sessions"],
        "paired_complete_months": observation["paired_complete_months"],
        "minimum_paired_months": xs_forward_monitor.MIN_PAIRED_MONTHS,
        "mature": observation["mature"],
    }
    if "as_of" in observation:
        projected["as_of"] = observation["as_of"]
        projected["cumulative_excess"] = finite_metric(
            payload["metrics"],
            "cumulative_excess",
            "XS forward metrics must be finite",
        )
    return projected


def _validated_projection(
    path: Path,
    latest_date: date | None,
    con: duckdb.DuckDBPyConnection | None,
) -> dict:
    payload = load_object(path)
    validate_report_envelope(
        payload,
        frozenset({"WAITING", "ACCUMULATING", "PASS-FORWARD", "INCONCLUSIVE", "REVIEW-KILL"}),
        "XS",
    )
    _validate_registration(payload)
    frozen = _validate_runtime(payload)
    _validate_observation(payload, latest_date)
    payload = _reconcile_payload(payload, latest_date, con)
    return _project(payload, frozen)


def status(
    path: Path,
    latest_date: date | None = None,
    con: duckdb.DuckDBPyConnection | None = None,
) -> dict:
    """Project prospective stock-momentum evidence or fail closed."""
    if not path.exists():
        return invalid_status()
    try:
        return _validated_projection(path, latest_date, con)
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        RecursionError,
        duckdb.Error,
    ):
        return invalid_status()
