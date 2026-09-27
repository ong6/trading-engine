"""Frozen contamination-probe banks and no-call coverage preflight."""
from __future__ import annotations

import math
import random
from collections import Counter
from datetime import date
from typing import Mapping, Sequence

from engine.lib.provenance import canonical_sha256
from farm.replay.probe_power import log_comb
from farm.replay.registration import (
    PROBE_BASELINE_MINIMUM,
    PROBE_CATEGORIES,
    PROBE_EQUIVALENCE_DELTA,
    PROBE_MONTH_MINIMUM,
)


class ProbeError(ValueError):
    """A probe bank or response cannot satisfy its frozen contract."""


def _month(value: str) -> str:
    try:
        date.fromisoformat(value + "-01")
    except ValueError as exc:
        raise ProbeError("invalid_probe_month") from exc
    return value


def _fact(row: Mapping, admitted_receipts: set[str]) -> dict:
    category = row.get("category")
    receipts = row.get("receipt_ids")
    choices = row.get("choices")
    correct = row.get("correct_choice")
    if category not in PROBE_CATEGORIES:
        raise ProbeError("unsupported_probe_category")
    if not isinstance(receipts, list) or not receipts or not set(receipts) <= admitted_receipts:
        raise ProbeError("probe_receipt_not_admitted")
    if (
        not isinstance(choices, list)
        or len(choices) != 4
        or len(set(choices)) != 4
        or not all(isinstance(item, str) and item.strip() for item in choices)
        or isinstance(correct, bool)
        or not isinstance(correct, int)
        or correct not in range(4)
        or row.get("reviewed_unambiguous") is not True
    ):
        raise ProbeError("probe_answer_not_reviewed")
    try:
        event_day = date.fromisoformat(str(row["event_date"]))
    except (KeyError, ValueError) as exc:
        raise ProbeError("invalid_probe_event_date") from exc
    result = dict(row)
    result["event_date"] = event_day.isoformat()
    return result


def coverage_preflight(
    records: Sequence[Mapping],
    months: Sequence[str],
    admitted_receipts: Sequence[str],
    *,
    minimum_per_month: int = PROBE_MONTH_MINIMUM,
    category_caps: Mapping[str, int] | None = None,
    seed: int = 1604,
    responses_seen: bool = False,
) -> dict:
    """Freeze exact achievable counts and fact IDs before any provider call."""
    if responses_seen:
        raise ProbeError("coverage_must_precede_responses")
    frozen_months = [_month(value) for value in months]
    if not frozen_months or frozen_months != sorted(set(frozen_months)):
        raise ProbeError("probe_month_grid_not_frozen")
    if isinstance(minimum_per_month, bool) or minimum_per_month < 1:
        raise ProbeError("invalid_probe_minimum")
    caps = dict(category_caps or {})
    if set(caps) - set(PROBE_CATEGORIES) or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in caps.values()
    ):
        raise ProbeError("invalid_probe_category_cap")
    receipts = set(admitted_receipts)
    parsed = [_fact(row, receipts) for row in records if row.get("category") != "index_close"]
    ids = [str(row.get("fact_id", "")) for row in parsed]
    if not all(ids) or len(ids) != len(set(ids)):
        raise ProbeError("duplicate_probe_fact")
    plan_months, short = {}, {}
    for month in frozen_months:
        selected, used_clusters = {name: [] for name in PROBE_CATEGORIES}, set()
        candidates = sorted(
            (row for row in parsed if row["event_date"][:7] == month),
            key=lambda row: canonical_sha256([seed, month, row["fact_id"]]),
        )
        for row in candidates:
            cluster = str(row.get("event_cluster", ""))
            if not cluster or cluster in used_clusters:
                continue
            category = row["category"]
            if len(selected[category]) >= caps.get(category, len(candidates)):
                continue
            used_clusters.add(cluster)
            selected[category].append(str(row["fact_id"]))
        counts = {name: len(selected[name]) for name in PROBE_CATEGORIES}
        total = sum(counts.values())
        plan_months[month] = {"counts": counts, "n": total, "fact_ids": selected}
        if total < minimum_per_month:
            short[month] = total
    plan = {
        "schema_version": 1,
        "categories": list(PROBE_CATEGORIES),
        "index_close": "dropped_no_qualified_engine_source",
        "minimum_per_month": minimum_per_month,
        "seed": seed,
        "months": plan_months,
        "insufficient_months": short,
        "status": "coverage_insufficient" if short else "ready",
    }
    plan["plan_sha256"] = canonical_sha256(plan)
    return plan


def validate_coverage_plan(plan: Mapping) -> None:
    unsigned = {key: value for key, value in plan.items() if key != "plan_sha256"}
    if (
        canonical_sha256(unsigned) != plan.get("plan_sha256")
        or plan.get("categories") != list(PROBE_CATEGORIES)
        or plan.get("status") != "ready"
    ):
        raise ProbeError("coverage_plan_not_ready")
    for row in plan.get("months", {}).values():
        counts = row.get("counts", {})
        if (
            set(counts) != set(PROBE_CATEGORIES)
            or row.get("n") != sum(counts.values())
            or any(len(row.get("fact_ids", {}).get(name, ())) != counts[name]
                   for name in PROBE_CATEGORIES)
        ):
            raise ProbeError("coverage_plan_shape_invalid")


def build_bank(
    records: Sequence[Mapping],
    month: str,
    admitted_receipts: Sequence[str],
    plan: Mapping,
) -> dict:
    """Build only the exact preflight-selected bank and keep its answer key private."""
    validate_coverage_plan(plan)
    month = _month(month)
    registration = plan.get("months", {}).get(month)
    if registration is None:
        raise ProbeError("probe_month_not_registered")
    by_id = {
        str(row["fact_id"]): _fact(row, set(admitted_receipts))
        for row in records
        if row.get("category") in PROBE_CATEGORIES and str(row.get("event_date", ""))[:7] == month
    }
    prompts, key = [], []
    for category in PROBE_CATEGORIES:
        for fact_id in registration["fact_ids"][category]:
            if fact_id not in by_id:
                raise ProbeError("probe_fact_set_changed")
            row = by_id[fact_id]
            order = list(range(4))
            random.Random(
                int(canonical_sha256([plan["seed"], month, fact_id]), 16)
            ).shuffle(order)
            probe_id = canonical_sha256([month, plan["seed"], fact_id])[:24]
            prompts.append({
                "id": probe_id,
                "date": row["event_date"],
                "question": row["question"],
                "choices": [row["choices"][index] for index in order],
            })
            key.append({
                "id": probe_id,
                "correct": order.index(row["correct_choice"]),
                "category": category,
                "fact_id": fact_id,
                "event_cluster": row["event_cluster"],
                "receipt_ids": row["receipt_ids"],
            })
    return {
        "month": month,
        "prompts": prompts,
        "key": key,
        "prompt_sha256": canonical_sha256(prompts),
        "key_sha256": canonical_sha256(key),
        "coverage_plan_sha256": plan["plan_sha256"],
    }


def _binomial_cdf(k: int, n: int, probability: float) -> float:
    if k >= n or probability == 0:
        return 1.0
    logs = [
        log_comb(n, value)
        + value * math.log(probability)
        + (n - value) * math.log1p(-probability)
        for value in range(k + 1)
    ]
    peak = max(logs)
    return min(1.0, math.exp(peak) * math.fsum(math.exp(value - peak) for value in logs))


def fisher_upper(correct: int, total: int, null_correct: int, null_total: int) -> float:
    """One-sided exact two-sample Fisher tail for greater historical recall."""
    successes, combined = correct + null_correct, total + null_total
    low = max(correct, successes - null_total)
    high = min(total, successes)
    denominator = log_comb(combined, total)
    logs = [
        log_comb(successes, value)
        + log_comb(combined - successes, total - value)
        - denominator
        for value in range(low, high + 1)
    ]
    peak = max(logs)
    return min(1.0, math.exp(peak) * math.fsum(math.exp(value - peak) for value in logs))


def clopper_pearson_upper(correct: int, total: int, alpha: float = 0.05) -> float:
    if not 0 <= correct <= total or total < 1:
        raise ProbeError("invalid_probe_score")
    if correct == total:
        return 1.0
    low, high = correct / total, 1.0
    for _ in range(55):
        middle = (low + high) / 2
        if _binomial_cdf(correct, total, middle) > alpha:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def score_responses(bank: Mapping, responses: Sequence[Mapping]) -> dict:
    answers = {}
    key = {row["id"]: row for row in bank["key"]}
    for row in responses:
        choice = row.get("choice")
        if (
            row.get("id") not in key
            or row["id"] in answers
            or isinstance(choice, bool)
            or not isinstance(choice, int)
            or choice not in range(4)
        ):
            return {"status": "untestable", "reason": "invalid_response"}
        answers[row["id"]] = choice
    if set(answers) != set(key):
        return {"status": "untestable", "reason": "incomplete_response"}
    hits = Counter(
        row["category"] for row in key.values() if answers[row["id"]] == row["correct"]
    )
    counts = Counter(row["category"] for row in key.values())
    correct, total = sum(hits.values()), len(key)
    return {
        "status": "valid",
        "correct": correct,
        "n": total,
        "accuracy": correct / total,
        "upper_95": clopper_pearson_upper(correct, total),
        "category_correct": dict(hits),
        "category_n": dict(counts),
    }


def score_month(
    bank: Mapping,
    responses: Sequence[Mapping],
    measured_null: Mapping,
    *,
    planned_months: int,
    positive_control_passed: bool,
    identity_matches: bool,
) -> dict:
    result = score_responses(bank, responses)
    if result["status"] != "valid":
        return result
    if not positive_control_passed or not identity_matches:
        return {"status": "untestable", "reason": "control_or_identity"}
    if measured_null.get("status") != "valid" or measured_null.get("n", 0) < (
        PROBE_BASELINE_MINIMUM
    ):
        return {"status": "baseline_unverified"}
    if not 1 <= planned_months <= 12:
        raise ProbeError("invalid_planned_month_count")
    tails = {
        "overall": fisher_upper(
            result["correct"], result["n"], measured_null["correct"], measured_null["n"]
        )
    }
    for category in PROBE_CATEGORIES:
        left, right = result["category_n"].get(category, 0), measured_null[
            "category_n"
        ].get(category, 0)
        if left and right:
            tails[category] = fisher_upper(
                result["category_correct"].get(category, 0),
                left,
                measured_null["category_correct"].get(category, 0),
                right,
            )
    alpha = 0.05 / (3 * planned_months)
    return {
        **result,
        "status": "fail" if min(tails.values()) <= alpha else "inconclusive",
        "month": bank["month"],
        "fail_alpha_per_test": alpha,
        "fail_p": tails,
    }


def pooled_admission(months: Sequence[Mapping], measured_null: Mapping) -> dict:
    if measured_null.get("status") != "valid":
        return {"status": "baseline_unverified"}
    if not months:
        return {"status": "untestable"}
    for row in months:
        status = row.get("status")
        if status == "fail":
            return {"status": "fail", "month": row.get("month")}
        if status in {"untestable", "baseline_unverified"}:
            return {"status": status, "month": row.get("month")}
        if status != "inconclusive":
            return {"status": "untestable", "month": row.get("month")}
    null_n, null_correct = measured_null.get("n"), measured_null.get("correct")
    if not isinstance(null_n, int) or null_n < PROBE_BASELINE_MINIMUM or not (
        isinstance(null_correct, int) and 0 <= null_correct <= null_n
    ):
        return {"status": "baseline_unverified"}
    correct = sum(int(row["correct"]) for row in months)
    total = sum(int(row["n"]) for row in months)
    upper = clopper_pearson_upper(correct, total)
    limit = null_correct / null_n + PROBE_EQUIVALENCE_DELTA
    return {
        "status": "pass" if upper <= limit else "inconclusive",
        "correct": correct,
        "n": total,
        "upper_95": upper,
        "equivalence_limit": limit,
    }
