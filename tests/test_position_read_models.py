"""Tests for active paper-position projections."""

from datetime import date

import duckdb
import pytest

from server import market_read_models, position_read_models, read_model_utils
from tests.conftest import insert_bars
from tests.read_model_helpers import liquid_universe, portfolio


def test_positions_ignore_real_quotes_after_the_operational_date(con):
    complete = date(2026, 9, 4)
    partial = date(2026, 9, 8)
    liquid_universe(con, ("AAA", "SPY"))
    insert_bars(con, "AAA", [complete], open_=99.0, close=100.0)
    insert_bars(con, "SPY", [complete], open_=199.0, close=200.0)
    insert_bars(con, "AAA", [partial], open_=499.0, close=500.0)
    portfolio(con, "book")
    con.execute("INSERT INTO sim_positions VALUES ('book', 'AAA', 2, 80)")

    assert market_read_models.latest_prices_date(con) == complete
    result = position_read_models.positions(con, "book", discretionary_id="discretionary")
    position = result["positions"][0]
    assert position["close"] == pytest.approx(100.0)
    assert position["market_value"] == pytest.approx(200.0)


def test_positions_fail_closed_without_an_operational_date(con):
    day = date(2026, 9, 8)
    liquid_universe(con, ("AAA", "MISSING"))
    insert_bars(con, "AAA", [day], open_=99.0, close=100.0)
    portfolio(con, "book")
    con.execute("INSERT INTO sim_positions VALUES ('book', 'AAA', 2, 80)")

    assert market_read_models.latest_prices_date(con) is None
    result = position_read_models.positions(con, "book", discretionary_id="discretionary")
    position = result["positions"][0]
    assert position["close"] is None
    assert "market_value" not in position


def test_positions_expose_only_active_portfolios(con):
    portfolio(con, "active")
    portfolio(con, "retired", active=False)
    con.execute(
        "INSERT INTO sim_positions VALUES ('active', 'LIVE', 2, 10), ('retired', 'ARCHIVE', 3, 20)"
    )

    aggregate = position_read_models.positions(con, None, discretionary_id="discretionary")

    assert [(row["portfolio_id"], row["ticker"]) for row in aggregate["positions"]] == [
        ("active", "LIVE")
    ]
    assert position_read_models.positions(con, "retired", discretionary_id="discretionary") is None
    assert position_read_models.positions(con, "unknown", discretionary_id="discretionary") is None


def test_positions_reject_malformed_stored_portfolio_identity(con):
    portfolio_id = "book\nother"
    portfolio(con, portfolio_id)
    con.execute("INSERT INTO sim_positions VALUES (?, 'LIVE', 2, 10)", [portfolio_id])

    with pytest.raises(ValueError, match="portfolio identifier is invalid"):
        position_read_models.positions(con, None, discretionary_id="discretionary")
    assert con.execute("SELECT portfolio_id FROM sim_positions").fetchone()[0] == portfolio_id


def test_positions_reject_malformed_stored_ticker(con):
    ticker = "BAD\nTICKER"
    portfolio(con, "book")
    con.execute("INSERT INTO sim_positions VALUES ('book', ?, 2, 10)", [ticker])

    with pytest.raises(ValueError, match="ticker is invalid"):
        position_read_models.positions(con, None, discretionary_id="discretionary")
    assert con.execute("SELECT ticker FROM sim_positions").fetchone()[0] == ticker


def test_positions_reject_invalid_stored_average_cost_without_rewriting(con):
    portfolio(con, "book")
    con.execute("INSERT INTO sim_positions VALUES ('book', 'AAA', 2, 0)")

    with pytest.raises(ValueError, match="public position average cost is invalid"):
        position_read_models.positions(con, "book", discretionary_id="discretionary")
    assert con.execute("SELECT avg_cost FROM sim_positions").fetchone()[0] == 0


@pytest.mark.parametrize("quantity", [-1, float("nan"), None])
def test_positions_do_not_omit_invalid_stored_quantity(con, quantity):
    portfolio(con, "book")
    con.execute("INSERT INTO sim_positions VALUES ('book', 'AAA', ?, 10)", [quantity])

    with pytest.raises(ValueError, match="public position quantity is invalid"):
        position_read_models.positions(con, "book", discretionary_id="discretionary")
    stored = con.execute("SELECT qty FROM sim_positions").fetchone()[0]
    assert (stored != stored) if quantity != quantity else stored == quantity


def test_positions_omit_closed_zero_quantity_rows(con):
    portfolio(con, "book")
    con.execute("INSERT INTO sim_positions VALUES ('book', 'CLOSED', 0, 10)")

    assert position_read_models.positions(con, "book", discretionary_id="discretionary") == {
        "portfolio": "book",
        "limit": 500,
        "matching_count": 0,
        "truncated": False,
        "positions": [],
    }


def test_positions_reject_malformed_direct_filter():
    con = duckdb.connect()
    try:
        with pytest.raises(ValueError, match="portfolio identifier is invalid"):
            position_read_models.positions(con, " book", discretionary_id="discretionary")
    finally:
        con.close()


def test_active_portfolio_without_positions_is_an_empty_current_book(con):
    portfolio(con, "empty")

    assert position_read_models.positions(con, "empty", discretionary_id="discretionary") == {
        "portfolio": "empty",
        "limit": 500,
        "matching_count": 0,
        "truncated": False,
        "positions": [],
    }


def test_positions_fail_closed_when_portfolio_catalog_is_missing():
    con = duckdb.connect()
    try:
        assert (
            position_read_models.positions(con, "missing", discretionary_id="discretionary") is None
        )
        assert position_read_models.positions(con, None, discretionary_id="discretionary") == {
            "portfolio": None,
            "limit": 500,
            "matching_count": 0,
            "truncated": False,
            "positions": [],
        }
    finally:
        con.close()


@pytest.mark.parametrize(
    ("quantity", "average_cost", "close", "message"),
    [
        (0, 10, 100.0, "public position quantity is invalid"),
        (float("nan"), 10, 100.0, "public position quantity is invalid"),
        (2, 0, 100.0, "public position average cost is invalid"),
        (2, float("inf"), 100.0, "public position average cost is invalid"),
        (2, 10, 0, "public position close is invalid"),
        (2, 10, float("nan"), "public position close is invalid"),
    ],
)
def test_positions_reject_values_outside_the_browser_contract(
    quantity, average_cost, close, message
):
    with pytest.raises(ValueError, match=message):
        position_read_models._position_item(("book", "AAA", quantity, average_cost, 1), close)


def test_positions_reject_nonfinite_derived_valuation():
    with pytest.raises(ValueError, match="public position market value is invalid"):
        position_read_models._position_item(("book", "AAA", 1e308, 1.0, 1), 1e308)


def test_discretionary_risk_rejects_invalid_stop_and_nonfinite_output():
    item = position_read_models._position_item(("discretionary", "AAA", 1, 1.0, 1), 1e308)

    with pytest.raises(ValueError, match="public position stop is invalid"):
        position_read_models._add_discretionary_risk(item.copy(), 0)
    with pytest.raises(ValueError, match="public position unrealized R is invalid"):
        position_read_models._add_discretionary_risk(item.copy(), 0.9999999999999999)


def test_positions_are_bounded_with_complete_matching_count(con, monkeypatch):
    portfolio(con, "book")
    con.execute(
        "INSERT INTO sim_positions VALUES "
        "('book', 'CCC', 1, 30), ('book', 'AAA', 1, 10), ('book', 'BBB', 1, 20)"
    )
    monkeypatch.setattr(position_read_models, "POSITIONS_LIMIT", 2)

    result = position_read_models.positions(con, "book", discretionary_id="discretionary")

    assert result == {
        "portfolio": "book",
        "limit": 2,
        "matching_count": 3,
        "truncated": True,
        "positions": [
            {
                "portfolio_id": "book",
                "ticker": "AAA",
                "qty": 1.0,
                "avg_cost": 10.0,
                "close": None,
            },
            {
                "portfolio_id": "book",
                "ticker": "BBB",
                "qty": 1.0,
                "avg_cost": 20.0,
                "close": None,
            },
        ],
    }


def test_positions_reject_unsafe_matching_count(con, monkeypatch):
    portfolio(con, "book")
    monkeypatch.setattr(
        position_read_models,
        "_position_rows",
        lambda *_args: [
            (
                "book",
                "AAA",
                1.0,
                10.0,
                read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1,
            )
        ],
    )

    with pytest.raises(ValueError, match="public count is invalid"):
        position_read_models.positions(con, "book", discretionary_id="discretionary")


def test_positions_projection_rejects_extra_envelope_and_row_fields(con):
    portfolio(con, "book")
    con.execute("INSERT INTO sim_positions VALUES ('book', 'AAA', 2, 10)")
    payload = position_read_models.positions(con, "book", discretionary_id="discretionary")

    with pytest.raises(ValueError, match="projection shape"):
        position_read_models._validate_positions_projection(
            {**payload, "internal": "not public"},
            discretionary_id="discretionary",
        )
    malformed = {
        **payload,
        "positions": [{**payload["positions"][0], "internal": "not public"}],
    }
    with pytest.raises(ValueError, match="position shape"):
        position_read_models._validate_positions_projection(
            malformed,
            discretionary_id="discretionary",
        )


def test_positions_projection_rejects_fields_for_the_wrong_row_state(con):
    portfolio(con, "book")
    con.execute("INSERT INTO sim_positions VALUES ('book', 'AAA', 2, 10)")
    payload = position_read_models.positions(con, "book", discretionary_id="discretionary")
    malformed = {
        **payload,
        "positions": [{**payload["positions"][0], "stop": 9.0}],
    }

    with pytest.raises(ValueError, match="position shape"):
        position_read_models._validate_positions_projection(
            malformed,
            discretionary_id="discretionary",
        )


def test_positions_follow_unicode_code_point_order(con):
    for portfolio_id in ("\uF900", "\U00010000"):
        portfolio(con, portfolio_id)
        con.execute(
            "INSERT INTO sim_positions VALUES (?, 'AAA', 2, 10)",
            [portfolio_id],
        )

    payload = position_read_models.positions(con, None, discretionary_id="discretionary")

    assert [row["portfolio_id"] for row in payload["positions"]] == [
        "\uF900",
        "\U00010000",
    ]
    payload["positions"].reverse()
    with pytest.raises(ValueError, match="not ordered"):
        position_read_models._validate_positions_projection(
            payload,
            discretionary_id="discretionary",
        )
