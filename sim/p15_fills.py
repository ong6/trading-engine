"""P15 limit-on-open execution layered over the frozen v4 fill model."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date

import duckdb

from . import execution, fills


@dataclass
class LimitFillResult(fills.FillResult):
    """A normal fill result plus the price rejected by the opening limit."""

    counterfactual_fill_px: float | None = None


def attempt_limit_on_open(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    side: str,
    qty: float,
    signal_date: date,
    fill_date: date,
    limit_px: float,
    profile: str | execution.ExecutionProfile | None = None,
) -> LimitFillResult:
    """Attempt one buy at the modelled open without ever crossing ``limit_px``."""
    if side != "buy":
        raise ValueError("limit-on-open v1 supports buy orders only")
    if (
        isinstance(limit_px, bool)
        or not isinstance(limit_px, (int, float))
        or not math.isfinite(float(limit_px))
        or limit_px <= 0
    ):
        raise ValueError("limit price must be finite and positive")
    candidate = fills.attempt_fill(
        con, ticker, side, qty, signal_date, fill_date, profile
    )
    values = asdict(candidate)
    if candidate.status != "filled" or candidate.fill_px <= float(limit_px):
        return LimitFillResult(**values)
    return LimitFillResult(
        **{**values, "status": "rejected", "reject_reason": "limit_not_reached",
           "fill_px": None},
        counterfactual_fill_px=candidate.fill_px,
    )
