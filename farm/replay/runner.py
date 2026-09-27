"""Chronological W4 replay orchestration over one isolated policy store."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from engine import p15_event_sources
from engine.lib import db
from farm.replay.asof import rewrite_known_split_adjustments, rewrite_private_prices
from farm.replay.clock import PHASES, completed_phases, init_clock_schema, record_phase_checkpoint
from farm.replay.registration import SPLIT_KNOWLEDGE_PRIMARY
from farm.replay.store import open_store
from server import p15_scoring_store
from sim import nyse, p15_books
from sim.schema import init_sim_schema

ET = ZoneInfo("America/New_York")
ANCHOR_ID = "p16_replay_checkpoint"


class ReplayRunnerError(ValueError):
    """Replay chronology or private book state differs from its contract."""


PhaseExecutor = Callable[[str, date, datetime], Sequence[Mapping]]
PhaseApplier = Callable[[object, str, date, datetime, Sequence[Mapping]], None]


def _completed(_phase: str, _session: date, _logical_at: datetime) -> Sequence[Mapping]:
    return ({"status": "completed"},)


@dataclass(frozen=True)
class ReplaySessionStore:
    """Everything needed to open one explicit private replay policy store."""

    path: Path
    research_root: Path
    live_db_path: Path
    cohort_id: str
    policy_id: str
    checkpoint: date
    initialized_at: datetime
    execute_phase: PhaseExecutor = _completed
    apply_phase: PhaseApplier | None = None
    run_books: bool = True
    reconstructed_bars: Sequence[Mapping] = ()
    actions: Sequence[Mapping] = ()
    split_knowledge_policy: str = SPLIT_KNOWLEDGE_PRIMARY


def session_phases(session: date) -> dict[str, datetime]:
    """Return registered logical clocks, including the actual early close."""
    if not nyse.is_session(session):
        raise ReplayRunnerError("replay_date_not_exchange_session")
    local_close = datetime.combine(session, p15_event_sources.session_close(session), ET)
    score = datetime.combine(session + timedelta(days=1), time(2), timezone.utc)
    return {
        "preopen": datetime.combine(session, time(9, 5), ET).astimezone(timezone.utc),
        "open": datetime.combine(session, time(9, 30), ET).astimezone(timezone.utc),
        "close": local_close.astimezone(timezone.utc),
        "close_visible": (local_close + timedelta(minutes=15)).astimezone(timezone.utc),
        "score": score,
        "postmortem": score,
    }


def _phase_clocks(session: date) -> dict[str, datetime]:
    clocks = session_phases(session)
    return {
        "PREOPEN": clocks["preopen"],
        "OPEN": clocks["open"],
        "CLOSE": clocks["close_visible"],
        "SCORE": clocks["score"],
        "POSTMORTEM": clocks["score"] + timedelta(microseconds=1),
    }


def _anchor(con, checkpoint: date) -> None:
    row = con.execute(
        "SELECT strategy,config,created,active,cash,initial_cash,execution_profile "
        "FROM portfolios WHERE id=?",
        [ANCHOR_ID],
    ).fetchone()
    expected = ("replay_anchor", "{}", checkpoint, True, 0.0, 0.0, "baseline_v1")
    if row is None:
        con.execute(
            "INSERT INTO portfolios "
            "(id,name,strategy,config,created,active,cash,initial_cash,execution_profile) "
            "VALUES (?,?,?,'{}',?,TRUE,0,0,'baseline_v1')",
            [ANCHOR_ID, ANCHOR_ID, "replay_anchor", checkpoint],
        )
        con.execute(
            "INSERT INTO sim_equity (portfolio_id,date,equity,cash,n_positions) "
            "VALUES (?,?,0,0,0)",
            [ANCHOR_ID, checkpoint],
        )
    elif row != expected:
        raise ReplayRunnerError("replay_checkpoint_anchor_differs")
    equity = con.execute(
        "SELECT equity,cash,n_positions FROM sim_equity WHERE portfolio_id=? AND date=?",
        [ANCHOR_ID, checkpoint],
    ).fetchone()
    if equity != (0.0, 0.0, 0):
        raise ReplayRunnerError("replay_checkpoint_anchor_missing")


def bootstrap_books(con, *, checkpoint: date, initialized_at: datetime) -> dict:
    """Initialize and activate pinned P15 books once in the private database."""
    if initialized_at.tzinfo is None:
        raise ReplayRunnerError("naive_replay_clock")
    db.init_schema(con)
    db.init_actions_schema(con)
    init_sim_schema(con)
    p15_scoring_store.init_schema(con)
    p15_books.init_schema(con)
    _anchor(con, checkpoint)
    state = p15_books.activation_state(con)
    if state == "absent":
        p15_books.initialize_books(con, checkpoint, initialized_at=initialized_at)
        state = "inactive"
    if state == "inactive":
        p15_books.activate_books(con, checkpoint)
        state = "active"
    if state != "active":
        raise ReplayRunnerError("replay_books_not_active")
    book_checkpoints = con.execute(
        "SELECT portfolio_id,MIN(date),MAX(date) FROM sim_equity "
        "WHERE portfolio_id IN (?,?,?) GROUP BY portfolio_id ORDER BY portfolio_id",
        list(p15_books.BOOK_IDS),
    ).fetchall()
    if len(book_checkpoints) != len(p15_books.BOOK_IDS) or any(
        first != checkpoint for _book, first, _last in book_checkpoints
    ):
        raise ReplayRunnerError("replay_book_checkpoint_differs")
    return {"status": "active", "checkpoint": checkpoint.isoformat(), "books": 3}


def run_book_session(con, *, market_date: date, observed_at: datetime) -> dict:
    """Run open fills then the pinned close/queue window; retries are idempotent."""
    clocks = session_phases(market_date)
    if observed_at.tzinfo is None or observed_at.astimezone(timezone.utc) < clocks["score"]:
        raise ReplayRunnerError("replay_session_before_score_clock")
    opened = p15_books.process_pending(con, market_date)
    completed = p15_books.run_window(con, market_date, observed_at=observed_at)
    if completed.get("status") != "completed":
        raise ReplayRunnerError("p15_book_window_incomplete")
    return {"status": "completed", "phases": clocks, "open": opened, "book": completed}


def book_snapshot(con) -> dict:
    """Expose only replay-book economics; the compatibility anchor is excluded."""
    books = {}
    for book_id in p15_books.BOOK_IDS:
        cash, initial_cash = con.execute(
            "SELECT cash,initial_cash FROM portfolios WHERE id=?", [book_id]
        ).fetchone()
        positions = con.execute(
            "SELECT ticker,qty,avg_cost FROM sim_positions WHERE portfolio_id=? ORDER BY ticker",
            [book_id],
        ).fetchall()
        books[book_id] = {
            "cash": cash,
            "initial_cash": initial_cash,
            "positions": [tuple(row) for row in positions],
        }
    return books


def run_session(store: ReplaySessionStore, session: date) -> dict:
    """Run one complete session, resuming only after its durable last phase.

    The caller supplies paths and pure/provider callbacks, never a connection.  Each
    callback runs while the DuckDB writer is closed; only its deterministic result is
    applied after the runner reopens the explicit ``kind='replay'`` store.
    """
    if not isinstance(store, ReplaySessionStore):
        raise ReplayRunnerError("explicit_replay_store_required")
    if not nyse.is_session(session) or session <= store.checkpoint:
        raise ReplayRunnerError("invalid_replay_session")
    clocks = _phase_clocks(session)
    with open_store(
        store.path, research_root=store.research_root,
        live_db_path=store.live_db_path, kind="replay",
    ) as con:
        bootstrap_books(con, checkpoint=store.checkpoint, initialized_at=store.initialized_at)
        init_clock_schema(con)
        done = completed_phases(
            con, cohort_id=store.cohort_id, policy_id=store.policy_id, session=session,
        )
    results: dict[str, list[dict]] = {}
    for phase in PHASES[len(done):]:
        logical_at = clocks[phase]
        terminal_rows = [dict(row) for row in store.execute_phase(phase, session, logical_at)]
        if not terminal_rows:
            terminal_rows = [{"status": "not_applicable"}]
        with open_store(
            store.path, research_root=store.research_root,
            live_db_path=store.live_db_path, kind="replay",
        ) as con:
            current = completed_phases(
                con, cohort_id=store.cohort_id, policy_id=store.policy_id, session=session,
            )
            if len(current) != PHASES.index(phase):
                raise ReplayRunnerError("replay_clock_changed_during_phase")
            if store.reconstructed_bars:
                with db.transaction(con):
                    rewrite_private_prices(
                        con, store.reconstructed_bars, store.actions,
                        as_of=clocks["CLOSE"],
                        knowledge_policy=store.split_knowledge_policy,
                    )
                    if phase == "OPEN":
                        rewrite_known_split_adjustments(
                            con, store.actions, known_at=logical_at,
                            knowledge_policy=store.split_knowledge_policy,
                        )
                        p15_books._rebuild_p15_state(con)
            elif store.run_books:
                raise ReplayRunnerError("replay_price_archive_missing")
            if store.apply_phase is not None:
                store.apply_phase(con, phase, session, logical_at, terminal_rows)
            if store.run_books and phase == "OPEN":
                p15_books.process_pending(con, session)
            if store.run_books and phase == "SCORE":
                outcome = p15_books.run_window(con, session, observed_at=logical_at)
                if outcome.get("status") != "completed":
                    raise ReplayRunnerError("p15_book_window_incomplete")
            record_phase_checkpoint(
                con, cohort_id=store.cohort_id, policy_id=store.policy_id,
                session=session, phase=phase, logical_at=logical_at,
                terminal_rows=terminal_rows, expected_rows=len(terminal_rows),
                recorded_at=logical_at,
            )
        results[phase] = terminal_rows
    with open_store(
        store.path, research_root=store.research_root,
        live_db_path=store.live_db_path, kind="replay", read_only=True,
    ) as con:
        complete = completed_phases(
            con, cohort_id=store.cohort_id, policy_id=store.policy_id, session=session,
        )
    return {
        "status": "completed" if complete == PHASES else "partial",
        "session": session.isoformat(),
        "completed_phases": list(complete),
        "executed": results,
    }
