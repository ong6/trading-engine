"""Frozen P9 deterministic gap-and-volume candidate for paired forward observation."""
from __future__ import annotations

from engine.daily_opportunities import MIN_STANDOUT_SCORE

MIN_DAILY_RETURN = 0.05
MIN_RELATIVE_VOLUME = 2.0


def select(bundle: dict) -> dict | None:
    """Choose the highest-ranked eligible buy without reading future data."""
    for candidate in bundle.get("candidates", []):
        if (
            candidate.get("standout_score", 0) >= MIN_STANDOUT_SCORE
            and candidate.get("daily_return", 0) >= MIN_DAILY_RETURN
            and candidate.get("relative_volume_20d", 0) >= MIN_RELATIVE_VOLUME
            and candidate.get("passes_template") is True
            and candidate.get("new_screen_pass") is True
        ):
            return {
                "schema_version": 1,
                "strategy_id": "daily_gap_volume_v1",
                "ticker": candidate["ticker"],
                "side": "buy",
                "signal_date": bundle["market_date"],
                "candidate_evidence_id": candidate["evidence_id"],
                "bundle_sha256": bundle["bundle_sha256"],
                "execution": "shadow_only",
            }
    return None
