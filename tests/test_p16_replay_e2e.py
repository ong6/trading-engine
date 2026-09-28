"""Deterministic fixture proof for the complete W4 historical-replay path."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import zipfile
from datetime import date, datetime, timedelta, timezone

import pytest

from engine.lib import db
from engine.lib.provenance import canonical_sha256
from farm.replay.asof import raw_price_spot_check, reconstruct_unadjusted_bars
from farm.replay.entities import news_rows_by_ticker
from farm.replay.lockbox import (
    ConfirmatoryArm,
    LockboxLedger,
    trial_set_sha256,
)
from farm.replay.notes import freeze_filter_spec, init_notes_schema
from farm.replay.report import write_replay_report
from farm.replay.runner import (
    ReplayLockboxRun,
    ReplaySessionStore,
    book_snapshot,
    bootstrap_books,
    run_session,
    session_phases,
)
from farm.replay.sources import FetchTask, collect_shards, gdelt_shard_urls
from farm.replay.store import open_store
from server import agent_model_client
from sim import nyse, p15_books

UTC = timezone.utc
CHECKPOINT = date(2024, 11, 15)
SESSIONS = tuple(
    date.fromisoformat(value)
    for value in (
        "2024-11-18", "2024-11-19", "2024-11-20", "2024-11-21", "2024-11-22",
        "2024-11-25", "2024-11-26", "2024-11-27", "2024-11-29", "2024-12-02",
    )
)
NOW = datetime(2026, 9, 27, 22, tzinfo=UTC)
NAME_TABLE = (
    {"security_id": "halt", "ticker": "HALT", "name": "Haltco Industries Inc"},
    {"security_id": "split-security", "ticker": "SPLT", "name": "Splitco Corp"},
    {"security_id": "aaa", "ticker": "AAA", "name": "Triple Alpha Holdings"},
)


def _gdelt_zip() -> bytes:
    fields = [""] * 61
    fields[0], fields[1], fields[26] = "gdelt-halt", "20241118", "010"
    fields[6] = "HALTCO INDUSTRIES"
    fields[59], fields[60] = "20241118140000", "https://example.test/halt"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("20241118140000.export.CSV", "\t".join(fields) + "\n")
    return output.getvalue()


def _warc_member(record_id: str, captured_at: str, headline: str) -> bytes:
    html = (
        '<html><head><meta property="article:published_time" '
        'content="2024-11-18T14:30:00Z"><title>' + headline
        + "</title></head><body>Archived evidence body.</body></html>"
    ).encode()
    http = b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n" + html
    warc = (
        "WARC/1.0\r\nWARC-Type: response\r\n"
        f"WARC-Record-ID: <urn:uuid:{record_id}>\r\n"
        f"WARC-Date: {captured_at}\r\n"
        "WARC-Target-URI: https://example.test/split\r\n"
        f"WARC-Payload-Digest: sha256:{hashlib.sha256(html).hexdigest()}\r\n"
        f"Content-Length: {len(http)}\r\n\r\n"
    ).encode() + http + b"\r\n\r\n"
    return gzip.compress(warc)


def _collect(root, live):
    gdelt = _gdelt_zip()
    warc = (
        _warc_member("early", "2024-11-18T15:00:00Z", "Splitco Corp split story available")
        + _warc_member("late", "2024-11-19T03:00:00Z", "Splitco Corp future story hidden")
    )
    event_url = gdelt_shard_urls("20241118140000")[0]
    cc_url = "https://data.commoncrawl.org/crawl-data/CC-NEWS/fixture.warc.gz"
    payloads = {event_url: gdelt, cc_url: warc}
    result = collect_shards(
        [
            FetchTask(
                "gdelt_events", "20241118140000", event_url, "complete",
                expected_md5=hashlib.md5(gdelt).hexdigest(),
            ),
            FetchTask("cc_news", "fixture.warc.gz", cc_url, "fixture.warc.gz"),
        ],
        catalog_path=root / "catalog.duckdb", research_root=root, live_db_path=live,
        transport=lambda url, _headers, _range: {
            "status": 200, "headers": {}, "body": payloads[url]
        },
        user_agent="W4 fixture contact", now=lambda: NOW, pause=lambda _seconds: None,
        name_table=NAME_TABLE,
    )
    assert result["status"] == "completed" and len(result["records"]) == 3
    # Tickers come from the entity mapper, not the fixture.
    return [
        {**row, "language": "en"}
        for row in news_rows_by_ticker(result["records"], NAME_TABLE)
    ]


def _history_sessions() -> list[date]:
    result = []
    current = date(2023, 1, 3)
    while current <= SESSIONS[-1]:
        if nyse.is_session(current):
            result.append(current)
        current += timedelta(days=1)
    return result


def _prices_and_split():
    sessions = _history_sessions()
    checkpoint_index = sessions.index(CHECKPOINT)
    split = {
        "action_id": "split-fixture", "security_id": "split-security", "ticker": "SPLT",
        "stable_mapping": True, "kind": "split", "ex_date": SESSIONS[6],
        "outcome": "applied", "new_shares_per_old": 2,
    }
    source = []
    for ticker, security_id, base in (
        ("SPY", "spy", 80.0), ("AAA", "aaa", 40.0),
        ("HALT", "halt", 20.0), ("SPLT", "split-security", 10.0),
        ("LATE", "late", 2.0), ("GONE", "gone", 2.0),
    ):
        for index, session in enumerate(sessions):
            if ticker == "HALT" and session == SESSIONS[1]:
                continue
            # Sub-$3 names never trade; they prove point-in-time membership only.
            if (ticker == "LATE" and session < SESSIONS[4]) or (
                ticker == "GONE" and session > SESSIONS[1]
            ):
                continue
            price = (
                base if ticker in {"LATE", "GONE"}
                else base + min(index, checkpoint_index) * 0.1
            )
            source.append({
                "security_id": security_id, "ticker": ticker, "session": session,
                "series": "source_back_adjusted_v1",
                "available_at": session_phases(session)["close_visible"].isoformat(),
                "open": price, "high": price + 1, "low": price - 1, "close": price,
                "volume": 2_000_000,
            })
    return reconstruct_unadjusted_bars(source, [split]), split


def _model_result(payload: dict, role: str):
    identity = agent_model_client.identity(role=role)
    if role == "p15_scoring":
        output = {"schema_version": 1, "assessments": [{
            "ticker": row["ticker"], "p_outperform_5": 0.7,
            "expected_excess_bp_5": 100.0 if row["ticker"] == "SPLT" else -25.0,
            "expected_excess_bp_10": 120.0 if row["ticker"] == "SPLT" else -30.0,
            "action": "buy_candidate" if row["ticker"] == "SPLT" else "ignore",
            "thesis": "Archived evidence supports the ranking.",
            "invalidation": "Independent evidence weakens.",
            "evidence_ids": [row["evidence_id"]],
        } for row in payload["candidates"]]}
        request = agent_model_client.p15_scoring_request_payload(payload)
    else:
        output = {"schema_version": 1, "decisions": [{
            "intent_id": row["intent_id"], "decision": "keep",
            "reason": "No adverse change.",
            "evidence_ids": row["allowed_evidence_ids"][:1],
        } for row in payload["intents"]]}
        request = agent_model_client.p15_preopen_request_payload(payload)
    return agent_model_client.ConnectorResult(
        output=output,
        response_id=f"{role}-{payload.get('market_date', payload.get('session_date'))}-"
        f"{payload.get('sample_index', 0)}",
        model=identity["model"], model_version=identity["model_version"],
        proxy_version=identity["required_proxy_version"],
        proxy_source_sha256=identity["required_proxy_source_sha256"],
        traecli_runtime=identity["required_traecli_runtime"],
        upstream_model_family=agent_model_client.UPSTREAM_MODEL_FAMILY,
        upstream_request_id=f"fixture-{role}-{payload.get('sample_index', 0)}",
        model_catalog_entry_sha256=identity["model_catalog_entry_sha256"],
        request_sha256=canonical_sha256(request),
        usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    )


def _lockbox(root, live):
    ledger = LockboxLedger(
        root / "lockbox.duckdb", research_root=root, live_db_path=live
    )
    arm = ConfirmatoryArm("trial-notes", "exec-notes", "1" * 64, "initiating")
    trial_set = trial_set_sha256((arm,), SESSIONS)
    registration = {
        "registration_sha256": arm.registration_sha256, "status": "registered",
        "sessions": [session.isoformat() for session in SESSIONS],
        "trial_set_sha256": trial_set, "registered_at": "2026-09-27T21:00:00Z",
        "authority": "historical_research_only",
    }
    begin = {
        "experiment_id": "fixture-experiment", "cohort_id": "fixture-cohort",
        "sessions": SESSIONS, "confirmatory_arms": (arm,),
        "initiating_execution_id": arm.execution_id,
        "expected_trial_set_sha256": trial_set, "committed_at": NOW,
        "registration_as_of": lambda trial_id, _at: (
            registration if trial_id == arm.trial_id else None
        ),
    }
    run = ReplayLockboxRun(
        ledger=ledger, begin=begin, trial_id=arm.trial_id,
        execution_id=arm.execution_id,
        registration_sha256=arm.registration_sha256, sessions=SESSIONS,
    )
    query = {
        "experiment_id": begin["experiment_id"], "cohort_id": begin["cohort_id"],
        "trial_id": arm.trial_id, "execution_id": arm.execution_id,
        "registration_sha256": arm.registration_sha256, "sessions": SESSIONS,
        "evaluated_at": NOW + timedelta(hours=1),
    }
    return run, query


def _initialize_store(path, root, live):
    with open_store(path, research_root=root, live_db_path=live, kind="replay") as con:
        bootstrap_books(con, checkpoint=CHECKPOINT, initialized_at=NOW)
        db.init_mining_schema(con)
        con.executemany(
            "INSERT INTO earnings_fetch_log VALUES (?,?,'empty',0,'fixture',?)",
            [(ticker, CHECKPOINT, datetime(2024, 11, 15, 21))
             for ticker in ("AAA", "HALT", "SPLT")],
        )
        init_notes_schema(con)
        con.execute(
            "INSERT INTO replay_labels VALUES (?,?,?,?,?,?,?)",
            ("future-label", date(2024, 11, 14), "h5", "2025-01-02T21:15:00Z",
             "terminal", 1.0, 2.0),
        )
        con.execute(
            "INSERT INTO replay_notes VALUES (?,?,?,?,?)",
            ("f" * 64, date(2024, 11, 14), "2025-01-02T21:15:00Z", None,
             '[{"rule":"Future rule.","uncertainty":"Future uncertainty."}]'),
        )


def _run_fixture(root):
    root.mkdir()
    live = root.parent / f"{root.name}-live.duckdb"
    live.touch()
    news_rows = _collect(root, live)
    bars, split = _prices_and_split()
    split_row = next(
        row for row in bars
        if row["security_id"] == "split-security" and row["session"] == SESSIONS[0]
    )
    spot_check = raw_price_spot_check(bars, [{
        "security_id": split_row["security_id"], "session": split_row["session"],
        "source": "alpha_vantage_time_series_daily_raw_v1", "stratum": "split_window",
        **{field: split_row[field] for field in ("open", "high", "low", "close", "volume")},
    }])
    assert spot_check["status"] == "pass"

    replay_path = root / "replay.duckdb"
    _initialize_store(replay_path, root, live)
    lockbox, lockbox_query = _lockbox(root, live)
    postmortem_inputs = []

    def postmortem(payload):
        postmortem_inputs.append(payload)
        rows = [{
            "decision_id": row["decision_id"],
            "expected_excess_bp": row["expected_excess_bp"],
            "realized_excess_bp": row["realized_excess_bp"], "error_type": "noise",
            "explanation": "The forecast lacked independent support.",
            "lesson": "Seek independent support.", "evidence_ids": [],
        } for row in payload["mature_labels"]]
        session = date.fromisoformat(payload["session"])
        lessons = ([{
            "rule": "Seek independent support.",
            "uncertainty": "Signals can conflict.",
        }] if rows and nyse.is_last_session_of_week(session) else [])
        return {"postmortems": rows, "lessons": lessons}

    store = ReplaySessionStore(
        path=replay_path, research_root=root, live_db_path=live,
        cohort_id="fixture-cohort", policy_id="replay-notes-sol-v1",
        checkpoint=CHECKPOINT, initialized_at=NOW,
        reconstructed_bars=bars, actions=[split], news_rows=news_rows,
        score_generate=lambda payload: _model_result(payload, "p15_scoring"),
        preopen_generate=lambda payload: _model_result(payload, "p15_preopen"),
        postmortem_generate=postmortem, notes_filter_spec=freeze_filter_spec(
            tickers=("AAA", "HALT", "SPLT"), company_names=(), aliases=()
        ),
        lockbox=lockbox, securities={"SPY": {"etf": True}},
    )
    runs = [run_session(store, session) for session in SESSIONS]

    with db.connect(replay_path, read_only=True, wait_s=0) as con:
        positions = con.execute(
            "SELECT p.portfolio_id,p.qty,p.avg_cost,f.qty,f.fill_px "
            "FROM sim_positions p JOIN sim_fills f ON f.portfolio_id=p.portfolio_id "
            "AND f.ticker=p.ticker AND f.side='buy' WHERE p.ticker='SPLT' "
            "ORDER BY p.portfolio_id"
        ).fetchall()
        pre_split, at_split = [
            con.execute(
                "SELECT equity FROM p15_book_windows "
                "WHERE portfolio_id='p15_ai_ranked' AND market_date=?", [session],
            ).fetchone()[0]
            for session in (SESSIONS[5], SESSIONS[6])
        ]
        snapshot = {
            "books": book_snapshot(con),
            "clock": con.execute(
                "SELECT session,phase,logical_at FROM replay_clock "
                "ORDER BY session,phase_index"
            ).fetchall(),
            "labels": con.execute(
                "SELECT decision_id,horizon,visible_at,status,realized_excess_bp "
                "FROM replay_labels WHERE decision_id!='future-label' "
                "ORDER BY decision_id,horizon"
            ).fetchall(),
            "notes": con.execute(
                "SELECT source_session,effective_at,lessons_json FROM replay_notes "
                "WHERE revision_sha256!=? ORDER BY source_session", ["f" * 64],
            ).fetchall(),
            "halt_attempts": con.execute(
                "SELECT outcome,reject_reason FROM p15_limit_attempts i "
                "JOIN p15_order_intents o ON o.id=i.intent_id "
                "WHERE o.ticker='HALT' ORDER BY attempt_date"
            ).fetchall(),
            "positions": positions,
            "screens": con.execute(
                "SELECT run_date,COUNT(*),MAX(rs_rank) FROM screen_results "
                "GROUP BY run_date ORDER BY run_date"
            ).fetchall(),
            "members": con.execute(
                "SELECT snapshot_date,ticker,active FROM universe_snapshot "
                "WHERE ticker IN ('LATE','GONE') ORDER BY snapshot_date,ticker"
            ).fetchall(),
            "pre_split_equity": pre_split, "at_split_equity": at_split,
        }
    with db.connect(root / "catalog.duckdb", read_only=True, wait_s=0) as con:
        archive_records = con.execute(
            "SELECT COUNT(*) FROM w4_evidence_records WHERE record_type='source_record'"
        ).fetchone()[0]

    report = write_replay_report(
        root / "reports" / "replay.md",
        {
            "status": "caller-status-ignored", "lockbox_tag": "caller-tag-ignored",
            "coverage": {
                "candidate_sessions": len(SESSIONS), "unavailable_chunks": 0,
                "capture_confirmed": 2, "publish_only_headlines": 0,
            },
            "primary_endpoint": {"status": "fixture_only", "eligible_sessions": 0},
            "book_status": runs[-1]["status"], "raw_price_status": spot_check["status"],
        },
        lockbox_ledger=lockbox.ledger, lockbox_query=lockbox_query,
    ).read_text()
    first_context = runs[0]["executed"]["SCORE"][0]["context"]
    stable = {
        "books": snapshot["books"],
        "clock": [[str(value) for value in row] for row in snapshot["clock"]],
        "archive_records": archive_records,
        "labels": [[str(value) for value in row] for row in snapshot["labels"]],
        "notes": [[str(value) for value in row] for row in snapshot["notes"]],
        "halt_attempts": snapshot["halt_attempts"],
        "positions": snapshot["positions"],
        "screens": [[str(value) for value in row] for row in snapshot["screens"]],
        "members": [[str(value) for value in row] for row in snapshot["members"]],
        "postmortem_batches": len(postmortem_inputs), "report": report,
        "first_context_ids": [row["source_id"] for row in first_context["candidates"][0][
            "headlines"
        ]],
    }
    return canonical_sha256(stable), stable, snapshot, first_context, postmortem_inputs


def test_fixture_http_to_real_parsers_executor_notes_and_report_is_deterministic(tmp_path):
    first_digest, first, snapshot, first_context, postmortems = _run_fixture(
        (tmp_path / "first").resolve()
    )
    second_digest, second, _snapshot, _context, _postmortems = _run_fixture(
        (tmp_path / "second").resolve()
    )

    assert first_digest == second_digest and first == second
    assert len(first["clock"]) == len(SESSIONS) * 5
    assert [row for row in first["clock"] if row[:2] == ["2024-11-29", "CLOSE"]][0][2] \
        == "2024-11-29T18:15:00Z"
    assert first["archive_records"] == 3
    # The builder, not the fixture, screens each session from as-of prices.
    assert [row[0] for row in snapshot["screens"]] == list(SESSIONS)
    assert all(count >= 3 for _day, count, _rank in snapshot["screens"])
    assert {row["ticker"] for row in first_context["candidates"]} >= {"HALT", "SPLT"}
    assert all(row["rs_rank"] is not None for row in first_context["candidates"])
    members = {(day, ticker): active for day, ticker, active in snapshot["members"]}
    assert ("LATE" not in {ticker for day, ticker in members if day < SESSIONS[4]})
    assert members[(SESSIONS[4], "LATE")] is True
    assert members[(SESSIONS[0], "GONE")] is True
    assert members[(SESSIONS[-1], "GONE")] is False
    visible_ids = {
        row["source_id"]
        for candidate in first_context["candidates"] for row in candidate["headlines"]
    }
    assert {"gdelt-halt", "<urn:uuid:early>"} <= visible_ids
    assert "<urn:uuid:late>" not in json.dumps(first_context)
    assert all("future-label" not in json.dumps(payload) for payload in postmortems)
    assert all("Future rule" not in json.dumps(payload) for payload in postmortems)
    assert first["labels"] and first["notes"]
    assert first["halt_attempts"][:2] == [
        ("pending", None), ("rejected", "stale_signal")
    ]
    assert len(snapshot["positions"]) == len(p15_books.BOOK_IDS)
    assert all(qty == pytest.approx(fill_qty * 2) for _book, qty, _cost, fill_qty, _px in snapshot[
        "positions"
    ])
    assert all(cost == pytest.approx(fill_px / 2) for _book, _qty, cost, _fq, fill_px in snapshot[
        "positions"
    ])
    assert snapshot["at_split_equity"] == pytest.approx(snapshot["pre_split_equity"])
    assert "Status: **complete**" in first["report"]
    assert "Lockbox tag: confirmatory" in first["report"]
    assert "Archived evidence body" not in first["report"]
