"""Deterministic fixture proof for the complete W4 historical-replay path."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from engine.lib import db
from engine.lib.provenance import canonical_sha256
from farm.replay.asof import raw_price_spot_check, reconstruct_unadjusted_bars
from farm.replay.notes import freeze_filter_spec
from farm.replay.report import write_replay_report
from farm.replay.runner import ReplaySessionStore, book_snapshot, run_session, session_phases
from farm.replay.sources import FetchTask, collect_shards, gdelt_shard_urls
from farm.replay.store import append_exact

UTC = timezone.utc
CHECKPOINT = date(2024, 11, 15)
SESSIONS = tuple(
    date.fromisoformat(value)
    for value in (
        "2024-11-18", "2024-11-19", "2024-11-20", "2024-11-21", "2024-11-22",
        "2024-11-25", "2024-11-26", "2024-11-27", "2024-11-29", "2024-12-02",
    )
)


def _decision(ticker: str, close: float, rank: int) -> dict:
    return {
        "ticker": ticker, "tradeable": True, "stratum": "mover", "close": close,
        "atr_14": 2.0, "baseline_rank": rank, "scoring_status": "available",
        "decision": "buy_candidate", "action": "buy", "p_outperform_5": 0.7,
        "expected_excess_bp_5": 100, "evidence_ids": [str(rank) * 64],
    }


def _run_fixture(root):
    root.mkdir()
    live = root.parent / f"{root.name}-live.duckdb"
    live.touch()
    payload = json.dumps([{
        "source_id": "halt-fixture", "headline": "Fixture issuer trading pause",
        "dateadded": "20241118140000", "event_at": "2024-11-18T14:00:00Z",
        "published_at": "2024-11-18T13:59:00Z", "precision": "second",
        "confidence": "fixture", "source_timezone": "UTC",
    }]).encode()
    collected = collect_shards(
        [FetchTask(
            "gdelt_events", "20241118140000",
            gdelt_shard_urls("20241118140000")[0], "complete",
        )],
        catalog_path=root / "catalog.duckdb", research_root=root, live_db_path=live,
        transport=lambda *_args: {"status": 200, "headers": {}, "body": payload},
        parse_rows=lambda _source, body: json.loads(body),
        user_agent="W4 fixture contact", now=lambda: datetime(2026, 9, 27, tzinfo=UTC),
        pause=lambda _seconds: None,
    )
    assert collected["status"] == "completed" and len(collected["records"]) == 1

    split = {
        "action_id": "split-fixture", "security_id": "split-security", "ticker": "SPLT",
        "stable_mapping": True, "kind": "split", "ex_date": SESSIONS[6],
        "outcome": "applied", "new_shares_per_old": 2,
    }
    bars = []
    for ticker, security_id, price in (
        ("SPY", "spy", 100.0), ("AAA", "aaa", 100.0),
        ("HALT", "halt", 20.0), ("SPLT", "split-security", 50.0),
    ):
        for session in (CHECKPOINT, *SESSIONS):
            if ticker == "HALT" and session == SESSIONS[1]:
                continue
            bars.append({
                "security_id": security_id, "ticker": ticker, "session": session,
                "series": "source_back_adjusted_v1",
                "available_at": session_phases(session)["close_visible"].isoformat(),
                "open": price, "high": price + 1, "low": price - 1, "close": price,
                "volume": 1_000_000,
            })
    rebuilt = reconstruct_unadjusted_bars(bars, [split])
    reference = [{
        "security_id": "split-security", "session": SESSIONS[0],
        "source": "alpha_vantage_time_series_daily_raw_v1", "stratum": "split_window",
        "open": 100, "high": 102, "low": 98, "close": 100, "volume": 500_000,
    }]
    spot_check = raw_price_spot_check(rebuilt, reference)
    assert spot_check["status"] == "pass"

    replay_path = root / "replay.duckdb"
    notes_seen = []

    def execute(phase, session, _logical_at, context):
        if phase == "SCORE":
            notes_seen.append((session.isoformat(), len(context["notes"])))
        row = {"status": "completed", "source_count": len(collected["records"])}
        if phase == "POSTMORTEM":
            row["lessons"] = [{
                "rule": "Seek independent support.",
                "uncertainty": "Signals can conflict.",
            }]
        return [row]

    def apply(con, phase, session, logical_at, _rows):
        if phase == "PREOPEN" and session == SESSIONS[0]:
            record = collected["records"][0]
            append_exact(
                con, record_type="archive_record", record_key=record["source_id"],
                payload={
                    "source": record["source"], "source_id": record["source_id"],
                    "available_at_replay": record["available_at_replay"].isoformat(),
                    "status": record["status"],
                },
                recorded_at=logical_at,
            )
        if phase != "SCORE" or session != SESSIONS[0]:
            return
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
            "INSERT INTO agent_evaluation_traces "
            "(id,policy_id,market_date,terminal_status,completed_at) "
            "VALUES (1,'p15-scoring-v1',?,'completed',?)",
            [session, logical_at],
        )
        con.executemany(
            "INSERT INTO agent_evaluation_decisions "
            "(id,trace_id,ticker,decision_payload) VALUES (?,1,?,?)",
            [
                (1, "AAA", json.dumps(_decision("AAA", 100, 1))),
                (2, "HALT", json.dumps(_decision("HALT", 20, 2))),
            ],
        )

    store = ReplaySessionStore(
        path=replay_path, research_root=root, live_db_path=live,
        cohort_id="fixture-cohort", policy_id="replay-notes-sol-v1",
        checkpoint=CHECKPOINT, initialized_at=datetime(2026, 9, 27, tzinfo=UTC),
        execute_phase=execute, apply_phase=apply, reconstructed_bars=rebuilt,
        actions=[split], notes_filter_spec=freeze_filter_spec(
            tickers=("AAA", "HALT", "SPLT"), company_names=(), aliases=()
        ),
        evaluation_tag="confirmatory",
    )
    runs = [run_session(store, session) for session in SESSIONS]

    with db.connect(replay_path, read_only=True, wait_s=0) as con:
        snapshot = {
            "books": book_snapshot(con),
            "clock": con.execute(
                "SELECT session,phase,logical_at FROM replay_clock "
                "ORDER BY session,phase_index"
            ).fetchall(),
            "archive_records": con.execute(
                "SELECT COUNT(*) FROM w4_evidence_records "
                "WHERE record_type='archive_record'"
            ).fetchone()[0],
            "notes": con.execute("SELECT COUNT(*) FROM replay_notes").fetchone()[0],
            "halt_attempts": con.execute(
                "SELECT outcome,reject_reason FROM p15_limit_attempts i "
                "JOIN p15_order_intents o "
                "ON o.id=i.intent_id WHERE o.ticker='HALT' ORDER BY attempt_date"
            ).fetchall(),
        }
    report_path = root / "reports" / "replay.md"
    report = write_replay_report(report_path, {
        "status": "complete", "lockbox_tag": "confirmatory",
        "coverage": {
            "candidate_sessions": len(SESSIONS), "unavailable_chunks": 0,
            "capture_confirmed": 0, "publish_only_headlines": len(collected["records"]),
        },
        "primary_endpoint": {"status": "fixture_only", "eligible_sessions": 0},
        "book_status": runs[-1]["status"], "raw_price_status": spot_check["status"],
    }).read_text()
    stable = {
        "books": snapshot["books"],
        "clock": [[str(value) for value in row] for row in snapshot["clock"]],
        "archive_records": snapshot["archive_records"], "notes": snapshot["notes"],
        "halt_attempts": snapshot["halt_attempts"], "notes_seen": notes_seen,
        "report": report,
    }
    return canonical_sha256(stable), stable


def test_fixture_http_to_collectors_replay_notes_and_report_is_deterministic(tmp_path):
    first_digest, first = _run_fixture((tmp_path / "first").resolve())
    second_digest, second = _run_fixture((tmp_path / "second").resolve())

    assert first_digest == second_digest and first == second
    assert len(first["clock"]) == len(SESSIONS) * 5
    assert [row for row in first["clock"] if row[:2] == ["2024-11-29", "CLOSE"]][0][2] \
        == "2024-11-29T18:15:00Z"
    assert first["archive_records"] == 1 and first["notes"] == len(SESSIONS)
    assert first["notes_seen"][0][1] == 0 and first["notes_seen"][-1][1] > 0
    assert first["halt_attempts"] == [
        *(('pending', None),) * 3,
        *(('rejected', 'stale_signal'),) * 3,
    ]
    assert "Status: **complete**" in first["report"]
    assert "Fixture issuer trading pause" not in first["report"]
