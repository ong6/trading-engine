"""Isolated paper-book initialization is planned without writing or enabling it."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

import pytest

from engine.lib.provenance import canonical_sha256
from server import (
    agent_paper_attribution,
    agent_paper_book_plan,
    agent_policy,
)
from sim.strategies.configs import config_by_id

START = date(2026, 9, 15)
PLANNED = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("policy_id", "mode", "portfolio_id"),
    [
        (
            "dual_momentum_agent_shadow_v1",
            "agent_only",
            "agent_dual_momentum_shadow_v1",
        ),
        (
            "dual_momentum_hybrid_veto_shadow_v1",
            "hybrid",
            "hybrid_dual_momentum_veto_shadow_v1",
        ),
    ],
)
def test_plan_binds_exact_inactive_isolated_book_without_authority(
    policy_id, mode, portfolio_id
):
    policy = agent_policy.get(policy_id)

    result = agent_paper_book_plan.plan(
        policy,
        START,
        planned_at=PLANNED,
    )

    assert agent_paper_book_plan.verify_plan(result, policy) == result
    assert result["mode"] == mode
    assert result["portfolio_id"] == portfolio_id
    assert result["portfolio_active"] is False
    assert result["allowed_atomic_insert_tables"] == [
        "portfolios",
        "agent_paper_book_attribution",
        "sim_equity",
    ]
    assert result["protected_portfolio_ids"] == [
        "dual_momentum",
        "spy_benchmark",
    ]
    assert result["scheduler_integration_implemented"] is False
    assert result["writer_implemented"] is True
    assert result["writer_entrypoint"] == "tools.initialize_agent_paper_book"
    assert result["database_mutation_performed"] is False
    assert result["order_route_implemented"] is False
    assert result["execution_authority"] == "none"
    assert result["plan_sha256"] == canonical_sha256(
        {key: value for key, value in result.items() if key != "plan_sha256"}
    )

    portfolio, attribution, equity = result["expected_records"]
    expected_contract = agent_paper_attribution.expected_book_contract(
        policy,
        START,
    )
    assert portfolio["values"] == {
        "id": portfolio_id,
        "name": f"{mode} isolated paper attribution book",
        "strategy": f"{mode}_policy",
        "config": json.dumps(
            expected_contract,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "created": START.isoformat(),
        "active": False,
        "cash": 39_000.0,
        "initial_cash": 39_000.0,
        "execution_profile": "baseline_v1",
    }
    assert json.loads(attribution["values"]["contract_payload"]) == expected_contract
    assert attribution["values"]["contract_sha256"] == canonical_sha256(
        expected_contract
    )
    assert equity["values"] == {
        "portfolio_id": portfolio_id,
        "date": START.isoformat(),
        "equity": 39_000.0,
        "cash": 39_000.0,
        "n_positions": 0,
    }
    assert result["expected_record_sha256s"] == [
        canonical_sha256(record) for record in result["expected_records"]
    ]
    assert result["required_preexisting_tables"] == [
        "portfolios",
        "agent_paper_book_attribution",
        "agent_paper_order_attribution",
        "sim_orders",
        "sim_fills",
        "sim_positions",
        "sim_dividends",
        "sim_equity",
    ]
    assert result["required_existing_control_portfolios"] == [
        {
            "portfolio_id": "dual_momentum",
            "strategy": "dual_momentum",
            "config_sha256": policy["strategy_config_sha256"],
            "active": True,
            "created_on_or_before": START.isoformat(),
            "initial_cash": 39_000.0,
            "execution_profile": "baseline_v1",
            "required_equity_date": START.isoformat(),
            "mutation_allowed": False,
        },
        {
            "portfolio_id": "spy_benchmark",
            "strategy": "spy_benchmark",
            "config_sha256": canonical_sha256(config_by_id("spy_benchmark")),
            "active": True,
            "created_on_or_before": START.isoformat(),
            "initial_cash": 39_000.0,
            "execution_profile": "baseline_v1",
            "required_equity_date": START.isoformat(),
            "mutation_allowed": False,
        },
    ]


def test_modes_have_distinct_books_and_contracts():
    agent_policy_value = agent_policy.get("dual_momentum_agent_shadow_v1")
    hybrid_policy = agent_policy.get("dual_momentum_hybrid_veto_shadow_v1")

    agent = agent_paper_book_plan.plan(
        agent_policy_value,
        START,
        planned_at=PLANNED,
    )
    hybrid = agent_paper_book_plan.plan(
        hybrid_policy,
        START,
        planned_at=PLANNED,
    )

    assert agent["portfolio_id"] != hybrid["portfolio_id"]
    assert agent["book_contract_sha256"] != hybrid["book_contract_sha256"]
    assert agent["plan_sha256"] != hybrid["plan_sha256"]
    assert agent["protected_portfolio_ids"] == hybrid["protected_portfolio_ids"]
    assert agent["portfolio_id"] not in agent["protected_portfolio_ids"]
    assert hybrid["portfolio_id"] not in hybrid["protected_portfolio_ids"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["expected_records"][0]["values"].__setitem__(
            "active", True
        ),
        lambda value: value["expected_records"][2]["values"].__setitem__(
            "n_positions", 1
        ),
        lambda value: value.__setitem__("writer_implemented", False),
        lambda value: value.__setitem__("execution_authority", "paper"),
        lambda value: value.__setitem__("plan_sha256", "0" * 64),
    ],
)
def test_verify_plan_rejects_tampering(mutation):
    policy = agent_policy.get("dual_momentum_agent_shadow_v1")
    result = agent_paper_book_plan.plan(
        policy,
        START,
        planned_at=PLANNED,
    )
    tampered = deepcopy(result)
    mutation(tampered)

    with pytest.raises(
        agent_paper_book_plan.PaperBookPlanError,
        match="does not match policy",
    ):
        agent_paper_book_plan.verify_plan(tampered, policy)


def test_plan_rejects_authority_or_invalid_time():
    policy = agent_policy.get("dual_momentum_agent_shadow_v1")
    authorized = {**policy, "execution_authority": "paper"}
    wrong_registry = {**policy, "registry_sha256": "0" * 64}

    with pytest.raises(
        agent_paper_book_plan.PaperBookPlanError,
        match="has authority",
    ):
        agent_paper_book_plan.plan(
            authorized,
            START,
            planned_at=PLANNED,
        )
    with pytest.raises(
        agent_paper_book_plan.PaperBookPlanError,
        match="identity is invalid",
    ):
        agent_paper_book_plan.plan(
            wrong_registry,
            START,
            planned_at=PLANNED,
        )
    with pytest.raises(
        agent_paper_book_plan.PaperBookPlanError,
        match="occurs after attribution start",
    ):
        agent_paper_book_plan.plan(
            policy,
            START,
            planned_at=PLANNED + timedelta(days=2),
        )
    with pytest.raises(
        agent_paper_book_plan.PaperBookPlanError,
        match="must be UTC",
    ):
        agent_paper_book_plan.plan(
            policy,
            START,
            planned_at=PLANNED.replace(tzinfo=None),
        )
