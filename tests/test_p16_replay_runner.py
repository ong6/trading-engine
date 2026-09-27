"""Real pinned-P15 integration for isolated W4 replay books."""
import json
from datetime import date, datetime, timezone

import duckdb
import pytest

from farm.replay.notes import freeze_filter_spec
from farm.replay.runner import (
    ANCHOR_ID,
    ReplaySessionStore,
    book_snapshot,
    bootstrap_books,
    run_book_session,
    run_session,
    session_phases,
)
from sim import p15_books
from tests.conftest import SESSIONS, insert_bars


def _seed_decision(con, market_date):
    decision = {
        "ticker": "AAA",
        "tradeable": True,
        "stratum": "mover",
        "close": 100.0,
        "atr_14": 2.0,
        "baseline_rank": 1,
        "scoring_status": "available",
        "decision": "buy_candidate",
        "action": "buy",
        "p_outperform_5": 0.7,
        "expected_excess_bp_5": 100,
        "evidence_ids": ["a" * 64],
    }
    con.execute(
        "CREATE TABLE IF NOT EXISTS agent_evaluation_traces "
        "(id BIGINT PRIMARY KEY,policy_id VARCHAR,market_date DATE,"
        "terminal_status VARCHAR,completed_at TIMESTAMP)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS agent_evaluation_decisions "
        "(id BIGINT PRIMARY KEY,trace_id BIGINT,ticker VARCHAR,decision_payload VARCHAR)"
    )
    con.execute(
        "INSERT INTO agent_evaluation_traces VALUES (1,'p15-scoring-v1',?,'completed',?)",
        [market_date, datetime.combine(market_date, datetime.min.time())],
    )
    con.execute(
        "INSERT INTO agent_evaluation_decisions VALUES (1,1,'AAA',?)",
        [json.dumps(decision)],
    )


def test_session_phases_use_actual_early_close_and_next_calendar_score():
    early = session_phases(date(2024, 11, 29))
    assert early["close"].isoformat() == "2024-11-29T18:00:00+00:00"
    assert early["close_visible"].isoformat() == "2024-11-29T18:15:00+00:00"
    assert early["score"].isoformat() == "2024-11-30T02:00:00+00:00"


def test_book_session_refuses_a_clock_before_scoring_cutoff():
    con = duckdb.connect(":memory:")
    checkpoint, signal = SESSIONS[28:30]
    bootstrap_books(
        con,
        checkpoint=checkpoint,
        initialized_at=datetime(2026, 9, 27, tzinfo=timezone.utc),
    )
    with pytest.raises(ValueError, match="before_score"):
        run_book_session(
            con, market_date=signal, observed_at=session_phases(signal)["close"]
        )


def test_private_bootstrap_fill_pnl_retry_and_anchor_isolation():
    con = duckdb.connect(":memory:")
    checkpoint, signal, fill = SESSIONS[28:31]
    initialized = datetime(2026, 9, 27, tzinfo=timezone.utc)
    assert bootstrap_books(
        con, checkpoint=checkpoint, initialized_at=initialized
    ) == {"status": "active", "checkpoint": checkpoint.isoformat(), "books": 3}
    assert bootstrap_books(
        con, checkpoint=checkpoint, initialized_at=initialized
    )["status"] == "active"
    for ticker in ("SPY", "AAA"):
        insert_bars(con, ticker, SESSIONS[:31], open_=100, close=100, high=101, low=99)
    _seed_decision(con, signal)
    run_book_session(
        con, market_date=signal, observed_at=session_phases(signal)["score"]
    )
    first = run_book_session(
        con, market_date=fill, observed_at=session_phases(fill)["score"]
    )
    before = (
        con.execute("SELECT COUNT(*) FROM sim_fills").fetchone()[0],
        con.execute("SELECT COUNT(*) FROM p15_book_windows").fetchone()[0],
        book_snapshot(con),
    )
    retry = run_book_session(
        con, market_date=fill, observed_at=session_phases(fill)["score"]
    )
    after = (
        con.execute("SELECT COUNT(*) FROM sim_fills").fetchone()[0],
        con.execute("SELECT COUNT(*) FROM p15_book_windows").fetchone()[0],
        book_snapshot(con),
    )
    assert first["status"] == retry["status"] == "completed"
    assert before == after and before[0] == 9
    assert all(state["cash"] < 10_000 for state in before[2].values())
    equity = con.execute(
        "SELECT equity FROM sim_equity WHERE portfolio_id IN (?,?,?) AND date=?",
        [*p15_books.BOOK_IDS, fill],
    ).fetchall()
    assert len(equity) == 3 and all(9_900 < row[0] < 10_000 for row in equity)
    assert con.execute(
        "SELECT COUNT(*) FROM sim_orders WHERE portfolio_id=?", [ANCHOR_ID]
    ).fetchone() == (0,)
    assert con.execute(
        "SELECT equity,cash,n_positions FROM sim_equity WHERE portfolio_id=?",
        [ANCHOR_ID],
    ).fetchall() == [(0.0, 0.0, 0)]
    assert set(before[2]) == set(p15_books.BOOK_IDS)


def test_run_session_owns_store_runs_exact_phase_order_and_resumes(tmp_path):
    root = (tmp_path / "research").resolve()
    root.mkdir()
    live = (tmp_path / "live.duckdb").resolve()
    live.touch()
    target = root / "replay.duckdb"
    checkpoint, session = SESSIONS[28:30]
    calls = []

    def execute(phase, market_date, logical_at, context):
        # The callback can open the file, proving the runner released its writer.
        with duckdb.connect(str(target), read_only=True) as reader:
            assert reader.execute("SELECT store_kind FROM w4_store_identity").fetchone() == (
                "replay",
            )
        calls.append((phase, market_date, logical_at))
        assert context["evaluation_tag"] == "post_lockbox_exploratory"
        return [{"status": "completed", "phase": phase}]

    store = ReplaySessionStore(
        path=target,
        research_root=root,
        live_db_path=live,
        cohort_id="fixture-cohort",
        policy_id="fixture-policy",
        checkpoint=checkpoint,
        initialized_at=datetime(2026, 9, 27, tzinfo=timezone.utc),
        execute_phase=execute,
        run_books=False,
    )
    first = run_session(store, session)
    second = run_session(store, session)
    assert first["status"] == second["status"] == "completed"
    assert first["completed_phases"] == [
        "PREOPEN", "OPEN", "CLOSE", "SCORE", "POSTMORTEM"
    ]
    assert second["executed"] == {}
    assert [row[0] for row in calls] == first["completed_phases"]
    with duckdb.connect(str(target), read_only=True) as con:
        assert con.execute(
            "SELECT phase FROM replay_clock ORDER BY phase_index"
        ).fetchall() == [(phase,) for phase in first["completed_phases"]]


def test_run_session_filters_notes_and_exposes_them_only_to_later_sessions(tmp_path):
    root = (tmp_path / "research").resolve()
    root.mkdir()
    live = (tmp_path / "live.duckdb").resolve()
    live.touch()
    seen = []
    first, second = SESSIONS[29:31]

    def execute(phase, market_date, _logical_at, context):
        if phase == "SCORE":
            seen.append((market_date, context["notes"], context["evaluation_tag"]))
        result = {"status": "completed"}
        if phase == "POSTMORTEM" and market_date == first:
            result["lessons"] = [
                {"rule": "Seek independent support.", "uncertainty": "Signals can conflict."}
            ]
        return [result]

    store = ReplaySessionStore(
        path=root / "replay.duckdb", research_root=root, live_db_path=live,
        cohort_id="fixture", policy_id="c-notes", checkpoint=SESSIONS[28],
        initialized_at=datetime(2026, 9, 27, tzinfo=timezone.utc),
        execute_phase=execute, run_books=False,
        notes_filter_spec=freeze_filter_spec(
            tickers=("AAA",), company_names=(), aliases=()
        ),
        evaluation_tag="confirmatory",
    )
    run_session(store, first)
    run_session(store, second)
    assert seen[0] == (first, [], "confirmatory")
    assert seen[1][0] == second and seen[1][1][0]["source_session"] == first.isoformat()
