"""Read-only policy registrations and isolated shadow evidence counts."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import duckdb

from engine.lib.util import table_exists

from . import agent_policy
from .read_model_utils import require_public_nonnegative_integer

LEGACY_POLICY_ID = "legacy_unregistered"
TERMINAL_OUTCOMES = (
    "cadence_no_action",
    "no_action",
    "proposal_result",
    "proposal_failure",
    "malformed_output",
    "transport_failure",
    "uncertain",
    "hybrid_no_veto_candidate",
    "hybrid_allow",
    "hybrid_veto",
    "hybrid_fallback_allow",
)


def _count_by_policy(
    con: duckdb.DuckDBPyConnection,
    table: str,
) -> Counter[str]:
    if not table_exists(con, table):
        return Counter()
    result: Counter[str] = Counter()
    for policy_id, count in con.execute(
        f"SELECT policy_id, COUNT(*) FROM {table} GROUP BY policy_id"
    ).fetchall():
        key = LEGACY_POLICY_ID if policy_id is None else policy_id
        result[key] = require_public_nonnegative_integer(count)
    return result


def _outcomes_by_policy(
    con: duckdb.DuckDBPyConnection,
) -> dict[str, Counter[str]]:
    if not table_exists(con, "agent_shadow_attempts") or not table_exists(
        con, "agent_shadow_events"
    ):
        return {}
    result: dict[str, Counter[str]] = {}
    placeholders = ",".join("?" for _ in TERMINAL_OUTCOMES)
    rows = con.execute(
        "SELECT a.policy_id, e.event_type, COUNT(*) "
        "FROM agent_shadow_attempts a JOIN agent_shadow_events e "
        "ON e.attempt_id = a.id "
        f"WHERE e.event_type IN ({placeholders}) "
        "GROUP BY a.policy_id, e.event_type",
        list(TERMINAL_OUTCOMES),
    ).fetchall()
    for policy_id, event_type, count in rows:
        key = LEGACY_POLICY_ID if policy_id is None else policy_id
        result.setdefault(key, Counter())[event_type] = (
            require_public_nonnegative_integer(count)
        )
    return result


def evaluation(
    con: duckdb.DuckDBPyConnection,
    *,
    registration_path: Path = agent_policy.REGISTRATION_PATH,
) -> dict:
    """Expose policy-separated evidence without claiming performance."""
    registry = agent_policy.registry(registration_path)
    attempt_counts = _count_by_policy(con, "agent_shadow_attempts")
    proposal_counts = _count_by_policy(con, "agent_proposals")
    outcomes = _outcomes_by_policy(con)
    registered_ids = {policy["id"] for policy in registry["policies"]}
    unknown_ids = (set(attempt_counts) | set(proposal_counts)) - registered_ids - {
        LEGACY_POLICY_ID
    }
    if unknown_ids:
        raise ValueError("agent evidence references an unregistered policy")

    policies = []
    for raw in registry["policies"]:
        policy = agent_policy.get(raw["id"], path=registration_path)
        reserved_exists = con.execute(
            "SELECT COUNT(*) FROM portfolios WHERE id = ?",
            [policy["reserved_portfolio_id"]],
        ).fetchone()[0]
        if reserved_exists not in {0, 1}:
            raise ValueError("agent reserved portfolio identity is duplicated")
        policies.append(
            {
                "policy_id": policy["id"],
                "policy_registration_sha256": policy["registration_sha256"],
                "mode": policy["mode"],
                "authority_stage": policy["authority_stage"],
                "generation_enabled": policy["generation_enabled"],
                "strategy_id": policy["strategy_id"],
                "reserved_portfolio_id": policy["reserved_portfolio_id"],
                "reserved_portfolio_created": reserved_exists == 1,
                "model_role": policy["model_role"],
                "model_failure_policy": policy["model_failure_policy"],
                "hybrid_behavior": policy["hybrid_behavior"],
                "strategy_control_id": policy["attribution"]["strategy_control_id"],
                "algorithm_control_id": policy["attribution"][
                    "algorithm_control_id"
                ],
                "attempt_count": attempt_counts[policy["id"]],
                "proposal_count": proposal_counts[policy["id"]],
                "terminal_outcomes": {
                    event_type: outcomes.get(policy["id"], Counter())[event_type]
                    for event_type in TERMINAL_OUTCOMES
                },
                "execution_authority": "none",
            }
        )

    legacy = {
        "policy_id": LEGACY_POLICY_ID,
        "mode": "legacy",
        "attempt_count": attempt_counts[LEGACY_POLICY_ID],
        "proposal_count": proposal_counts[LEGACY_POLICY_ID],
        "terminal_outcomes": {
            event_type: outcomes.get(LEGACY_POLICY_ID, Counter())[event_type]
            for event_type in TERMINAL_OUTCOMES
        },
        "included_in_registered_policy_evaluation": False,
    }
    return {
        "schema_version": 1,
        "registry_sha256": registry["registry_sha256"],
        "evaluation_scope": "registration_and_evidence_counts_only",
        "performance_claim": "none",
        "evidence_pooling": "prohibited",
        "execution_authority": "none",
        "policies": policies,
        "legacy_unregistered": legacy,
    }
