"""Explicit runtime revision stamped into every walk-forward evidence cohort."""
from __future__ import annotations

from engine.lib.provenance import canonical_sha256

REVISION = 2
DECISION_DATE = "2026-10-06"
COST_PROFILE = "ibkr_pro_tiered_v1"
COST_BREAK_SESSION = "migration --d0 parameter"
MIGRATION = (
    "Owner decision 2026-10-06: every engine book pays ibkr_pro_tiered_v1 from the "
    "parameterized D0 and restarts its evaluation clock. Additive account schema, "
    "monotonic order sequence and shared ledger/replay replace the prior runtime; a "
    "snapshot-copy pre-D0 rerun proved league.csv and league.md byte-identical. "
    "Walk-forward protocol geometry, comparisons and gates are unchanged."
)


def payload() -> dict:
    body = {
        "revision": REVISION,
        "decision_date": DECISION_DATE,
        "cost_profile": COST_PROFILE,
        "cost_break_session": COST_BREAK_SESSION,
        "migration": MIGRATION,
    }
    return {**body, "sha256": canonical_sha256(body)}
