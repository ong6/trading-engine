"""P16-only adapter around frozen P15 evaluation status."""
from __future__ import annotations

import copy
from datetime import datetime

import duckdb

from farm import p16_diagnostics

from . import p16_book_store, p16_reporting


def with_primary_kill(projection: dict) -> dict:
    """Project a P15 primary kill onto every book comparison without editing P15."""
    result = copy.deepcopy(projection)
    p15 = result.get("p15")
    if not isinstance(p15, dict) or p15.get("primary", {}).get("status") != "kill":
        return result
    books = p15.get("books")
    if not isinstance(books, dict) or not isinstance(books.get("comparisons"), list):
        return result
    books["status"] = "killed"
    for comparison in books["comparisons"]:
        if not isinstance(comparison, dict):
            continue
        status = p16_diagnostics.book_comparison_status(
            "kill", eligible=comparison.get("eligible") is True, final_look=False,
        )
        comparison["status"] = status
        comparison["promotion_status"] = status
    return result


def project(con, *, generated_at: datetime) -> dict:
    """Contain P16 validation/storage failures behind an unavailable projection."""
    try:
        return p16_reporting.project(con, generated_at=generated_at)
    except (duckdb.Error, OSError, ValueError, KeyError, TypeError):
        return {
            "schema_version": 1, "status": "unavailable",
            "evaluation_policy_id": p16_reporting.EVALUATION_POLICY_ID,
            "family_report": None, "origin_grid": None,
            "promotion_candidate_ids": [],
            "construction": {
                "schema_version": 1, "status": "unavailable",
                "mechanics_version": p16_book_store.MECHANICS_VERSION,
                "book_ids": list(p16_book_store.LOGICAL_BOOK_IDS), "books": [],
                "reason": "p16_status_projection_failed", "execution_authority": "none",
            },
            "promotion_authority": "owner_review_required",
            "execution_authority": "none",
            "reason": "p16_status_projection_failed",
        }
