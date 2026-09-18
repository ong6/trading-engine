"""Pure plan for initializing one isolated, inactive agent paper book.

The plan describes the exact records accepted by the separate backup-gated
operator initializer. This module does not open a database, create a table or
portfolio, schedule a strategy, or grant paper execution authority.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

from engine.lib.provenance import canonical_sha256
from sim.strategies.configs import config_by_id

from . import agent_paper_attribution, agent_policy

PLAN_SCHEMA_VERSION = 1
RECORD_SCHEMA_VERSION = 1


class PaperBookPlanError(ValueError):
    """An isolated-book initialization plan is malformed or inconsistent."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _timestamp(value: object) -> str:
    if (
        type(value) is not datetime
        or value.utcoffset() is None
        or value.utcoffset().total_seconds() != 0
    ):
        raise PaperBookPlanError("paper book plan time must be UTC")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PaperBookPlanError("paper book plan time is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PaperBookPlanError("paper book plan time is invalid") from exc
    if _timestamp(parsed) != value:
        raise PaperBookPlanError("paper book plan time is not canonical")
    return parsed


def _policy_contract(policy: dict, start: date) -> dict:
    if not isinstance(policy, dict):
        raise PaperBookPlanError("paper book policy is invalid")
    expected_fields = agent_policy.POLICY_FIELDS | {
        "registration_sha256",
        "registry_sha256",
    }
    if (
        policy.get("authority_stage") != "shadow_proposal_only"
        or policy.get("execution_authority") != "none"
        or policy.get("mode") not in {"agent_only", "hybrid"}
    ):
        raise PaperBookPlanError("paper book policy has authority")
    try:
        registered = agent_policy.get(policy["id"])
    except (KeyError, TypeError, agent_policy.PolicyError) as exc:
        raise PaperBookPlanError("paper book policy identity is invalid") from exc
    if set(policy) != expected_fields or policy != registered:
        raise PaperBookPlanError("paper book policy identity is invalid")
    try:
        contract = agent_paper_attribution.expected_book_contract(policy, start)
    except (KeyError, TypeError, agent_paper_attribution.PaperAttributionError) as exc:
        raise PaperBookPlanError("paper book policy is invalid") from exc
    controls = (
        contract["source_portfolio_id"],
        contract["algorithm_control_id"],
        contract["strategy_control_id"],
    )
    if (
        contract["portfolio_id"] in controls
        or policy["control_id"] == contract["portfolio_id"]
        or policy["control_id"] in controls
        or contract["algorithm_control_id"]
        == contract["strategy_control_id"]
    ):
        raise PaperBookPlanError("paper book identities are not isolated")
    return contract


def _body(policy: dict, start: date, planned_at: datetime) -> dict:
    if type(start) is not date:
        raise PaperBookPlanError("paper book attribution start must be a date")
    planned = _timestamp(planned_at)
    if planned_at.date() > start:
        raise PaperBookPlanError("paper book plan occurs after attribution start")
    contract = _policy_contract(policy, start)
    contract_sha256 = canonical_sha256(contract)
    initial_cash = contract["initial_cash"]
    portfolio_id = contract["portfolio_id"]
    control_ids = sorted(
        {
            contract["algorithm_control_id"],
            contract["strategy_control_id"],
        }
    )
    required_controls = []
    for control_id in control_ids:
        control_config = config_by_id(control_id)
        required_controls.append(
            {
                "portfolio_id": control_id,
                "strategy": control_config["strategy"],
                "config_sha256": canonical_sha256(control_config),
                "active": True,
                "created_on_or_before": start.isoformat(),
                "initial_cash": initial_cash,
                "execution_profile": contract["execution_profile_id"],
                "required_equity_date": start.isoformat(),
                "mutation_allowed": False,
            }
        )
    records = [
        {
            "schema_version": RECORD_SCHEMA_VERSION,
            "table": "portfolios",
            "operation": "insert_only",
            "values": {
                "id": portfolio_id,
                "name": f"{contract['mode']} isolated paper attribution book",
                "strategy": contract["book_strategy"],
                "config": _canonical_json(contract),
                "created": start.isoformat(),
                "active": False,
                "cash": initial_cash,
                "initial_cash": initial_cash,
                "execution_profile": contract["execution_profile_id"],
            },
        },
        {
            "schema_version": RECORD_SCHEMA_VERSION,
            "table": agent_paper_attribution.BOOK_ATTRIBUTION_TABLE,
            "operation": "insert_only",
            "values": {
                "portfolio_id": portfolio_id,
                "policy_id": contract["policy_id"],
                "policy_registration_sha256": contract[
                    "policy_registration_sha256"
                ],
                "mode": contract["mode"],
                "contract_payload": _canonical_json(contract),
                "contract_sha256": contract_sha256,
                "recorded_at": planned,
            },
        },
        {
            "schema_version": RECORD_SCHEMA_VERSION,
            "table": "sim_equity",
            "operation": "insert_only",
            "values": {
                "portfolio_id": portfolio_id,
                "date": start.isoformat(),
                "equity": initial_cash,
                "cash": initial_cash,
                "n_positions": 0,
            },
        },
    ]
    record_hashes = [canonical_sha256(record) for record in records]
    allowed_tables = [record["table"] for record in records]
    protected_portfolios = sorted(
        {
            contract["source_portfolio_id"],
            contract["algorithm_control_id"],
            contract["strategy_control_id"],
        }
    )
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "status": "ready_for_backup_gated_inactive_initialization",
        "policy_id": contract["policy_id"],
        "policy_registration_sha256": contract["policy_registration_sha256"],
        "registry_sha256": contract["registry_sha256"],
        "mode": contract["mode"],
        "portfolio_id": portfolio_id,
        "attribution_start_date": start.isoformat(),
        "planned_at": planned,
        "book_contract_sha256": contract_sha256,
        "expected_records": records,
        "expected_record_sha256s": record_hashes,
        "required_absence": {
            "portfolio_id": portfolio_id,
            "book_contract_policy_id": contract["policy_id"],
            "book_contract_portfolio_id": portfolio_id,
            "simulator_rows_for_portfolio": [
                "sim_orders",
                "sim_fills",
                "sim_positions",
                "sim_dividends",
                "sim_equity",
            ],
        },
        "required_preexisting_tables": [
            "portfolios",
            agent_paper_attribution.BOOK_ATTRIBUTION_TABLE,
            agent_paper_attribution.ORDER_ATTRIBUTION_TABLE,
            "sim_orders",
            "sim_fills",
            "sim_positions",
            "sim_dividends",
            "sim_equity",
        ],
        "required_existing_control_portfolios": required_controls,
        "allowed_atomic_insert_tables": allowed_tables,
        "protected_portfolio_ids": protected_portfolios,
        "required_transaction": "single_atomic_insert_only_transaction",
        "post_write_verifier": "server.agent_paper_attribution.assess_policy",
        "portfolio_active": False,
        "scheduler_integration_implemented": False,
        "writer_implemented": True,
        "writer_entrypoint": "tools.initialize_agent_paper_book",
        "database_mutation_performed": False,
        "order_route_implemented": False,
        "execution_authority": "none",
    }


def verify_plan(plan: object, policy: dict) -> dict:
    """Verify a plan against one already validated frozen policy."""
    if not isinstance(plan, dict) or set(plan) != {
        "schema_version",
        "status",
        "policy_id",
        "policy_registration_sha256",
        "registry_sha256",
        "mode",
        "portfolio_id",
        "attribution_start_date",
        "planned_at",
        "book_contract_sha256",
        "expected_records",
        "expected_record_sha256s",
        "required_absence",
        "required_preexisting_tables",
        "required_existing_control_portfolios",
        "allowed_atomic_insert_tables",
        "protected_portfolio_ids",
        "required_transaction",
        "post_write_verifier",
        "portfolio_active",
        "scheduler_integration_implemented",
        "writer_implemented",
        "writer_entrypoint",
        "database_mutation_performed",
        "order_route_implemented",
        "execution_authority",
        "plan_sha256",
    }:
        raise PaperBookPlanError("paper book plan shape is invalid")
    try:
        start = date.fromisoformat(plan["attribution_start_date"])
        planned_at = _parse_timestamp(plan["planned_at"])
    except (TypeError, ValueError) as exc:
        raise PaperBookPlanError("paper book plan dates are invalid") from exc
    if start.isoformat() != plan["attribution_start_date"]:
        raise PaperBookPlanError("paper book plan dates are invalid")
    expected_body = _body(policy, start, planned_at)
    body = {key: value for key, value in plan.items() if key != "plan_sha256"}
    if (
        body != expected_body
        or plan["plan_sha256"] != canonical_sha256(expected_body)
    ):
        raise PaperBookPlanError("paper book plan does not match policy")
    return plan


def plan(
    policy: dict,
    attribution_start_date: date,
    *,
    planned_at: datetime,
) -> dict:
    """Build one exact, non-executable isolated-book initialization plan."""
    body = _body(policy, attribution_start_date, planned_at)
    return verify_plan(
        {**body, "plan_sha256": canonical_sha256(body)},
        policy,
    )
