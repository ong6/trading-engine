"""Future-only fill-v5 guard; no profile is installed in the live dispatcher."""
from __future__ import annotations

import math

TIERS = {"lt_5m", "5m_20m", "20m_50m", "gte_50m"}


def validate_auction_artifact(artifact: dict) -> dict:
    """Require later direct paper-auction evidence before a v5 cohort can use it."""
    if (not isinstance(artifact, dict) or artifact.get("status") != "validated"
            or artifact.get("independent_targets_verified") is not True
            or artifact.get("execution_basis_verified") is not True
            or artifact.get("execution_basis") != "opening_auction_direct_paper_evidence"
            or set(artifact.get("auction_slippage_bp", {})) != TIERS):
        raise ValueError("fill v5 artifact is not activation-eligible")
    for value in artifact["auction_slippage_bp"].values():
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(float(value)) or value < 0):
            raise ValueError("fill v5 auction coefficient is invalid")
    return artifact


def fill_price(open_price: float, side: str, liquidity_tier: str, artifact: dict) -> float:
    """Apply only direct-evidence auction slippage from a validated future artifact."""
    validate_auction_artifact(artifact)
    if (not isinstance(open_price, (int, float)) or isinstance(open_price, bool)
            or not math.isfinite(float(open_price)) or open_price <= 0
            or side not in {"buy", "sell"} or liquidity_tier not in TIERS):
        raise ValueError("fill v5 request is invalid")
    sign = 1 if side == "buy" else -1
    return float(open_price) * (
        1 + sign * float(artifact["auction_slippage_bp"][liquidity_tier]) / 10_000)
