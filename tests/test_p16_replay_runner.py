"""Real pinned-P15 integration for isolated W4 replay books."""
from datetime import date, datetime, timezone

import duckdb
import pytest

from engine.lib import db
from farm.replay.asof import reconstruct_unadjusted_bars
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
from server import agent_evaluation
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
        "horizon_sessions": 5,
        "confidence": 0.7,
    }
    observed_at = datetime.combine(market_date, datetime.min.time(), timezone.utc)
    agent_evaluation.record_trace(con, {
        "window_id": f"test-p16:{market_date.isoformat()}",
        "policy_id": "p15-scoring-v1", "cadence": "nightly",
        "prompt_role": "test", "market_date": market_date,
        "observed_at": observed_at, "completed_at": observed_at,
        "information_cutoff_at": observed_at,
        "source_kind": "test", "source_identifier": "test-p16",
        "source_refs": [{"kind": "test", "sha256": "a" * 64}],
        "input_payload": {"test": True}, "output_payload": {"test": True},
        "request_sha256": "b" * 64, "response_id": "test-p16-response",
        "model": "test", "model_version": "test",
        "instructions_sha256": "c" * 64, "toolset_sha256": "d" * 64,
        "model_catalog_entry_sha256": "e" * 64,
        "proxy_source_sha256": "f" * 64, "traecli_runtime": "test",
        "upstream_model_family": "test", "upstream_request_id": "test-p16",
        "latency_ms": 0.0,
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "terminal_status": "completed", "execution_authority": "none",
        "decisions": [decision],
    })


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
    )
    run_session(store, first)
    run_session(store, second)
    assert seen[0] == (first, [], "post_lockbox_exploratory")
    assert seen[1][0] == second and seen[1][1][0]["source_session"] == first.isoformat()


def test_multi_session_crash_resume_matches_uninterrupted_books(tmp_path):
    root = (tmp_path / "research").resolve()
    root.mkdir()
    live = (tmp_path / "live.duckdb").resolve()
    live.touch()
    checkpoint = SESSIONS[28]
    sessions = SESSIONS[29:39]
    bars = reconstruct_unadjusted_bars(
        [
            {
                "security_id": "spy", "ticker": "SPY", "session": session,
                "series": "source_back_adjusted_v1",
                "available_at": session_phases(session)["close_visible"].isoformat(),
                "open": 100, "high": 101, "low": 99, "close": 100,
                "volume": 1_000_000,
            }
            for session in [checkpoint, *sessions]
        ],
        [],
    )

    def store(name, execute):
        return ReplaySessionStore(
            path=root / f"{name}.duckdb", research_root=root, live_db_path=live,
            cohort_id="fixture", policy_id="control", checkpoint=checkpoint,
            initialized_at=datetime(2026, 9, 27, tzinfo=timezone.utc),
            execute_phase=execute, reconstructed_bars=bars,
        )

    def completed(_phase, _session, _logical_at, _context):
        return [{"status": "completed"}]

    uninterrupted = store("uninterrupted", completed)
    for session in sessions:
        run_session(uninterrupted, session)

    failed_once = False

    def crashing(phase, session, logical_at, context):
        nonlocal failed_once
        if session == sessions[4] and phase == "CLOSE" and not failed_once:
            failed_once = True
            raise RuntimeError("fixture crash")
        return completed(phase, session, logical_at, context)

    resumed = store("resumed", crashing)
    for session in sessions:
        try:
            run_session(resumed, session)
        except RuntimeError as exc:
            assert str(exc) == "fixture crash"
            run_session(resumed, session)

    snapshots = []
    for item in (uninterrupted, resumed):
        with db.connect(item.path, read_only=True, wait_s=0) as con:
            snapshots.append({
                "books": book_snapshot(con),
                "fills": con.execute("SELECT COUNT(*) FROM sim_fills").fetchone()[0],
                "orders": con.execute("SELECT COUNT(*) FROM sim_orders").fetchone()[0],
                "clocks": con.execute("SELECT session,phase FROM replay_clock ORDER BY session,phase_index").fetchall(),
            })
    assert snapshots[0] == snapshots[1]
    assert len(snapshots[0]["clocks"]) == 10 * 5
