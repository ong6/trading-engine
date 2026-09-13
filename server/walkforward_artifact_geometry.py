"""Validate planned, retained, and data-floor-dropped walk-forward folds."""

from __future__ import annotations

from datetime import date

from farm.walkforward import protocol as walkforward_protocol
from server.status_validation import iso_date
from server.walkforward_artifact_identity import validated_protocol


def _positive_int(value: object, message: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(message)
    return value


def fold_geometry(value: object) -> tuple[int, str, str, str]:
    if not isinstance(value, dict):
        raise ValueError("invalid fold")
    index = _positive_int(value.get("index"), "invalid fold index")
    try:
        train_start = iso_date(value["train_start"])
        split_date = iso_date(value["split_date"])
        validate_end = iso_date(value["validate_end"])
    except (KeyError, ValueError):
        raise ValueError("invalid fold dates") from None
    if not train_start < split_date < validate_end:
        raise ValueError("invalid fold geometry")
    return index, train_start.isoformat(), split_date.isoformat(), validate_end.isoformat()


def _dropped_geometry(dropped: list) -> list[tuple[int, str, str, str]]:
    geometry = []
    for fold in dropped:
        if (
            not isinstance(fold, dict)
            or fold.get("status") != "dropped"
            or not isinstance(fold.get("reason"), str)
            or not fold["reason"].strip()
        ):
            raise ValueError("invalid dropped fold")
        geometry.append(fold_geometry(fold))
    return geometry


def _validate_fold_partition(
    retained: list[tuple[int, str, str, str]],
    dropped: list[tuple[int, str, str, str]],
    planned_count: int,
) -> tuple[list[int], list[int]]:
    retained_indices = [geometry[0] for geometry in retained]
    dropped_indices = [geometry[0] for geometry in dropped]
    all_indices = retained_indices + dropped_indices
    if (
        len(set(retained_indices)) != len(retained_indices)
        or len(set(dropped_indices)) != len(dropped_indices)
        or set(retained_indices).intersection(dropped_indices)
        or set(all_indices) != set(range(1, planned_count + 1))
    ):
        raise ValueError("walk-forward folds do not account for planned grid")
    return retained_indices, dropped_indices


def _expected_geometry(fold, data_floor: date, *, retained: bool):
    train_start = max(fold.train_start, data_floor) if retained else fold.train_start
    return (
        fold.index,
        train_start.isoformat(),
        fold.split_date.isoformat(),
        fold.validate_end.isoformat(),
    )


def _validate_fold_geometry(
    actual_geometry: list[tuple[int, str, str, str]],
    planned_by_index: dict,
    data_floor: date,
    *,
    retained: bool,
) -> None:
    message = (
        "retained fold does not match planned geometry"
        if retained
        else "dropped fold does not match planned geometry"
    )
    for actual in actual_geometry:
        if actual != _expected_geometry(planned_by_index[actual[0]], data_floor, retained=retained):
            raise ValueError(message)


def validate_planned_folds(
    protocol: dict,
    protocol_geometry: list[tuple[int, str, str, str]],
    dropped: list,
    data_floor_value: object,
    planned_fold_count: object,
) -> set[int]:
    dropped_geometry = _dropped_geometry(dropped)
    planned_count = _positive_int(planned_fold_count, "invalid planned fold count")
    _retained_indices, dropped_indices = _validate_fold_partition(
        protocol_geometry, dropped_geometry, planned_count
    )
    anchor, months = validated_protocol(protocol)
    data_floor = iso_date(data_floor_value, "invalid data floor")
    planned = walkforward_protocol.make_folds(
        date.fromisoformat(anchor),
        **months,
        n_folds=planned_count,
    )
    planned_by_index = {fold.index: fold for fold in planned}
    expected_dropped = {fold.index for fold in planned if fold.split_date <= data_floor}
    if set(dropped_indices) != expected_dropped:
        raise ValueError("dropped folds do not match data floor")
    _validate_fold_geometry(protocol_geometry, planned_by_index, data_floor, retained=True)
    _validate_fold_geometry(dropped_geometry, planned_by_index, data_floor, retained=False)
    return {
        fold.index
        for fold in planned
        if fold.index not in expected_dropped and fold.train_start < data_floor
    }


def validated_protocol_geometry(
    protocol: dict,
    folds: list,
    registration: dict,
) -> list[tuple[int, str, str, str]]:
    if any(
        protocol.get(name) != expected
        for name, expected in registration["protocol_windows"].items()
    ):
        raise ValueError("result protocol does not match registration")
    protocol_geometry = [fold_geometry(fold) for fold in protocol["folds"]]
    result_geometry = [fold_geometry(fold) for fold in folds]
    if (
        len(set(protocol_geometry)) != len(protocol_geometry)
        or result_geometry != protocol_geometry
    ):
        raise ValueError("result folds do not match protocol")
    return protocol_geometry
