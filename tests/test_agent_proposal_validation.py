"""Deterministic proposal claims are recomputed and fail closed in shadow."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from server import agent_context, agent_proposal_validation, agent_proposals
from tests.agent_test_helpers import (
    complete_dual_momentum_history,
    context,
    fixed_etf_market,
    proposal_body,
)

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


def _complete(con) -> tuple[dict, dict]:
    fixed_etf_market(con)
    complete_dual_momentum_history(con)
    bounded = context(con)
    return bounded, proposal_body(bounded, now=NOW)


def test_complete_claim_passes_with_canonical_recomputation(con):
    bounded, proposal = _complete(con)

    result = agent_proposal_validation.evaluate(con, proposal, bounded)

    assert result["status"] == "pass"
    assert result["scope"] == agent_proposal_validation.VALIDATION_SCOPE
    assert result["execution_authority"] == "none"
    assert result["failed_gates"] == []
    assert result["recomputed_claim"]["signal_close"] == 120.0
    assert result["recomputed_claim"]["quantity_at_signal_close"] == pytest.approx(
        1_000 / 120
    )
    assert result["recomputed_claim"]["liquidity"]["observed_sessions"] == 60
    assert agent_proposal_validation.verify(result) == result


def test_incomplete_features_and_liquidity_are_independent_failures(con):
    fixed_etf_market(con)
    bounded = context(con)

    result = agent_proposal_validation.evaluate(
        con,
        proposal_body(bounded, now=NOW),
        bounded,
    )

    assert result["status"] == "fail"
    assert result["failed_gates"] == [
        "feature_availability",
        "liquidity_participation",
    ]
    assert result["recomputed_claim"]["liquidity"]["observed_sessions"] == 1


def test_liquidity_participation_breach_is_recomputed_from_prices(con):
    bounded, proposal = _complete(con)
    con.execute("UPDATE prices SET volume = 1 WHERE ticker = 'SPY'")

    result = agent_proposal_validation.evaluate(con, proposal, bounded)

    assert result["failed_gates"] == ["liquidity_participation"]
    assert result["recomputed_claim"]["liquidity"]["participation"] > 0.01


def test_policy_notional_and_capital_limits_are_both_enforced(con):
    bounded, proposal = _complete(con)
    proposal["max_notional"] = 39_001

    result = agent_proposal_validation.evaluate(con, proposal, bounded)

    assert result["failed_gates"] == [
        "notional_ceiling",
        "capital_concentration",
    ]


def test_invalid_buy_stop_is_rejected(con):
    bounded, proposal = _complete(con)
    proposal["stop"] = bounded["instrument"]["close"]

    result = agent_proposal_validation.evaluate(con, proposal, bounded)

    assert result["failed_gates"] == ["stop_geometry"]


def test_sell_without_reserved_inventory_is_rejected(con):
    bounded, proposal = _complete(con)
    proposal["side"] = "sell"
    proposal["stop"] = None

    result = agent_proposal_validation.evaluate(con, proposal, bounded)

    assert result["failed_gates"] == ["sell_inventory"]


def test_hybrid_proposal_is_rejected_at_veto_only_boundary(con):
    fixed_etf_market(con)
    complete_dual_momentum_history(con)
    bounded = agent_context.build(
        con,
        "dual_momentum",
        "SPY",
        policy_id="dual_momentum_hybrid_veto_shadow_v1",
    )

    result = agent_proposals.submit(
        con,
        proposal_body(bounded, now=NOW),
        now=NOW,
    )

    assert result["status"] == "shadow_rejected"
    assert result["validation_status"] == "not_run"
    assert result["validation_sha256"] is None
    assert result["reasons"] == [
        "hybrid policy requires the veto-only decision boundary"
    ]
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


def test_exact_replay_preserves_validation_evidence_without_orders(con):
    bounded, proposal = _complete(con)

    first = agent_proposals.submit(con, proposal, now=NOW)
    stored_before = con.execute(
        "SELECT validation_sha256, validation_payload FROM agent_proposals"
    ).fetchone()
    second = agent_proposals.submit(con, proposal, now=NOW)
    stored_after = con.execute(
        "SELECT validation_sha256, validation_payload FROM agent_proposals"
    ).fetchone()

    assert first["validation_status"] == "pass"
    assert second == {**first, "replayed": True}
    assert stored_after == stored_before
    assert con.execute("SELECT COUNT(*) FROM agent_proposals").fetchone() == (1,)
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)
