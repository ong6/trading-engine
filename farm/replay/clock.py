"""Monotone logical replay phases with terminal-coverage checkpoints."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Mapping, Sequence

from engine.lib.provenance import canonical_sha256
from farm.replay.store import ReplayStoreError, append_exact, load_record

PHASES = ("PREOPEN", "OPEN", "CLOSE", "SCORE", "POSTMORTEM")
TERMINAL_STATUSES = frozenset({"completed", "unavailable", "failed", "not_applicable"})


def init_clock_schema(con) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS replay_clock (
            cohort_id VARCHAR NOT NULL,
            policy_id VARCHAR NOT NULL,
            session DATE NOT NULL,
            phase VARCHAR NOT NULL,
            phase_index INTEGER NOT NULL,
            logical_at VARCHAR NOT NULL,
            checkpoint_sha256 VARCHAR NOT NULL,
            PRIMARY KEY(cohort_id, policy_id, session, phase))"""
    )


def completed_phases(con, *, cohort_id: str, policy_id: str, session: date) -> tuple[str, ...]:
    rows = con.execute(
        "SELECT phase,phase_index FROM replay_clock WHERE cohort_id=? AND policy_id=? "
        "AND session=? ORDER BY phase_index",
        [cohort_id, policy_id, session],
    ).fetchall()
    phases = tuple(row[0] for row in rows)
    if phases != PHASES[: len(phases)] or any(
        index != expected for expected, (_phase, index) in enumerate(rows)
    ):
        raise ReplayStoreError("replay_clock_not_contiguous")
    return phases


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
    init_clock_schema(con)
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
        previous_at = datetime.fromisoformat(
            previous["payload"]["logical_at"].replace("Z", "+00:00")
        )
        if logical_at.astimezone(timezone.utc) <= previous_at:
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
    checkpoint_sha256 = append_exact(
        con,
        record_type=record_type,
        record_key=phase,
        payload=payload,
        recorded_at=recorded_at,
    )
    existing = con.execute(
        "SELECT phase_index,logical_at,checkpoint_sha256 FROM replay_clock "
        "WHERE cohort_id=? AND policy_id=? AND session=? AND phase=?",
        [cohort_id, policy_id, session, phase],
    ).fetchone()
    expected = (phase_index, logical_at_iso, checkpoint_sha256)
    if existing is None:
        con.execute(
            "INSERT INTO replay_clock VALUES (?,?,?,?,?,?,?)",
            [cohort_id, policy_id, session, phase, phase_index, logical_at_iso,
             checkpoint_sha256],
        )
    elif existing != expected:
        raise ReplayStoreError("replay_clock_conflict")
    return checkpoint_sha256
