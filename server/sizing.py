"""Position sizing for discretionary tickets — fixed-fractional risk.

The risk unit is 1R = entry − stop (per share). Position size is the whole-share
qty whose dollar risk equals `risk_pct` of current equity. Longs only in v1
(entry must be above stop); shorts (side='sell' that isn't closing an existing
position) are rejected upstream in risk.py, never sized here.
"""
from __future__ import annotations

import math


def size_position(
    equity: float, entry: float, stop: float, risk_pct: float = 0.01
) -> dict:
    """{qty, risk_dollars, r_per_share} for a long at `entry` with `stop`.

    qty = floor( (equity * risk_pct) / (entry - stop) ). Requires entry > stop
    (long); otherwise raises ValueError — the caller's stop_present gate should
    have caught it, this is the belt-and-braces guard.
    """
    r_per_share = entry - stop
    if r_per_share <= 0:
        raise ValueError(f"long sizing requires entry ({entry}) > stop ({stop})")
    risk_dollars = equity * risk_pct
    qty = math.floor(risk_dollars / r_per_share)
    return {
        "qty": qty,
        "risk_dollars": risk_dollars,
        "r_per_share": r_per_share,
    }
