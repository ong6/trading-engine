"""In-tree P15 replay executor and label-producer tests."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import duckdb
import pytest

from engine.lib.provenance import canonical_sha256
from farm.replay.asof import reconstruct_unadjusted_bars
from farm.replay.executor import (
    apply_score,
    censored_label_counts,
    execute_preopen,
    execute_score,
    init_executor_schema,
    produce_labels,
)
from farm.replay.notes import init_notes_schema, visible_mature_labels
from farm.replay.registration import SPLIT_KNOWLEDGE_PRIMARY, SPLIT_KNOWLEDGE_SENSITIVITY
from farm.replay.runner import session_phases
from server import agent_model_client


def _score_plan() -> dict:
    candidate = {
        "ticker": "AAA", "evidence_id": "a" * 64, "held": False,
        "baseline_score": 1, "baseline_rank": 1, "stratum": "mover",
    }
    requests = [
        {
            "schema_version": 1, "policy_id": "p15-scoring-v1",
            "market_date": "2024-01-02", "information_cutoff_at": "2024-01-03T02:00:00Z",
            "chunk_index": 0, "sample_index": sample, "permutation_seed": sample,
            "market": {}, "market_headlines": [], "event_facts": [],
            "tradingview_quotes": [], "candidates": [candidate],
        }
        for sample in range(3)
    ]
    return {
        "kind": "score", "bundle": {"bundle_sha256": "b" * 64},
        "context": {}, "allowed": {"AAA": {"a" * 64}},
        "chunks": [{"candidates": [candidate], "requests": requests}],
        "sample_count": 3,
    }


def _score_result(payload: dict, *, invalid: bool = False):
    identity = agent_model_client.identity(role="p15_scoring")
    probability = 2.0 if invalid else 0.6
    output = {"schema_version": 1, "assessments": [{
        "ticker": "AAA", "p_outperform_5": probability,
        "expected_excess_bp_5": 70.0 + payload["sample_index"] * 10,
        "expected_excess_bp_10": 100.0, "action": "buy_candidate",
        "thesis": "Positive expected excess.",
        "invalidation": "Expected excess turns negative.", "evidence_ids": ["a" * 64],
    }]}
    return agent_model_client.ConnectorResult(
        output=output, response_id=f"response-{payload['sample_index']}",
        model=identity["model"], model_version=identity["model_version"],
        proxy_version=identity["required_proxy_version"],
        proxy_source_sha256=identity["required_proxy_source_sha256"],
        traecli_runtime=identity["required_traecli_runtime"],
        upstream_model_family=agent_model_client.UPSTREAM_MODEL_FAMILY,
        upstream_request_id=f"upstream-{payload['sample_index']}",
        model_catalog_entry_sha256=identity["model_catalog_entry_sha256"],
        request_sha256=canonical_sha256(
            agent_model_client.p15_scoring_request_payload(payload)
        ),
        usage={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
    )


def test_score_executor_uses_three_samples_and_records_canonical_trace():
    result = execute_score(_score_plan(), _score_result)
    assert result["decisions"][0]["expected_excess_bp_5"] == 80
    assert len(result["samples"]) == 3

    con = duckdb.connect(":memory:")
    init_executor_schema(con)
    written = apply_score(
        con, result, cohort_id="fixture", policy_id="c-notes",
        session=date(2024, 1, 2),
        logical_at=datetime(2024, 1, 3, 2, tzinfo=timezone.utc),
        security_ids={"AAA": "aaa"},
    )
    assert written == 1
    assert con.execute(
        "SELECT policy_id,terminal_status FROM agent_evaluation_traces"
    ).fetchone() == ("p15-scoring-v1", "completed")
    assert con.execute(
        "SELECT ticker,security_id,expected_excess_bp FROM replay_decisions"
    ).fetchone() == ("AAA", "aaa", 80.0)


def test_invalid_score_chunk_becomes_explicitly_unavailable():
    result = execute_score(_score_plan(), lambda payload: _score_result(payload, invalid=True))
    assert len(result["samples"]) == 1
    assert result["samples"][0]["status"] == "failed"
    assert result["decisions"][0]["scoring_status"] == "unavailable"


def test_preopen_provider_result_after_registered_window_keeps_intent():
    payload = {
        "schema_version": 1, "policy_id": "p15-preopen-v1",
        "session_date": "2024-01-03", "cutoff_at": "2024-01-03T14:05:00Z",
        "execution_authority": "cancel_only",
        "intents": [{
            "intent_id": 1, "portfolio_id": "p15_ai_ranked", "ticker": "AAA",
            "limit_px": 100.0, "nightly_assessment": {}, "new_headlines": [],
            "new_event_facts": [], "allowed_evidence_ids": ["a" * 64],
        }],
        "control_noops": [], "receipt_sha256s": [],
    }
    identity = agent_model_client.identity(role="p15_preopen")
    response = agent_model_client.ConnectorResult(
        output={"schema_version": 1, "decisions": [{
            "intent_id": 1, "decision": "cancel", "reason": "New adverse evidence.",
            "evidence_ids": ["a" * 64],
        }]},
        response_id="preopen-response", model=identity["model"],
        model_version=identity["model_version"],
        proxy_version=identity["required_proxy_version"],
        proxy_source_sha256=identity["required_proxy_source_sha256"],
        traecli_runtime=identity["required_traecli_runtime"],
        upstream_model_family=agent_model_client.UPSTREAM_MODEL_FAMILY,
        upstream_request_id="preopen-upstream",
        model_catalog_entry_sha256=identity["model_catalog_entry_sha256"],
        request_sha256=canonical_sha256(
            agent_model_client.p15_preopen_request_payload(payload)
        ),
        usage={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
    )
    ticks = iter((0.0, 1_200.0))
    result = execute_preopen(
        {"kind": "preopen", "payload": payload, "allowed": {1: {"a" * 64}}},
        lambda _payload: response, monotonic=lambda: next(ticks),
    )
    assert result["status"] == "late"
    assert result["decisions"][0]["decision"] == "keep"


def _label_fixture(*, split_session, policy, drop_asset_exit=False, late_asset_exit=False):
    con = duckdb.connect(":memory:")
    init_executor_schema(con)
    init_notes_schema(con)
    signal, entry, exit_session = date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 9)
    con.execute(
        "INSERT INTO replay_decisions VALUES (?,?,?,?,?,?,?)",
        ("decision", 1, signal, "AAA", "aaa", 25.0, "{}"),
    )
    action = {
        "action_id": "aaa-split", "security_id": "aaa", "ticker": "AAA",
        "stable_mapping": True, "kind": "split", "ex_date": split_session,
        "outcome": "applied", "new_shares_per_old": 2,
    }
    source = []
    for ticker, security_id, entry_price, exit_price in (
        ("AAA", "aaa", 50.0, 50.0), ("SPY", "spy", 100.0, 100.0)
    ):
        for session, price in ((entry, entry_price), (exit_session, exit_price)):
            if drop_asset_exit and ticker == "AAA" and session == exit_session:
                continue
            available = session_phases(session)["close_visible"]
            if late_asset_exit and ticker == "AAA" and session == exit_session:
                available += timedelta(days=1)
            source.append({
                "security_id": security_id, "ticker": ticker, "session": session,
                "series": "source_back_adjusted_v1",
                "available_at": available.isoformat(),
                "open": price, "high": price, "low": price, "close": price, "volume": 10,
            })
    bars = reconstruct_unadjusted_bars(source, [action])
    assert produce_labels(
        con, session=exit_session,
        visible_at=session_phases(exit_session)["close_visible"],
        reconstructed_bars=bars, actions=[action], knowledge_policy=policy,
    ) == 1
    return con, con.execute(
        "SELECT horizon,status,realized_excess_bp FROM replay_labels"
    ).fetchone()


@pytest.mark.parametrize("policy", [SPLIT_KNOWLEDGE_PRIMARY, SPLIT_KNOWLEDGE_SENSITIVITY])
def test_label_producer_uses_split_normalized_asset_and_spy_returns(policy):
    _con, row = _label_fixture(split_session=date(2024, 1, 8), policy=policy)
    assert row[:2] == ("h5", "terminal")
    assert row[2] == pytest.approx(0.0)


def test_label_split_on_exit_session_follows_store_knowledge_policy():
    split_session = date(2024, 1, 9)
    _con, primary = _label_fixture(split_session=split_session, policy=SPLIT_KNOWLEDGE_PRIMARY)
    assert primary[:2] == ("h5", "terminal")
    assert primary[2] == pytest.approx(0.0)
    con, sensitivity = _label_fixture(
        split_session=split_session, policy=SPLIT_KNOWLEDGE_SENSITIVITY
    )
    assert sensitivity == ("h5", "censored:late_split_knowledge", None)
    assert censored_label_counts(con) == {"late_split_knowledge": 1}


def test_label_with_missing_bar_is_censored_and_hidden_from_notes():
    con, row = _label_fixture(
        split_session=date(2024, 1, 8), policy=SPLIT_KNOWLEDGE_PRIMARY, drop_asset_exit=True,
    )
    assert row == ("h5", "censored:missing_asset_bar", None)
    assert censored_label_counts(con) == {"missing_asset_bar": 1}
    assert visible_mature_labels(
        con, session=date(2024, 1, 11),
        cutoff=datetime(2024, 1, 11, 23, tzinfo=timezone.utc),
    ) == []


def test_label_with_bar_published_after_close_is_censored_late_bar():
    con, row = _label_fixture(
        split_session=date(2024, 1, 8), policy=SPLIT_KNOWLEDGE_PRIMARY, late_asset_exit=True,
    )
    assert row == ("h5", "censored:late_bar", None)
    assert censored_label_counts(con) == {"late_bar": 1}
