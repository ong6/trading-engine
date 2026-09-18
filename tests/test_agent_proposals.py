"""Shadow agent proposals are bound, idempotent, atomic, and non-executing."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from engine.lib.provenance import canonical_sha256
from server import (
    agent_context,
    agent_contract,
    agent_model_client,
    agent_proposals,
    agent_store,
)
from server.json_utils import loads_object
from tests.agent_test_helpers import (
    complete_dual_momentum_history,
    context,
    fixed_etf_market,
    proposal_body,
)

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


def test_context_is_bounded_reproducible_and_has_no_execution_authority(con):
    fixed_etf_market(con)

    first = context(con)
    second = context(con)

    assert first == second
    assert first["schema_version"] == 10
    assert first["execution_authority"] == "none"
    assert first["mode"] == "shadow"
    assert first["policy"]["id"] == "dual_momentum_agent_shadow_v1"
    assert first["policy"]["mode"] == "agent_only"
    assert first["policy"]["generation_enabled"] is True
    assert first["policy"]["execution_authority"] == "none"
    assert len(first["policy"]["registration_sha256"]) == 64
    assert first["decision_model"]["transport"] == "trae_cli_proxy"
    assert first["decision_model"]["model"] == "GPT-5.6-Sol:max"
    assert first["decision_model"]["model_version"] == "unversioned-catalog-alias"
    assert first["decision_model"]["provider_model_revision"] is None
    assert (
        first["decision_model"]["provider_model_revision_available"] is False
    )
    assert first["decision_model"]["model_catalog_entry"] == (
        agent_model_client.EXPECTED_MODEL_CATALOG_ENTRY
    )
    assert first["decision_model"]["model_catalog_entry_sha256"] == (
        agent_model_client.MODEL_CATALOG_ENTRY_SHA256
    )
    assert first["decision_model"]["required_traecli_runtime"] == (
        agent_model_client.REQUIRED_TRAECLI_RUNTIME
    )
    assert first["decision_model"]["tools"] == "none"
    assert first["decision_model"]["execution_authority"] == "none"
    assert first["portfolio"] == {
        "id": "dual_momentum",
        "active": True,
        "initial_cash": 39_000.0,
        "shadow_max_notional": 39_000.0,
        "execution_profile": "baseline_v1",
        "config_sha256": first["strategy"]["config_sha256"],
    }
    assert first["instrument"] == {
        "ticker": "SPY",
        "active": True,
        "liquid": True,
        "etf": True,
        "quote_date": "2026-09-11",
        "close": 100.0,
        "source": "yfinance",
        "fetched_at": "2026-09-12T00:00:00Z",
        "quarantine": None,
        "data_contract": first["instrument"]["data_contract"],
    }
    data_contract = first["instrument"]["data_contract"]
    assert data_contract["schema_version"] == 4
    assert data_contract["quality_status"] == "limited"
    assert data_contract["usage_authority"] == "shadow_context_only"
    assert data_contract["availability"] == {
        "source_published_at": None,
        "usable_at": "2026-09-12T00:00:00Z",
        "policy": "usable_no_earlier_than_latest_ingestion",
    }
    assert data_contract["revision"]["point_in_time_replayable"] is False
    assert data_contract["record"]["raw_retained"] is False
    assert len(data_contract["record"]["normalized_sha256"]) == 64
    assert data_contract["adjustment"]["point_in_time_revision_safe"] is False
    assert first["decision_features"] == {
        "schema_version": 1,
        "kind": "registered_universe_total_returns",
        "strategy_id": "dual_momentum",
        "as_of": "2026-09-11",
        "lookback_sessions": [252],
        "required_tickers": ["BIL", "EFA", "SPY"],
        "complete_tickers": [],
        "assets": first["decision_features"]["assets"],
    }
    assert [asset["ticker"] for asset in first["decision_features"]["assets"]] == [
        "BIL",
        "EFA",
        "SPY",
    ]
    assert first["decision_features"]["assets"][2]["status"] == "unavailable"
    assert (
        first["decision_features"]["assets"][2]["unavailable_reason"]
        == "insufficient_or_stale_price_history"
    )
    assert len(first["context_sha256"]) == 64


def test_context_exposes_recomputable_registered_universe_total_returns(con):
    fixed_etf_market(con)
    market_date = complete_dual_momentum_history(con)

    payload = context(con)

    features = payload["decision_features"]
    assert features["as_of"] == market_date.isoformat()
    assert features["complete_tickers"] == ["BIL", "EFA", "SPY"]
    by_ticker = {item["ticker"]: item for item in features["assets"]}
    assert by_ticker["SPY"]["lookbacks"][0]["total_return"] == pytest.approx(0.20)
    assert by_ticker["EFA"]["lookbacks"][0]["total_return"] == pytest.approx(0.10)
    assert by_ticker["BIL"]["lookbacks"][0]["total_return"] == pytest.approx(0.04)
    for ticker, feature in by_ticker.items():
        assert feature["status"] == "complete"
        assert feature["required_session_count"] == 253
        assert feature["observed_session_count"] == 253
        assert feature["corporate_action_coverage"]["ticker"] == ticker
        assert feature["feature_sha256"] == canonical_sha256(
            {key: value for key, value in feature.items() if key != "feature_sha256"}
        )
        calculation = feature["lookbacks"][0]
        assert calculation["calculation_sha256"] == canonical_sha256(
            {
                key: value
                for key, value in calculation.items()
                if key != "calculation_sha256"
            }
        )
    assert len(by_ticker["BIL"]["lookbacks"][0]["dividends"]) == 1
    assert (
        by_ticker["BIL"]["lookbacks"][0]["cash_dividends_per_share"]
        == 4.0
    )


def test_missing_action_coverage_marks_only_that_feature_unavailable(con):
    fixed_etf_market(con)
    complete_dual_momentum_history(con)
    con.execute("DELETE FROM actions_fetch_log WHERE ticker = 'EFA'")

    features = context(con)["decision_features"]

    assert features["complete_tickers"] == ["BIL", "SPY"]
    efa = next(item for item in features["assets"] if item["ticker"] == "EFA")
    assert efa["status"] == "unavailable"
    assert efa["unavailable_reason"] == "corporate_action_coverage_unavailable"
    assert efa["lookbacks"] == []
    assert efa["feature_sha256"] is None


@pytest.mark.parametrize(
    ("strategy_id", "ticker", "detail"),
    [
        ("template_top5", "SPY", "not admitted"),
        ("agentic_alloc", "SPY", "not admitted"),
        ("sector_momentum", "SPY", "does not match"),
        ("dual_momentum", "AAA", "not allowlisted"),
    ],
)
def test_context_rejects_unadmitted_strategy_or_instrument(
    con, strategy_id, ticker, detail
):
    fixed_etf_market(con, ticker)

    with pytest.raises(agent_context.ContextError, match=detail):
        context(con, strategy_id, ticker)


def test_context_rejects_stale_quote_and_active_quarantine(con, monkeypatch):
    fixed_etf_market(con)
    monkeypatch.setattr(
        agent_context,
        "latest_prices_date",
        lambda _con: datetime(2026, 9, 11, tzinfo=timezone.utc).date(),
    )
    con.execute(
        "INSERT INTO universe VALUES "
        "('EFA', 'EFA', 'EFA', 'NYSE', TRUE, NULL, DATE '2020-01-01', "
        "TRUE, TRUE, TRUE)"
    )
    con.execute(
        "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
        "VALUES ('EFA', DATE '2026-09-10', 50, 51, 49, 50, 1000000)"
    )

    with pytest.raises(agent_context.ContextError, match="current eligible quote"):
        context(con, "dual_momentum", "EFA")

    con.execute(
        "INSERT INTO price_quarantine "
        "(ticker, status, reason) VALUES ('SPY', 'active', 'confirmed defect')"
    )
    with pytest.raises(agent_context.ContextError, match="quarantined"):
        context(con)


@pytest.mark.parametrize(
    ("mutation", "detail"),
    [
        (
            "UPDATE portfolios SET active = FALSE WHERE id = 'dual_momentum'",
            "not active",
        ),
        (
            "UPDATE portfolios SET config = '{}' WHERE id = 'dual_momentum'",
            "does not match source",
        ),
        (
            "UPDATE portfolios SET execution_profile = NULL "
            "WHERE id = 'dual_momentum'",
            "execution profile is invalid",
        ),
    ],
)
def test_context_requires_current_active_strategy_registration(con, mutation, detail):
    fixed_etf_market(con)
    con.execute(mutation)

    with pytest.raises(agent_context.ContextError, match=detail):
        context(con)


def test_shadow_submission_records_evidence_without_creating_order(con):
    fixed_etf_market(con)
    complete_dual_momentum_history(con)
    bounded = context(con)
    body = proposal_body(bounded, now=NOW)

    result = agent_proposals.submit(con, body, now=NOW)

    assert result["proposal_record_id"] == 1
    assert result["proposal_id"] == "proposal-0001"
    assert result["status"] == "shadow_accepted"
    assert (
        result["validation_scope"]
        == "deterministic_shadow_recomputation_and_risk"
    )
    assert result["validation_status"] == "pass"
    assert len(result["validation_sha256"]) == 64
    assert result["execution_authority"] == "none"
    assert result["context_sha256"] == bounded["context_sha256"]
    assert result["validated_context_sha256"] == bounded["context_sha256"]
    assert result["reasons"] == []
    assert result["replayed"] is False
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)
    assert con.execute(
        "SELECT status, proposal_id, context_sha256 FROM agent_proposals"
    ).fetchone() == ("shadow_accepted", "proposal-0001", bounded["context_sha256"])
    stored_context = con.execute(
        "SELECT validated_context FROM agent_proposals"
    ).fetchone()[0]
    assert loads_object(stored_context) == bounded
    validation_sha256, stored_validation = con.execute(
        "SELECT validation_sha256, validation_payload FROM agent_proposals"
    ).fetchone()
    validation = loads_object(stored_validation)
    assert validation["status"] == "pass"
    assert validation["validation_sha256"] == validation_sha256
    assert validation["recomputed_claim"]["quantity_at_signal_close"] == pytest.approx(
        1_000 / 120
    )
    assert validation["failed_gates"] == []
    assert con.execute("SELECT actor, action FROM audit_log").fetchone() == (
        "agent:paper-research-agent",
        "agent_proposal_shadow",
    )


def test_context_mismatch_is_persisted_as_rejection_without_order(con):
    fixed_etf_market(con)
    bounded = context(con)
    body = proposal_body(bounded, now=NOW, context_sha256="f" * 64)

    result = agent_proposals.submit(con, body, now=NOW)

    assert result["status"] == "shadow_rejected"
    assert result["reasons"] == ["context_sha256 does not match current server context"]
    assert result["context_sha256"] == "f" * 64
    assert result["validated_context_sha256"] == bounded["context_sha256"]
    assert loads_object(
        con.execute("SELECT validated_context FROM agent_proposals").fetchone()[0]
    ) == bounded
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)
    assert con.execute("SELECT status FROM agent_proposals").fetchone() == (
        "shadow_rejected",
    )


def test_notional_above_context_ceiling_is_shadow_rejected(con):
    fixed_etf_market(con)
    complete_dual_momentum_history(con)
    bounded = context(con)

    result = agent_proposals.submit(
        con,
        proposal_body(bounded, now=NOW, max_notional=39_001),
        now=NOW,
    )

    assert result["status"] == "shadow_rejected"
    assert result["validation_status"] == "fail"
    assert result["reasons"] == ["notional_ceiling", "capital_concentration"]
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model", "another-model"),
        ("model_version", "another-version"),
        ("prompt_sha256", "a" * 64),
        ("toolset_sha256", "b" * 64),
    ],
)
def test_shadow_submission_is_bound_to_context_connector_identity(con, field, value):
    fixed_etf_market(con)
    bounded = context(con)

    result = agent_proposals.submit(
        con,
        proposal_body(bounded, now=NOW, **{field: value}),
        now=NOW,
    )

    assert result["status"] == "shadow_rejected"
    assert result["reasons"] == [f"{field} does not match current server context"]
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


@pytest.mark.parametrize(
    ("field", "value", "detail"),
    [
        ("source", None, "source is invalid"),
        ("source", "", "source is invalid"),
        ("source", "other", "source is not admitted"),
        ("fetched_at", None, "no ingestion timestamp"),
        ("close", float("nan"), "positive and finite"),
        ("close", 0, "positive and finite"),
    ],
)
def test_context_rejects_quote_without_complete_provenance(con, field, value, detail):
    fixed_etf_market(con)
    con.execute(f"UPDATE prices SET {field} = ? WHERE ticker = 'SPY'", [value])

    with pytest.raises(agent_context.ContextError, match=detail):
        context(con)


def test_exact_replay_returns_prior_result_without_new_rows(con):
    fixed_etf_market(con)
    body = proposal_body(context(con), now=NOW)

    first = agent_proposals.submit(con, body, now=NOW)
    second = agent_proposals.submit(con, body, now=NOW)

    assert first["replayed"] is False
    assert second == {**first, "replayed": True}
    assert con.execute("SELECT COUNT(*) FROM agent_proposals").fetchone() == (1,)
    assert con.execute("SELECT COUNT(*) FROM audit_log").fetchone() == (1,)
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


@pytest.mark.parametrize(
    "overrides",
    [
        {"proposal_id": "proposal-0002"},
        {"idempotency_key": "decision-window-0002"},
        {"thesis": "A conflicting payload."},
    ],
)
def test_identifier_reuse_with_different_proposal_is_conflict(con, overrides):
    fixed_etf_market(con)
    bounded = context(con)
    body = proposal_body(bounded, now=NOW)
    agent_proposals.submit(con, body, now=NOW)

    with pytest.raises(agent_contract.ProposalError, match="already used") as error:
        agent_proposals.submit(con, proposal_body(bounded, now=NOW, **overrides), now=NOW)

    assert error.value.status_code == 409
    assert con.execute("SELECT COUNT(*) FROM agent_proposals").fetchone() == (1,)
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


def test_submission_rolls_back_proposal_and_audit_together(con, monkeypatch):
    fixed_etf_market(con)
    body = proposal_body(context(con), now=NOW)
    monkeypatch.setattr(
        agent_proposals,
        "_audit",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("audit failed")),
    )

    with pytest.raises(RuntimeError, match="audit failed"):
        agent_proposals.submit(con, body, now=NOW)

    assert con.execute("SELECT COUNT(*) FROM agent_proposals").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM audit_log").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


def test_context_build_failure_records_no_validated_context(con):
    fixed_etf_market(con)
    bounded = context(con)
    con.execute("UPDATE portfolios SET active = FALSE WHERE id = 'dual_momentum'")

    result = agent_proposals.submit(con, proposal_body(bounded, now=NOW), now=NOW)

    assert result["status"] == "shadow_rejected"
    assert result["validated_context_sha256"] is None
    assert con.execute(
        "SELECT validated_context FROM agent_proposals"
    ).fetchone() == (None,)


def test_schema_upgrade_adds_validated_context_without_rewriting_existing_rows(con):
    con.execute(
        "CREATE TABLE agent_proposals ("
        "id BIGINT PRIMARY KEY, proposal_id VARCHAR UNIQUE, "
        "idempotency_key VARCHAR UNIQUE)"
    )
    con.execute(
        "INSERT INTO agent_proposals VALUES (1, 'legacy-proposal', 'legacy-window')"
    )

    agent_store.init_schema(con)

    columns = {
        row[1] for row in con.execute("PRAGMA table_info('agent_proposals')").fetchall()
    }
    assert {
        "validated_context",
        "policy_id",
        "policy_registration_sha256",
        "validation_sha256",
        "validation_payload",
    } <= columns
    assert con.execute(
        "SELECT id, proposal_id, idempotency_key, validated_context, "
        "policy_id, policy_registration_sha256, validation_sha256, "
        "validation_payload "
        "FROM agent_proposals"
    ).fetchall() == [
        (1, "legacy-proposal", "legacy-window", None, None, None, None, None)
    ]
