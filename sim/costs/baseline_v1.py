"""Zero-dollar compatibility costs for every pre-migration simulator fill."""
from __future__ import annotations

from .profiles import CostProfile, FeeBreakdown


def _charge(**_kwargs) -> FeeBreakdown:
    return FeeBreakdown(profile_id="baseline_v1")


PROFILE = CostProfile(
    id="baseline_v1",
    description="Legacy compatibility profile: no separately charged dollar fees.",
    rates=(),
    verified={"kind": "compatibility", "dollar_fees": 0},
    calculator=_charge,
)
