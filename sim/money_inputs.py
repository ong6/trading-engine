"""Numeric boundaries for money mutations and retained orders."""
from __future__ import annotations

import math
from numbers import Real


def finite_number(value, name: str, *, positive=False, nonnegative=False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    if positive and number <= 0:
        raise ValueError(f"{name} must be positive")
    if nonnegative and number < 0:
        raise ValueError(f"{name} must be non-negative")
    return number


def order_refusal(side, qty, *, sides=("buy", "sell", "short", "cover"), **prices):
    if side not in sides:
        return "invalid_order: side"
    try:
        finite_number(qty, "quantity", positive=True)
        for name, value in prices.items():
            if value is not None:
                finite_number(value, name, positive=True)
    except ValueError as exc:
        return f"invalid_order: {exc}"
    return None
