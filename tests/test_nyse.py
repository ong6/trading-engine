"""sim/nyse.py — the NYSE rule calendar. Validated once against all 6,706 store
sessions 2000-01-03..2026-09-01 (0 disagreements); these pin the rules."""
from datetime import date

import pytest

from sim import nyse


@pytest.mark.parametrize("d", [
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
    date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3),   # Jul 4 is a Saturday
    date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25),
    date(2024, 3, 29),   # Good Friday
    date(2021, 12, 24),  # Christmas on Saturday → Friday
    date(2022, 6, 20),   # Juneteenth on Sunday → Monday
    date(2025, 1, 9),    # ad hoc: Carter funeral
    date(2001, 9, 11),
])
def test_holidays_closed(d):
    assert not nyse.is_session(d)


@pytest.mark.parametrize("d", [
    date(2021, 12, 31),  # New Year's 2022 on Saturday → NOT observed Friday
    date(2026, 9, 1), date(2026, 10, 30), date(2020, 6, 19),  # pre-2022 Juneteenth
    date(2023, 11, 24),  # day after Thanksgiving (half day, still a session)
])
def test_sessions_open(d):
    assert nyse.is_session(d)


def test_weekends_closed():
    assert not nyse.is_session(date(2026, 9, 5)) and not nyse.is_session(date(2026, 9, 6))


def test_easter():
    assert nyse._easter(2024) == date(2024, 3, 31)
    assert nyse._easter(2026) == date(2026, 4, 5)
    assert nyse._easter(2000) == date(2000, 4, 23)


def test_last_session_of_month_weekend_end():
    # October 2026 ends on a Saturday: Fri 10-30 IS the last session.
    assert nyse.is_last_session_of_month(date(2026, 10, 30))
    assert not nyse.is_last_session_of_month(date(2026, 10, 29))
    assert nyse.is_last_session_of_month(date(2026, 9, 30))


def test_last_session_of_week_holiday_friday():
    # Christmas 2026 is a Friday → Thursday 12-24 closes the week.
    assert nyse.is_last_session_of_week(date(2026, 12, 24))
    assert not nyse.is_last_session_of_week(date(2026, 12, 23))
    assert nyse.is_last_session_of_week(date(2026, 9, 4))
    assert not nyse.is_last_session_of_week(date(2026, 9, 3))
