"""P15 session evidence survives removal of an unusable SPY observation."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd

from engine.lib.data_quality import OHLC, session_schedule
from engine.lib.util import table_exists

HARD_INVALID_REASONS = frozenset({
    *(f"{field}_{kind}" for field in OHLC for kind in ("null", "nonfinite", "nonpositive")),
    "high_geometry", "low_geometry", "volume_negative", "volume_unrepresentable",
    "invalid_ticker", "invalid_date", "off_calendar", "invalid_interval",
})


def observed_sessions(con, *, after: date | None = None, through: date | None = None,
                      include_after: bool = False, known_at: datetime | None = None,
                      limit: int | None = None) -> list[date]:
    """Union captured daily SPY dates; prices remain separate from session identity.

    Only a captured basis hold needs an XNYS membership check. No exchange dates
    are generated. Receipt cutoffs apply before selecting or limiting dates.
    """
    filters, args = ["ticker='SPY'", "date IS NOT NULL"], []
    if after is not None:
        filters.append("date>=?" if include_after else "date>?")
        args.append(after)
    if through is not None:
        filters.append("date<=?")
        args.append(through)
    cutoff = None if known_at is None else known_at.astimezone(timezone.utc).replace(tzinfo=None)
    where = " AND ".join(filters)
    dates = set()
    if table_exists(con, "prices"):
        availability = " AND fetched_at IS NOT NULL AND fetched_at<=?" if cutoff else ""
        dates.update(row[0] for row in con.execute(
            f"SELECT DISTINCT date FROM prices WHERE {where}{availability}",
            [*args, *([cutoff] if cutoff else [])],
        ).fetchall())
    if table_exists(con, "price_observation_rejects"):
        availability = " AND recorded_at<=? AND COALESCE(fetched_at,recorded_at)<=?" if cutoff else ""
        for day, reason in con.execute(
            f"SELECT DISTINCT date,reason FROM price_observation_rejects "
            f"WHERE {where} AND interval='1d'{availability}",
            [*args, *([cutoff, cutoff] if cutoff else [])],
        ).fetchall():
            reasons = set(reason.split(","))
            if reasons & HARD_INVALID_REASONS or (
                reasons == {"basis_unverified"}
                and pd.Timestamp(day) in session_schedule(day.year).index
            ):
                dates.add(day)
    result = sorted(dates)
    return result if limit is None else result[:limit]
