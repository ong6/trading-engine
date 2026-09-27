"""Monotone logical replay phases with terminal-coverage checkpoints."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Mapping, Sequence

from engine.lib.provenance import canonical_sha256
from farm.replay.store import ReplayStoreError, append_exact, load_record

PHASES = ("input", "open", "close", "label", "postmortem")
TERMINAL_STATUSES = frozenset({"completed", "unavailable", "failed", "not_applicable"})


def record_phase_checkpoint(
    con,
    *,
    cohort_id: str,
    policy_id: str,
    session: date,
    phase: str,
    logical_at: datetime,
    terminal_rows: Sequence[Mapping],
    expected_rows: int,
    recorded_at: datetime,
) -> str:
    if phase not in PHASES or expected_rows < 0 or len(terminal_rows) != expected_rows:
        raise ReplayStoreError("phase_terminal_coverage_incomplete")
    if any(row.get("status") not in TERMINAL_STATUSES for row in terminal_rows):
        raise ReplayStoreError("phase_row_not_terminal")
    if logical_at.tzinfo is None:
        raise ReplayStoreError("logical_clock_must_be_timezone_aware")
    logical_at_iso = logical_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    phase_index = PHASES.index(phase)
    record_type = f"clock:{cohort_id}:{policy_id}:{session.isoformat()}"
    previous_sha256 = None
    if phase_index:
        previous = load_record(con, record_type, PHASES[phase_index - 1])
        if previous is None:
            raise ReplayStoreError("previous_phase_missing")
        previous_sha256 = previous["payload_sha256"]
        if logical_at_iso <= previous["payload"]["logical_at"]:
            raise ReplayStoreError("logical_clock_not_monotone")
    payload = {
        "schema_version": 1,
        "cohort_id": cohort_id,
        "policy_id": policy_id,
        "session": session.isoformat(),
        "phase": phase,
        "logical_at": logical_at_iso,
        "expected_rows": expected_rows,
        "terminal_rows_sha256": canonical_sha256(list(terminal_rows)),
        "previous_checkpoint_sha256": previous_sha256,
    }
    return append_exact(
        con,
        record_type=record_type,
        record_key=phase,
        payload=payload,
        recorded_at=recorded_at,
    )
