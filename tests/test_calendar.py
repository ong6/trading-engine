"""Session calendar derived from the prices table."""
from datetime import date

from sim import calendar as cal
from tests.conftest import SESSIONS, insert_bars


def _load(con):
    insert_bars(con, "SPY", SESSIONS)
    insert_bars(con, "AAA", SESSIONS)   # two tickers per session on purpose
    return con


def test_next_trading_day_skips_weekend(con):
    _load(con)
    assert cal.next_trading_day(con, date(2024, 6, 7)) == date(2024, 6, 10)   # Fri -> Mon


def test_next_trading_day_skips_holiday(con):
    _load(con)
    assert cal.next_trading_day(con, date(2024, 7, 3)) == date(2024, 7, 5)    # Jul 4
    assert cal.next_trading_day(con, date(2024, 6, 18)) == date(2024, 6, 20)  # Juneteenth


def test_next_trading_day_from_non_session_date(con):
    _load(con)
    assert cal.next_trading_day(con, date(2024, 6, 8)) == date(2024, 6, 10)   # Saturday


def test_next_trading_day_none_at_latest_bar(con):
    _load(con)
    assert cal.next_trading_day(con, SESSIONS[-1]) is None


def test_trading_days_between_counts_sessions_not_rows(con):
    _load(con)
    assert cal.trading_days_between(con, date(2024, 7, 3), date(2024, 7, 8)) == 2  # 5th, 8th
    assert cal.trading_days_between(con, date(2024, 6, 7), date(2024, 6, 7)) == 0
    assert cal.trading_days_between(con, SESSIONS[0], SESSIONS[-1]) == len(SESSIONS) - 1


def test_is_week_signal_friday_true_midweek_false(con):
    _load(con)
    assert cal.is_week_signal(con, date(2024, 6, 7)) is True
    assert cal.is_week_signal(con, date(2024, 6, 5)) is False


def test_is_week_signal_thursday_before_friday_holiday(con):
    # Make Friday 2024-06-28 a holiday: Thursday is then the week's last session.
    _load(con)
    con.execute("DELETE FROM prices WHERE date = DATE '2024-06-28'")
    assert cal.is_week_signal(con, date(2024, 6, 27)) is True


def test_is_week_signal_latest_bar_falls_back_to_friday(con):
    insert_bars(con, "SPY", [date(2024, 6, 6)])            # Thursday, latest
    assert cal.is_week_signal(con, date(2024, 6, 6)) is False
    insert_bars(con, "SPY", [date(2024, 6, 7)])            # Friday, latest
    assert cal.is_week_signal(con, date(2024, 6, 7)) is True


def test_is_month_signal(con):
    _load(con)
    assert cal.is_month_signal(con, date(2024, 6, 28)) is True     # next is Jul 1
    assert cal.is_month_signal(con, date(2024, 6, 27)) is False


def test_is_month_signal_latest_bar_uses_calendar_roll(con):
    insert_bars(con, "SPY", [date(2024, 7, 30)])
    assert cal.is_month_signal(con, date(2024, 7, 30)) is False
    insert_bars(con, "SPY", [date(2024, 7, 31)])
    assert cal.is_month_signal(con, date(2024, 7, 31)) is True
