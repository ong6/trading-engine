"""Read-only data coverage gates for admitting new strategy research.

These gates answer only whether the local point-in-time archive is long enough
to justify drafting and testing a new hypothesis. ``READY_FOR_CHARTER`` is not
evidence of an edge, approval for a paper book, or permission to trade.
"""

from __future__ import annotations

import duckdb

from . import fundamentals_readiness, intraday_readiness, stock_readiness
from .read_model_utils import require_public_nonempty_string
from .readiness_common import require_exact_fields

FAMILY_VALIDATORS = {
    "stock_selection": stock_readiness.validate,
    "fundamentals": fundamentals_readiness.validate,
    "intraday": intraday_readiness.validate,
}
PUBLIC_FIELDS = frozenset(
    {
        "schema_version",
        "purpose",
        "paper_only",
        "automatic_action",
        "ready_families",
        "families",
        "notice",
    }
)


def validate(payload: dict) -> None:
    """Require the exact non-promotional envelope and derived family summary."""
    require_exact_fields(payload, PUBLIC_FIELDS, "research-readiness")
    if (
        payload["schema_version"] != 10
        or payload["purpose"] != "candidate_admission_only"
        or payload["paper_only"] is not True
        or payload["automatic_action"] != "none"
    ):
        raise ValueError("research-readiness envelope is invalid")
    require_public_nonempty_string(payload["notice"], "research-readiness notice")
    families = payload["families"]
    if not isinstance(families, dict) or set(families) != set(FAMILY_VALIDATORS):
        raise ValueError("research-readiness families are invalid")
    for name, validator in FAMILY_VALIDATORS.items():
        if not isinstance(families[name], dict):
            raise ValueError("research-readiness family is invalid")
        validator(families[name])
    expected_ready = sorted(
        name for name, family in families.items() if family["status"] == "READY_FOR_CHARTER"
    )
    if payload["ready_families"] != expected_ready:
        raise ValueError("research-readiness summary contradicts family statuses")


def assess(con: duckdb.DuckDBPyConnection) -> dict:
    """Return deterministic, non-promotional research-data readiness."""
    families = {
        "stock_selection": stock_readiness.assess(con),
        "fundamentals": fundamentals_readiness.assess(con),
        "intraday": intraday_readiness.assess(con),
    }
    result = {
        "schema_version": 10,
        "purpose": "candidate_admission_only",
        "paper_only": True,
        "automatic_action": "none",
        "ready_families": sorted(
            name for name, value in families.items() if value["status"] == "READY_FOR_CHARTER"
        ),
        "families": families,
        "notice": (
            "READY_FOR_CHARTER means only that data coverage cleared a minimum gate; it is "
            "not evidence of profitability or permission to activate a strategy."
        ),
    }
    validate(result)
    return result
