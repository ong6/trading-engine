"""Chronological W4 replay orchestration over one isolated policy store."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from functools import cached_property
from pathlib import Path
from typing import Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from engine import p15_event_sources
from engine.lib import db
from farm.replay import entities
from farm.replay.asof import (
    build_price_index,
    rewrite_known_split_adjustments,
    rewrite_private_prices,
)
from farm.replay.clock import PHASES, completed_phases, init_clock_schema, record_phase_checkpoint
from farm.replay.executor import (
    apply_preopen,
    apply_score,
    execute_preopen,
    execute_score,
    init_executor_schema,
    prepare_preopen,
    prepare_score,
    produce_labels,
)
from farm.replay.lockbox import LockboxLedger, dispatch_lockbox, evaluation_tag
from farm.replay.notes import (
    NotesFilterSpec,
    init_notes_schema,
    record_notes_output,
    visible_mature_labels,
    visible_notes,
)
from farm.replay.registration import SPLIT_KNOWLEDGE_PRIMARY
from farm.replay.store import open_store
from farm.replay.universe import build_session_universe
from server import agent_model_client, p15_scoring_store
from sim import nyse, p15_books
from sim.schema import init_sim_schema

ET = ZoneInfo("America/New_York")
ANCHOR_ID = "p16_replay_checkpoint"


class ReplayRunnerError(ValueError):
    """Replay chronology or private book state differs from its contract."""


PhaseExecutor = Callable[[str, date, datetime, Mapping], Sequence[Mapping]]
PhaseApplier = Callable[[object, str, date, datetime, Sequence[Mapping]], None]
PostmortemGenerator = Callable[[Mapping], Mapping]


def _completed(
    _phase: str, _session: date, _logical_at: datetime, _context: Mapping
) -> Sequence[Mapping]:
    return ({"status": "completed"},)


@dataclass(frozen=True)
class ReplayLockboxRun:
    ledger: LockboxLedger
    begin: Mapping
    trial_id: str
    execution_id: str
    registration_sha256: str
    sessions: Sequence[date]


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
    apply_phase: PhaseApplier | None = None
    run_books: bool = True
    reconstructed_bars: Sequence[Mapping] = ()
    actions: Sequence[Mapping] = ()
    split_knowledge_policy: str = SPLIT_KNOWLEDGE_PRIMARY
    notes_filter_spec: NotesFilterSpec | None = None
    news_rows: Sequence[Mapping] = ()
    # As-of name table; news rows without a ticker are mapped through it.
    name_table: Sequence[Mapping] = ()
    fact_rows: Sequence[Mapping] = ()
    score_generate: Callable[[dict], agent_model_client.ConnectorResult] = (
        agent_model_client.generate_p15_scoring_json
    )
    preopen_generate: Callable[[dict], agent_model_client.ConnectorResult] = (
        agent_model_client.generate_p15_preopen_json
    )
    postmortem_generate: PostmortemGenerator | None = None
    sample_count: int = 3
    lockbox: ReplayLockboxRun | None = None
    securities: Mapping[str, Mapping] = field(default_factory=dict)
    # Test seam only: replaces the in-tree executors, labels and SCORE/PREOPEN
    # application.  Production callers never set it.
    _test_execute_phase: PhaseExecutor | None = None

    def __post_init__(self) -> None:
        if self._test_execute_phase is not None and "PYTEST_CURRENT_TEST" not in os.environ:
            raise ValueError("test_only_execute_phase")

    @cached_property
    def price_index(self):
        """Bars validated and indexed once per store object, reused by every phase."""
        return build_price_index(self.reconstructed_bars, self.actions)

    @cached_property
    def ticker_news_rows(self) -> list[Mapping]:
        """News rows keyed by ticker; untickered rows go through the entity mapper."""
        tickered = [row for row in self.news_rows if row.get("ticker")]
        untickered = [row for row in self.news_rows if not row.get("ticker")]
        return tickered + entities.news_rows_by_ticker(untickered, self.name_table)


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
    init_executor_schema(con)
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


def _lockbox_tag(store: ReplaySessionStore, logical_at: datetime) -> str:
    if store.lockbox is None:
        return "post_lockbox_exploratory"
    lockbox = store.lockbox
    return evaluation_tag(
        lockbox.ledger,
        experiment_id=str(lockbox.begin["experiment_id"]),
        cohort_id=str(lockbox.begin["cohort_id"]),
        trial_id=lockbox.trial_id,
        execution_id=lockbox.execution_id,
        registration_sha256=lockbox.registration_sha256,
        sessions=lockbox.sessions,
        # The logical clock keeps reruns reproducible; the ledger refuses an
        # evaluation before its own commit, so clamp to the marker time.
        evaluated_at=max(logical_at, lockbox.begin["committed_at"]),
    ).tag


def _prepare_default_phase(con, store: ReplaySessionStore, phase: str, session: date,
                           logical_at: datetime, context: Mapping) -> Mapping | None:
    if phase == "SCORE":
        return prepare_score(
            con, cohort_id=store.cohort_id, policy_id=store.policy_id,
            session=session, cutoff=logical_at, news_rows=store.ticker_news_rows,
            fact_rows=store.fact_rows, sample_count=store.sample_count,
        )
    if phase == "PREOPEN":
        return prepare_preopen(
            con, session=session, cutoff=logical_at, news_rows=store.ticker_news_rows,
            fact_rows=store.fact_rows,
        )
    if phase == "POSTMORTEM" and store.postmortem_generate is not None:
        return {"kind": "postmortem", "payload": {
            "schema_version": 1, "session": session.isoformat(),
            "written_at": logical_at.isoformat(),
            "mature_labels": context["mature_labels"], "notes": context["notes"],
        }}
    return None


def _execute_default_phase(store: ReplaySessionStore, phase: str,
                           plan: Mapping | None) -> Sequence[Mapping]:
    if phase == "SCORE":
        return (execute_score(plan, store.score_generate),)
    if phase == "PREOPEN":
        return (execute_preopen(plan, store.preopen_generate),)
    if phase == "POSTMORTEM" and plan is not None:
        output = store.postmortem_generate(plan["payload"])
        if not isinstance(output, Mapping):
            raise ReplayRunnerError("invalid_postmortem_provider_output")
        return ({"status": "completed", "kind": "postmortem", **dict(output)},)
    return _completed(phase, date.min, datetime.min.replace(tzinfo=timezone.utc), {})


def _security_ids(rows: Sequence[Mapping]) -> dict[str, str]:
    return {
        str(row.get("ticker")): str(row.get("security_id"))
        for row in rows if row.get("ticker") and row.get("security_id")
    }


def _run_session(store: ReplaySessionStore, session: date) -> dict:
    """Inner session body; lockbox dispatch wraps this function exactly once."""
    clocks = _phase_clocks(session)
    with open_store(
        store.path, research_root=store.research_root,
        live_db_path=store.live_db_path, kind="replay",
    ) as con:
        bootstrap_books(con, checkpoint=store.checkpoint, initialized_at=store.initialized_at)
        init_clock_schema(con)
        init_notes_schema(con)
        done = completed_phases(
            con, cohort_id=store.cohort_id, policy_id=store.policy_id, session=session,
        )
    results: dict[str, list[dict]] = {}
    for phase in PHASES[len(done):]:
        logical_at = clocks[phase]
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
                        as_of=logical_at, phase=phase,
                        knowledge_policy=store.split_knowledge_policy,
                        index=store.price_index,
                    )
                    if phase == "SCORE":
                        # Production screens after the close and before scoring.
                        build_session_universe(con, session, securities=store.securities)
                    if phase == "OPEN":
                        rewrite_known_split_adjustments(
                            con, store.actions, known_at=logical_at,
                            knowledge_policy=store.split_knowledge_policy,
                        )
                        p15_books._rebuild_p15_state(con)
            elif store.run_books:
                raise ReplayRunnerError("replay_price_archive_missing")
        tag = _lockbox_tag(store, logical_at)
        with open_store(
            store.path, research_root=store.research_root,
            live_db_path=store.live_db_path, kind="replay", read_only=True,
        ) as con:
            phase_context = {
                "mature_labels": visible_mature_labels(con, session=session, cutoff=logical_at),
                "notes": visible_notes(con, session=session, cutoff=logical_at),
                "evaluation_tag": tag,
            }
            plan = None if store._test_execute_phase is not None else _prepare_default_phase(
                con, store, phase, session, logical_at, phase_context
            )
        executed = (
            store._test_execute_phase(phase, session, logical_at, phase_context)
            if store._test_execute_phase is not None
            else _execute_default_phase(store, phase, plan)
        )
        terminal_rows = [{**dict(row), "evaluation_tag": tag} for row in executed]
        if not terminal_rows:
            terminal_rows = [{"status": "not_applicable", "evaluation_tag": tag}]
        with open_store(
            store.path, research_root=store.research_root,
            live_db_path=store.live_db_path, kind="replay",
        ) as con:
            current = completed_phases(
                con, cohort_id=store.cohort_id, policy_id=store.policy_id, session=session,
            )
            if len(current) != PHASES.index(phase):
                raise ReplayRunnerError("replay_clock_changed_during_phase")
            if store._test_execute_phase is None and phase == "PREOPEN":
                apply_preopen(con, terminal_rows[0], session=session, logical_at=logical_at)
            if store._test_execute_phase is None and phase == "CLOSE":
                terminal_rows[0]["labels_written"] = produce_labels(
                    con, session=session, visible_at=logical_at,
                    reconstructed_bars=store.reconstructed_bars, actions=store.actions,
                    knowledge_policy=store.split_knowledge_policy, price_index=store.price_index,
                )
            if store._test_execute_phase is None and phase == "SCORE":
                terminal_rows[0]["decisions_written"] = apply_score(
                    con, terminal_rows[0], cohort_id=store.cohort_id,
                    policy_id=store.policy_id, session=session, logical_at=logical_at,
                    security_ids=_security_ids(store.reconstructed_bars),
                )
            if store.apply_phase is not None:
                store.apply_phase(con, phase, session, logical_at, terminal_rows)
            if phase == "POSTMORTEM" and store.notes_filter_spec is not None:
                record_notes_output(
                    con, session=session, written_at=logical_at,
                    postmortems=[item for row in terminal_rows for item in row.get("postmortems", ())],
                    lessons=[item for row in terminal_rows for item in row.get("lessons", ())],
                    filter_spec=store.notes_filter_spec,
                )
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
        "session": session.isoformat(), "evaluation_tag": _lockbox_tag(store, clocks["POSTMORTEM"]),
        "completed_phases": list(complete), "executed": results,
    }


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
    if store.lockbox is not None and session in set(store.lockbox.sessions):
        begin = dict(store.lockbox.begin)
        if not store.lockbox.ledger.dispatch_completed(
            str(begin["experiment_id"]), str(begin["cohort_id"])
        ):
            return dispatch_lockbox(
                store.lockbox.ledger, begin=begin,
                dispatch=lambda _marker: _run_session(store, session),
            )
    return _run_session(store, session)
