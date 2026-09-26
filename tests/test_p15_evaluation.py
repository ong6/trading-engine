"""P15 gate statistics and prospective-cohort tests."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from engine import p15_evaluation
from engine.lib import db
from engine.lib.provenance import canonical_sha256
from farm.walkforward.monthly import newey_west_t
from tests.conftest import SESSIONS, insert_bars
from tools import agent_trial_register

NOW = datetime(2026, 12, 1, 12, tzinfo=timezone.utc)


def test_p15_reports_follow_configured_data_directory(tmp_path):
    configured = tmp_path / "restored-data"
    environment = {**os.environ, "TRADING_ENGINE_DATA_DIR": str(configured)}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from engine.p15_evaluation import LOOK_ANCHOR_PATH; "
            "from server.agent_evaluation_reporting import DEFAULT_OUTPUT,DEFAULT_P15_OUTPUT; "
            "print(LOOK_ANCHOR_PATH); print(DEFAULT_OUTPUT); print(DEFAULT_P15_OUTPUT)",
        ],
        cwd=p15_evaluation.REPO_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.splitlines() == [
        str(configured / "reports/agent-eval/p15-look-anchors.jsonl"),
        str(configured / "reports/agent-evaluation.json"),
        str(configured / "reports/agent-eval/p15.md"),
    ]


def test_average_rank_spearman_handles_ties_and_constants():
    assert p15_evaluation.average_ranks([3, 1, 1, 2]) == [4.0, 1.5, 1.5, 3.0]
    assert p15_evaluation.spearman([1, 2, 2, 4], [4, 2, 2, 1]) == pytest.approx(-1)
    assert p15_evaluation.spearman([1, 1], [1, 2]) is None


def test_newey_west_matches_existing_reference():
    values = [0.04, -0.01, 0.03, 0.02, -0.005, 0.01]
    expected = newey_west_t(values, lag=4)
    assert p15_evaluation.newey_west(values, lag=4) == pytest.approx(expected)


def test_primary_interval_matches_hand_computed_hansen_hodrick_answer():
    result = p15_evaluation._hansen_hodrick_interval([1.25, -0.75] * 30)

    assert result["n"] == 60
    assert result["mean"] == pytest.approx(0.25)
    assert result["raw_long_run_variance"] == pytest.approx(14 / 15)
    assert result["variance_inflation"] == pytest.approx(1.22502128663532)
    assert result["long_run_variance"] == pytest.approx(1.143353200859632)
    assert result["se"] == pytest.approx(0.13804306096647476)
    assert result["critical_value"] == pytest.approx(2.128045234184983)
    assert result["lower"] == pytest.approx(-0.043761878002013865)
    assert result["upper"] == pytest.approx(0.5437618780020139)
    assert result["variance_estimator"] == "hansen_hodrick"
    assert result["kernel"] == "uniform" and result["lag"] == 4
    assert result["fallback_used"] is False


def test_primary_interval_uses_fixed_nonoverlapping_offset_zero_sample():
    values = [0.0] * 60
    values[::5] = range(1, 13)

    result = p15_evaluation._primary_interval(values)

    assert result["origin_count"] == 60
    assert result["n"] == 12 and result["df"] == 11
    assert result["mean"] == pytest.approx(6.5)
    assert result["se"] == pytest.approx((13 / 12) ** 0.5)
    assert result["critical_value"] == pytest.approx(2.431291192871)
    assert result["sampling"] == "nonoverlapping_offset0"
    assert result["stride"] == 5 and result["offset"] == 0
    constant = p15_evaluation._primary_interval([1.0] * 60)
    assert constant["se"] is None and constant["lower"] is None


def test_primary_standard_error_falls_back_only_for_nonpositive_hh_variance():
    values = [-1, -1, -1, -1, -1, 0, -1, -1, -1]

    result = p15_evaluation._primary_standard_error(values)
    constant = p15_evaluation._primary_standard_error([1.0] * 60)

    assert result["raw_long_run_variance"] == pytest.approx(46 / 2187)
    assert result["variance_inflation"] == pytest.approx(8.904078604516508)
    assert result["long_run_variance"] == pytest.approx(0.18728286045165035)
    assert result["se"] == pytest.approx(0.1442539660350801)
    assert result["variance_estimator"] == "newey_west"
    assert result["kernel"] == "bartlett" and result["lag"] == 8
    assert result["fallback_used"] is True
    assert constant["se"] is None and constant["long_run_variance"] == 0


def test_primary_three_look_simulation_controls_null_and_detects_planted_ic():
    rng = np.random.default_rng(20260926)
    false_passes = planted_passes = 0
    trials = 10_000
    for _ in range(trials):
        shocks = rng.normal(0.0, 0.1, 124)
        delta = np.convolve(shocks, np.ones(5) / 5, mode="valid")
        for shift, counter in ((0.0, "null"), (0.03, "planted")):
            scored = [
                {"delta_ic": float(value + shift),
                 "model_ic": float(value + shift), "baseline_ic": 0.0,
                 "evaluated_at": NOW.isoformat(),
                 "market_date": (
                     date(2026, 1, 1) + timedelta(days=index)
                 ).isoformat()}
                for index, value in enumerate(delta)
            ]
            passed = p15_evaluation.evaluate_looks(scored)[0] == "pass"
            if counter == "null":
                false_passes += passed
            else:
                planted_passes += passed
    assert false_passes == 347
    assert planted_passes == 8_638


def test_fixed_looks_use_immutable_prefixes_and_terminal_rules():
    positive = [{"delta_ic": 0.2 + (index % 3) * 0.01,
                 "model_ic": 0.3, "baseline_ic": 0.09,
                 "evaluated_at": NOW.isoformat(),
                 "market_date": (date(2026, 1, 1) + timedelta(days=index)).isoformat()}
                for index in range(61)]
    status, looks, next_look = p15_evaluation.evaluate_looks(positive)
    assert status == "pass" and [item["look"] for item in looks] == [60]
    assert looks[0]["delta"]["n"] == 12 and next_look is None
    assert looks[0]["hansen_hodrick_diagnostic"]["n"] == 60
    status, looks, next_look = p15_evaluation.evaluate_looks(positive[:59])
    assert (status, looks, next_look) == ("collecting", [], 60)
    neutral = [{"delta_ic": (-1) ** index * 0.01,
                "model_ic": 0.1, "baseline_ic": 0.1,
                "evaluated_at": NOW.isoformat(),
                "market_date": (date(2026, 1, 1) + timedelta(days=index)).isoformat()}
               for index in range(120)]
    status, looks, next_look = p15_evaluation.evaluate_looks(neutral)
    assert status == "kill" and looks[-1]["look"] == 120 and next_look is None


def test_reached_look_is_persisted_once_and_tamper_evident(con, monkeypatch, tmp_path):
    scored = [
        {"delta_ic": 0.2 + (index % 3) * 0.01,
         "model_ic": 0.3, "baseline_ic": 0.09, "pair_count": 40,
         "evaluated_at": NOW.isoformat(),
         "market_date": (date(2026, 1, 1) + timedelta(days=index)).isoformat()}
        for index in range(60)
    ]
    registration_sha = "a" * 64
    anchor_path = tmp_path / "look-anchors.jsonl"
    p15_evaluation.init_look_schema(con)

    first = p15_evaluation.persist_reached_looks(
        con, scored, registration_sha, evaluated_at=NOW, anchor_path=anchor_path,
    )
    with db.transaction(con):
        assert p15_evaluation.publish_pending_look_anchors(
            con, registration_sha, anchor_path=anchor_path,
        ) == 1
    first_anchor = anchor_path.read_text()
    con.execute(
        "UPDATE p15_evaluation_look_anchors SET external_anchor_sha256=NULL"
    )
    with db.transaction(con):
        assert p15_evaluation.publish_pending_look_anchors(
            con, registration_sha, anchor_path=anchor_path,
        ) == 1
    assert anchor_path.read_text() == first_anchor
    retained = con.execute(
        "SELECT result_payload,look_sha256 FROM p15_evaluation_looks"
    ).fetchone()
    monkeypatch.setattr(
        p15_evaluation, "_look",
        lambda *_args: (_ for _ in ()).throw(AssertionError("look recomputed")),
    )
    replay = p15_evaluation.persist_reached_looks(
        con, scored, registration_sha, evaluated_at=NOW, anchor_path=anchor_path,
    )

    assert first == replay
    assert first[0]["look"] == 60 and first[0]["status"] == "pass"
    assert con.execute("SELECT COUNT(*) FROM p15_evaluation_looks").fetchone() == (1,)
    assert con.execute(
        "SELECT result_payload,look_sha256 FROM p15_evaluation_looks"
    ).fetchone() == retained

    anchor_path.unlink()
    with pytest.raises(p15_evaluation.P15EvaluationError, match="look evidence differs"):
        p15_evaluation.load_retained_looks(
            con, scored, registration_sha, anchor_path=anchor_path,
        )
    anchor_path.write_text(first_anchor)
    con.execute("UPDATE p15_evaluation_looks SET result_payload='{}'")
    with pytest.raises(p15_evaluation.P15EvaluationError, match="look evidence differs"):
        p15_evaluation.load_retained_looks(
            con, scored, registration_sha, anchor_path=anchor_path,
        )
    con.execute(
        "UPDATE p15_evaluation_looks SET result_payload=?,look_sha256=?",
        list(retained),
    )
    con.execute("DELETE FROM p15_evaluation_looks")
    with pytest.raises(p15_evaluation.P15EvaluationError, match="look evidence differs"):
        p15_evaluation.persist_reached_looks(
            con, scored, registration_sha, evaluated_at=NOW,
            anchor_path=anchor_path,
        )
    con.execute("DELETE FROM p15_evaluation_look_anchors")
    with pytest.raises(p15_evaluation.P15EvaluationError, match="look evidence differs"):
        p15_evaluation.persist_reached_looks(
            con, scored, registration_sha, evaluated_at=NOW,
            anchor_path=anchor_path,
        )


def test_rolled_back_look_never_publishes_external_anchor(con, tmp_path):
    scored = [
        {"delta_ic": 0.2 + (index % 3) * 0.01,
         "model_ic": 0.3, "baseline_ic": 0.09, "pair_count": 40,
         "evaluated_at": NOW.isoformat(),
         "market_date": (date(2026, 1, 1) + timedelta(days=index)).isoformat()}
        for index in range(60)
    ]
    registration_sha = "a" * 64
    anchor_path = tmp_path / "look-anchors.jsonl"
    p15_evaluation.init_look_schema(con)

    with pytest.raises(RuntimeError, match="after look insert"):
        with db.transaction(con):
            p15_evaluation.persist_reached_looks(
                con, scored, registration_sha, evaluated_at=NOW,
                anchor_path=anchor_path,
            )
            raise RuntimeError("after look insert")

    assert con.execute("SELECT COUNT(*) FROM p15_evaluation_looks").fetchone() == (0,)
    assert con.execute(
        "SELECT COUNT(*) FROM p15_evaluation_look_anchors"
    ).fetchone() == (0,)
    assert not anchor_path.exists()


def _primary_schema(con):
    con.execute("CREATE TABLE agent_evaluation_traces "
                "(id BIGINT,market_date DATE,observed_at TIMESTAMP,policy_id VARCHAR)")
    con.execute("CREATE TABLE agent_evaluation_decisions "
                "(id BIGINT,trace_id BIGINT,decision VARCHAR,decision_payload VARCHAR)")
    con.execute("CREATE TABLE agent_evaluation_labels_v2 "
                "(decision_id BIGINT,horizon_sessions INTEGER,label_basis VARCHAR,"
                "net_excess_return DOUBLE,missing_bar_status VARCHAR,labeled_at TIMESTAMP)")


def test_primary_scores_same_mature_cohort_and_flags_missing_labels(con):
    _primary_schema(con)
    market_date = date(2024, 7, 1)
    con.execute(
        "INSERT INTO agent_evaluation_traces VALUES (1,?,?,'p15-scoring-v1')",
        [market_date, datetime(2024, 7, 1, 22)],
    )
    for index in range(20):
        payload = {"stratum": "mover", "scoring_status": "available",
                   "p_outperform_5": 0.01 + index / 25,
                   "expected_excess_bp_5": float(index),
                   "expected_excess_bp_10": float(index), "baseline_score": 20 - index}
        con.execute(
            "INSERT INTO agent_evaluation_decisions VALUES (?,?,?,?)",
            [index + 1, 1, "buy_candidate", json.dumps(payload)],
        )
        con.execute(
            "INSERT INTO agent_evaluation_labels_v2 VALUES (?,?,?,?,?,?)",
            [index + 1, 5, "next_session_open", float(index), "complete", NOW],
        )
    sessions = [market_date + timedelta(days=index) for index in range(1, 9)]
    insert_bars(con, "SPY", sessions, open_=100, close=100, high=101, low=99)
    con.execute("UPDATE prices SET fetched_at=?", [NOW.replace(tzinfo=None)])

    result = p15_evaluation.primary(con, NOW)

    assert result["status"] == "collecting"
    assert result["scored_session_count"] == 1
    assert result["diagnostics"]["model_brier"] is not None
    con.execute(
        "INSERT INTO agent_evaluation_decisions VALUES (21,1,'unavailable',?)",
        [json.dumps({"stratum": "held_only", "scoring_status": "unavailable"})],
    )
    irrelevant = p15_evaluation.primary(con, NOW)
    assert irrelevant["status"] == "collecting"
    assert irrelevant["missing_mature_label_count"] == 0
    con.execute("DELETE FROM agent_evaluation_labels_v2 WHERE decision_id=1")
    assert p15_evaluation.primary(con, NOW)["status"] == "invalid"


def test_primary_waits_three_sessions_before_invalidating_missing_used_label(con):
    _primary_schema(con)
    market_date = date(2024, 7, 1)
    con.execute(
        "INSERT INTO agent_evaluation_traces VALUES (1,?,?,'p15-scoring-v1')",
        [market_date, datetime(2024, 7, 1, 22)],
    )
    for index in range(21):
        payload = {
            "stratum": "mover", "scoring_status": "available",
            "p_outperform_5": 0.01 + index / 25,
            "expected_excess_bp_5": float(index),
            "expected_excess_bp_10": float(index), "baseline_score": 21 - index,
        }
        con.execute(
            "INSERT INTO agent_evaluation_decisions VALUES (?,?,?,?)",
            [index + 1, 1, "buy_candidate", json.dumps(payload)],
        )
        if index < 20:
            con.execute(
                "INSERT INTO agent_evaluation_labels_v2 VALUES (?,?,?,?,?,?)",
                [index + 1, 5, "next_session_open", float(index), "complete", NOW],
            )
    first_five = [market_date + timedelta(days=index) for index in range(1, 6)]
    insert_bars(con, "SPY", first_five, open_=100, close=100, high=101, low=99)
    con.execute("UPDATE prices SET fetched_at=?", [NOW.replace(tzinfo=None)])

    waiting = p15_evaluation.primary(con, NOW)

    assert waiting["status"] == "collecting"
    assert waiting["missing_mature_label_count"] == 0
    assert waiting["immature_session_count"] == 1
    assert waiting["scored_session_count"] == 0

    later = [market_date + timedelta(days=index) for index in range(6, 9)]
    insert_bars(con, "SPY", later, open_=100, close=100, high=101, low=99)
    con.execute("UPDATE prices SET fetched_at=?", [NOW.replace(tzinfo=None)])

    expired = p15_evaluation.primary(con, NOW)
    assert expired["status"] == "invalid"
    assert expired["missing_mature_label_count"] == 1


def test_book_projection_pairs_only_identical_intervals_and_counts_stock_exits(con):
    con.execute("CREATE TABLE p15_book_contracts (portfolio_id VARCHAR)")
    con.execute("CREATE TABLE p15_book_windows "
                "(portfolio_id VARCHAR,market_date DATE,equity DOUBLE)")
    con.execute("CREATE TABLE p15_book_fills "
                "(intent_id BIGINT,portfolio_id VARCHAR,ticker VARCHAR,qty DOUBLE,"
                "fill_px DOUBLE,fill_date DATE)")
    con.execute("CREATE TABLE p15_order_intents "
                "(id BIGINT,portfolio_id VARCHAR,ticker VARCHAR,side VARCHAR,status VARCHAR)")
    dates = [date(2026, 1, 2)]
    while (dates[-1] - dates[0]).days < 90:
        dates.append(p15_evaluation.nyse.next_session(dates[-1]))
    growth = {"p15_ai_ranked": 1, "p15_rule_control": 3, "p15_hybrid_veto": 2}
    for offset, book in enumerate(p15_evaluation.BOOK_IDS):
        con.execute(
            "INSERT INTO portfolios (id,active,initial_cash) VALUES (?,?,10000)",
            [book, True],
        )
        con.execute("INSERT INTO p15_book_contracts VALUES (?)", [book])
        con.executemany(
            "INSERT INTO p15_book_windows VALUES (?,?,?)",
            [(book, day, 10_000 * (1 + growth[book] * index / 10_000))
             for index, day in enumerate(dates)],
        )
        for index in range(30):
            intent = offset * 100 + index + 1
            con.execute(
                "INSERT INTO p15_order_intents VALUES (?,?,?,'sell','filled')",
                [intent, book, f"T{index}"],
            )
            con.execute(
                "INSERT INTO p15_book_fills VALUES (?,?,?,?,?,?)",
                [intent, book, f"T{index}", 1, 100, dates[-1]],
            )
    con.execute(
        "DELETE FROM p15_book_windows WHERE portfolio_id='p15_ai_ranked' AND market_date=?",
        [dates[10]],
    )

    result = p15_evaluation.books(con, {
        "status": "collecting",
        "book_look_dates": [{"look": 60, "through_market_date": dates[-6].isoformat(),
                             "evaluated_at": datetime.combine(
                                 dates[-1], datetime.min.time(), timezone.utc
                             ).isoformat()}],
    })

    assert all(item["comparison_eligible"] for item in result["books"])
    pairs = {item["challenger"]: item["paired_return_count"]
             for item in result["comparisons"]}
    assert pairs == {"p15_ai_ranked": len(dates) - 3,
                     "p15_hybrid_veto": len(dates) - 1}
    assert all(item["turnover_notional"] == 3_000 for item in result["books"])
    terminal = p15_evaluation.books(con, {
        "status": "pass",
        "book_look_dates": [{"look": 120, "through_market_date": dates[-6].isoformat(),
                             "evaluated_at": datetime.combine(
                                 dates[-1], datetime.min.time(), timezone.utc
                             ).isoformat()}],
    })
    assert terminal["status"] == "inconclusive"
    assert terminal["comparisons"][0]["promotion_status"] == "inconclusive"


def test_preopen_cancel_metrics_exclude_limit_misses_and_pending_labels(con):
    con.execute("CREATE TABLE p15_preopen_runs "
                "(id BIGINT,policy_id VARCHAR,status VARCHAR,completed_at TIMESTAMP)")
    con.execute("CREATE TABLE p15_preopen_decisions "
                "(id BIGINT,run_id BIGINT,intent_id BIGINT,portfolio_id VARCHAR,decision VARCHAR,"
                "applied_at TIMESTAMP)")
    con.execute("CREATE TABLE p15_limit_attempts "
                "(intent_id BIGINT,attempt_date DATE,outcome VARCHAR)")
    con.execute("CREATE TABLE p15_limit_labels "
                "(intent_id BIGINT,net_excess_return DOUBLE,labeled_at TIMESTAMP)")
    con.execute("INSERT INTO p15_preopen_runs VALUES (1,'p15-preopen-v1','completed',?)", [NOW])
    con.executemany("INSERT INTO p15_preopen_decisions VALUES (?,?,?,?,?,?)", [
        (1, 1, 1, "p15_ai_ranked", "cancel", NOW),
        (2, 1, 2, "p15_ai_ranked", "cancel", NOW),
        (3, 1, 3, "p15_ai_ranked", "cancel", NOW),
    ])
    con.executemany("INSERT INTO p15_limit_attempts VALUES (?,?,?)", [
        (1, date(2026, 9, 28), "cancelled_would_fill"),
        (2, date(2026, 9, 28), "cancelled_limit_not_reached"),
        (3, date(2026, 9, 28), "cancelled_would_fill"),
    ])
    con.execute("INSERT INTO p15_limit_labels VALUES (1,-0.02,?)", [NOW])

    result = p15_evaluation.preopen(con, NOW)["books"][0]

    assert result["cancel_count"] == 3 and result["effective_cancel_count"] == 2
    assert result["ineffective_limit_miss_count"] == result["pending_label_count"] == 1
    assert result["cancel_hit_rate"] == 1.0 and result["mean_saved_bp"] == 200


def test_event_metrics_keep_bases_separate_and_include_missing(con):
    con.execute("CREATE TABLE p15_event_windows "
                "(id BIGINT,window_id VARCHAR,status VARCHAR,observed_at TIMESTAMP)")
    con.execute("CREATE TABLE p15_event_triggers (status VARCHAR,triggered_at TIMESTAMP)")
    con.execute("CREATE TABLE p15_event_decisions "
                "(id BIGINT,window_id VARCHAR,decision_payload VARCHAR,latency_ms DOUBLE,scoring_status VARCHAR,"
                "decision_at TIMESTAMP)")
    con.execute("CREATE TABLE p15_event_labels "
                "(decision_id BIGINT,horizon_sessions INTEGER,label_basis VARCHAR,"
                "net_excess_return DOUBLE,missing_bar_status VARCHAR,labeled_at TIMESTAMP)")
    con.execute("INSERT INTO p15_event_windows VALUES (1,'window','completed',?)", [NOW])
    for index in range(5):
        payload = json.dumps({"expected_excess_bp_5": float(index)})
        con.execute("INSERT INTO p15_event_decisions VALUES (?,'window',?,?,'available',?)",
                    [index + 1, payload, (index + 1) * 100_000, NOW])
        con.executemany("INSERT INTO p15_event_labels VALUES (?,?,?,?,?,?)", [
            (index + 1, 5, "next_bar", float(index),
             "missing_next_bar_last_available_close" if index == 0 else "complete", NOW),
            (index + 1, 5, "next_session_open", float(4 - index), "complete", NOW),
        ])

    result = p15_evaluation.events(con, NOW)

    assert result["p95_latency_ms_all"] == 500_000
    assert result["by_basis"]["next_bar"]["ic"] == pytest.approx(1)
    assert result["by_basis"]["next_session_open"]["ic"] == pytest.approx(-1)
    assert result["by_basis"]["next_bar"]["missing_status_counts"] == {
        "complete": 4, "missing_next_bar_last_available_close": 1,
    }


def test_event_missing_next_bar_becomes_invalid_only_at_h5_maturity(con):
    con.execute("CREATE TABLE p15_event_windows "
                "(id BIGINT,window_id VARCHAR,status VARCHAR,observed_at TIMESTAMP)")
    con.execute("CREATE TABLE p15_event_triggers (status VARCHAR,triggered_at TIMESTAMP)")
    con.execute("CREATE TABLE p15_event_decisions "
                "(id BIGINT,window_id VARCHAR,decision_payload VARCHAR,latency_ms DOUBLE,scoring_status VARCHAR,"
                "decision_at TIMESTAMP)")
    con.execute("CREATE TABLE p15_event_labels "
                "(decision_id BIGINT,horizon_sessions INTEGER,label_basis VARCHAR,"
                "net_excess_return DOUBLE,missing_bar_status VARCHAR,labeled_at TIMESTAMP)")
    decision_at = datetime(2024, 7, 17, 14, tzinfo=timezone.utc)
    con.execute("INSERT INTO p15_event_windows VALUES (1,'window','completed',?)", [decision_at])
    con.execute("INSERT INTO p15_event_decisions VALUES (1,'window',?,1,'available',?)", [
        json.dumps({"expected_excess_bp_5": 10}), decision_at,
    ])
    insert_bars(con, "SPY", SESSIONS[30:34], open_=100, close=100, high=101, low=99)
    con.execute("UPDATE prices SET fetched_at=?", [NOW.replace(tzinfo=None)])
    before = p15_evaluation.events(con, NOW)
    insert_bars(con, "SPY", [SESSIONS[34]], open_=100, close=100, high=101, low=99)
    con.execute("UPDATE prices SET fetched_at=? WHERE date=?", [NOW.replace(tzinfo=None),
                                                                  SESSIONS[34]])
    mature = p15_evaluation.events(con, NOW)

    assert before["by_basis"]["next_bar"]["missing_mature_label_count"] == 0
    assert mature["status"] == "invalid"
    assert mature["by_basis"]["next_bar"]["missing_mature_label_count"] == 1


def test_event_quintile_ties_use_decision_identity_not_realized_return():
    rows = [
        (2, json.dumps({"expected_excess_bp_5": 10}), -1.0, "complete"),
        (1, json.dumps({"expected_excess_bp_5": 10}), 1.0, "complete"),
        (3, json.dumps({"expected_excess_bp_5": 5}), 0.0, "complete"),
        (4, json.dumps({"expected_excess_bp_5": 0}), 0.0, "complete"),
        (5, json.dumps({"expected_excess_bp_5": -5}), -0.5, "complete"),
    ]

    result = p15_evaluation._event_basis(rows)

    assert result["top_bottom_quintile_spread"] == 1.5


def test_p8_rule_has_readiness_and_expectancy_but_no_result_gate(con):
    con.execute("CREATE TABLE agent_evaluation_traces "
                "(market_date DATE,policy_id VARCHAR,terminal_status VARCHAR)")
    con.executemany("INSERT INTO agent_evaluation_traces VALUES (?,'nightly_opportunity_tool_v1',"
                    "'completed')", [(date(2026, 9, 23) + timedelta(days=i),) for i in range(60)])

    result = p15_evaluation.p8_rule(con, datetime(2026, 12, 22, tzinfo=timezone.utc))

    assert result["status"] == "review_ready"
    assert result["cohort_start"] == "2026-09-23"
    assert result["trade_expectancy_status"] == "withheld"
    assert result["lower_bound_is_gate"] is False
    assert "pass" not in result and "kill" not in result


def test_trial_register_preserves_distinct_policy_model_prompt_versions(con):
    con.execute("CREATE TABLE agent_evaluation_traces "
                "(policy_id VARCHAR,model VARCHAR,model_version VARCHAR,instructions_sha256 VARCHAR,"
                "toolset_sha256 VARCHAR,model_catalog_entry_sha256 VARCHAR,"
                "proxy_source_sha256 VARCHAR,traecli_runtime VARCHAR,"
                "upstream_model_family VARCHAR,observed_at TIMESTAMP)")
    con.executemany("INSERT INTO agent_evaluation_traces VALUES (?,?,?,?,?,?,?,?,?,?)", [
        ("policy-v1", "model", "v1", "a" * 64, "c", "d", "e", "runtime", "family", NOW),
        ("policy-v1", "model", "v1", "a" * 64, "c", "d", "e", "runtime", "family", NOW),
        ("policy-v1", "model", "v2", "b" * 64, "c", "d", "e", "runtime", "family", NOW),
    ])

    result = agent_trial_register.project(con, NOW)

    assert result["version_count"] == result["selection_trial_count"] == 2
    assert result["returned_version_count"] == 2 and result["versions_truncated"] is False
    assert [item["observation_count"] for item in result["versions"]] == [2, 1]
    assert all(
        item["identity"][6] == canonical_sha256("runtime")
        for item in result["versions"]
    )


def test_trial_register_is_bounded_but_preserves_total(con):
    con.execute("CREATE TABLE agent_evaluation_traces "
                "(policy_id VARCHAR,model VARCHAR,model_version VARCHAR,instructions_sha256 VARCHAR,"
                "toolset_sha256 VARCHAR,model_catalog_entry_sha256 VARCHAR,"
                "proxy_source_sha256 VARCHAR,traecli_runtime VARCHAR,"
                "upstream_model_family VARCHAR,observed_at TIMESTAMP)")
    con.executemany(
        "INSERT INTO agent_evaluation_traces VALUES (?,'model','v1',?,'c','d','e','runtime',"
        "'family',?)",
        [(f"policy-{index:03}", f"{index:064x}", NOW) for index in range(101)],
    )

    result = agent_trial_register.project(con, NOW)

    assert result["version_count"] == 101
    assert result["returned_version_count"] == agent_trial_register.LIMIT
    assert result["versions_truncated"] is True


def test_trial_register_keeps_distinct_event_policy_and_model_versions(con):
    con.execute("CREATE TABLE p15_event_windows "
                "(id BIGINT,window_id VARCHAR,observed_at TIMESTAMP)")
    con.execute("CREATE TABLE p15_event_calls "
                "(window_id VARCHAR,status VARCHAR,response_payload VARCHAR)")
    def response(model):
        return json.dumps({
            "model": model, "model_version": "v1", "proxy_version": "proxy",
            "proxy_source_sha256": "a", "traecli_runtime": "runtime",
            "upstream_model_family": "family", "model_catalog_entry_sha256": "b",
        })
    con.executemany("INSERT INTO p15_event_windows VALUES (?,?,?)", [
        (1, "p15-events-v1:2026-09-28:10:05", NOW),
        (2, "p15-events-v2:2026-09-28:10:20", NOW),
    ])
    con.executemany("INSERT INTO p15_event_calls VALUES (?,?,?)", [
        ("p15-events-v1:2026-09-28:10:05", "completed", response("one")),
        ("p15-events-v2:2026-09-28:10:20", "completed", response("two")),
    ])

    result = agent_trial_register.project(con, NOW)

    assert result["version_count"] == 2
    assert [item["policy_id"] for item in result["versions"]] == [
        "p15-events-v1", "p15-events-v2",
    ]
    assert all(
        item["identity"][4] == canonical_sha256("runtime")
        for item in result["versions"]
    )


def test_overall_pass_requires_primary_book_bound_and_all_drawdowns(con, monkeypatch):
    monkeypatch.setattr(p15_evaluation, "primary", lambda *_args: {"status": "pass"})
    book_result = {
        "status": "collecting",
        "books": [{"maximum_drawdown": -0.1} for _book in p15_evaluation.BOOK_IDS],
        "comparisons": [{"positive_lower_bound": False, "promotion_status": "collecting"}],
    }
    monkeypatch.setattr(p15_evaluation, "books", lambda *_args: book_result)
    monkeypatch.setattr(p15_evaluation, "preopen", lambda *_args: {})
    monkeypatch.setattr(p15_evaluation, "events", lambda *_args: {})
    monkeypatch.setattr(p15_evaluation, "observer_pairing", lambda *_args: {})
    monkeypatch.setattr(p15_evaluation, "p8_rule", lambda *_args: {})

    assert p15_evaluation.project(con, generated_at=NOW)["p15"]["status"] == "collecting"
    book_result["comparisons"][0]["positive_lower_bound"] = True
    book_result["comparisons"][0]["promotion_status"] = "pass"
    projected = p15_evaluation.project(con, generated_at=NOW)["p15"]
    assert projected["status"] == "pass" and projected["promotion_ready"] is True
