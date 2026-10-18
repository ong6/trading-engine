"""Additive engine-v2 schema and monotonic order-id allocation."""
from __future__ import annotations

import duckdb

from sim.schema import (
    PORTFOLIO_ACCOUNT_JOIN,
    init_sim_schema,
    next_order_id,
    portfolio_account,
    set_portfolio_account,
)


def test_v2_tables_and_portfolio_defaults_exist(con):
    expected = {
        "instruments",
        "portfolio_accounts",
        "sim_order_details",
        "sim_fill_details",
        "sim_fill_fees",
        "sim_cash_events",
        "sim_position_lots",
        "sim_day_trades",
        "sim_book_breaks",
    }
    found = {
        row[0] for row in con.execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchall()
    }
    assert expected <= found
    con.execute(
        "INSERT INTO portfolios (id,active,cash) VALUES ('defaults',FALSE,1000)"
    )
    assert portfolio_account(con, "defaults") == {
        "engine": "league",
        "cost_profile": "baseline_v1",
        "account_type": "cash_legacy",
        "visibility": "public",
        "status": "inactive",
        "price_source": "prices",
        "day_trade_rule": "pdt_25k_legacy",
        "allow_short": False,
        "updated_at": None,
    }
    updated = set_portfolio_account(
        con, "defaults", engine="account", account_type="margin",
        visibility="private", status="halted", allow_short=True,
    )
    assert updated["engine"] == "account"
    assert updated["account_type"] == "margin"
    assert updated["visibility"] == "private"
    assert updated["status"] == "halted"
    assert updated["allow_short"] is True
    assert PORTFOLIO_ACCOUNT_JOIN == (
        "LEFT JOIN portfolio_accounts pa USING (portfolio_id)"
    )


def test_v2_keeps_legacy_positional_table_shapes(con):
    expected = {
        "portfolios": 9,
        "sim_orders": 8,
        "sim_fills": 10,
        "sim_positions": 4,
        "sim_equity": 5,
    }
    for table, count in expected.items():
        actual = con.execute(
            "SELECT COUNT(*) FROM information_schema.columns WHERE table_name=?",
            [table],
        ).fetchone()[0]
        assert actual == count


def test_bootstrap_starts_above_legacy_maximum_and_never_reuses_deleted_id():
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE sim_orders (id BIGINT PRIMARY KEY, portfolio_id VARCHAR, "
        "ticker VARCHAR, side VARCHAR, qty DOUBLE, signal_date DATE, "
        "status VARCHAR, reject_reason VARCHAR)"
    )
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(3,'p','AAA','buy',1,DATE '2026-01-02','filled',NULL),"
        "(9,'p','BBB','buy',1,DATE '2026-01-02','filled',NULL)"
    )
    init_sim_schema(con)
    first = next_order_id(con)
    assert first == 10
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(?,'p','CCC','buy',1,DATE '2026-01-02','pending',NULL)",
        [first],
    )
    con.execute("DELETE FROM sim_orders WHERE id=?", [first])
    assert next_order_id(con) == 11
    con.close()


def test_repeated_schema_initialisation_does_not_reset_sequence(con):
    first = next_order_id(con)
    init_sim_schema(con)
    assert next_order_id(con) == first + 1


def test_sequence_advances_past_an_interleaved_legacy_max_writer(con):
    first = next_order_id(con)
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(?,'p','AAA','buy',1,DATE '2026-01-02','pending',NULL)",
        [first],
    )
    legacy = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM sim_orders").fetchone()[0]
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(?,'p','BBB','buy',1,DATE '2026-01-02','pending',NULL)",
        [legacy],
    )
    assert next_order_id(con) == legacy + 1


def test_legacy_nine_value_portfolio_insert_remains_valid(con):
    con.execute(
        "INSERT INTO portfolios VALUES "
        "('legacy','Legacy','noop','{}',DATE '2026-01-02',TRUE,100,100,'baseline_v1')"
    )
    assert portfolio_account(con, "legacy")["status"] == "active"
