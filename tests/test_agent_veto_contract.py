"""The hybrid output can only allow or veto one frozen candidate."""

from __future__ import annotations

import pytest

from server import agent_veto_contract

CANDIDATE = "a" * 64
EVIDENCE = frozenset({CANDIDATE, "b" * 64})


def body(**overrides):
    value = {
        "schema_version": 1,
        "decision": "veto",
        "candidate_sha256": CANDIDATE,
        "reason": "The bounded evidence invalidates this buy candidate.",
        "evidence_ids": [CANDIDATE],
    }
    value.update(overrides)
    return value


def test_contract_accepts_only_allow_or_veto_for_exact_candidate():
    assert agent_veto_contract.normalize(
        body(),
        expected_candidate_sha256=CANDIDATE,
        allowed_evidence_ids=EVIDENCE,
    ) == body()
    assert agent_veto_contract.normalize(
        body(decision="allow"),
        expected_candidate_sha256=CANDIDATE,
        allowed_evidence_ids=EVIDENCE,
    )["decision"] == "allow"


@pytest.mark.parametrize(
    ("overrides", "detail"),
    [
        ({"decision": "proposal"}, "allow or veto"),
        ({"candidate_sha256": "c" * 64}, "does not match"),
        ({"evidence_ids": ["invented"]}, "outside the context allowlist"),
        ({"ticker": "EFA"}, "unknown veto field"),
        ({"max_notional": 1}, "unknown veto field"),
        ({"side": "sell"}, "unknown veto field"),
    ],
)
def test_contract_rejects_candidate_or_order_mutation(overrides, detail):
    with pytest.raises(agent_veto_contract.VetoDecisionError, match=detail):
        agent_veto_contract.normalize(
            body(**overrides),
            expected_candidate_sha256=CANDIDATE,
            allowed_evidence_ids=EVIDENCE,
        )


def test_public_schema_explicitly_forbids_order_and_sell_control():
    schema = agent_veto_contract.output_schema()

    assert schema["additional_fields"] is False
    assert schema["order_creation"] is False
    assert schema["order_mutation"] is False
    assert schema["sell_veto"] is False
