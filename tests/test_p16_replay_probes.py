"""W4 contamination probes freeze coverage before any model call."""
import pytest

from farm.replay.probe_power import pooled_power, power_preflight
from farm.replay.probes import (
    ProbeError,
    build_bank,
    coverage_preflight,
    dispatch_after_preflight,
    fisher_upper,
    pooled_admission,
    score_month,
    score_responses,
)


def _facts(count=300, month="2024-01", categories=("headline",)):
    rows = []
    for index in range(count):
        category = categories[index % len(categories)]
        rows.append({
            "fact_id": f"fact-{index}",
            "event_cluster": f"cluster-{index}",
            "event_date": f"{month}-{index % 28 + 1:02d}",
            "category": category,
            "question": f"Fixture question {index}?",
            "choices": [f"choice-{index}-{choice}" for choice in range(4)],
            "correct_choice": index % 4,
            "receipt_ids": ["receipt"],
            "reviewed_unambiguous": True,
        })
    return rows


def test_preflight_uses_total_minimum_and_allows_empty_category():
    plan = coverage_preflight(_facts(), ["2024-01"], ["receipt"])
    assert plan["status"] == "ready"
    assert plan["months"]["2024-01"]["counts"] == {
        "earnings_outcome": 0,
        "headline": 300,
    }


def test_insufficient_coverage_prevents_dispatch():
    plan = coverage_preflight(_facts(299), ["2024-01"], ["receipt"])
    called = []
    assert plan["status"] == "coverage_insufficient"
    try:
        dispatch_after_preflight(plan, lambda: called.append(True))
    except ProbeError as exc:
        assert "not_ready" in str(exc)
    else:
        raise AssertionError("insufficient plan dispatched")
    assert called == []


def test_bank_is_deterministic_and_hides_answers_from_prompts():
    facts = _facts(300, categories=("headline", "earnings_outcome"))
    plan = coverage_preflight(facts, ["2024-01"], ["receipt"])
    first = build_bank(facts, "2024-01", ["receipt"], plan)
    second = build_bank(list(reversed(facts)), "2024-01", ["receipt"], plan)
    assert first == second
    assert len(first["prompts"]) == 300
    assert set(first["prompts"][0]) == {"id", "date", "question", "choices"}
    assert "correct" not in first["prompts"][0]


def test_duplicate_event_clusters_do_not_inflate_coverage():
    facts = _facts()
    for row in facts[150:]:
        row["event_cluster"] = f"cluster-{int(row['fact_id'].split('-')[1]) - 150}"
    plan = coverage_preflight(facts, ["2024-01"], ["receipt"])
    assert plan["status"] == "coverage_insufficient"
    assert plan["months"]["2024-01"]["n"] == 150


def test_fact_receipts_must_come_from_the_admitted_export():
    try:
        coverage_preflight(_facts(), ["2024-01"], [])
    except ProbeError as exc:
        assert "receipt_not_admitted" in str(exc)
    else:
        raise AssertionError("unadmitted receipt accepted")


def test_response_failures_are_untestable_and_valid_bank_is_scored():
    facts = _facts(300, categories=("headline", "earnings_outcome"))
    plan = coverage_preflight(facts, ["2024-01"], ["receipt"])
    bank = build_bank(facts, "2024-01", ["receipt"], plan)
    incomplete = [{"id": row["id"], "choice": 0} for row in bank["key"][:-1]]
    assert score_responses(bank, incomplete) == {
        "status": "untestable",
        "reason": "incomplete_response",
    }
    responses = [{"id": row["id"], "choice": row["correct"]} for row in bank["key"]]
    result = score_responses(bank, responses)
    assert result["status"] == "valid" and result["correct"] == 300


def test_pooled_gate_requires_measured_baseline_of_registered_size():
    month = {"status": "inconclusive", "correct": 60, "n": 300}
    assert pooled_admission([month], {"status": "valid", "correct": 90, "n": 349}) == {
        "status": "baseline_unverified"
    }
    result = pooled_admission(
        [month], {"status": "valid", "correct": 90, "n": 350}
    )
    assert result["status"] in {"pass", "inconclusive"}


def test_real_month_score_chain_is_the_only_pooled_admission_input():
    baseline_facts = _facts(350, "2024-02", ("headline", "earnings_outcome"))
    baseline_plan = coverage_preflight(
        baseline_facts, ["2024-02"], ["receipt"], minimum_per_month=350
    )
    baseline_bank = build_bank(
        baseline_facts, "2024-02", ["receipt"], baseline_plan
    )
    baseline = score_responses(
        baseline_bank,
        [{"id": row["id"], "choice": (row["correct"] + 1) % 4}
         for row in baseline_bank["key"]],
    )
    facts = _facts(300, "2024-01", ("headline", "earnings_outcome"))
    plan = coverage_preflight(facts, ["2024-01"], ["receipt"])
    bank = build_bank(facts, "2024-01", ["receipt"], plan)
    responses = [
        {"id": row["id"], "choice": (row["correct"] + 1) % 4}
        for row in bank["key"]
    ]
    month = score_month(
        bank, responses, baseline, planned_months=1,
        positive_control_passed=True, identity_matches=True,
    )
    assert month["status"] == "inconclusive"
    assert pooled_admission([month], baseline)["status"] == "pass"

    failed = score_month(
        bank,
        [{"id": row["id"], "choice": row["correct"]} for row in bank["key"]],
        baseline,
        planned_months=1,
        positive_control_passed=True,
        identity_matches=True,
    )
    assert failed["status"] == "fail"
    assert pooled_admission([failed], baseline) == {
        "status": "fail", "month": "2024-01"
    }


def test_exact_fisher_tail_and_power_gate_use_frozen_sizes():
    assert fisher_upper(2, 2, 0, 2) == pytest.approx(1 / 6)
    null = pooled_power([300, 300, 300], 350, 0.25, 0.25)
    contaminated = pooled_power([300, 300, 300], 350, 0.25, 0.35)
    assert 0 <= contaminated < null <= 1
    result = power_preflight([300, 300, 300], 350, scenarios=(0.25,))
    assert result["status"] in {"ready", "power_insufficient"}
