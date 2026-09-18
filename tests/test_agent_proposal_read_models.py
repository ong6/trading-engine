"""Tests for the bounded shadow-agent proposal ledger projection."""

from __future__ import annotations

from datetime import datetime

import duckdb
import pytest

from server import (
    agent_proposal_read_models,
    agent_proposals,
    agent_store,
)
from tests.agent_test_helpers import (
    complete_dual_momentum_history,
    context,
    fixed_etf_market,
    proposal_body,
)

NOW = datetime(2026, 9, 13, 12, 0)


def _insert_projection_row(
    con,
    record_id: int,
    *,
    status: str = "shadow_accepted",
    reasons: str | None = None,
) -> None:
    reasons = reasons if reasons is not None else (
        "[]" if status == "shadow_accepted" else '["context mismatch"]'
    )
    con.execute(
        "INSERT INTO agent_proposals ("
        "id, proposal_id, mode, policy_id, policy_registration_sha256, "
        "agent_id, model, model_version, strategy_id, "
        "ticker, side, max_notional, signal_at, expires_at, status, "
        "context_sha256, validated_context_sha256, reasons, received_at"
        ") VALUES (?, ?, 'hybrid', NULL, NULL, 'agent-1', 'GPT-5.6-Sol:max', "
        "'unversioned-catalog-alias', "
        "'dual_momentum', 'SPY', 'buy', 1000, ?, ?, ?, ?, ?, ?, ?)",
        [
            record_id,
            f"proposal-{record_id}",
            NOW,
            datetime(2026, 9, 14, 12, 0),
            status,
            "1" * 64,
            "1" * 64,
            reasons,
            NOW,
        ],
    )


def test_missing_table_returns_complete_empty_contract():
    con = duckdb.connect()
    try:
        assert agent_proposal_read_models.proposals(con, "shadow_rejected") == {
            "status": "shadow_rejected",
            "validation_scope": "deterministic_shadow_recomputation_and_risk",
            "execution_authority": "none",
            "limit": agent_proposal_read_models.PROPOSALS_LIMIT,
            "matching_count": 0,
            "truncated": False,
            "proposals": [],
        }
    finally:
        con.close()


def test_projection_has_exact_bounded_public_shape(con):
    fixed_etf_market(con)
    complete_dual_momentum_history(con)
    bounded = context(con)
    result = agent_proposals.submit(con, proposal_body(bounded), now=NOW)
    con.execute("ALTER TABLE agent_proposals ADD COLUMN internal_secret VARCHAR")
    con.execute("UPDATE agent_proposals SET internal_secret = 'not public'")

    payload = agent_proposal_read_models.proposals(con, None)

    assert payload["matching_count"] == 1
    assert payload["truncated"] is False
    assert payload["proposals"] == [
        {
            "id": 1,
            "proposal_id": "proposal-0001",
            "mode": "agent_only",
            "policy_id": "dual_momentum_agent_shadow_v1",
            "policy_registration_sha256": bounded["policy"][
                "registration_sha256"
            ],
            "agent_id": "paper-research-agent",
            "model": "GPT-5.6-Sol:max",
            "model_version": "unversioned-catalog-alias",
            "strategy_id": "dual_momentum",
            "ticker": "SPY",
            "side": "buy",
            "max_notional": 1000.0,
            "signal_at": NOW,
            "expires_at": datetime(2026, 9, 14, 12, 0),
            "status": "shadow_accepted",
            "context_sha256": bounded["context_sha256"],
            "validated_context_sha256": bounded["context_sha256"],
            "validation_status": "pass",
            "validation_sha256": result["validation_sha256"],
            "reasons": [],
            "received_at": NOW,
        }
    ]
    exposed = payload["proposals"][0]
    for internal in (
        "idempotency_key",
        "prompt_sha256",
        "toolset_sha256",
        "thesis",
        "invalidation",
        "evidence_ids",
        "normalized_proposal",
        "validated_context",
        "validation_payload",
        "internal_secret",
    ):
        assert internal not in exposed


def test_projection_orders_bounds_counts_and_filters(con, monkeypatch):
    monkeypatch.setattr(agent_proposal_read_models, "PROPOSALS_LIMIT", 3)
    agent_store.init_schema(con)
    for record_id, status in (
        (1, "shadow_accepted"),
        (2, "shadow_rejected"),
        (3, "shadow_accepted"),
        (4, "shadow_rejected"),
        (5, "shadow_accepted"),
    ):
        _insert_projection_row(con, record_id, status=status)

    all_rows = agent_proposal_read_models.proposals(con, None)
    rejected = agent_proposal_read_models.proposals(con, "shadow_rejected")

    assert [row["id"] for row in all_rows["proposals"]] == [5, 4, 3]
    assert all_rows["matching_count"] == 5
    assert all_rows["truncated"] is True
    assert [row["id"] for row in rejected["proposals"]] == [4, 2]
    assert rejected["matching_count"] == 2
    assert rejected["truncated"] is False


@pytest.mark.parametrize(
    ("column", "value", "detail"),
    [
        ("proposal_id", "bad proposal", "identifier"),
        ("mode", "algorithm_only", "mode"),
        ("ticker", " bad", "ticker"),
        ("max_notional", float("nan"), "notional"),
        ("status", "approved", "status"),
        ("context_sha256", "bad", "context identity"),
        ("reasons", "{", "reasons"),
    ],
)
def test_projection_fails_closed_on_malformed_stored_values(
    con,
    column,
    value,
    detail,
):
    agent_store.init_schema(con)
    _insert_projection_row(con, 1)
    con.execute(f"UPDATE agent_proposals SET {column} = ?", [value])

    with pytest.raises(ValueError, match=detail):
        agent_proposal_read_models.proposals(con, None)


def test_projection_rejects_inconsistent_status_reason_pair(con):
    agent_store.init_schema(con)
    _insert_projection_row(con, 1, status="shadow_accepted", reasons='["unexpected"]')

    with pytest.raises(ValueError, match="validation result"):
        agent_proposal_read_models.proposals(con, None)


def test_projection_rejects_validation_evidence_copied_to_another_context(con):
    fixed_etf_market(con)
    complete_dual_momentum_history(con)
    bounded = context(con)
    agent_proposals.submit(con, proposal_body(bounded), now=NOW)
    con.execute(
        "UPDATE agent_proposals SET validated_context_sha256 = ?",
        ["f" * 64],
    )

    with pytest.raises(ValueError, match="stored agent proposal validation"):
        agent_proposal_read_models.proposals(con, None)
