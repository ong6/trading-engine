"""P15 scoring-universe and policy-contract tests."""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone

import pytest

from engine.daily_opportunities import p15_universe
from engine.lib import db
from engine.lib.provenance import canonical_sha256
from server import agent_evaluation, agent_model_client, p15_scoring_runner
from tests.test_daily_opportunities import MARKET_DATE, _database, _news_response

P15_NOW = datetime(2026, 9, 22, 2, 30, tzinfo=timezone.utc)


def _p15_database(path):
    _database(path)
    con = db.connect(path)
    captured = P15_NOW.replace(hour=1).replace(tzinfo=None)
    con.execute("UPDATE prices SET fetched_at=?", [captured])
    con.executemany(
        "INSERT INTO earnings_fetch_log VALUES (?,?,?,?,?,?)",
        [("FAST", MARKET_DATE, "ok", 1, "test", captured),
         ("QUIET", MARKET_DATE, "empty", 0, "test", captured)],
    )
    con.close()


def test_p15_universe_keeps_p8_frozen_and_assigns_deterministic_strata(tmp_path):
    database = tmp_path / "market.duckdb"
    _database(database)
    con = db.connect(database)
    con.execute(
        "UPDATE prices SET open=119,high=120,low=118,close=119 "
        "WHERE ticker='QUIET' AND date=?",
        [MARKET_DATE],
    )
    before = p15_universe(con, MARKET_DATE, held_tickers={"FAST", "QUIET"})
    con.execute(
        "INSERT INTO prices (ticker,date,open,high,low,close,volume) "
        "VALUES ('FAST',?,?,?,?,?,?)",
        [MARKET_DATE + timedelta(days=1), 200, 201, 199, 200, 9_000_000],
    )
    con.execute(
        "INSERT INTO screen_results (run_date,ticker,close,rs_rank,template_score,"
        "passes_template,dist_50d,dist_200d,off_52w_low,off_52w_high,base_tight,"
        "vol_dryup,new_today,universe_policy) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'all')",
        [MARKET_DATE + timedelta(days=1), "QUIET", 119, 100, 9, True,
         0.2, 0.3, 1.0, -0.01, False, False, True],
    )
    after = p15_universe(con, MARKET_DATE, held_tickers={"FAST", "QUIET"})
    con.close()

    assert before == after
    assert before["universe_version"] == "p15-universe-v1"
    assert [(item["ticker"], item["stratum"]) for item in before["candidates"]] == [
        ("FAST", "mover"), ("QUIET", "held_only")
    ]
    assert before["candidates"][0]["held"] is True
    assert before["candidates"][1]["tradeable"] is False
    assert before["candidates"][1]["reason"] == "held_only"
    assert [item["selection_ordinal"] for item in before["candidates"]] == [1, 2]
    assert [item["baseline_score"] for item in before["candidates"]] == [2, 1]


def test_p15_universe_uses_prior_session_dollar_volume_and_quarantine(tmp_path):
    database = tmp_path / "market.duckdb"
    _database(database)
    con = db.connect(database)
    con.execute(
        "UPDATE prices SET volume=1000 WHERE ticker='FAST' AND date<?",
        [MARKET_DATE],
    )
    low_liquidity = p15_universe(con, MARKET_DATE, held_tickers={"FAST"})
    held = next(item for item in low_liquidity["candidates"] if item["ticker"] == "FAST")
    assert held["median_dollar_volume_20d"] < 20_000_000
    assert held["reason"] == "low_median_dollar_volume"
    assert held["stratum"] == "held_only" and held["tradeable"] is False

    con.execute(
        "UPDATE prices SET volume=1000000 WHERE ticker='FAST' AND date<?",
        [MARKET_DATE],
    )
    con.execute(
        "INSERT INTO price_quarantine "
        "(ticker,status,reason,evidence,confirmed_at,resolved_at,resolution) "
        "VALUES ('FAST','active','bad scale','receipt',CURRENT_TIMESTAMP,NULL,NULL)"
    )
    quarantined = p15_universe(con, MARKET_DATE, held_tickers={"FAST"})
    con.close()

    held = next(item for item in quarantined["candidates"] if item["ticker"] == "FAST")
    assert held["reason"] == "quarantined"
    assert held["stratum"] == "held_only" and held["tradeable"] is False


def test_p15_universe_excludes_post_cutoff_prices_and_earnings(tmp_path):
    database = tmp_path / "market.duckdb"
    _p15_database(database)
    cutoff = datetime(2026, 9, 22, 2, 30, tzinfo=timezone.utc)
    con = db.connect(database)
    con.execute(
        "UPDATE prices SET fetched_at=? WHERE ticker='QUIET'",
        [cutoff.replace(hour=3).replace(tzinfo=None)],
    )
    con.execute(
        "INSERT INTO earnings_calendar VALUES ('FAST',?,?,FALSE,'future',?)",
        [MARKET_DATE + timedelta(days=2), MARKET_DATE,
         cutoff.replace(hour=3).replace(tzinfo=None)],
    )

    bundle = p15_universe(con, MARKET_DATE, information_cutoff_at=cutoff)
    con.close()

    assert [item["ticker"] for item in bundle["candidates"]] == ["FAST"]
    assert bundle["candidates"][0]["earnings"]["next_date"] == "2026-10-01"


def test_p15_trade_gates_rebind_candidate_and_bundle_evidence(tmp_path):
    database = tmp_path / "market.duckdb"
    _database(database)
    con = db.connect(database, read_only=True)
    original = p15_universe(con, MARKET_DATE)
    con.close()
    original["market"]["regime"] = "risk_off"

    gated = p15_scoring_runner._gate_candidates(original)

    assert gated is not original
    assert all(not item["tradeable"] and item["reason"] == "risk_off"
               for item in gated["candidates"])
    for candidate in gated["candidates"]:
        body = {key: value for key, value in candidate.items() if key != "evidence_id"}
        assert candidate["evidence_id"] == canonical_sha256(body)
    body = {key: value for key, value in gated.items() if key != "bundle_sha256"}
    assert gated["bundle_sha256"] == canonical_sha256(body)


def _scoring_result(payload, *, invalid=False):
    offset = payload["sample_index"] * 10.0
    assessments = []
    for candidate in payload["candidates"]:
        assessments.append({
            "ticker": candidate["ticker"], "p_outperform_5": 0.6,
            "expected_excess_bp_5": 75.0 + offset,
            "expected_excess_bp_10": 100.0 + offset,
            "action": "buy_candidate", "thesis": "Positive expected excess.",
            "invalidation": "Expected excess turns negative.",
            "evidence_ids": [candidate["evidence_id"]],
        })
    if invalid:
        assessments[0]["p_outperform_5"] = 2.0
    request = agent_model_client.p15_scoring_request_payload(payload)
    return agent_model_client.ConnectorResult(
        output={"schema_version": 1, "assessments": assessments},
        response_id=f"response-{payload['sample_index']}",
        model=agent_model_client.MODEL, model_version=agent_model_client.MODEL_VERSION,
        proxy_version="0.7",
        proxy_source_sha256=agent_model_client.REQUIRED_PROXY_SOURCE_SHA256,
        traecli_runtime=agent_model_client.REQUIRED_TRAECLI_RUNTIME,
        upstream_model_family=agent_model_client.UPSTREAM_MODEL_FAMILY,
        upstream_request_id=f"upstream-{payload['sample_index']}",
        model_catalog_entry_sha256=agent_model_client.MODEL_CATALOG_ENTRY_SHA256,
        request_sha256=canonical_sha256(request),
        usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    )


def test_p15_scoring_runner_retains_three_samples_and_replays_without_calls(tmp_path):
    database = tmp_path / "market.duckdb"
    _p15_database(database)
    now = datetime(2026, 9, 22, 2, 30, tzinfo=timezone.utc)
    calls = []

    def generate(payload):
        calls.append(payload)
        return _scoring_result(payload)

    first = p15_scoring_runner.run(
        database=database, now=now, generate=generate, fetch_news=_news_response,
        clock=lambda: now,
    )
    con = db.connect(database)
    con.execute(
        "UPDATE prices SET close=999 WHERE ticker='FAST' AND date=?", [MARKET_DATE]
    )
    con.close()
    second = p15_scoring_runner.run(
        database=database, now=now, generate=generate,
        fetch_news=lambda *_args: (_ for _ in ()).throw(AssertionError("news replayed")),
        clock=lambda: now,
    )

    assert first["candidate_count"] == 2 and first["model_call_count"] == 3
    assert first["unavailable_count"] == 0 and first["replayed"] is False
    assert second["replayed"] is True and second["model_call_count"] == 0
    assert len(calls) == 3
    assert all(sorted(item["ticker"] for item in call["candidates"]) == ["FAST", "QUIET"]
               for call in calls)
    assert len({tuple(item["ticker"] for item in call["candidates"]) for call in calls}) == 2
    con = db.connect(database, read_only=True)
    try:
        assert con.execute("SELECT COUNT(*) FROM p15_scoring_samples").fetchone() == (3,)
        assert con.execute(
            "SELECT COUNT(*) FROM agent_evaluation_decisions d "
            "JOIN agent_evaluation_traces t ON t.id=d.trace_id "
            "WHERE t.policy_id='p15-scoring-v1'"
        ).fetchone() == (2,)
        payloads = [row[0] for row in con.execute(
            "SELECT decision_payload FROM agent_evaluation_decisions ORDER BY ticker"
        ).fetchall()]
        assert all('"baseline_score"' in payload and '"expected_excess_bp_5":85.0' in payload
                   for payload in payloads)
    finally:
        con.close()


def test_p15_scoring_invalid_sample_marks_whole_chunk_unavailable(tmp_path):
    database = tmp_path / "market.duckdb"
    _p15_database(database)
    now = datetime(2026, 9, 22, 2, 30, tzinfo=timezone.utc)

    result = p15_scoring_runner.run(
        database=database, now=now,
        generate=lambda payload: _scoring_result(
            payload, invalid=payload["sample_index"] == 1
        ),
        fetch_news=_news_response, clock=lambda: now,
    )

    assert result["model_call_count"] == 3 and result["unavailable_count"] == 2
    con = db.connect(database, read_only=True)
    try:
        assert con.execute(
            "SELECT DISTINCT decision FROM agent_evaluation_decisions"
        ).fetchall() == [("unavailable",)]
        assert con.execute(
            "SELECT COUNT(*) FROM p15_scoring_samples "
            "WHERE status='failed' AND response_payload IS NOT NULL"
        ).fetchone() == (1,)
    finally:
        con.close()
    con = db.connect(database)
    for ticker in ("SPY", "FAST", "QUIET"):
        con.execute(
            "INSERT INTO prices (ticker,date,open,high,low,close,volume,fetched_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [ticker, MARKET_DATE + timedelta(days=1), 100, 102, 99, 101, 1_000_000,
             now.replace(tzinfo=None)],
        )
    agent_evaluation.label_mature(con, labeled_at=now)
    assert con.execute(
        "SELECT COUNT(*) FROM agent_evaluation_labels_v2 "
        "WHERE label_basis='next_session_open' AND horizon_sessions=1"
    ).fetchone() == (2,)
    con.close()


def test_p15_scoring_dry_run_uses_copy_and_leaves_source_unchanged(tmp_path):
    database = tmp_path / "market.duckdb"
    _p15_database(database)
    before = database.read_bytes()
    now = datetime(2026, 9, 22, 2, 30, tzinfo=timezone.utc)

    result = p15_scoring_runner.dry_run(
        database=database, now=now, generate=_scoring_result,
        fetch_news=_news_response, clock=lambda: now,
        copier=lambda source, target: shutil.copy2(source, target),
    )

    assert result["dry_run"] is True and result["candidate_count"] == 2
    assert database.read_bytes() == before
    con = db.connect(database, read_only=True)
    try:
        assert con.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name LIKE 'p15_scoring_%'"
        ).fetchone() == (0,)
    finally:
        con.close()


def test_p15_scoring_rejects_noon_start_before_writing(tmp_path):
    database = tmp_path / "market.duckdb"
    _p15_database(database)
    late = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)

    with pytest.raises(p15_scoring_runner.ScoringError, match="12:00 UTC"):
        p15_scoring_runner.run(
            database=database, now=late, generate=_scoring_result,
            fetch_news=_news_response, clock=lambda: late,
        )

    con = db.connect(database, read_only=True)
    try:
        assert con.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name LIKE 'p15_scoring_%'"
        ).fetchone() == (0,)
    finally:
        con.close()


def test_p15_scoring_discards_complete_samples_if_finalization_crosses_noon(tmp_path):
    database = tmp_path / "market.duckdb"
    _p15_database(database)
    start = datetime(2026, 9, 22, 11, 59, tzinfo=timezone.utc)
    calls = 0

    def clock():
        nonlocal calls
        calls += 1
        return start if calls < 10 else start.replace(hour=12, minute=0)

    result = p15_scoring_runner.run(
        database=database, now=start, generate=_scoring_result,
        fetch_news=_news_response, clock=clock,
    )

    assert result["status"] == "failed" and result["reason"] == "deadline_exceeded"
    con = db.connect(database, read_only=True)
    try:
        assert con.execute("SELECT status FROM p15_scoring_runs").fetchone() == ("failed",)
        assert con.execute("SELECT COUNT(*) FROM agent_evaluation_traces").fetchone() == (0,)
    finally:
        con.close()
