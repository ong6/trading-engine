"""NYSE regular-session calendar, computed from the published holiday rules.

Why this exists: `calendar.is_week_signal` / `is_month_signal` decide cadence
from the `prices` table, and the live league always steps the LATEST bar — so
the "is there a later session in this period?" question has no answer in the
data. The old fallback (`weekday() == 4`, `(d+1).month != d.month`) silently
skipped any month whose last session was not the last calendar day and any
week whose last session was not a Friday — roughly 29% of month-ends and every
holiday week. Whether a calendar date is an exchange session is public
knowledge, not a peek at future prices, so consulting the rule set is honest.

Rules (NYSE, current): New Year's Day, Martin Luther King Jr. Day (3rd Mon Jan),
Washington's Birthday (3rd Mon Feb), Good Friday (Easter − 2), Memorial Day
(last Mon May), Juneteenth (Jun 19, from 2022), Independence Day (Jul 4), Labor
Day (1st Mon Sep), Thanksgiving (4th Thu Nov), Christmas (Dec 25).
Fixed-date holidays falling on Saturday are observed Friday, on Sunday Monday —
EXCEPT New Year's on a Saturday, which the NYSE does not observe on Dec 31.

Unscheduled closures (e.g. 2001-09-11..14, 2012-10-29/30 Sandy, 2018-12-05,
2025-01-09 national days of mourning) are listed explicitly; the list is only
needed for history, since the live decision is always about the future.
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

# Unscheduled full-day closures since 2000 (public record).
AD_HOC_CLOSURES: frozenset[date] = frozenset({
    date(2001, 9, 11), date(2001, 9, 12), date(2001, 9, 13), date(2001, 9, 14),
    date(2004, 6, 11),   # Reagan funeral
    date(2007, 1, 2),    # Ford funeral
    date(2012, 10, 29), date(2012, 10, 30),  # Hurricane Sandy
    date(2018, 12, 5),   # G.H.W. Bush funeral
    date(2025, 1, 9),    # Carter funeral
})


def _easter(year: int) -> date:
    """Gregorian Easter Sunday (Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th (1-based) `weekday` (Mon=0) of the month; n=-1 for the last."""
    if n > 0:
        first = date(year, month, 1)
        off = (weekday - first.weekday()) % 7
        return first + timedelta(days=off + 7 * (n - 1))
    nxt = date(year + (month == 12), (month % 12) + 1, 1)
    last = nxt - timedelta(days=1)
    off = (last.weekday() - weekday) % 7
    return last - timedelta(days=off)


def _observed(d: date, new_years: bool = False) -> date | None:
    """Weekend observance. Saturday → Friday (except New Year's: not observed),
    Sunday → Monday."""
    if d.weekday() == 5:
        return None if new_years else d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=None)
def holidays(year: int) -> frozenset[date]:
    """Scheduled full-day NYSE holidays for `year` (observed dates)."""
    out: set[date] = set()
    for d in (
        _observed(date(year, 1, 1), new_years=True),
        _nth_weekday(year, 1, 0, 3),          # MLK
        _nth_weekday(year, 2, 0, 3),          # Presidents' Day
        _easter(year) - timedelta(days=2),    # Good Friday
        _nth_weekday(year, 5, 0, -1),         # Memorial Day
        _observed(date(year, 6, 19)) if year >= 2022 else None,
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),          # Labor Day
        _nth_weekday(year, 11, 3, 4),         # Thanksgiving
        _observed(date(year, 12, 25)),
    ):
        if d is not None:
            out.add(d)
    # Historical: MLK Day has been an NYSE holiday since 1998; all rules above
    # already hold for every year this engine stores (2000+).
    return frozenset(out)


def is_session(d: date) -> bool:
    """True if `d` is a regular NYSE trading session per the rule set."""
    if d.weekday() >= 5:
        return False
    if d in AD_HOC_CLOSURES:
        return False
    return d not in holidays(d.year)


def next_session(d: date) -> date:
    """First scheduled session strictly after `d`."""
    d = d + timedelta(days=1)
    while not is_session(d):
        d += timedelta(days=1)
    return d


def is_last_session_of_week(d: date) -> bool:
    """True if no scheduled session remains in d's ISO week after d."""
    return next_session(d).isocalendar()[:2] != d.isocalendar()[:2]


def is_last_session_of_month(d: date) -> bool:
    """True if no scheduled session remains in d's calendar month after d."""
    n = next_session(d)
    return (n.year, n.month) != (d.year, d.month)
