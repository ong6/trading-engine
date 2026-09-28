"""Bounded quote-window collector for inert P16 execution measurement."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Callable

from engine import p16_fill_capture

Fetch = Callable[[str, int, datetime], dict | list[dict]]


def _receipt(value: dict) -> str:
    retained = value.get("receipt_sha256")
    if isinstance(retained, str) and len(retained) == 64:
        return retained
    serializable = {key: item.isoformat() if isinstance(item, datetime) else item
                    for key, item in value.items()}
    return hashlib.sha256(json.dumps(
        serializable, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def collect_window(
    session_date: date, security_ids: list[str], window_index: int, *,
    observed_at: datetime, fetch: Fetch, source: str, source_version: str,
) -> list[dict]:
    """Keep the first valid quote in the fixed window and retain failures in-place."""
    results = []
    for security_id in security_ids:
        try:
            raw = fetch(security_id, window_index, observed_at)
            snapshots = raw if isinstance(raw, list) else [raw]
            normalized = [p16_fill_capture.normalize_quote(
                session_date, window_index, {**item, "source": source}) for item in snapshots]
            quote = next((item for item in normalized if item["status"] == "valid"),
                         normalized[0])
            receipt = _receipt(snapshots[normalized.index(quote)])
            reason = None if quote["status"] == "valid" else quote["status"]
        except (IndexError, OSError, RuntimeError, ValueError, TypeError):
            quote, reason = {"status": "capture_failed", "window_index": window_index}, \
                "quote_capture_failed"
            receipt = hashlib.sha256(
                f"{session_date}|{security_id}|{window_index}|{observed_at.isoformat()}|failed"
                .encode()).hexdigest()
        payload = {"source": source, "source_version": source_version,
                   "status": quote["status"], "capture_kind": "quote",
                   "window_index": window_index, "quote": quote}
        results.append({"security_id": security_id, "receipt_sha256": receipt,
                        "payload": payload, "reason": reason})
    return results
