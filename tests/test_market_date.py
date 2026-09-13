"""Breadth-qualified market dates cannot be advanced by partial or phantom data."""

from datetime import date

import pytest

from engine import market_date
from engine.lib import db
from tests.conftest import insert_bars


def _liquid_universe(con, tickers):
    con.execute(
        "CREATE TABLE universe (ticker VARCHAR PRIMARY KEY, active BOOLEAN, liquid BOOLEAN)"
    )
    con.executemany(
        "INSERT INTO universe (ticker, active, liquid) VALUES (?, TRUE, TRUE)",
        [(ticker,) for ticker in tickers],
    )


def test_operational_date_ignores_partial_and_phantom_later_dates(con):
    tickers = ("A", "B", "C", "D")
    _liquid_universe(con, tickers)
    complete = date(2026, 9, 4)
    partial = date(2026, 9, 8)
    phantom = date(2026, 9, 9)
    for ticker in tickers:
        insert_bars(con, ticker, [complete], open_=100, high=101, low=99, close=100)
    for ticker in tickers[:2]:
        insert_bars(con, ticker, [partial], open_=101, high=102, low=100, close=101)
    insert_bars(
        con, "A", [phantom], open_=101, high=101, low=101, close=101, volume=0
    )

    assert db.latest_real_prices_date(con) == partial
    assert db.latest_operational_market_date(con, minimum_names=1) == complete


def test_operational_date_accepts_configured_breadth_and_validates_limits(con):
    tickers = tuple("ABCDEFGHIJ")
    _liquid_universe(con, tickers)
    day = date(2026, 9, 8)
    for ticker in tickers[:9]:
        insert_bars(con, ticker, [day], open_=100, high=101, low=99, close=100)

    assert db.latest_operational_market_date(con, minimum_names=1) == day
    assert db.latest_operational_market_date(
        con, minimum_names=1, minimum_coverage=0.91
    ) is None


def test_market_date_cli_requires_initialized_liquid_universe(con, monkeypatch):
    insert_bars(
        con,
        "ORPHAN",
        [date(2026, 9, 4)],
        open_=100,
        high=101,
        low=99,
        close=100,
    )
    assert db.latest_real_prices_date(con) == date(2026, 9, 4)
    assert db.latest_operational_market_date(con) is None

    class ConnectionProxy:
        def execute(self, *args, **kwargs):
            return con.execute(*args, **kwargs)

        def close(self):
            pass

    monkeypatch.setattr(market_date.db, "connect", lambda *_args, **_kwargs: ConnectionProxy())
    monkeypatch.setattr("sys.argv", ["market_date.py", "--db", "ignored"])

    try:
        market_date.main()
    except SystemExit as exc:
        assert str(exc) == "[market-date] no active liquid universe"
    else:
        raise AssertionError("empty universe should fail closed")


def test_market_date_cli_rejects_a_newer_incomplete_real_tail(con, monkeypatch):
    complete = date(2026, 9, 4)
    partial = date(2026, 9, 8)
    _liquid_universe(con, ("A", "B"))
    for ticker in ("A", "B"):
        insert_bars(con, ticker, [complete], open_=100, high=101, low=99, close=100)
    insert_bars(con, "A", [partial], open_=101, high=102, low=100, close=101)

    class ConnectionProxy:
        def execute(self, *args, **kwargs):
            return con.execute(*args, **kwargs)

        def close(self):
            pass

    monkeypatch.setattr(market_date.db, "connect", lambda *_args, **_kwargs: ConnectionProxy())
    monkeypatch.setattr("sys.argv", ["market_date.py", "--db", "ignored"])

    with pytest.raises(SystemExit) as exc_info:
        market_date.main()
    assert str(exc_info.value) == (
        "[market-date] incomplete real-bar tail: latest real date 2026-09-08 "
        "is newer than qualified date 2026-09-04"
    )


def test_market_date_cli_rejects_newer_rows_outside_active_liquid_universe(
    con, monkeypatch
):
    complete = date(2026, 9, 4)
    later = date(2026, 9, 8)
    _liquid_universe(con, ("A", "B"))
    con.execute("INSERT INTO universe VALUES ('INACTIVE', FALSE, TRUE)")
    con.execute("INSERT INTO universe VALUES ('ILLIQUID', TRUE, FALSE)")
    for ticker in ("A", "B"):
        insert_bars(con, ticker, [complete], open_=100, high=101, low=99, close=100)
    for ticker in ("INACTIVE", "ILLIQUID", "ORPHAN"):
        insert_bars(con, ticker, [later], open_=101, high=102, low=100, close=101)

    class ConnectionProxy:
        def execute(self, *args, **kwargs):
            return con.execute(*args, **kwargs)

        def close(self):
            pass

    monkeypatch.setattr(market_date.db, "connect", lambda *_args, **_kwargs: ConnectionProxy())
    monkeypatch.setattr("sys.argv", ["market_date.py", "--db", "ignored"])

    with pytest.raises(SystemExit, match="incomplete real-bar tail"):
        market_date.main()


def _active_book(con, portfolio_id: str, equity_date: date | None) -> None:
    con.execute(
        "INSERT INTO portfolios (id, name, strategy, config, created, active, cash) "
        "VALUES (?, ?, 'none', '{}', DATE '2026-09-01', TRUE, 39000)",
        [portfolio_id, portfolio_id],
    )
    if equity_date is not None:
        con.execute(
            "INSERT INTO sim_equity (portfolio_id, date, equity, cash, n_positions) "
            "VALUES (?, ?, 39000, 39000, 0)",
            [portfolio_id, equity_date],
        )


def test_league_continuity_accepts_same_or_next_nyse_session(con):
    _active_book(con, "book", date(2026, 9, 4))

    market_date.validate_league_continuity(con, date(2026, 9, 4))
    market_date.validate_league_continuity(con, date(2026, 9, 8))  # Labor Day weekend


def test_league_continuity_rejects_skipped_session(con):
    _active_book(con, "book", date(2026, 9, 4))

    with pytest.raises(ValueError, match="expected 2026-09-08.*2026-09-09"):
        market_date.validate_league_continuity(con, date(2026, 9, 9))


def test_league_continuity_rejects_divergent_or_missing_active_books(con):
    _active_book(con, "a", date(2026, 9, 4))
    _active_book(con, "b", date(2026, 9, 3))
    with pytest.raises(ValueError, match="checkpoints disagree"):
        market_date.validate_league_continuity(con, date(2026, 9, 8))

    con.execute("DELETE FROM portfolios")
    con.execute("DELETE FROM sim_equity")
    _active_book(con, "missing", None)
    with pytest.raises(ValueError, match="no equity checkpoint: missing"):
        market_date.validate_league_continuity(con, date(2026, 9, 8))
