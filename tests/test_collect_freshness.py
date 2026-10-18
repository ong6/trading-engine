"""Account-held and pending names remain in the daily price universe."""
from __future__ import annotations

import duckdb

from engine import account_watch


def _universe(con):
    con.execute(
        """CREATE TABLE universe (
        ticker VARCHAR PRIMARY KEY, yf_ticker VARCHAR, liquid BOOLEAN)"""
    )
    con.executemany(
        "INSERT INTO universe VALUES (?, ?, ?)",
        [
            ("LIQ", "LIQ", True),
            ("HELD", "HELD-YF", False),
            ("PEND", "PEND", False),
            ("WATCH", "WATCH", False),
        ],
    )


def test_incremental_universe_includes_held_pending_and_watched_names():
    con = duckdb.connect()
    try:
        _universe(con)
        con.execute("CREATE TABLE portfolios (id VARCHAR, active BOOLEAN)")
        con.execute("CREATE TABLE sim_positions (portfolio_id VARCHAR, ticker VARCHAR, qty DOUBLE)")
        con.execute("CREATE TABLE sim_orders (ticker VARCHAR, status VARCHAR)")
        account_watch.init_schema(con)
        con.execute("INSERT INTO portfolios VALUES ('acct-a', TRUE), ('old', FALSE)")
        con.execute(
            "INSERT INTO sim_positions VALUES "
            "('acct-a', 'HELD', 2), ('old', 'WATCH', 3)"
        )
        con.execute("INSERT INTO sim_orders VALUES ('PEND', 'pending')")
        con.execute("INSERT INTO account_watch VALUES ('acct-a', 'WATCH')")

        names = account_watch.incremental_universe(con)
        supplemental = account_watch.supplemental_universe(con)
    finally:
        con.close()

    assert names == {
        "HELD-YF": "HELD", "LIQ": "LIQ", "PEND": "PEND", "WATCH": "WATCH"
    }
    assert supplemental == {"HELD-YF": "HELD", "PEND": "PEND", "WATCH": "WATCH"}


def test_incremental_universe_tolerates_missing_account_tables():
    con = duckdb.connect()
    try:
        _universe(con)
        assert account_watch.incremental_universe(con) == {"LIQ": "LIQ"}
    finally:
        con.close()


def test_supplemental_universe_defaults_to_logged_two_thousand_cap(caplog):
    con = duckdb.connect()
    try:
        con.execute(
            "CREATE TABLE universe (ticker VARCHAR PRIMARY KEY, yf_ticker VARCHAR, liquid BOOLEAN)"
        )
        rows = [(f"T{index:04d}", f"T{index:04d}", False) for index in range(2001)]
        con.executemany("INSERT INTO universe VALUES (?, ?, ?)", rows)
        account_watch.init_schema(con)
        con.executemany(
            "INSERT INTO account_watch VALUES ('acct-a', ?)",
            [[ticker] for ticker, _provider, _liquid in rows],
        )

        names = account_watch.supplemental_universe(con)
    finally:
        con.close()

    assert len(names) == account_watch.DEFAULT_SUPPLEMENTAL_LIMIT
    assert "truncating supplemental universe from 2001 to 2000" in caplog.text
