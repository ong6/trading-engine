"""Authority-aware risk projection preserves the durable historical halt."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from engine.lib.provenance import canonical_sha256
from server import (
    broker_paper_authority_transcript,
    broker_paper_risk_projection,
    broker_paper_runtime,
    broker_paper_usage,
    broker_risk,
    broker_risk_control,
)
from tests.test_broker_paper_lease import NOW, _assess, _lease
from tests.test_broker_risk import _identity, _policy, _request, _snapshot


def _activation(lease, candidate, runtime):
    body = {
        "schema_version": (
            broker_paper_authority_transcript.TRANSCRIPT_SCHEMA_VERSION
        ),
        "event_type": "activation_recorded",
        "event_sequence": 1,
        "lease_id": lease.lease_id,
        "lease_sha256": lease.sha256(),
        "account_id": lease.account_id,
        "mode": lease.mode,
        "occurred_at": (NOW + timedelta(seconds=2)).isoformat().replace("+00:00", "Z"),
        "prior_event_sha256": None,
        "submission_authority": "none",
        "candidate_assessment_sha256": candidate["assessment_sha256"],
        "startup_assessment_sha256": candidate["startup_assessment_sha256"],
        "control_event_count": runtime.control.event_count,
        "control_event_sha256": runtime.control.latest_event_sha256,
        "runtime_epoch_sha256": runtime.runtime_epoch_sha256,
    }
    return {**body, "event_sha256": canonical_sha256(body)}


def _inputs(con):
    lease = _lease()
    candidate = _assess(lease)
    broker_risk_control.record_halt(
        con,
        halt_key="projection-halt-1",
        account_id=lease.account_id,
        reason="historical halt remains immutable",
        now=NOW,
    )
    runtime = broker_paper_runtime.load_runtime_control(con, lease.account_id)
    activation = _activation(lease, candidate, runtime)
    usage = broker_paper_usage.load_open_usage(
        lease,
        (activation,),
        trusted_event_count=1,
        trusted_latest_event_sha256=activation["event_sha256"],
        trusted_activation_event_sha256=activation["event_sha256"],
        candidate_assessment_sha256=candidate["assessment_sha256"],
        startup_assessment_sha256=candidate["startup_assessment_sha256"],
        activation_runtime_epoch_sha256=runtime.runtime_epoch_sha256,
        current_runtime_epoch_sha256=runtime.runtime_epoch_sha256,
        current_control=runtime.control,
        now=NOW + timedelta(seconds=10),
    )
    snapshot = replace(
        _snapshot(),
        operational_halt=True,
        operational_control_sha256=runtime.control_status_sha256,
    )
    return lease, candidate, usage, runtime, snapshot


def _project(values, **changes):
    lease, candidate, usage, runtime, snapshot = values
    kwargs = {
        "trusted_candidate_assessment_sha256": candidate["assessment_sha256"],
        "now": NOW + timedelta(seconds=11),
    }
    kwargs.update(changes)
    return broker_paper_risk_projection.project_open_epoch(
        lease,
        candidate,
        usage,
        runtime,
        snapshot,
        **kwargs,
    )


def test_projection_preserves_historical_halt_and_remains_non_executable(con):
    values = _inputs(con)
    snapshot = values[-1]

    projection = _project(values)

    assert snapshot.operational_halt is True
    assert projection.historical_operational_halt is True
    assert projection.effective_operational_halt is False
    assert projection.effective_control_source.endswith("_design_only")
    assert projection.risk_evaluation_implemented is False
    assert projection.submission_authority == "none"
    assert projection.original_operational_control_sha256 == (
        snapshot.operational_control_sha256
    )
    assert broker_paper_risk_projection.verify_projection(projection) == projection
    assert projection.projection_sha256 == canonical_sha256(projection.payload())
    with pytest.raises(TypeError, match="typed contract"):
        broker_risk.evaluate(_policy(), _identity(), _request(), projection)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda values: values.__setitem__(
            1,
            {
                **values[1],
                "assessment_sha256": "f" * 64,
            },
        ),
        lambda values: values.__setitem__(
            2,
            replace(values[2], evidence_sha256="f" * 64),
        ),
        lambda values: values.__setitem__(
            3,
            replace(values[3], runtime_epoch_sha256="f" * 64),
        ),
        lambda values: values.__setitem__(
            4,
            replace(values[4], operational_control_sha256="f" * 64),
        ),
        lambda values: values.__setitem__(
            4,
            replace(values[4], operational_halt=False),
        ),
    ],
)
def test_projection_rejects_candidate_usage_runtime_or_snapshot_drift(
    con,
    mutate,
):
    values = list(_inputs(con))
    mutate(values)

    with pytest.raises(broker_paper_risk_projection.PaperRiskProjectionError):
        _project(values)


def test_projection_rejects_expiry(con):
    values = _inputs(con)

    with pytest.raises(
        broker_paper_risk_projection.PaperRiskProjectionError,
        match="binding is invalid",
    ):
        _project(values, now=values[0].expires_at)


def test_module_has_no_mutation_or_submission_surface():
    assert {
        "append",
        "activate",
        "consume",
        "persist",
        "record_halt",
        "reserve",
        "submit",
        "submit_order",
        "renew",
        "revoke",
    }.isdisjoint(vars(broker_paper_risk_projection))
    assert set(
        broker_paper_risk_projection.project_open_epoch.__globals__
    ).isdisjoint(
        {
            "duckdb",
            "db",
            "http",
            "requests",
            "urllib",
            "socket",
            "subprocess",
            "os",
            "BrokerAdapter",
        }
    )
