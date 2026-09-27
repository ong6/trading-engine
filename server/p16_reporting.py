"""Read-only JSON and Markdown projections for P16 evaluation evidence."""
from __future__ import annotations

import math
from datetime import datetime

from farm import p16_evaluation_report

from . import p16_store

EVALUATION_POLICY_ID = "p16-eval-v2"


def project(con, *, generated_at: datetime) -> dict:
    """Project the latest visible, validated P16 family report."""
    base = {
        "schema_version": 1,
        "status": "not_initialized",
        "evaluation_policy_id": EVALUATION_POLICY_ID,
        "family_report": None,
        "promotion_authority": "owner_review_required",
        "execution_authority": "none",
    }
    stored = p16_store.family_report_as_of(con, generated_at=generated_at)
    if stored is None:
        return base
    report = p16_evaluation_report.validate_report(stored["payload"])
    status = report.get("status")
    if status not in {"available", "incomplete", "stale"}:
        raise ValueError("P16 family report status is invalid")
    return {**base, "status": status, "family_report": report}


def _number(value: object) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool) \
            or not math.isfinite(value):
        return "unavailable"
    return f"{value:.6g}"


def markdown(report: dict) -> str:
    """Render the P16 section from a validated status projection."""
    if (not isinstance(report, dict) or report.get("schema_version") != 1
            or report.get("evaluation_policy_id") != EVALUATION_POLICY_ID
            or report.get("promotion_authority") != "owner_review_required"
            or report.get("execution_authority") != "none"):
        raise ValueError("P16 status projection is invalid")
    status = report.get("status")
    family = report.get("family_report")
    lines = ["# P16 evaluation", "", f"Status: **{status}**", ""]
    if family is None:
        if status != "not_initialized":
            raise ValueError("P16 status lacks its family report")
        return "\n".join(lines)
    p16_evaluation_report.validate_report(family)
    if status != family.get("status"):
        raise ValueError("P16 status differs from its family report")
    lines.extend([
        f"Report cutoff: `{family['report_at']}`  ",
        f"Origin endpoint: `{family['origin_endpoint']}`  ",
        "Promotion authority: **owner review required**  ",
        "Execution authority: **none**", "",
        "| Comparison | Current log-e | Maximum log-e | DSR | Neutral IC | Promotion | Filters |",
        "|---|---:|---:|---:|---:|---|---|",
    ])
    for row in family["comparisons"]:
        primary = row["sequential"]["primary"]
        dsr = row["deflated_sharpe"]
        neutral = row["factor_neutral"]
        filters = ", ".join(row["filter_reasons"]) or "none"
        lines.append(
            f"| {row['comparison_id']} | {_number(primary.get('log_e'))} | "
            f"{_number(primary.get('max_log_e'))} | {_number(dsr.get('probability'))} | "
            f"{_number(neutral.get('mean_neutral_ic'))} | "
            f"{'yes' if row['candidate_for_promotion'] else 'no'} | {filters} |"
        )
    lines.extend(["", "## Transfer coefficient", "",
                  "| Book | Status | TC diagonal |", "|---|---|---:|"])
    for row in family["transfer"]:
        lines.append(f"| {row['book_id']} | {row.get('status', 'unavailable')} | "
                     f"{_number(row.get('tc_diagonal'))} |")
    return "\n".join(lines) + "\n"
