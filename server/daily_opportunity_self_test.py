"""Non-mutating structural self-test for the P8/P9 paper-agent boundary."""
from __future__ import annotations

import json

from engine.lib.provenance import canonical_sha256
from engine.lib.settings import REPO_ROOT

from . import agent_model_client, daily_opportunity_execution

REGISTRATION = REPO_ROOT / "server" / "agent-cadence-registration.json"


def run() -> dict:
    registration = json.loads(REGISTRATION.read_text())
    variants = registration.get("variants")
    expected = {"hourly_market_watch_v4", "four_hour_opportunity_review_v4",
                "nightly_opportunity_tool_v1", "daily_gap_volume_veto_v1"}
    errors = []
    if not isinstance(variants, list) or {item.get("id") for item in variants} != expected:
        errors.append("cadence_registry")
    writers = [item for item in variants or [] if item.get("execution_authority") != "none"]
    if len(writers) != 1 or writers[0].get("id") != registration.get("execution_policy_id"):
        errors.append("single_execution_policy")
    tool = agent_model_client.TRADE_TOOL
    if (tool.get("name") != "submit_paper_trade"
            or {"quantity", "account", "broker", "price"}
            & set(tool.get("parameters", {}).get("properties", {}))):
        errors.append("tool_authority")
    if (daily_opportunity_execution.BOOK_CONFIG.get("simulator_only") is not True
            or daily_opportunity_execution.BOOK_CONFIG.get("strategy") != "agent_only_policy"):
        errors.append("book_contract")
    if not {"maximum_hold_sessions", "close_below_signal_low"} == set(
        daily_opportunity_execution.EXIT_REASONS
    ):
        errors.append("exit_contract")
    return {
        "status": "pass" if not errors else "failed",
        "errors": errors, "variant_count": len(variants or []),
        "execution_policy_count": len(writers),
        "registration_sha256": canonical_sha256(registration),
        "tool_schema_sha256": canonical_sha256(tool),
        "broker_route": "absent",
    }


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
