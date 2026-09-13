"""Named, versioned execution-cost assumptions.

Market friction and broker/exchange fees are deliberately separate.  The
baseline profile reproduces the historical simulator exactly; profiles with
unverified broker charges must never be labelled as broker-specific.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ExecutionProfile:
    id: str
    description: str
    spread_rule: str = "mdv_tiers_v1"
    spread_multiplier: float = 1.0
    fixed_adverse_bps: float = 5.0
    impact_coefficient_bps: float = 0.0
    impact_exponent: float = 0.5
    impact_reference_participation: float = 0.01
    commission_per_share: float = 0.0
    commission_minimum: float = 0.0
    commission_max_fraction: float | None = None
    sell_fee_bps: float = 0.0
    max_participation: float = 0.01
    fractional_shares: bool = True

    def as_dict(self) -> dict:
        return asdict(self)


BASELINE = ExecutionProfile(
    id="baseline_v1",
    description=("Compatibility profile: liquidity-tier half-spread plus 5 bp "
                 "adverse movement per side; no separately verified broker fees."),
)

COST_2X = ExecutionProfile(
    id="cost_2x_v1",
    description=("Sensitivity profile: exactly twice baseline market friction; "
                 "no separately verified broker fees."),
    spread_multiplier=2.0,
    fixed_adverse_bps=10.0,
)

PARTICIPATION_STRESS = ExecutionProfile(
    id="participation_stress_v1",
    description=("Baseline friction plus square-root participation impact, reaching "
                 "10 bp at 1% of trailing median daily dollar volume."),
    impact_coefficient_bps=10.0,
)

PROFILES = {p.id: p for p in (BASELINE, COST_2X, PARTICIPATION_STRESS)}
DEFAULT_PROFILE_ID = BASELINE.id


def resolve_profile(profile: str | ExecutionProfile | None) -> ExecutionProfile:
    if isinstance(profile, ExecutionProfile):
        return profile
    profile_id = profile or DEFAULT_PROFILE_ID
    try:
        return PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError(
            f"unknown execution profile {profile_id!r}; known: {', '.join(PROFILES)}"
        ) from exc


def half_spread_bps(median_dollar_volume: float | None) -> float:
    """Conservative half-spread estimate from trailing median dollar volume."""
    if median_dollar_volume is None or median_dollar_volume < 5_000_000:
        return 25.0
    if median_dollar_volume < 20_000_000:
        return 15.0
    if median_dollar_volume < 50_000_000:
        return 10.0
    return 5.0


def cost_components(profile: str | ExecutionProfile | None, *, side: str,
                    qty: float, open_px: float,
                    median_dollar_volume: float | None) -> dict[str, float]:
    """Return deterministic per-side costs in bps and dollars.

    Participation uses the intended raw-open notional.  Fixed-dollar charges
    are converted to bps so the fill price remains the single cash-accounting
    price used throughout the simulator.
    """
    p = resolve_profile(profile)
    notional = abs(float(qty) * float(open_px))
    participation = (
        notional / median_dollar_volume
        if median_dollar_volume is not None and median_dollar_volume > 0 else 0.0
    )
    spread = half_spread_bps(median_dollar_volume) * p.spread_multiplier
    impact = 0.0
    if p.impact_coefficient_bps and participation > 0:
        impact = p.impact_coefficient_bps * math.pow(
            participation / p.impact_reference_participation, p.impact_exponent)

    commission = max(p.commission_per_share * abs(float(qty)), p.commission_minimum)
    if p.commission_max_fraction is not None:
        commission = min(commission, notional * p.commission_max_fraction)
    fee_bps = commission / notional * 1e4 if notional > 0 else 0.0
    if side == "sell":
        fee_bps += p.sell_fee_bps
    elif side != "buy":
        raise ValueError(f"bad side {side!r}")

    market_bps = spread + p.fixed_adverse_bps + impact
    return {
        "half_spread_bps": spread,
        "fixed_adverse_bps": p.fixed_adverse_bps,
        "impact_bps": impact,
        "market_bps": market_bps,
        "fee_bps": fee_bps,
        "total_bps": market_bps + fee_bps,
        "participation": participation,
        "commission_dollars": commission,
    }
