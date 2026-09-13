"""Market and event evidence used by discretionary-risk gates."""

from datetime import datetime, timedelta, timezone

import pytest

from server import risk_market

NOW = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)
TODAY = NOW.date()


def _earn(con, ticker, when, as_of, est=False):
    con.execute("INSERT INTO earnings_calendar VALUES (?, ?, ?, ?)", [ticker, when, as_of, est])


@pytest.fixture
def earn_con(con):
    con.execute(
        "CREATE TABLE earnings_calendar (ticker VARCHAR, earnings_date DATE, "
        "as_of DATE, is_estimate BOOLEAN)"
    )
    return con


def test_earnings_window_fail_inside_pass_outside(earn_con):
    _earn(earn_con, "AAA", TODAY + timedelta(days=7), TODAY, est=True)
    result = risk_market.earnings_window(earn_con, "AAA", acked=False, now=NOW)
    assert result["status"] == "fail" and "estimate" in result["detail"]

    _earn(earn_con, "BBB", TODAY + timedelta(days=8), TODAY)
    assert risk_market.earnings_window(earn_con, "BBB", acked=False, now=NOW)["status"] == "pass"

    _earn(earn_con, "CCC", TODAY - timedelta(days=1), TODAY)
    assert risk_market.earnings_window(earn_con, "CCC", acked=False, now=NOW)["status"] == "pass"
    assert risk_market.earnings_window(earn_con, "ZZZ", acked=True, now=NOW)["status"] == "unknown"


def test_spy_regime_for_date_does_not_resolve_market_date(con, monkeypatch):
    monkeypatch.setattr(
        risk_market.risk_book,
        "latest_prices_date",
        lambda _con: (_ for _ in ()).throw(AssertionError("unexpected date lookup")),
    )

    label, detail = risk_market.spy_regime_for_date(con, None)

    assert label == "unknown"
    assert detail == "SPY has 0 bars (<200) — regime unknown"


def test_earnings_window_uses_latest_snapshot_only(earn_con):
    _earn(earn_con, "AAA", TODAY + timedelta(days=2), TODAY - timedelta(days=30))
    _earn(earn_con, "AAA", TODAY + timedelta(days=40), TODAY)

    assert risk_market.earnings_window(earn_con, "AAA", acked=False, now=NOW)["status"] == "pass"


def test_earnings_window_uses_injected_submission_time(earn_con):
    submitted_at = datetime(2026, 9, 9, 23, 59, tzinfo=timezone.utc)
    _earn(earn_con, "AAA", submitted_at.date() + timedelta(days=7), submitted_at.date())

    result = risk_market.earnings_window(
        earn_con,
        "AAA",
        acked=False,
        now=submitted_at,
    )

    assert result["status"] == "fail"
    assert str(submitted_at.date() + timedelta(days=7)) in result["detail"]


def test_earnings_window_ignores_snapshots_published_after_submission(earn_con):
    submitted_at = datetime(2026, 9, 9, 23, 59, tzinfo=timezone.utc)
    _earn(earn_con, "AAA", submitted_at.date() + timedelta(days=3), submitted_at.date())
    _earn(
        earn_con,
        "AAA",
        submitted_at.date() + timedelta(days=30),
        submitted_at.date() + timedelta(days=1),
    )

    result = risk_market.earnings_window(
        earn_con,
        "AAA",
        acked=False,
        now=submitted_at,
    )

    assert result["status"] == "fail"
    assert str(submitted_at.date() + timedelta(days=3)) in result["detail"]


def test_earnings_window_fails_closed_for_database_errors(monkeypatch):
    class BrokenConnection:
        def execute(self, *_args, **_kwargs):
            raise risk_market.duckdb.CatalogException("unreadable earnings schema")

    result = risk_market.earnings_window(
        BrokenConnection(),
        "AAA",
        acked=False,
        now=datetime(2026, 9, 9, tzinfo=timezone.utc),
    )

    assert result == {
        "name": "earnings_window",
        "status": "unknown",
        "detail": "no earnings data — check manually",
    }


def test_earnings_window_does_not_hide_programming_errors(monkeypatch, con):
    monkeypatch.setattr(
        risk_market,
        "table_exists",
        lambda *_args: (_ for _ in ()).throw(AssertionError("programming defect")),
    )

    with pytest.raises(AssertionError, match="programming defect"):
        risk_market.earnings_window(
            con,
            "AAA",
            acked=False,
            now=datetime(2026, 9, 9, tzinfo=timezone.utc),
        )
