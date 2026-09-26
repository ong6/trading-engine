"""P15 gate statistics and prospective-cohort tests."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from engine import p15_evaluation
from farm.walkforward.monthly import newey_west_t
from tests.conftest import SESSIONS, insert_bars
from tools import agent_trial_register

NOW = datetime(2026, 12, 1, 12, tzinfo=timezone.utc)


def test_average_rank_spearman_handles_ties_and_constants():
    assert p15_evaluation.average_ranks([3, 1, 1, 2]) == [4.0, 1.5, 1.5, 3.0]
    assert p15_evaluation.spearman([1, 2, 2, 4], [4, 2, 2, 1]) == pytest.approx(-1)
    assert p15_evaluation.spearman([1, 1], [1, 2]) is None


def test_newey_west_matches_existing_reference():
    values = [0.04, -0.01, 0.03, 0.02, -0.005, 0.01]
    expected = newey_west_t(values, lag=4)
    assert p15_evaluation.newey_west(values, lag=4) == pytest.approx(expected)


def test_fixed_looks_use_immutable_prefixes_and_terminal_rules():
    positive = [{"delta_ic": 0.2 + (index % 3) * 0.01,
                 "model_ic": 0.3, "baseline_ic": 0.09,
                 "evaluated_at": NOW.isoformat(),
                 "market_date": (date(2026, 1, 1) + timedelta(days=index)).isoformat()}
                for index in range(61)]
    status, looks, next_look = p15_evaluation.evaluate_looks(positive)
    assert status == "pass" and [item["look"] for item in looks] == [60]
    assert looks[0]["delta"]["n"] == 60 and next_look is None
    status, looks, next_look = p15_evaluation.evaluate_looks(positive[:59])
    assert (status, looks, next_look) == ("collecting", [], 60)
    neutral = [{"delta_ic": (-1) ** index * 0.01,
                "model_ic": 0.1, "baseline_ic": 0.1,
                "evaluated_at": NOW.isoformat(),
                "market_date": (date(2026, 1, 1) + timedelta(days=index)).isoformat()}
               for index in range(120)]
    status, looks, next_look = p15_evaluation.evaluate_looks(neutral)
    assert status == "kill" and looks[-1]["look"] == 120 and next_look is None


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
    sessions = [market_date + timedelta(days=index) for index in range(1, 8)]
    insert_bars(con, "SPY", sessions, open_=100, close=100, high=101, low=99)
    con.execute("UPDATE prices SET fetched_at=?", [NOW.replace(tzinfo=None)])

    result = p15_evaluation.primary(con, NOW)

    assert result["status"] == "collecting"
    assert result["scored_session_count"] == 1
    assert result["diagnostics"]["model_brier"] is not None
    con.execute("DELETE FROM agent_evaluation_labels_v2 WHERE decision_id=1")
    assert p15_evaluation.primary(con, NOW)["status"] == "invalid"


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
