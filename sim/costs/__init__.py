"""Registry for dollar-denominated fill and financing cost profiles."""
from __future__ import annotations

from .baseline_v1 import PROFILE as BASELINE_V1
from .ibkr_pro_tiered_v1 import PROFILE as IBKR_PRO_TIERED_V1
from .ibkr_pro_tiered_v1 import borrow_fee as _ibkr_borrow_fee
from .ibkr_pro_tiered_v1 import margin_interest as _ibkr_margin_interest
from .profiles import CostProfile, FeeBreakdown, RateRow

PROFILES = {profile.id: profile for profile in (BASELINE_V1, IBKR_PRO_TIERED_V1)}


def resolve_profile(profile: str | CostProfile | None) -> CostProfile:
    if isinstance(profile, CostProfile):
        return profile
    profile_id = profile or BASELINE_V1.id
    try:
        return PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError(
            f"unknown cost profile {profile_id!r}; known: {', '.join(PROFILES)}"
        ) from exc


def charge(profile: str | CostProfile | None, **fill) -> FeeBreakdown:
    """Charge one fill or option combo under a named immutable profile."""
    return resolve_profile(profile).charge(**fill)


def borrow_fee(short_market_value: float, days: int = 1, *, session_date,
               profile: str | CostProfile | None = "ibkr_pro_tiered_v1") -> float:
    """Return the profile's total borrow debit for a calendar-day span."""
    selected = resolve_profile(profile)
    if selected.id == BASELINE_V1.id:
        return 0.0
    if selected.id == IBKR_PRO_TIERED_V1.id:
        return _ibkr_borrow_fee(short_market_value, days, session_date=session_date)
    raise ValueError(f"profile {selected.id!r} has no borrow schedule")


def margin_interest(debit: float, days: int = 1, *, session_date,
                    profile: str | CostProfile | None = "ibkr_pro_tiered_v1") -> float:
    """Return the profile's total margin-interest debit for a day span."""
    selected = resolve_profile(profile)
    if selected.id == BASELINE_V1.id:
        return 0.0
    if selected.id == IBKR_PRO_TIERED_V1.id:
        return _ibkr_margin_interest(debit, days, session_date=session_date)
    raise ValueError(f"profile {selected.id!r} has no margin schedule")


__all__ = [
    "BASELINE_V1",
    "IBKR_PRO_TIERED_V1",
    "CostProfile",
    "FeeBreakdown",
    "RateRow",
    "borrow_fee",
    "charge",
    "margin_interest",
    "resolve_profile",
]
