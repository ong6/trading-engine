"""Closed model-output decisions reject ambiguity and invented evidence."""

from __future__ import annotations

import pytest

from server import agent_decision_contract

EVIDENCE = frozenset({"a" * 64, "b" * 64})


def proposal(**overrides):
    body = {
        "schema_version": 1,
        "decision": "proposal",
        "side": "buy",
        "max_notional": 1_000,
        "stop": None,
        "confidence": 0.5,
        "thesis": "A bounded shadow-only claim.",
        "invalidation": "The claim expires with the decision window.",
        "evidence_ids": ["a" * 64],
    }
    body.update(overrides)
    return body


def test_accepts_exact_no_action_and_proposal_shapes():
    assert agent_decision_contract.normalize(
        {"schema_version": 1, "decision": "no_action", "reason": "No sufficient edge."},
        allowed_evidence_ids=EVIDENCE,
    ) == {
        "schema_version": 1,
        "decision": "no_action",
        "reason": "No sufficient edge.",
    }
    assert agent_decision_contract.normalize(
        proposal(),
        allowed_evidence_ids=EVIDENCE,
    ) == {
        **proposal(),
        "max_notional": 1_000.0,
        "confidence": 0.5,
    }


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ({"schema_version": 1, "decision": "hold"}, "decision must"),
        (
            {
                "schema_version": 1,
                "decision": "no_action",
                "reason": "none",
                "ticker": "SPY",
            },
            "unknown decision field",
        ),
        (proposal(evidence_ids=["invented"]), "outside the context allowlist"),
        (proposal(evidence_ids=["a" * 64, "a" * 64]), "duplicates"),
        (proposal(max_notional=float("nan")), "positive finite"),
        (proposal(confidence=1.1), "between 0 and 1"),
    ],
)
def test_rejects_open_or_invalid_model_claims(body, detail):
    with pytest.raises(agent_decision_contract.DecisionError, match=detail):
        agent_decision_contract.normalize(body, allowed_evidence_ids=EVIDENCE)
