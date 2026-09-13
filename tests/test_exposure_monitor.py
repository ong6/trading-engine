"""Tests for stale market exposure monitoring."""

from datetime import date, timedelta

import pytest

from server import (
    exposure_monitor,
    read_model_utils,
)
from tests.conftest import insert_bars


def test_stale_exposure_surfaces_held_and_pending_names(con):
    con.execute(
        "INSERT INTO portfolios (id, name, strategy, config, created, active, cash) "
        "VALUES ('book', 'book', 'none', '{}', DATE '2026-09-01', TRUE, 39000)"
    )
    insert_bars(con, "STALE", [date(2026, 9, 3)], high=101, low=99)
    insert_bars(con, "FRESH", [date(2026, 9, 4)], high=101, low=99)
    con.execute("INSERT INTO sim_positions VALUES ('book', 'STALE', 2, 10)")
    con.execute("INSERT INTO sim_positions VALUES ('book', 'FRESH', 1, 10)")
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(1, 'book', 'STALE', 'sell', 2, DATE '2026-09-04', 'pending', NULL)"
    )

    status = exposure_monitor.status(con, date(2026, 9, 4))

    assert status["ticker_count"] == 1
    assert status["position_count"] == 1
    assert status["pending_order_count"] == 1
    assert status["positions"][0]["ticker"] == "STALE"
    assert status["pending_orders"][0]["ticker"] == "STALE"
    assert status["positions_limit"] == exposure_monitor.STALE_DETAIL_LIMIT
    assert status["positions_truncated"] is False
    assert status["pending_orders_limit"] == exposure_monitor.STALE_DETAIL_LIMIT
    assert status["pending_orders_truncated"] is False


def test_stale_exposure_ignores_zero_volume_flat_phantom_bar(con):
    con.execute(
        "INSERT INTO portfolios (id, name, strategy, config, created, active, cash) "
        "VALUES ('book', 'book', 'none', '{}', DATE '2026-09-01', TRUE, 39000)"
    )
    insert_bars(con, "DEAD", [date(2026, 9, 3)], close=10, high=101, low=9)
    insert_bars(con, "DEAD", [date(2026, 9, 4)], close=10, volume=0)
    con.execute("INSERT INTO sim_positions VALUES ('book', 'DEAD', 2, 10)")

    status = exposure_monitor.status(con, date(2026, 9, 4))

    assert status["position_count"] == 1
    assert status["positions"][0]["last_traded"] == date(2026, 9, 3)


def test_stale_exposure_ignores_real_quotes_after_the_operational_date(con):
    con.execute(
        "INSERT INTO portfolios (id, name, strategy, config, created, active, cash) "
        "VALUES ('book', 'book', 'none', '{}', DATE '2026-09-01', TRUE, 39000)"
    )
    insert_bars(con, "LATE", [date(2026, 9, 3)], high=101, low=99)
    insert_bars(con, "LATE", [date(2026, 9, 8)], high=201, low=199)
    con.execute("INSERT INTO sim_positions VALUES ('book', 'LATE', 2, 10)")

    status = exposure_monitor.status(con, date(2026, 9, 4))

    assert status["position_count"] == 1
    assert status["positions"][0]["last_traded"] == date(2026, 9, 3)


def test_stale_exposure_ignores_inactive_holdings_and_pending_orders(con):
    con.execute(
        "INSERT INTO portfolios (id, name, strategy, config, created, active, cash) "
        "VALUES ('retired', 'retired', 'none', '{}', DATE '2026-09-01', FALSE, 39000)"
    )
    insert_bars(con, "STALE", [date(2026, 9, 3)], high=101, low=99)
    con.execute("INSERT INTO sim_positions VALUES ('retired', 'STALE', 2, 10)")
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(1, 'retired', 'STALE', 'sell', 2, DATE '2026-09-04', 'pending', NULL)"
    )

    status = exposure_monitor.status(con, date(2026, 9, 4))

    assert status["position_count"] == 0
    assert status["pending_order_count"] == 0


def test_stale_exposure_rejects_malformed_active_portfolio_identity(con):
    portfolio_id = " book"
    con.execute(
        "INSERT INTO portfolios (id, name, strategy, config, created, active, cash) "
        "VALUES (?, 'book', 'none', '{}', DATE '2026-09-01', TRUE, 39000)",
        [portfolio_id],
    )
    con.execute("INSERT INTO sim_positions VALUES (?, 'STALE', 2, 10)", [portfolio_id])

    with pytest.raises(ValueError, match="portfolio identifier is invalid"):
        exposure_monitor.status(con, date(2026, 9, 4))
    assert con.execute("SELECT portfolio_id FROM sim_positions").fetchone()[0] == portfolio_id


def test_stale_exposure_skips_history_when_every_exposed_name_is_current(con):
    con.execute(
        "INSERT INTO portfolios (id, name, strategy, config, created, active, cash) "
        "VALUES ('book', 'book', 'none', '{}', DATE '2026-09-01', TRUE, 39000)"
    )
    insert_bars(con, "HELD", [date(2026, 9, 4)], high=101, low=99)
    con.execute("INSERT INTO sim_positions VALUES ('book', 'HELD', 2, 10)")

    class RecordingConnection:
        def __init__(self, actual):
            self.actual = actual
            self.statements = []

        def execute(self, statement, parameters=None):
            self.statements.append(statement)
            if parameters is None:
                return self.actual.execute(statement)
            return self.actual.execute(statement, parameters)

    recording = RecordingConnection(con)
    exposure_monitor.status(recording, date(2026, 9, 4))

    statements = "\n".join(recording.statements)
    assert "ticker = ANY(?)" in statements
    assert "MAX(date)" not in statements


def test_stale_exposure_bounds_details_without_weakening_totals(con, monkeypatch):
    monkeypatch.setattr(exposure_monitor, "STALE_DETAIL_LIMIT", 2)
    con.execute(
        "INSERT INTO portfolios (id, name, strategy, config, created, active, cash) "
        "VALUES ('book', 'book', 'none', '{}', DATE '2026-09-01', TRUE, 39000)"
    )
    for index in range(3):
        ticker = f"P{index}"
        con.execute("INSERT INTO sim_positions VALUES ('book', ?, 1, 10)", [ticker])
    for index in range(3):
        ticker = f"O{index}"
        con.execute(
            "INSERT INTO sim_orders VALUES (?, 'book', ?, 'buy', 1, ?, 'pending', NULL)",
            [index + 1, ticker, date(2026, 9, 4) - timedelta(days=index)],
        )

    status = exposure_monitor.status(con, date(2026, 9, 4))

    assert status["ticker_count"] == 6
    assert status["position_count"] == 3
    assert status["pending_order_count"] == 3
    assert len(status["positions"]) == 2
    assert len(status["pending_orders"]) == 2
    assert status["positions_truncated"] is True
    assert status["pending_orders_truncated"] is True


def test_empty_stale_exposure_has_complete_bound_metadata(con):
    status = exposure_monitor.status(con, None)

    assert status == {
        "as_of": None,
        "ticker_count": 0,
        "position_count": 0,
        "pending_order_count": 0,
        "positions": [],
        "positions_limit": exposure_monitor.STALE_DETAIL_LIMIT,
        "positions_truncated": False,
        "pending_orders": [],
        "pending_orders_limit": exposure_monitor.STALE_DETAIL_LIMIT,
        "pending_orders_truncated": False,
    }


def test_stale_exposure_rejects_malformed_stored_ticker(con):
    ticker = " BAD"
    con.execute(
        "INSERT INTO portfolios (id, name, strategy, config, created, active, cash) "
        "VALUES ('book', 'book', 'none', '{}', DATE '2026-09-01', TRUE, 39000)"
    )
    con.execute("INSERT INTO sim_positions VALUES ('book', ?, 1, 10)", [ticker])

    with pytest.raises(ValueError, match="ticker is invalid"):
        exposure_monitor.status(con, date(2026, 9, 4))
    assert con.execute("SELECT ticker FROM sim_positions").fetchone()[0] == ticker


def test_stale_exposure_rejects_unsafe_pending_order_identifier_without_rewriting(con):
    unsafe = read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1
    con.execute(
        "INSERT INTO portfolios (id, name, strategy, config, created, active, cash) "
        "VALUES ('book', 'book', 'none', '{}', DATE '2026-09-01', TRUE, 39000)"
    )
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(?, 'book', 'STALE', 'buy', 1, DATE '2026-09-04', 'pending', NULL)",
        [unsafe],
    )

    with pytest.raises(ValueError, match="public identifier is invalid"):
        exposure_monitor.status(con, date(2026, 9, 4))
    assert con.execute("SELECT id FROM sim_orders").fetchone() == (unsafe,)


@pytest.mark.parametrize("quantity", [None, -1.0, float("nan"), float("inf")])
def test_stale_exposure_rejects_invalid_position_quantity_without_rewriting(con, quantity):
    con.execute(
        "INSERT INTO portfolios (id, name, strategy, config, created, active, cash) "
        "VALUES ('book', 'book', 'none', '{}', DATE '2026-09-01', TRUE, 39000)"
    )
    con.execute("INSERT INTO sim_positions VALUES ('book', 'STALE', ?, 10)", [quantity])

    with pytest.raises(ValueError, match="quantity is invalid"):
        exposure_monitor.status(con, date(2026, 9, 4))
    stored = con.execute("SELECT qty FROM sim_positions").fetchone()[0]
    if quantity != quantity:
        assert stored != stored
    else:
        assert stored == quantity


@pytest.mark.parametrize("quantity", [None, float("nan"), float("inf")])
def test_stale_exposure_rejects_invalid_pending_quantity_without_rewriting(con, quantity):
    con.execute(
        "INSERT INTO portfolios (id, name, strategy, config, created, active, cash) "
        "VALUES ('book', 'book', 'none', '{}', DATE '2026-09-01', TRUE, 39000)"
    )
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(1, 'book', 'STALE', 'buy', ?, DATE '2026-09-04', 'pending', NULL)",
        [quantity],
    )

    with pytest.raises(ValueError, match="quantity is invalid"):
        exposure_monitor.status(con, date(2026, 9, 4))
    stored = con.execute("SELECT qty FROM sim_orders WHERE id = 1").fetchone()[0]
    if quantity != quantity:
        assert stored != stored
    else:
        assert stored == quantity


@pytest.mark.parametrize(
    ("side", "signal_date", "message"),
    [
        ("hold", date(2026, 9, 4), "side is invalid"),
        (None, date(2026, 9, 4), "side is invalid"),
        ("buy", None, "signal date"),
        ("buy", date(2026, 9, 5), "after the operational date"),
    ],
)
def test_stale_exposure_rejects_invalid_pending_identity_without_rewriting(
    con, side, signal_date, message
):
    con.execute(
        "INSERT INTO portfolios (id, name, strategy, config, created, active, cash) "
        "VALUES ('book', 'book', 'none', '{}', DATE '2026-09-01', TRUE, 39000)"
    )
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(1, 'book', 'STALE', ?, 1, ?, 'pending', NULL)",
        [side, signal_date],
    )

    with pytest.raises(ValueError, match=message):
        exposure_monitor.status(con, date(2026, 9, 4))
    assert con.execute("SELECT side, signal_date FROM sim_orders WHERE id = 1").fetchone() == (
        side,
        signal_date,
    )
