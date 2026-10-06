"""Additive engine-v2 schema and monotonic order-id allocation."""
from __future__ import annotations

import duckdb

from sim.schema import init_sim_schema, next_order_id


def test_v2_tables_and_portfolio_defaults_exist(con):
    expected = {
        "instruments",
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
        "INSERT INTO portfolios (id,cash) VALUES ('defaults',1000)"
    )
    assert con.execute(
        "SELECT engine,cost_profile,account_type,visibility,status,price_source "
        "FROM portfolios WHERE id='defaults'"
    ).fetchone() == ("league", None, "cash_legacy", "public", "active", "prices")


def test_v2_keeps_legacy_positional_table_shapes(con):
    expected = {
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
