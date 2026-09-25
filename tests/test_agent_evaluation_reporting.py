"""Canonical paired agent scoring and contamination diagnostics."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from engine.lib import db
from farm.agent_evaluation_analysis import contamination_diagnostics, expected_windows
from server import agent_evaluation, agent_evaluation_reporting, daily_opportunity_store

NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


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
        "INSERT INTO agent_evaluation_labels "
        "(id,schema_version,decision_id,horizon_sessions,entry_date,exit_date,entry_open,"
        "exit_close,asset_return,spy_return,excess_return,maximum_adverse_excursion,"
        "maximum_favorable_excursion,price_prefix_sha256,labeled_at,label_sha256,"
        "round_trip_cost_bps,net_return,net_excess_return) VALUES "
        "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [label_id, 1, decision_id, 5, date(2026, 9, 2), date(2026, 9, 8),
         100.0, 100 * (1 + asset_return), asset_return, 0.01, asset_return - 0.01,
         -0.02, 0.04, prefix, NOW, f"{label_id:064x}", 20.0, asset_return,
         asset_return - 0.01],
    )
    label_v2_id = con.execute(
        "SELECT COALESCE(MAX(id),0)+1 FROM agent_evaluation_labels_v2"
    ).fetchone()[0]
    con.execute(
        "INSERT INTO agent_evaluation_labels_v2 VALUES ("
        + ",".join("?" for _ in range(21))
        + ")",
        [label_v2_id, 1, decision_id, 5, "common_entry", date(2026, 9, 2),
         date(2026, 9, 8), 100.0, 100 * (1 + asset_return), asset_return, 0.01,
         asset_return - 0.01, -0.02, 0.04, prefix, "complete", NOW,
         f"{label_v2_id + 1000:064x}", 20.0, asset_return, asset_return - 0.01],
    )


def test_report_scores_and_pairs_only_identical_outcome_prefixes(con):
    agent_evaluation.init_schema(con)
    left, right = list(agent_evaluation.POLICIES)[:2]
    left_trace = _trace(left, "buy", 0.8)
    left_trace.update(window_id="nightly:2026-09-25", market_date=date(2026, 9, 25))
    right_trace = _trace(right, "sell", 0.7)
    observed = datetime(2026, 9, 28, 14, tzinfo=timezone.utc)
    right_trace.update(
        window_id="hourly_market_watch_v5:2026-09-28T14",
        market_date=date(2026, 9, 25),
        observed_at=observed,
        information_cutoff_at=observed,
        completed_at=observed,
    )
    agent_evaluation.record_trace(con, left_trace)
    agent_evaluation.record_trace(con, right_trace)
    _label(con, left, 0.05)
    _label(con, right, 0.05)
    con.execute(
        "INSERT INTO prices (ticker,date,open,high,low,close,volume) "
        "VALUES ('SPY','2026-09-28',100,101,99,100,1000)"
    )

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
        "UPDATE agent_evaluation_labels_v2 SET price_prefix_sha256=? WHERE decision_id=("
        "SELECT d.id FROM agent_evaluation_decisions d JOIN agent_evaluation_traces t "
        "ON t.id=d.trace_id WHERE t.policy_id=?)", ["8" * 64, right],
    )
    changed = agent_evaluation_reporting.build_report(con, generated_at=NOW)
    pair = next(item for item in changed["pairs"]
                if item["left_policy"] == left and item["right_policy"] == right)
    assert pair["paired_count"] == 0 and pair["incompatible_outcome_count"] == 1


def test_p8_trace_cannot_use_p15_decision_vocabulary(con):
    agent_evaluation.init_schema(con)
    trace = _trace("nightly_opportunity_tool_v1", "none", 0.5)
    trace["decisions"][0]["decision"] = "buy_candidate"

    with pytest.raises(agent_evaluation.EvaluationError, match="decision values"):
        agent_evaluation.record_trace(con, trace)


def test_common_entry_pairing_uses_first_window_and_reports_all_windows(con):
    agent_evaluation.init_schema(con)
    market_date = date(2026, 9, 25)
    observed = datetime(2026, 9, 28, 15, tzinfo=timezone.utc)
    nightly = _trace("nightly_opportunity_tool_v1", "buy", 0.7)
    nightly.update(
        window_id="nightly:2026-09-25",
        market_date=market_date,
        observed_at=datetime(2026, 9, 26, 2, tzinfo=timezone.utc),
        information_cutoff_at=datetime(2026, 9, 26, 2, tzinfo=timezone.utc),
        completed_at=datetime(2026, 9, 26, 2, tzinfo=timezone.utc),
    )
    hourly = _trace("hourly_market_watch_v5", "buy", 0.6)
    hourly.update(
        window_id="hourly_market_watch_v5:2026-09-28T14",
        market_date=market_date,
        observed_at=observed,
        information_cutoff_at=observed,
        completed_at=observed,
    )
    later = {**hourly, "window_id": "hourly_market_watch_v5:2026-09-28T15"}
    for trace in (nightly, hourly, later):
        trace["decisions"] = [{
            **trace["decisions"][0],
            "ticker": "FAST",
        }]
        agent_evaluation.record_trace(con, trace)
    for session, close in (
        (date(2026, 9, 28), 101.0),
        (date(2026, 9, 29), 103.0),
    ):
        for ticker in ("SPY", "FAST"):
            con.execute(
                "INSERT INTO prices (ticker,date,open,high,low,close,volume) "
                "VALUES (?,?,?,?,?,?,?)",
                [ticker, session, close - 1, close + 1, close - 2, close, 1_000],
            )

    con.execute("UPDATE prices SET fetched_at=?", [NOW.replace(tzinfo=None)])
    agent_evaluation.label_mature(con, labeled_at=NOW)

    legacy_entries = dict(con.execute(
        "SELECT t.policy_id,MIN(l.entry_date) FROM agent_evaluation_labels l "
        "JOIN agent_evaluation_decisions d ON d.id=l.decision_id "
        "JOIN agent_evaluation_traces t ON t.id=d.trace_id "
        "WHERE l.horizon_sessions=1 GROUP BY t.policy_id"
    ).fetchall())
    assert legacy_entries == {
        "nightly_opportunity_tool_v1": date(2026, 9, 28),
        "hourly_market_watch_v5": date(2026, 9, 29),
    }
    common = con.execute(
        "SELECT COUNT(*),COUNT(DISTINCT entry_date),MIN(entry_date) "
        "FROM agent_evaluation_labels_v2 WHERE label_basis='common_entry' "
        "AND horizon_sessions=1"
    ).fetchone()
    assert common == (3, 1, date(2026, 9, 29))
    report = agent_evaluation_reporting.build_report(con, generated_at=NOW)
    primary = next(item for item in report["pairs"]
                   if item["right_policy"] == "hourly_market_watch_v5")
    secondary = next(item for item in report["pairs_all_windows"]
                     if item["right_policy"] == "hourly_market_watch_v5")
    assert primary["window_scope"] == "first" and primary["paired_count"] == 1
    assert primary["right_ambiguous_count"] == 0
    assert secondary["window_scope"] == "all" and secondary["paired_count"] == 2


@pytest.mark.parametrize("first_window", ["unavailable", "absent"])
def test_missing_first_window_is_not_replaced_in_primary_pairing(con, first_window):
    agent_evaluation.init_schema(con)
    market_date = date(2026, 9, 25)
    nightly = _trace("nightly_opportunity_tool_v1", "buy", 0.7)
    nightly.update(
        window_id="nightly:2026-09-25",
        market_date=market_date,
        observed_at=datetime(2026, 9, 26, 2, tzinfo=timezone.utc),
        information_cutoff_at=datetime(2026, 9, 26, 2, tzinfo=timezone.utc),
        completed_at=datetime(2026, 9, 26, 2, tzinfo=timezone.utc),
    )
    first = _trace("hourly_market_watch_v5", "none", 0.0)
    first.update(
        window_id="hourly_market_watch_v5:2026-09-28T14",
        market_date=market_date,
        observed_at=datetime(2026, 9, 28, 14, tzinfo=timezone.utc),
        information_cutoff_at=datetime(2026, 9, 28, 14, tzinfo=timezone.utc),
        completed_at=datetime(2026, 9, 28, 14, tzinfo=timezone.utc),
    )
    first["decisions"][0].update(
        ticker="FAST", decision="unavailable", action="none", confidence=0.0
    )
    later = _trace("hourly_market_watch_v5", "buy", 0.6)
    later.update(
        window_id="hourly_market_watch_v5:2026-09-28T15",
        market_date=market_date,
        observed_at=datetime(2026, 9, 28, 15, tzinfo=timezone.utc),
        information_cutoff_at=datetime(2026, 9, 28, 15, tzinfo=timezone.utc),
        completed_at=datetime(2026, 9, 28, 15, tzinfo=timezone.utc),
    )
    nightly["decisions"][0]["ticker"] = "FAST"
    later["decisions"][0]["ticker"] = "FAST"
    traces = (nightly, later) if first_window == "absent" else (nightly, first, later)
    for trace in traces:
        agent_evaluation.record_trace(con, trace)
    for session in (date(2026, 9, 28), date(2026, 9, 29)):
        for ticker in ("SPY", "FAST"):
            con.execute(
                "INSERT INTO prices (ticker,date,open,high,low,close,volume) "
                "VALUES (?,?,?,?,?,?,?)",
                [ticker, session, 100, 102, 99, 101, 1_000],
            )

    con.execute("UPDATE prices SET fetched_at=?", [NOW.replace(tzinfo=None)])
    agent_evaluation.label_mature(con, labeled_at=NOW)
    report = agent_evaluation_reporting.build_report(con, generated_at=NOW)

    primary = next(item for item in report["pairs"]
                   if item["right_policy"] == "hourly_market_watch_v5")
    secondary = next(item for item in report["pairs_all_windows"]
                     if item["right_policy"] == "hourly_market_watch_v5")
    assert primary["paired_count"] == 0
    assert secondary["paired_count"] == 1


def test_precohort_trace_is_retained_but_excluded_from_evaluation(con):
    agent_evaluation.init_schema(con)
    trace = _trace("hourly_market_watch_v5", "none", 0.5)
    before_start = datetime(2026, 9, 25, 16, 55, tzinfo=timezone.utc)
    trace.update(
        window_id="hourly_market_watch_v5:2026-09-25T16",
        market_date=date(2026, 9, 24),
        observed_at=before_start,
        information_cutoff_at=before_start,
        completed_at=before_start,
    )
    trace["decisions"][0].update(decision="watch", action="none")
    agent_evaluation.record_trace(con, trace)
    _label(con, "hourly_market_watch_v5", 0.01)

    report = agent_evaluation_reporting.build_report(con, generated_at=NOW)

    assert con.execute("SELECT COUNT(*) FROM agent_evaluation_traces").fetchone() == (1,)
    assert report["policies"]["hourly_market_watch_v5"]["trace_count"] == 0
    assert report["coverage"]["decision_count"] == 0


def test_common_entry_labels_missing_path_at_last_available_close(con):
    agent_evaluation.init_schema(con)
    market_date = date(2026, 9, 25)
    nightly = _trace("nightly_opportunity_tool_v1", "buy", 0.7)
    nightly.update(
        window_id="nightly:2026-09-25",
        market_date=market_date,
        observed_at=datetime(2026, 9, 26, 2, tzinfo=timezone.utc),
        information_cutoff_at=datetime(2026, 9, 26, 2, tzinfo=timezone.utc),
        completed_at=datetime(2026, 9, 26, 2, tzinfo=timezone.utc),
    )
    hourly = _trace("hourly_market_watch_v5", "buy", 0.6)
    hourly.update(
        window_id="hourly_market_watch_v5:2026-09-28T15",
        market_date=market_date,
        observed_at=datetime(2026, 9, 28, 15, tzinfo=timezone.utc),
        information_cutoff_at=datetime(2026, 9, 28, 15, tzinfo=timezone.utc),
        completed_at=datetime(2026, 9, 28, 15, tzinfo=timezone.utc),
    )
    for trace in (nightly, hourly):
        trace["decisions"][0]["ticker"] = "FAST"
        agent_evaluation.record_trace(con, trace)
    sessions = [
        date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30),
        date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5),
    ]
    for index, session in enumerate(sessions):
        con.execute(
            "INSERT INTO prices (ticker,date,open,high,low,close,volume) "
            "VALUES ('SPY',?,?,?,?,?,?)",
            [session, 100 + index, 102 + index, 99 + index, 101 + index, 1_000],
        )
    for index, session in enumerate(sessions[1:3]):
        con.execute(
            "INSERT INTO prices (ticker,date,open,high,low,close,volume) "
            "VALUES ('FAST',?,?,?,?,?,?)",
            [session, 100 + index, 102 + index, 99 + index, 101 + index, 1_000],
        )

    con.execute(
        "UPDATE prices SET fetched_at=?",
        [datetime(2026, 10, 6, tzinfo=timezone.utc).replace(tzinfo=None)],
    )
    agent_evaluation.label_mature(
        con, labeled_at=datetime(2026, 10, 6, tzinfo=timezone.utc)
    )

    rows = con.execute(
        "SELECT label_basis,missing_bar_status,entry_date,exit_date "
        "FROM agent_evaluation_labels_v2 WHERE horizon_sessions=5 ORDER BY decision_id"
    ).fetchall()
    assert rows == [
        ("common_entry", "last_available_close", date(2026, 9, 29), date(2026, 9, 30)),
        ("common_entry", "last_available_close", date(2026, 9, 29), date(2026, 9, 30)),
    ]


def test_v2_label_records_missing_entry_at_prior_last_close(con):
    labeled_at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    for session in (date(2026, 9, 29), date(2026, 9, 30)):
        con.execute(
            "INSERT INTO prices (ticker,date,open,high,low,close,volume,fetched_at) "
            "VALUES ('SPY',?,?,?,?,?,?,?)",
            [session, 100, 102, 99, 101, 1_000, labeled_at.replace(tzinfo=None)],
        )
    con.execute(
        "INSERT INTO prices (ticker,date,open,high,low,close,volume,fetched_at) "
        "VALUES ('FAST','2026-09-28',100,102,99,101,1000,?)",
        [labeled_at.replace(tzinfo=None)],
    )

    outcome = agent_evaluation._label_outcome(
        con, "FAST", [date(2026, 9, 29), date(2026, 9, 30)], labeled_at
    )

    assert outcome["missing_bar_status"] == "missing_entry_last_available_close"
    assert outcome["entry_date"] == date(2026, 9, 29)
    assert outcome["exit_date"] == date(2026, 9, 28)
    assert outcome["net_excess_return"] == 0.0


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
            {"id": "hourly_market_watch_v5", "cadence": "hourly",
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
    variants = [{"id": "hourly_market_watch_v5", "cadence": "hourly",
                 "timezone": "America/New_York", "scheduled_local_times": ["09:15"]}]
    summer = expected_windows(
        datetime(2026, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 2, tzinfo=timezone.utc),
        [date(2026, 7, 1)], variants,
    )
    winter = expected_windows(
        datetime(2026, 12, 1, tzinfo=timezone.utc), datetime(2026, 12, 2, tzinfo=timezone.utc),
        [date(2026, 12, 1)], variants,
    )
    assert summer == {"hourly_market_watch_v5:2026-07-01T13"}
    assert winter == {"hourly_market_watch_v5:2026-12-01T14"}




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
