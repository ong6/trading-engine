"""Canonical paired agent scoring and contamination diagnostics."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from engine.lib import db
from farm.agent_evaluation_analysis import contamination_diagnostics, expected_windows
from server import agent_evaluation, agent_evaluation_reporting, daily_opportunity_store

NOW = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)


def _trace(policy: str, action: str, confidence: float) -> dict:
    cadence = agent_evaluation.POLICIES[policy]
    return {
        "window_id": f"{policy}:window", "policy_id": policy, "cadence": cadence,
        "prompt_role": "test", "market_date": date(2026, 9, 1),
        "observed_at": NOW, "completed_at": NOW, "information_cutoff_at": NOW,
        "source_kind": "test", "source_identifier": policy,
        "source_refs": [{"kind": "test", "sha256": "a" * 64}],
        "input_payload": {"same": True}, "output_payload": {"action": action},
        "request_sha256": "b" * 64, "response_id": f"response-{policy}",
        "model": "test", "model_version": "v1",
        "instructions_sha256": "c" * 64, "toolset_sha256": "d" * 64,
        "model_catalog_entry_sha256": "e" * 64, "proxy_source_sha256": "f" * 64,
        "traecli_runtime": "test", "upstream_model_family": "test",
        "upstream_request_id": f"upstream-{policy}", "latency_ms": 100.0,
        "usage": {"input_tokens": 8, "output_tokens": 2, "total_tokens": 10},
        "terminal_status": "completed", "execution_authority": "none",
        "decisions": [{"ticker": "SPY", "decision": "swing", "action": action,
                       "horizon_sessions": 5, "confidence": confidence}],
    }


def _label(con, policy: str, asset_return: float, prefix: str = "9" * 64) -> None:
    decision_id = con.execute(
        "SELECT d.id FROM agent_evaluation_decisions d JOIN agent_evaluation_traces t "
        "ON t.id=d.trace_id WHERE t.policy_id=?", [policy],
    ).fetchone()[0]
    label_id = con.execute(
        "SELECT COALESCE(MAX(id),0)+1 FROM agent_evaluation_labels"
    ).fetchone()[0]
    con.execute(
        "INSERT INTO agent_evaluation_labels VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [label_id, 1, decision_id, 5, date(2026, 9, 2), date(2026, 9, 8),
         100.0, 100 * (1 + asset_return), asset_return, 0.01, asset_return - 0.01,
         -0.02, 0.04, prefix, NOW, f"{label_id:064x}"],
    )


def test_report_scores_and_pairs_only_identical_outcome_prefixes(con):
    agent_evaluation.init_schema(con)
    left, right = list(agent_evaluation.POLICIES)[:2]
    agent_evaluation.record_trace(con, _trace(left, "buy", 0.8))
    agent_evaluation.record_trace(con, _trace(right, "sell", 0.7))
    _label(con, left, 0.05)
    _label(con, right, 0.05)

    report = agent_evaluation_reporting.build_report(con, generated_at=NOW)

    assert report["policies"][left]["directional_accuracy"] == 1.0
    assert report["policies"][left]["brier_score"] == pytest.approx(0.04)
    horizon = report["policies"][left]["by_horizon"]["5"]
    assert horizon == {
        "labeled_action_count": 1, "directional_accuracy": 1.0,
        "brier_score": pytest.approx(0.04), "mean_signed_return": 0.05,
        "mean_excess_return": 0.04, "mean_adverse_excursion": -0.02,
        "mean_favorable_excursion": 0.04,
        "agent_vs_long_candidate_delta": 0.0, "agent_vs_cash_delta": 0.05,
        "confusion_matrix": {"true_positive": 1, "false_positive": 0,
                             "true_negative": 0, "false_negative": 0},
    }
    assert report["policies"][right]["directional_accuracy"] == 0.0
    pair = next(item for item in report["pairs"]
                if item["left_policy"] == left and item["right_policy"] == right)
    assert pair["paired_count"] == 1
    assert pair["left_wins"] == 1
    assert pair["mean_signed_return_delta"] == pytest.approx(0.10)
    assert pair["same_input_count"] == 1
    con.execute(
        "UPDATE agent_evaluation_labels SET price_prefix_sha256=? WHERE decision_id=("
        "SELECT d.id FROM agent_evaluation_decisions d JOIN agent_evaluation_traces t "
        "ON t.id=d.trace_id WHERE t.policy_id=?)", ["8" * 64, right],
    )
    changed = agent_evaluation_reporting.build_report(con, generated_at=NOW)
    pair = next(item for item in changed["pairs"]
                if item["left_policy"] == left and item["right_policy"] == right)
    assert pair["paired_count"] == 0 and pair["incompatible_outcome_count"] == 1


def test_report_accounts_for_missing_labels_and_absent_forecasts(con):
    agent_evaluation.init_schema(con)
    policy = next(iter(agent_evaluation.POLICIES))
    trace = _trace(policy, "none", 0.5)
    trace["decisions"][0]["decision"] = "watch"
    agent_evaluation.record_trace(con, trace)

    report = agent_evaluation_reporting.build_report(con, generated_at=NOW)

    assert report["coverage"]["decision_count"] == 1
    assert report["coverage"]["mature_expected_label_count"] == 0
    assert report["coverage"]["missing_mature_label_count"] == 0
    assert report["coverage"]["immature_label_count"] == 4
    assert report["coverage"]["scheduled_window_status"] == "complete"
    assert report["policies"][policy]["abstention_rate"] == 1.0
    assert report["policies"][policy]["forecast_error"]["status"] == "unavailable"
    for offset in range(1, 3):
        session = date(2026, 9, 1 + offset)
        con.execute(
            "INSERT INTO prices (ticker,date,open,high,low,close,volume) "
            "VALUES ('SPY',?,?,?,?,?,?)", [session, 100, 101, 99, 100, 1_000],
        )
    missing = agent_evaluation_reporting.build_report(con, generated_at=NOW)
    assert missing["coverage"]["mature_expected_label_count"] == 1
    assert missing["coverage"]["missing_mature_label_count"] == 1
    assert missing["coverage"]["immature_label_count"] == 3


def test_report_accounts_for_due_cadence_windows(con, tmp_path):
    agent_evaluation.init_schema(con)
    registration = tmp_path / "cadence.json"
    registration.write_text(json.dumps({
        "evaluation_start_at": "2026-09-23T00:00:00Z",
        "variants": [
            {"id": "nightly_opportunity_tool_v1", "cadence": "nightly",
             "timezone": "UTC", "scheduled_local_times": ["02:00"]},
            {"id": "hourly_market_watch_v1", "cadence": "hourly",
             "timezone": "America/New_York", "scheduled_local_times": ["09:15"]},
        ],
    }))
    con.execute(
        "INSERT INTO prices (ticker,date,open,high,low,close,volume) "
        "VALUES ('SPY','2026-09-23',100,101,99,100,1000)"
    )
    report = agent_evaluation_reporting.build_report(
        con, generated_at=datetime(2026, 9, 24, 1, tzinfo=timezone.utc),
        registration_path=registration,
    )
    assert report["coverage"]["scheduled_window_status"] == "incomplete"
    assert report["coverage"]["expected_window_count"] == 1
    assert report["coverage"]["missing_window_count"] == 1


def test_expected_windows_uses_dst_aware_utc_bucket_ids():
    variants = [{"id": "hourly_market_watch_v1", "cadence": "hourly",
                 "timezone": "America/New_York", "scheduled_local_times": ["09:15"]}]
    summer = expected_windows(
        datetime(2026, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 2, tzinfo=timezone.utc),
        [date(2026, 7, 1)], variants,
    )
    winter = expected_windows(
        datetime(2026, 12, 1, tzinfo=timezone.utc), datetime(2026, 12, 2, tzinfo=timezone.utc),
        [date(2026, 12, 1)], variants,
    )
    assert summer == {"hourly_market_watch_v1:2026-07-01T13"}
    assert winter == {"hourly_market_watch_v1:2026-12-01T14"}


def test_contamination_report_never_claims_promotion(tmp_path):
    path = tmp_path / "result.json"
    path.write_text(json.dumps({
        "interpretation": "contaminated_retrospective_diagnostic_only",
        "known_contamination": ["possible_model_training_memory"],
        "results": [
            {"variant": "price_named", "decision_date": "2022-01-31",
             "selected_ticker": "XOM",
             "decision": {"direction": "up", "confidence": 0.6,
                          "expected_return_pct": 5.0}},
            {"variant": "price_blinded", "decision_date": "2022-01-31",
             "selected_ticker": "XOM",
             "decision": {"direction": "up", "confidence": 0.7,
                          "expected_return_pct": 4.0}},
        ],
    }))

    result = contamination_diagnostics((path,))

    assert result["promotion_authority"] == "none"
    assert result["probes"]["named_vs_blinded"] == "complete"
    assert result["probes"]["synthetic_perturbation"] == "not_run"
    assert result["choice_agreement"] == result["direction_agreement"] == 1.0
    assert result["variant_comparisons"]["price_blinded"]["choice_agreement"] == 1.0


def test_report_projects_execution_quality_without_ambiguous_columns(con):
    daily_opportunity_store.init_schema(con)
    con.execute(
        "INSERT INTO portfolios (id,initial_cash) VALUES ('daily_opportunity_agent_v1',10000)"
    )
    con.execute(
        "INSERT INTO sim_fills VALUES (1,'daily_opportunity_agent_v1','SPY','buy',2,"
        "'2026-09-02',101,101.1,10,10)"
    )
    con.execute(
        "INSERT INTO daily_opportunity_execution_quality "
        "(order_id,assessment_id,side,decision_at,tool_started_at,tool_completed_at,"
        "order_recorded_at,fill_date,fill_time_precision,decision_to_tool_ms,tool_latency_ms,"
        "tool_to_order_ms,order_to_fill_sessions,arrival_price,open_price,fill_price,"
        "gap_shortfall_bps,total_shortfall_bps,cost_bps,captured_at,quality_sha256,"
        "post_fill_position_qty,post_fill_cash,post_fill_equity,equity_as_of) VALUES ("
        "1,1,'buy',?,?,?,?, '2026-09-02','session_open_date',1,2,3,1,100,101,101.1,"
        "100,110,10,?,?,2,9797.8,NULL,NULL)",
        [NOW, NOW, NOW, NOW, NOW, "a" * 64],
    )

    report = agent_evaluation_reporting.build_report(con, generated_at=NOW)

    assert report["execution"]["fill_count"] == 1
    assert report["execution"]["mean_cost_bps"] == 10.0
    assert report["execution"]["turnover_notional"] == pytest.approx(202.2)


def test_report_cli_atomically_publishes_empty_forward_state(tmp_path):
    database, output = tmp_path / "market.duckdb", tmp_path / "report.json"
    con = db.connect(database)
    agent_evaluation.init_schema(con)
    con.close()

    assert agent_evaluation_reporting.main([
        "--database", str(database), "--output", str(output),
        "--contamination", str(tmp_path / "absent.json"),
    ]) == 0

    report = json.loads(output.read_text())
    assert report["coverage"]["trace_count"] == 0
    assert report["contamination"]["status"] == "unavailable"
    assert report["promotion_authority"] == "none"
    assert report["data_provenance"]["historical_membership_authority"] is False
