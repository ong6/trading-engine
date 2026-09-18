"""Closed schema and normalization tests for shadow agent proposals."""

from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import TypeAdapter

from server import agent_contract, main
from tests.agent_test_helpers import proposal_body

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
CONTEXT = {
    "policy": {
        "id": "dual_momentum_agent_shadow_v1",
        "mode": "agent_only",
        "registration_sha256": "8" * 64,
    },
    "strategy": {"id": "dual_momentum", "config_sha256": "3" * 64},
    "instrument": {"ticker": "SPY"},
    "decision_model": {
        "model": "GPT-5.6-Sol:max",
        "model_version": "unversioned-catalog-alias",
        "instructions_sha256": "1" * 64,
        "toolset_sha256": "2" * 64,
    },
    "provenance": {
        "agent_boundary_sha256": "4" * 64,
        "runtime_source_sha256": "5" * 64,
        "data_snapshot_sha256": "6" * 64,
    },
    "context_sha256": "7" * 64,
}


@pytest.mark.parametrize(
    ("field", "value", "detail"),
    [
        ("schema_version", True, "schema_version must be 2"),
        ("schema_version", 1, "schema_version must be 2"),
        ("proposal_id", "bad id", "proposal_id is invalid"),
        ("prompt_sha256", "A" * 64, "lowercase SHA-256"),
        ("ticker", "spy", "canonical uppercase"),
        ("mode", "automatic", "mode must be"),
        ("side", "hold", "side must be"),
        ("max_notional", True, "finite number"),
        ("max_notional", float("inf"), "positive finite number"),
        ("confidence", 1.1, "between 0 and 1"),
        ("evidence_ids", [], "nonempty bounded array"),
    ],
)
def test_proposal_contract_rejects_malformed_fields(field, value, detail):
    with pytest.raises(agent_contract.ProposalError, match=detail) as error:
        agent_contract.normalize(proposal_body(CONTEXT, now=NOW, **{field: value}), now=NOW)

    assert error.value.status_code == 400


def test_proposal_contract_rejects_unknown_and_missing_fields():
    with pytest.raises(agent_contract.ProposalError, match="unknown proposal field"):
        agent_contract.normalize(proposal_body(CONTEXT, now=NOW, extra=True), now=NOW)

    body = proposal_body(CONTEXT, now=NOW)
    body.pop("context_sha256")
    with pytest.raises(agent_contract.ProposalError, match="missing proposal field"):
        agent_contract.normalize(body, now=NOW)


@pytest.mark.parametrize(
    ("signal_delta", "expiry_delta", "detail"),
    [
        (timedelta(days=-2), timedelta(days=1), "signal_at"),
        (timedelta(minutes=6), timedelta(days=1), "signal_at"),
        (timedelta(), timedelta(), "expires_at"),
        (timedelta(), timedelta(days=8), "expires_at"),
        (timedelta(minutes=4), timedelta(minutes=3), "after signal_at"),
    ],
)
def test_proposal_contract_enforces_time_window(signal_delta, expiry_delta, detail):
    with pytest.raises(agent_contract.ProposalError, match=detail):
        agent_contract.normalize(
            proposal_body(
                CONTEXT,
                now=NOW,
                signal_at=(NOW + signal_delta).isoformat(),
                expires_at=(NOW + expiry_delta).isoformat(),
            ),
            now=NOW,
        )


def test_proposal_http_schema_is_closed_and_versioned():
    operation = main.app.openapi()["paths"]["/agent/proposals/shadow"]["post"]
    schema_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    schema = main.app.openapi()["components"]["schemas"][schema_ref.rsplit("/", 1)[-1]]

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == agent_contract.PROPOSAL_FIELDS
    assert set(schema["properties"]) == agent_contract.PROPOSAL_FIELDS
    assert schema["properties"]["mode"]["enum"] == ["agent_only", "hybrid"]
    assert schema["properties"]["side"]["enum"] == ["buy", "sell"]


def test_http_parser_preserves_scalar_types_for_domain_validation():
    adapter = TypeAdapter(agent_contract.TradeProposalRequest)
    parsed = adapter.validate_python(proposal_body(CONTEXT, now=NOW, max_notional=True))

    assert parsed.max_notional is True
    with pytest.raises(agent_contract.ProposalError, match="finite number"):
        agent_contract.normalize(asdict(parsed), now=NOW)
