"""Chronological W4 replay orchestration over one isolated policy store."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from engine import p15_event_sources
from engine.lib import db
from server import p15_scoring_store
from sim import nyse, p15_books
from sim.schema import init_sim_schema

ET = ZoneInfo("America/New_York")
ANCHOR_ID = "p16_replay_checkpoint"


class ReplayRunnerError(ValueError):
    """Replay chronology or private book state differs from its contract."""


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
