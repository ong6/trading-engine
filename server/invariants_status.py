"""Project the snapshot-invariant result (``tools/check_invariants.py``) for ``/meta``.

The hourly ops digest runs the check in shadow mode whenever the published snapshot's
sha256 changes and leaves the result in ``logs/ops/invariants.json``; ``/meta`` only reads
that file. The section is ``stale`` after 26 hours or when the result's snapshot is no longer
the published one. It names invariants, violation classes and subjects, never paths or
values. Standard library only.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

RESULT_STALE_AFTER_MINUTES = 26 * 60
PUBLIC_REGRESSION_LIMIT = 20
SUBJECT_MAX_CHARS = 120
RESULT_STATUSES = frozenset({"pass", "regression", "error"})
PUBLIC_STATUSES = RESULT_STATUSES | {"stale", "absent", "invalid"}
# tools/invariants registry names, in report order (tests/test_meta_projection.py pins both).
INVARIANT_NAMES = (
    "ohlc_geometry", "one_split_basis_per_ticker", "split_recorded_vs_restated",
    "fee_row_per_fill", "equity_per_active_book", "closeouts_once", "publication_order",
    "preopen_not_voided", "experiment_results_finite", "walkforward_results_finite",
)
_CLASS = re.compile(r"[a-z][a-z0-9_]{0,63}")


def _subject(value: object) -> str:
    text = "".join(char for char in str(value) if char.isprintable())
    return text.replace("/", ":")[:SUBJECT_MAX_CHARS]


def invalid_status() -> dict:
    return {"status": "invalid", "mode": "shadow", "checked_at": None, "age_minutes": None,
            "stale_after_minutes": RESULT_STALE_AFTER_MINUTES, "snapshot_as_of": None,
            "snapshot_current": None, "regression_count": 0, "baselined_count": 0,
            "invariants": [], "regressions": [], "truncated": False}


def public_status(path: Path, *, current_sha256: str | None,
                  now: datetime | None = None) -> dict:
    """The newest shadow result, checked against the currently published snapshot."""
    now = now or datetime.now(UTC)
    base = {**invalid_status(), "status": "absent"}
    try:
        result = json.loads(path.read_text())
    except FileNotFoundError:
        return base
    except (OSError, ValueError):
        return invalid_status()
    try:
        checked = datetime.fromisoformat(result["checked_at"]).astimezone(UTC)
        status = result["status"]
        snapshot = result.get("snapshot") or {}
        items = result.get("invariants") or {}
        if status not in RESULT_STATUSES or not set(items) <= set(INVARIANT_NAMES) or (
                status != "error" and not snapshot):
            raise ValueError("unknown status, invariant or missing snapshot")
        invariants, regressions, baselined = [], [], 0
        for name in INVARIANT_NAMES:
            if name not in items:
                continue
            item = items[name]
            if item["status"] not in RESULT_STATUSES:
                raise ValueError("unknown invariant status")
            invariants.append({"name": name, "status": item["status"]})
            baselined += int(item["baselined_count"])
            for found in item["regressions"]:
                if not _CLASS.fullmatch(found["class"]):
                    raise ValueError("unexpected class")
                regressions.append({"invariant": name, "class": found["class"],
                                    "subject": _subject(found["subject"])})
        count = int(result.get("regression_count", len(regressions)))
        as_of = snapshot.get("as_of")
        if as_of is not None:
            as_of = datetime.fromisoformat(as_of).astimezone(UTC).isoformat(timespec="seconds")
    except (KeyError, TypeError, ValueError, AttributeError):
        return invalid_status()
    age = max(0, int((now - checked).total_seconds() // 60))
    current = bool(snapshot) and current_sha256 is not None \
        and snapshot.get("sha256") == current_sha256
    stale = age > RESULT_STALE_AFTER_MINUTES or (bool(snapshot) and not current)
    count = max(count, len(regressions))
    return {
        "status": "stale" if stale else status,
        "mode": "shadow",
        "checked_at": checked.isoformat(timespec="seconds"),
        "age_minutes": age,
        "stale_after_minutes": RESULT_STALE_AFTER_MINUTES,
        "snapshot_as_of": as_of,
        "snapshot_current": current if snapshot else None,
        "regression_count": count,
        "baselined_count": baselined,
        "invariants": invariants,
        "regressions": regressions[:PUBLIC_REGRESSION_LIMIT],
        "truncated": count > min(len(regressions), PUBLIC_REGRESSION_LIMIT),
    }
