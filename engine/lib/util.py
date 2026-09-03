"""Small helpers that used to be copy-pasted per module (lifted 2026-09-03).

Each function here replaced several byte-identical (or behaviourally identical)
private copies; the copies that differed in behaviour were deliberately left in
place — see docs/architecture-review-2026-09-02.md §A2 "Small helpers".
"""
from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> str:
    """ISO-8601 UTC timestamp, second precision, 'Z' suffix (the prep-file convention)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def table_exists(con, name: str) -> bool:
    """True if `name` is a table in the connection's information_schema."""
    return con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = ?", [name]
    ).fetchone() is not None


def median(xs: list[float]) -> float | None:
    """Median of a non-empty list (mean of the middle pair when even); None if empty.

    Does NOT drop None entries — callers that need that filter first.
    """
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _missing(v) -> bool:
    return v is None or (isinstance(v, float) and v != v)


def pct(v, dp: int = 2, *, none: str = "·", minus: str = "-") -> str:
    """Report cell for a fraction: `+1.23%`; `none` for None/NaN.

    Default sign handling is the f-string's (`+`/`-`). Pass `minus="−"` for the
    typographic-minus convention the backtest / walk-forward reports use.
    """
    if _missing(v):
        return none
    if minus == "-":
        return f"{v * 100:+.{dp}f}%"
    return f"{'+' if v >= 0 else minus}{abs(v) * 100:.{dp}f}%"


def num(v, dp: int = 2, *, none: str = "·", signed: bool = False, minus: str = "-") -> str:
    """Report cell for a plain number: `1.23` (or `+1.23` when signed); `none` for None/NaN."""
    if _missing(v):
        return none
    if not signed:
        return f"{v:.{dp}f}"
    if minus == "-":
        return f"{v:+.{dp}f}"
    return f"{'+' if v >= 0 else minus}{abs(v):.{dp}f}"
