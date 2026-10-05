"""Fail-soft loader for the optional engine health snapshot."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .file_utils import read_bytes
from .json_utils import loads_object
from .status_validation import iso_date, iso_timestamp

log = logging.getLogger(__name__)
PUBLIC_SUMMARY_FIELDS = ("regime", "last_run", "last_screen", "screen_date")
# Full-universe verifier summaries exceed the generic 1 MiB operational-file cap.
MAX_META_SNAPSHOT_BYTES = 8 * 1024 * 1024


def public_summary(payload: dict) -> dict:
    """Project only validated header fields from the complete producer snapshot."""
    summary = {field: payload[field] for field in PUBLIC_SUMMARY_FIELDS if field in payload}
    if "regime" in summary and summary["regime"] not in {"risk-on", "risk-off"}:
        raise ValueError("metadata regime is invalid")
    for field in ("last_run", "last_screen"):
        value = summary.get(field)
        if value is not None:
            iso_timestamp(value, f"metadata {field} must be a canonical timestamp")
    screen_date = summary.get("screen_date")
    if screen_date is not None:
        iso_date(screen_date, "metadata screen_date must be YYYY-MM-DD")
    return summary


def load(path: Path) -> tuple[dict, dict]:
    """Load the snapshot without hiding independent live projections."""
    if not os.path.lexists(path):
        return {}, {"status": "missing", "path": str(path)}
    if path.is_symlink() or not path.is_file():
        return {}, {
            "status": "invalid",
            "reason": "not-regular",
            "path": str(path),
        }
    try:
        payload = loads_object(read_bytes(
            path, max_bytes=MAX_META_SNAPSHOT_BYTES, label="metadata"
        ))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("metadata snapshot is unreadable or malformed", exc_info=exc)
        return {}, {
            "status": "invalid",
            "reason": "unreadable-or-malformed",
            "path": str(path),
        }
    except ValueError as exc:
        log.warning("metadata snapshot is malformed", exc_info=exc)
        return {}, {"status": "invalid", "reason": "malformed", "path": str(path)}
    return payload, {"status": "ok", "path": str(path)}
