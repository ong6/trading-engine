"""Tests for bounded active paper-order projections."""

from datetime import date

import duckdb
import pytest

from server import order_read_models, read_model_utils
from tests.read_model_helpers import portfolio


def test_orders_missing_tables_return_the_complete_empty_contract():
    con = duckdb.connect()
    try:
        assert order_read_models.orders(con, "filled") == {
            "status": "filled",
            "limit": order_read_models.ORDERS_LIMIT,
            "matching_count": 0,
            "truncated": False,
            "orders": [],
        }
    finally:
        con.close()


def test_orders_expose_only_active_portfolios(con):
    portfolio(con, "active")
    portfolio(con, "retired", active=False)
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(1, 'active', 'LIVE', 'buy', 2, DATE '2026-09-01', 'filled', NULL), "
        "(2, 'retired', 'ARCHIVE', 'buy', 3, DATE '2026-09-01', 'filled', NULL)"
    )

    all_orders = order_read_models.orders(con, None)
    filled_orders = order_read_models.orders(con, "filled")

    assert [row["id"] for row in all_orders["orders"]] == [1]
    assert all_orders["matching_count"] == 1
    assert [row["id"] for row in filled_orders["orders"]] == [1]
    assert filled_orders["matching_count"] == 1


def test_orders_project_internal_p15_terminal_status_as_filled(con):
    portfolio(con, "p15_ai_ranked")
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(1,'p15_ai_ranked','AAA','buy',2,DATE '2026-09-01','p15_filled',NULL)"
    )

    assert order_read_models.orders(con, None)["orders"][0]["status"] == "filled"
    assert order_read_models.orders(con, "filled")["matching_count"] == 1


def test_orders_reject_malformed_stored_portfolio_identity(con):
    portfolio_id = "x" * 129
    portfolio(con, portfolio_id)
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(1, ?, 'LIVE', 'buy', 2, DATE '2026-09-01', 'pending', NULL)",
        [portfolio_id],
    )

    with pytest.raises(ValueError, match="portfolio identifier is invalid"):
        order_read_models.orders(con, None)
    assert con.execute("SELECT portfolio_id FROM sim_orders").fetchone()[0] == portfolio_id


def test_orders_reject_malformed_stored_ticker(con):
    ticker = "x" * 33
    portfolio(con, "active")
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(1, 'active', ?, 'buy', 2, DATE '2026-09-01', 'pending', NULL)",
        [ticker],
    )

    with pytest.raises(ValueError, match="ticker is invalid"):
        order_read_models.orders(con, None)
    assert con.execute("SELECT ticker FROM sim_orders").fetchone()[0] == ticker


def test_orders_reject_unsafe_order_identifier_without_rewriting(con):
    unsafe = read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1
    portfolio(con, "active")
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(?, 'active', 'LIVE', 'buy', 2, DATE '2026-09-01', 'pending', NULL)",
        [unsafe],
    )

    with pytest.raises(ValueError, match="public identifier is invalid"):
        order_read_models.orders(con, None)
    assert con.execute("SELECT id FROM sim_orders").fetchone() == (unsafe,)


def test_orders_reject_unsafe_linked_ticket_identifier_without_rewriting(con):
    unsafe = read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1
    portfolio(con, "active")
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(1, 'active', 'LIVE', 'buy', 2, DATE '2026-09-01', 'pending', NULL)"
    )
    con.execute(
        "INSERT INTO disc_tickets "
        "(id, ticker, side, qty, status, order_id, created_at) "
        "VALUES (?, 'LIVE', 'buy', 2, 'submitted', 1, now())",
        [unsafe],
    )

    with pytest.raises(ValueError, match="public identifier is invalid"):
        order_read_models.orders(con, None)
    assert con.execute("SELECT id FROM disc_tickets").fetchone() == (unsafe,)


def test_orders_project_only_explicit_public_columns(con):
    portfolio(con, "active")
    con.execute("ALTER TABLE sim_orders ADD COLUMN internal_secret VARCHAR")
    con.execute(
        "INSERT INTO sim_orders "
        "(id, portfolio_id, ticker, side, qty, signal_date, status, reject_reason, "
        "internal_secret) VALUES "
        "(1, 'active', 'LIVE', 'buy', 2, DATE '2026-09-01', 'pending', NULL, "
        "'not public')"
    )

    order = order_read_models.orders(con, None)["orders"][0]

    assert order == {
        "id": 1,
        "portfolio_id": "active",
        "ticker": "LIVE",
        "side": "buy",
        "qty": 2.0,
        "signal_date": date(2026, 9, 1),
        "status": "pending",
        "reject_reason": None,
        "ticket_id": None,
        "playbook": None,
        "stop": None,
        "target": None,
        "detail_truncated": False,
    }


def test_orders_payload_rejects_unsafe_matching_count():
    rows = [{"_matching_count": read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1}]

    with pytest.raises(ValueError, match="public count is invalid"):
        order_read_models._orders_payload(None, rows)


def test_orders_bound_legacy_text_without_rewriting_stored_values(con):
    portfolio(con, "active")
    reason = "r" * (order_read_models.REJECT_REASON_MAX_CHARS + 7)
    playbook = "p" * (order_read_models.PLAYBOOK_MAX_CHARS + 5)
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(1, 'active', 'LIVE', 'buy', 2, DATE '2026-09-01', 'rejected', ?)",
        [reason],
    )
    con.execute(
        "INSERT INTO disc_tickets "
        "(id, ticker, side, qty, playbook, gates, status, order_id, created_at) "
        "VALUES (1, 'LIVE', 'buy', 2, ?, '[]', 'rejected', 1, now())",
        [playbook],
    )

    order = order_read_models.orders(con, None)["orders"][0]

    assert order["reject_reason"] == reason[: order_read_models.REJECT_REASON_MAX_CHARS]
    assert order["playbook"] == playbook[: order_read_models.PLAYBOOK_MAX_CHARS]
    assert order["detail_truncated"] is True
    assert con.execute("SELECT reject_reason FROM sim_orders WHERE id = 1").fetchone()[0] == reason
    assert con.execute("SELECT playbook FROM disc_tickets WHERE id = 1").fetchone()[0] == playbook


def test_orders_bound_filtered_and_unfiltered_active_history(con):
    portfolio(con, "active")
    portfolio(con, "retired", active=False)
    active_rows = [
        (
            order_id,
            "active",
            f"T{order_id}",
            "buy",
            1,
            date(2026, 9, 1),
            "filled" if order_id <= 505 else "rejected",
            None if order_id <= 505 else "test rejection",
        )
        for order_id in range(1, 516)
    ]
    retired_rows = [
        (order_id, "retired", "OLD", "buy", 1, date(2026, 9, 1), "filled", None)
        for order_id in range(10_001, 10_004)
    ]
    con.executemany("INSERT INTO sim_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)", active_rows)
    con.executemany("INSERT INTO sim_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)", retired_rows)

    all_orders = order_read_models.orders(con, None)
    filled_orders = order_read_models.orders(con, "filled")
    rejected_orders = order_read_models.orders(con, "rejected")

    assert all_orders["limit"] == order_read_models.ORDERS_LIMIT == 500
    assert all_orders["matching_count"] == 515
    assert all_orders["truncated"] is True
    assert [row["id"] for row in all_orders["orders"]] == list(range(515, 15, -1))
    assert all("_matching_count" not in row for row in all_orders["orders"])
    assert filled_orders["matching_count"] == 505
    assert filled_orders["truncated"] is True
    assert [row["id"] for row in filled_orders["orders"]] == list(range(505, 5, -1))
    assert rejected_orders["matching_count"] == 10
    assert rejected_orders["truncated"] is False
    assert [row["id"] for row in rejected_orders["orders"]] == list(range(515, 505, -1))


def _valid_order_row(**overrides):
    row = {
        "id": 1,
        "portfolio_id": "active",
        "ticker": "AAA",
        "side": "buy",
        "qty": 2.0,
        "signal_date": date(2026, 9, 1),
        "status": "pending",
        "reject_reason": None,
        "_matching_count": 1,
        "ticket_id": None,
        "playbook": None,
        "stop": None,
        "target": None,
    }
    return {**row, **overrides}


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"side": "hold"}, "public order side is invalid"),
        ({"qty": 0}, "public order quantity is invalid"),
        ({"qty": float("nan")}, "public order quantity is invalid"),
        ({"signal_date": None}, "public order signal date is invalid"),
        ({"status": "unknown"}, "public order status is invalid"),
        ({"reject_reason": "unexpected"}, "public order rejection reason is invalid"),
        (
            {"status": "rejected", "reject_reason": "   "},
            "public order rejection reason is invalid",
        ),
        ({"playbook": 1}, "public order playbook is invalid"),
        ({"stop": 0}, "public order stop is invalid"),
        ({"target": float("inf")}, "public order target is invalid"),
    ],
)
def test_orders_reject_rows_outside_the_browser_contract(overrides, message):
    with pytest.raises(ValueError, match=message):
        order_read_models._orders_payload(None, [_valid_order_row(**overrides)])


def test_orders_reject_duplicate_identifiers_and_filter_mismatch():
    with pytest.raises(ValueError, match="public order identifier is duplicated"):
        order_read_models._orders_payload(
            None,
            [_valid_order_row(_matching_count=2), _valid_order_row(_matching_count=2)],
        )
    with pytest.raises(ValueError, match="public order status is invalid"):
        order_read_models._orders_payload("filled", [_valid_order_row()])


def test_orders_projection_rejects_extra_envelope_and_row_fields():
    payload = order_read_models._orders_payload(None, [_valid_order_row()])

    with pytest.raises(ValueError, match="projection shape"):
        order_read_models._validate_orders_projection({**payload, "internal": "not public"}, None)
    malformed = {
        **payload,
        "orders": [{**payload["orders"][0], "internal": "not public"}],
    }
    with pytest.raises(ValueError, match="order shape"):
        order_read_models._validate_orders_projection(malformed, None)


def test_orders_projection_rejects_unordered_rows():
    payload = order_read_models._orders_payload(
        None,
        [
            _valid_order_row(id=2, _matching_count=2),
            _valid_order_row(id=1, _matching_count=2),
        ],
    )
    payload["orders"].reverse()

    with pytest.raises(ValueError, match="not ordered"):
        order_read_models._validate_orders_projection(payload, None)


def test_orders_projection_rejects_incoherent_display_truncation():
    payload = order_read_models._orders_payload(None, [_valid_order_row()])
    payload["orders"][0]["detail_truncated"] = True

    with pytest.raises(ValueError, match="truncation state"):
        order_read_models._validate_orders_projection(payload, None)


def test_orders_reject_invalid_stored_quantity_without_rewriting(con):
    portfolio(con, "active")
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(1, 'active', 'LIVE', 'buy', ?, DATE '2026-09-01', 'pending', NULL)",
        [float("nan")],
    )

    with pytest.raises(ValueError, match="public order quantity is invalid"):
        order_read_models.orders(con, None)
    assert con.execute("SELECT isnan(qty) FROM sim_orders").fetchone() == (True,)
