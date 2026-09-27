"""Read-only JSON and Markdown projections for P16 evaluation evidence."""
from __future__ import annotations

import math
from datetime import date, datetime
from pathlib import Path

import duckdb

from engine.lib.provenance import canonical_sha256
from farm import p16_evaluation_report

from . import p16_book_store, p16_preentry, p16_registration, p16_store

EVALUATION_POLICY_ID = "p16-eval-v2"


def project(
    con, *, generated_at: datetime,
    registration_path: Path = p16_registration.REGISTRATION_PATH,
) -> dict:
    """Project the latest visible, validated P16 family report."""
    registration = p16_registration.load(registration_path, required=False)
    try:
        construction = p16_book_store.status_projection(
            con, registration_sha256=None if registration is None
            else registration["registration_sha256"],
        )
    except (duckdb.Error, p16_book_store.P16BookError, ValueError):
        construction = {
            "schema_version": 1, "status": "unavailable",
            "mechanics_version": p16_book_store.MECHANICS_VERSION,
            "book_ids": list(p16_book_store.LOGICAL_BOOK_IDS), "books": [],
            "reason": "construction_validation_failed", "execution_authority": "none",
        }
    origin_grid = None
    if registration is not None:
        origin_grid = p16_preentry.grid_report(
            con, registration_sha256=registration["registration_sha256"],
            family_id=registration["evaluation"]["family_id"],
            epoch_session=date.fromisoformat(
                registration["evaluation"]["epoch_session"]),
            members=p16_registration.family_members(registration),
            generated_at=generated_at,
        )
    blocked = origin_grid is not None \
        and origin_grid["status"] == "blocked_missing_origin_decision"
    base = {
        "schema_version": 1,
        "status": "not_initialized",
        "evaluation_policy_id": EVALUATION_POLICY_ID,
        "family_report": None,
        "origin_grid": origin_grid, "promotion_candidate_ids": [],
        "construction": construction,
        "promotion_authority": "owner_review_required",
        "execution_authority": "none",
    }
    stored = p16_store.family_report_as_of(con, generated_at=generated_at)
    if stored is None:
        return {**base, "status": "incomplete" if blocked else "not_initialized"}
    report = p16_evaluation_report.validate_report(stored["payload"])
    status = report.get("status")
    if status not in {"available", "incomplete", "stale"}:
        raise ValueError("P16 family report status is invalid")
    return {
        **base, "status": "incomplete" if blocked else status,
        "family_report": report,
        "promotion_candidate_ids": [] if blocked else report["promotion_candidate_ids"],
    }


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
    origin_grid = report.get("origin_grid")
    blocked = isinstance(origin_grid, dict) \
        and origin_grid.get("status") == "blocked_missing_origin_decision"
    if origin_grid is not None and (
            origin_grid.get("grid_report_sha256") != canonical_sha256({
                key: value for key, value in origin_grid.items()
                if key != "grid_report_sha256"})):
        raise ValueError("P16 origin-grid report differs")
    lines = ["# P16 evaluation", "", f"Status: **{status}**", ""]
    construction = report.get("construction")
    if not isinstance(construction, dict) or construction.get("execution_authority") != "none":
        raise ValueError("P16 construction projection is invalid")
    construction_lines = [
        "## Portfolio construction v2", "",
        f"Status: **{construction['status']}**", "",
        "| Book | Active | Lambda | Cost / turnover | Latest target |",
        "|---|---|---:|---:|---|",
    ]
    for row in construction["books"]:
        target = row.get("latest_target")
        construction_lines.append(
            f"| {row['book_id']} | {'yes' if row['active'] else 'no'} | "
            f"{_number(row.get('risk_aversion'))} | {_number(row.get('cost_per_turnover'))} | "
            f"{target['signal_date'] if target else 'unavailable'} |"
        )
    if family is None:
        if status != "not_initialized" and not (status == "incomplete" and blocked):
            raise ValueError("P16 status lacks its family report")
        if blocked:
            lines.extend(_gap_lines(origin_grid))
        lines.extend(["", *construction_lines])
        return "\n".join(lines)
    p16_evaluation_report.validate_report(family)
    if status != family.get("status") and not (status == "incomplete" and blocked):
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
            f"{'yes' if row['candidate_for_promotion'] and not blocked else 'no'} | "
            f"{filters if not blocked else 'missing_preentry_decision'} |"
        )
    if blocked:
        lines.extend(["", *_gap_lines(origin_grid)])
    lines.extend(["", "## Transfer coefficient", "",
                  "| Book | Status | TC diagonal |", "|---|---|---:|"])
    for row in family["transfer"]:
        lines.append(f"| {row['book_id']} | {row.get('status', 'unavailable')} | "
                     f"{_number(row.get('tc_diagonal'))} |")
    lines.extend(["", *construction_lines])
    return "\n".join(lines) + "\n"


def _gap_lines(origin_grid: dict) -> list[str]:
    index = origin_grid["first_permanently_missing_session_index"]
    market_date = origin_grid["first_permanently_missing_origin"]
    return [
        f"Fixed-grid gap: origin index {index} ({market_date}) has no decision retained "
        "before its forward entry; later origins keep their registered indices and were not "
        "backfilled into this slot.",
        "", "Promotion is blocked while the fixed-grid prefix is incomplete.",
    ]
