"""Strict JSON loading for operational evidence and API projections."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .file_utils import MAX_OPERATIONAL_FILE_BYTES, read_bytes

MAX_JSON_NESTING = 100
MAX_JSON_FILE_BYTES = MAX_OPERATIONAL_FILE_BYTES


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number: {value}")
    return parsed


def _require_bounded_nesting(value: Any) -> None:
    pending = [(value, 1)]
    while pending:
        item, depth = pending.pop()
        if not isinstance(item, (dict, list)):
            continue
        if depth > MAX_JSON_NESTING:
            raise ValueError(f"JSON nesting exceeds {MAX_JSON_NESTING} levels")
        children = item.values() if isinstance(item, dict) else item
        pending.extend((child, depth + 1) for child in children)


def loads_strict(value: str | bytes | bytearray) -> Any:
    """Decode standard JSON with unique object keys at every nesting level."""
    try:
        payload = json.loads(
            value,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except RecursionError as exc:
        raise ValueError(f"JSON nesting exceeds {MAX_JSON_NESTING} levels") from exc
    _require_bounded_nesting(payload)
    return payload


def loads_unique_object(value: str | bytes | bytearray) -> dict[str, Any]:
    """Decode an object with unique keys for identity-only legacy classification."""
    try:
        payload = json.loads(value, object_pairs_hook=_unique_object)
    except RecursionError as exc:
        raise ValueError(f"JSON nesting exceeds {MAX_JSON_NESTING} levels") from exc
    _require_bounded_nesting(payload)
    if not isinstance(payload, dict):
        raise ValueError("top-level JSON value must be an object")
    return payload


def require_finite_numbers(value: Any) -> None:
    """Reject non-finite floats in an already duplicate-key-safe JSON tree."""
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("non-finite JSON number")
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def loads_object(value: str | bytes | bytearray) -> dict[str, Any]:
    """Decode one unambiguous JSON object."""
    payload = loads_strict(value)
    if not isinstance(payload, dict):
        raise ValueError("top-level JSON value must be an object")
    return payload


def load_object(path: Path, *, allow_symlinked_parents: bool = True) -> dict[str, Any]:
    """Read one size-bounded JSON object from a regular, non-symlink file."""
    return loads_object(
        read_bytes(
            path,
            max_bytes=MAX_JSON_FILE_BYTES,
            label="JSON",
            allow_symlinked_parents=allow_symlinked_parents,
        )
    )
