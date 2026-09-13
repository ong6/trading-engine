"""Public validation facade for one published walk-forward result."""

from __future__ import annotations

from server.walkforward_artifact_folds import validate_summary, validate_terminal_folds
from server.walkforward_artifact_geometry import (
    validate_planned_folds,
    validated_protocol_geometry,
)
from server.walkforward_artifact_identity import (
    positive_number,
    validate_registration_identity,
)
from server.walkforward_artifact_identity import signature as cohort_signature


def _result_sections(payload: dict) -> tuple[dict, list, list, dict]:
    protocol = payload.get("protocol")
    protocol_folds = protocol.get("folds") if isinstance(protocol, dict) else None
    folds = payload.get("folds")
    dropped = payload.get("dropped_folds")
    summary = payload.get("summary")
    if (
        not isinstance(protocol_folds, list)
        or not protocol_folds
        or not isinstance(folds, list)
        or not isinstance(dropped, list)
        or not isinstance(summary, dict)
        or protocol.get("n_folds") != len(protocol_folds)
        or len(folds) != len(protocol_folds)
    ):
        raise ValueError("incomplete walk-forward result")
    return protocol, folds, dropped, summary


def validate_result(payload: dict, registration: dict) -> None:
    """Reject a result that disagrees with its registration or embedded evidence."""
    validate_registration_identity(payload, registration)
    protocol, folds, dropped, summary = _result_sections(payload)
    protocol_geometry = validated_protocol_geometry(protocol, folds, registration)
    clamped_indices = validate_planned_folds(
        protocol,
        protocol_geometry,
        dropped,
        registration["data_floor"],
        registration.get("planned_fold_count"),
    )

    artifact_initial_cash = positive_number(payload.get("initial_cash"), "invalid initial cash")
    validate_terminal_folds(folds, clamped_indices, artifact_initial_cash)
    validate_summary(folds, summary)


def signature(payload: dict) -> tuple[dict, str]:
    """Validate and canonicalize assumptions shared by one evidence cohort."""
    return cohort_signature(payload)
