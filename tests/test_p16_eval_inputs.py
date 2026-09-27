import json
from datetime import date, datetime, timezone

import duckdb
import pytest

from engine.lib.provenance import canonical_sha256
from farm import p16_eval_inputs

NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


@pytest.fixture
def con(monkeypatch):
    connection = duckdb.connect(":memory:")
    calls = []
    monkeypatch.setattr(
        p16_eval_inputs.agent_evaluation, "validate_p15_evidence",
        lambda _con, generated_at=None: calls.append(generated_at),
    )
    connection.execute(
        "CREATE TABLE agent_evaluation_traces "
        "(id BIGINT,policy_id VARCHAR,market_date DATE,information_cutoff_at TIMESTAMP,"
        "completed_at TIMESTAMP,source_kind VARCHAR,source_identifier VARCHAR,"
        "source_refs VARCHAR,input_payload VARCHAR,input_sha256 VARCHAR,output_sha256 VARCHAR,"
        "request_sha256 VARCHAR,terminal_status VARCHAR,trace_sha256 VARCHAR)"
    )
    connection.execute(
        "CREATE TABLE agent_evaluation_decisions "
        "(id BIGINT,trace_id BIGINT,ticker VARCHAR,decision VARCHAR,assessment_sha256 VARCHAR,"
        "decision_payload VARCHAR,decision_sha256 VARCHAR)"
    )
    connection.execute(
        "CREATE TABLE agent_evaluation_labels_v2 "
        "(id BIGINT,decision_id BIGINT,horizon_sessions INTEGER,label_basis VARCHAR,"
        "entry_date DATE,exit_date DATE,missing_bar_status VARCHAR,labeled_at TIMESTAMP,"
        "label_sha256 VARCHAR,price_prefix_sha256 VARCHAR,round_trip_cost_bps DOUBLE,"
        "net_excess_return DOUBLE)"
    )
    connection.execute(
        "CREATE TABLE p15_scoring_runs (id BIGINT,policy_id VARCHAR,market_date DATE,"
        "status VARCHAR,universe_sha256 VARCHAR,context_sha256 VARCHAR,"
        "aggregate_trace_sha256 VARCHAR,information_cutoff_at TIMESTAMP,completed_at TIMESTAMP)"
    )
    yield connection, calls
    connection.close()


def _insert_origin(con, *, bad_score=False):
    candidates = []
    definitions = [
        ("AAA", "mover", 1, 4, "available", 30.0),
        ("BBB", "trend", 2, 3 if not bad_score else 30, "unavailable", None),
        ("CCC", "held_only", 3, 2, "unavailable", None),
        ("DDD", "mover", 4, 1, "available", 5.0),
    ]
    for ticker, stratum, rank, score, _status, _champion in definitions:
        candidate = {"ticker": ticker, "stratum": stratum, "baseline_rank": rank,
                     "baseline_score": score, "evidence_id": ticker.lower() * 21 + "a"}
        candidates.append(candidate)
    body = {"market_date": "2026-09-22", "candidates": candidates}
    universe = {**body, "bundle_sha256": canonical_sha256(body)}
    input_payload = json.dumps({"universe": universe, "context": {}})
    con.execute(
        "INSERT INTO agent_evaluation_traces VALUES "
        "(1,'p15-scoring-v1','2026-09-22','2026-09-22 20:00:00',"
        "'2026-09-22 20:10:00','p15_scoring_run','7',?,?,?,?,?, 'completed',?)",
        [json.dumps([{"kind": "p15_universe", "sha256": universe["bundle_sha256"]}]),
         input_payload, "1" * 64, "2" * 64, "8" * 64, "3" * 64],
    )
    con.execute(
        "INSERT INTO p15_scoring_runs VALUES "
        "(7,'p15-scoring-v1','2026-09-22','completed',?,?,?,"
        "'2026-09-22 20:00:00','2026-09-22 20:10:00')",
        [canonical_sha256(universe), "4" * 64, "3" * 64],
    )
    for index, (ticker, _stratum, _rank, _score, status, champion) in enumerate(
        definitions, 1,
    ):
        payload = {**candidates[index - 1], "scoring_status": status,
                   "expected_excess_bp_5": champion}
        con.execute(
            "INSERT INTO agent_evaluation_decisions VALUES (?,?,?,?,?,?,?)",
            [index, 1, ticker, "unavailable" if status == "unavailable" else "buy_candidate",
             str(index + 8) * 64, json.dumps(payload), str(index) * 64],
        )
    labels = [
        (1, 1, 5, "next_session_open", "complete", "2026-09-29 12:00:00", 0.04),
        (2, 2, 5, "missing_entry_last_available_close",
         "missing_entry_last_available_close", "2026-09-29 12:00:00", 0.0),
        (3, 3, 5, "next_session_open", "complete", "2026-09-29 12:00:00", -0.01),
        (4, 4, 10, "next_session_open", "complete", "2026-09-29 12:00:00", 0.08),
        (5, 4, 5, "next_session_open", "complete", "2026-10-01 12:00:00", 0.02),
    ]
    for row_id, decision_id, horizon, basis, status, labeled_at, outcome in labels:
        con.execute(
            "INSERT INTO agent_evaluation_labels_v2 VALUES "
            "(?,?,?,?,'2026-09-23','2026-09-29',?,?,?,?,20,?)",
            [row_id, decision_id, horizon, basis, status, labeled_at,
             str(row_id + 4) * 64, str(row_id + 5) * 64, outcome],
        )


def test_origin_uses_frozen_terminal_h5_inputs_and_negative_rank(con):
    connection, validation_calls = con
    _insert_origin(connection)

    result = p16_eval_inputs.load_origin(
        connection, market_date=date(2026, 9, 22), report_cutoff=NOW,
    )

    assert validation_calls == [NOW]
    assert result["status"] == "pending"
    assert result["frozen_candidate_count"] == 4
    assert result["held_only_excluded_count"] == 1
    assert result["evaluation_candidate_count"] == 3
    assert result["terminal_h5_count"] == 2
    assert result["unresolved_h5_tickers"] == ["DDD"]
    assert [row["ticker"] for row in result["decision_rows"]] == ["AAA", "BBB", "DDD"]
    assert result["decision_rows"][0] == {
        "ticker": "AAA", "stratum": "mover", "champion_score": 30.0,
        "champion_score_available": True, "rule_score": -1,
        "baseline_rank": 1, "baseline_score": 4, "decision_sha256": "1" * 64,
    }
    assert result["decision_rows"][1]["champion_score"] is None
    assert result["decision_rows"][1]["champion_score_available"] is False
    assert [row["ticker"] for row in result["rows"]] == ["AAA", "BBB"]
    assert result["rows"][0]["rule_score"] == -1
    assert result["rows"][0]["champion_score"] == 30
    assert result["rows"][1]["champion_score"] is None
    assert result["rows"][1]["champion_score_available"] is False
    assert result["rows"][1]["fallback_label"] is True
    assert result["rows"][1]["missing_bar_status"] == "missing_entry_last_available_close"
    assert result["source"] == {
        "run_id": 7, "bundle_sha256": json.loads(connection.execute(
            "SELECT input_payload FROM agent_evaluation_traces"
        ).fetchone()[0])["universe"]["bundle_sha256"],
        "universe_sha256": connection.execute(
            "SELECT universe_sha256 FROM p15_scoring_runs"
        ).fetchone()[0],
        "context_sha256": "4" * 64, "input_sha256": "1" * 64,
        "source_refs_sha256": canonical_sha256([{
            "kind": "p15_universe", "sha256": json.loads(connection.execute(
                "SELECT input_payload FROM agent_evaluation_traces"
            ).fetchone()[0])["universe"]["bundle_sha256"],
        }]), "output_sha256": "2" * 64, "trace_sha256": "3" * 64,
        "request_sha256": "8" * 64,
    }
    assert result["input_snapshot_sha256"] == canonical_sha256({
        key: value for key, value in result.items() if key != "input_snapshot_sha256"
    })


def test_origin_rejects_baseline_score_not_equivalent_to_negative_rank(con):
    connection, _calls = con
    _insert_origin(connection, bad_score=True)

    with pytest.raises(p16_eval_inputs.EvaluationInputError, match="negative rank"):
        p16_eval_inputs.load_origin(
            connection, market_date=date(2026, 9, 22), report_cutoff=NOW,
        )


def test_origin_rejects_candidate_fields_that_differ_from_frozen_universe(con):
    connection, _calls = con
    _insert_origin(connection)
    raw = connection.execute(
        "SELECT decision_payload FROM agent_evaluation_decisions WHERE ticker='AAA'"
    ).fetchone()[0]
    payload = json.loads(raw)
    payload["evidence_id"] = "f" * 64
    connection.execute(
        "UPDATE agent_evaluation_decisions SET decision_payload=? WHERE ticker='AAA'",
        [json.dumps(payload)],
    )

    with pytest.raises(p16_eval_inputs.EvaluationInputError, match="candidate fields"):
        p16_eval_inputs.load_origin(
            connection, market_date=date(2026, 9, 22), report_cutoff=NOW,
        )


def test_origin_rejects_scoring_completed_after_report_cutoff(con):
    connection, _calls = con
    _insert_origin(connection)
    connection.execute(
        "UPDATE agent_evaluation_traces SET completed_at='2026-10-01 12:00:00'"
    )

    with pytest.raises(p16_eval_inputs.EvaluationInputError, match="unavailable"):
        p16_eval_inputs.load_origin(
            connection, market_date=date(2026, 9, 22), report_cutoff=NOW,
        )


def test_origin_rejects_duplicate_decisions_even_without_schema_constraint(con):
    connection, _calls = con
    _insert_origin(connection)
    connection.execute(
        "INSERT INTO agent_evaluation_decisions SELECT 20,trace_id,ticker,decision,"
        "assessment_sha256,decision_payload,decision_sha256 "
        "FROM agent_evaluation_decisions WHERE ticker='AAA'"
    )

    with pytest.raises(p16_eval_inputs.EvaluationInputError, match="duplicate tickers"):
        p16_eval_inputs.load_origin(
            connection, market_date=date(2026, 9, 22), report_cutoff=NOW,
        )


def test_origin_requires_aware_report_cutoff(con):
    connection, validation_calls = con
    with pytest.raises(p16_eval_inputs.EvaluationInputError, match="timezone-aware"):
        p16_eval_inputs.load_origin(
            connection, market_date=date(2026, 9, 22),
            report_cutoff=datetime(2026, 9, 30, 12),
        )
    assert validation_calls == []


def test_preentry_origin_retains_scores_before_any_h5_label_matures(con):
    connection, _calls = con
    _insert_origin(connection)

    result = p16_eval_inputs.load_origin(
        connection, market_date=date(2026, 9, 22),
        report_cutoff=datetime(2026, 9, 23, 12, tzinfo=timezone.utc),
    )

    assert result["status"] == "pending" and result["rows"] == []
    assert [row["ticker"] for row in result["decision_rows"]] == ["AAA", "BBB", "DDD"]
    assert result["unresolved_h5_tickers"] == ["AAA", "BBB", "DDD"]
