"""Side-aware accounting and deterministic phase-ordered replay."""
from __future__ import annotations

from datetime import datetime

import pytest

from sim import ledger, portfolio, settle
from sim.costs import FeeBreakdown
from sim.schema import INITIAL_CASH, set_portfolio_account
from tests.conftest import SESSIONS


def test_fill_model_version_is_v5():
    assert portfolio.FILL_MODEL_VERSION == "v5"


def _record_fill(con, book, order_id, ticker, side, qty, price, session, fees=None):
    fill = {
        "order_id": order_id,
        "portfolio_id": book,
        "ticker": ticker,
        "side": side,
        "qty": qty,
        "fill_px": price,
        "fill_date": session,
    }
    applied = ledger.apply_fill(con, fill, fees)
    con.execute(
        "INSERT INTO sim_fills VALUES (?,?,?,?,?,?,?,?,0,0)",
        [order_id, book, ticker, side, applied, session, price, price],
    )
    return applied


def _margin_account(con, book, *, engine="league"):
    set_portfolio_account(
        con, book, engine=engine, account_type="margin", allow_short=True,
    )


def test_short_cover_round_trip_tracks_lot_cash_and_fees(con, book):
    _margin_account(con, book)
    one_dollar = FeeBreakdown("ibkr_pro_tiered_v1", commission=1, total_usd=1)
    assert ledger.apply_fill(con, {
        "order_id": 1, "portfolio_id": book, "ticker": "XYZ", "side": "short",
        "qty": 10, "fill_px": 50, "fill_date": SESSIONS[1],
    }, one_dollar) == 10
    assert portfolio.get_positions(con, book)["XYZ"] == {"qty": -10, "avg_cost": 50}
    assert ledger.apply_fill(con, {
        "order_id": 2, "portfolio_id": book, "ticker": "XYZ", "side": "cover",
        "qty": 10, "fill_px": 40, "fill_date": SESSIONS[2],
    }, one_dollar) == 10
    assert portfolio.get_positions(con, book) == {}
    assert portfolio.get_cash(con, book) == INITIAL_CASH + 500 - 400 - 2
    assert con.execute("SELECT COUNT(*) FROM sim_position_lots").fetchone() == (0,)
    assert con.execute(
        "SELECT order_id,total_usd FROM sim_fill_fees ORDER BY order_id"
    ).fetchall() == [(1, 1.0), (2, 1.0)]


def test_long_and_short_sides_cannot_cross_zero_implicitly(con, book):
    _margin_account(con, book)
    ledger.apply_fill(con, {
        "portfolio_id": book, "ticker": "LONG", "side": "buy", "qty": 2, "fill_px": 10,
    })
    with pytest.raises(ValueError, match="use sell"):
        ledger.apply_fill(con, {
            "portfolio_id": book, "ticker": "LONG", "side": "short",
            "qty": 1, "fill_px": 10,
        })
    ledger.apply_fill(con, {
        "portfolio_id": book, "ticker": "SHORT", "side": "short",
        "qty": 2, "fill_px": 10,
    })
    with pytest.raises(ValueError, match="use cover"):
        ledger.apply_fill(con, {
            "portfolio_id": book, "ticker": "SHORT", "side": "buy",
            "qty": 1, "fill_px": 10,
        })


def test_short_dividend_is_a_signed_debit(con, book):
    _margin_account(con, book)
    session = SESSIONS[3]
    con.execute(
        "CREATE TABLE corporate_actions "
        "(ticker VARCHAR,ex_date DATE,kind VARCHAR,value DOUBLE)"
    )
    ledger.apply_fill(con, {
        "portfolio_id": book, "ticker": "XYZ", "side": "short", "qty": 10, "fill_px": 50,
    })
    con.execute(
        "INSERT INTO corporate_actions VALUES ('XYZ',?,'dividend',0.5)", [session]
    )
    before = portfolio.get_cash(con, book)
    assert portfolio.credit_dividends(con, session) == {"credited": 1, "amount": -5.0}
    assert portfolio.get_cash(con, book) == before - 5
    assert con.execute(
        "SELECT qty,dps,amount FROM sim_dividends"
    ).fetchone() == (-10.0, 0.5, -5.0)


def test_cash_events_are_append_only_and_replayable(con, book):
    event = {
        "portfolio_id": book,
        "event_date": SESSIONS[2],
        "seq": 1,
        "kind": "borrow_fee",
        "amount": -0.35,
        "instrument_id": "XYZ",
        "created_at": datetime(2026, 10, 12, 22),
    }
    before = portfolio.get_cash(con, book)
    assert ledger.apply_cash_event(con, event) == 1
    assert portfolio.get_cash(con, book) == pytest.approx(before - 0.35)
    with pytest.raises(Exception, match="Constraint"):
        ledger.apply_cash_event(con, event)
    con.execute("UPDATE portfolios SET cash=0 WHERE id=?", [book])
    ledger.rebuild_state(con)
    assert portfolio.get_cash(con, book) == pytest.approx(INITIAL_CASH - 0.35)


def test_rebuild_exactly_reproduces_legacy_multiday_book(con, book):
    d1, d2, d3, d4 = SESSIONS[1:5]
    _record_fill(con, book, 1, "AAA", "buy", 10, 100, d1)
    _record_fill(con, book, 2, "BBB", "buy", 5, 20, d1)
    con.execute(
        "INSERT INTO sim_dividends VALUES (?,?,?,10,0.5,5)", [book, "AAA", d2]
    )
    con.execute("UPDATE portfolios SET cash=cash+5 WHERE id=?", [book])
    settle.ensure_table(con)
    con.execute(
        "INSERT INTO sim_settlements VALUES "
        "(?, 'BBB', 'cash', 5, 30, NULL, NULL, ?, 'fixture', NULL, ?)",
        [book, d3, datetime(2026, 10, 12, 22)],
    )
    settle.apply_settlement_event(con, book, "BBB", "cash", 5, 30, None, None)
    _record_fill(con, book, 3, "AAA", "sell", 4, 110, d4)
    ledger.apply_cash_event(con, {
        "portfolio_id": book, "event_date": d4, "kind": "adjustment", "amount": -2,
    })
    expected_cash = portfolio.get_cash(con, book)
    expected_positions = con.execute(
        "SELECT * FROM sim_positions ORDER BY portfolio_id,ticker"
    ).fetchall()
    con.execute("UPDATE portfolios SET cash=1 WHERE id=?", [book])
    con.execute("DELETE FROM sim_positions")

    portfolio.rebuild_state(con)

    assert portfolio.get_cash(con, book) == expected_cash
    assert con.execute(
        "SELECT * FROM sim_positions ORDER BY portfolio_id,ticker"
    ).fetchall() == expected_positions
    assert con.execute("SELECT COUNT(*) FROM sim_fill_fees").fetchone() == (0,)


def test_rebuild_replays_fill_fee_once(con, book):
    fees = FeeBreakdown(
        "ibkr_pro_tiered_v1", commission=1.05, exchange_fee=0.45,
        clearing_fee=0.06, pass_through=0.000777, cat_fee=0.0009,
        total_usd=1.56,
    )
    _record_fill(con, book, 1, "XYZ", "buy", 300, 5, SESSIONS[1], fees)
    expected = portfolio.get_cash(con, book)
    con.execute("UPDATE portfolios SET cash=0 WHERE id=?", [book])
    con.execute("DELETE FROM sim_positions")
    ledger.rebuild_state(con)
    assert portfolio.get_cash(con, book) == expected == INITIAL_CASH - 1_500 - 1.56
    assert portfolio.get_positions(con, book)["XYZ"]["qty"] == 300


def test_cash_legacy_portfolio_cannot_short(con, book):
    with pytest.raises(ValueError, match="cash_legacy"):
        ledger.apply_fill(con, {
            "portfolio_id": book, "ticker": "XYZ", "side": "short",
            "qty": 1, "fill_px": 10,
        })


def test_account_fill_requires_order_identity_and_session(con, book):
    _margin_account(con, book, engine="account")
    with pytest.raises(ValueError, match="order_id and fill date"):
        ledger.apply_fill(con, {
            "portfolio_id": book, "ticker": "XYZ", "side": "buy",
            "qty": 1, "fill_px": 10,
        })


@pytest.mark.parametrize(
    "opening,closing,opening_px,closing_px,expected_cash",
    [
        ("buy", "sell", 10, 12, INITIAL_CASH + 20),
        ("short", "cover", 12, 10, INITIAL_CASH + 20),
    ],
)
def test_account_same_day_round_trip_replays_by_fill_timestamp(
    con, book, opening, closing, opening_px, closing_px, expected_cash,
):
    _margin_account(con, book, engine="account")
    session = SESSIONS[2]
    _record_fill(con, book, 20, "XYZ", opening, 10, opening_px, session)
    _record_fill(con, book, 10, "XYZ", closing, 10, closing_px, session)
    con.executemany(
        "INSERT INTO sim_fill_details (order_id,fill_ts,fill_kind,multiplier) "
        "VALUES (?,?,?,1)",
        [
            (20, datetime(2026, 10, 12, 13, 30), "open_auction"),
            (10, datetime(2026, 10, 12, 20, 0), "close_auction"),
        ],
    )
    assert portfolio.get_cash(con, book) == expected_cash
    con.execute("UPDATE portfolios SET cash=0 WHERE id=?", [book])
    con.execute("DELETE FROM sim_positions")
    ledger.rebuild_state(con)
    assert portfolio.get_cash(con, book) == expected_cash
    assert portfolio.get_positions(con, book) == {}
    assert con.execute(
        "SELECT open_order_id,close_order_id FROM sim_day_trades"
    ).fetchall() == [(20, 10)]


def test_legacy_same_day_fills_keep_sells_before_buys(con, book):
    _record_fill(con, book, 1, "XYZ", "buy", 10, 10, SESSIONS[1])
    _record_fill(con, book, 3, "XYZ", "sell", 10, 12, SESSIONS[2])
    _record_fill(con, book, 2, "XYZ", "buy", 5, 11, SESSIONS[2])
    expected = (portfolio.get_cash(con, book), portfolio.get_positions(con, book))
    ledger.rebuild_state(con)
    assert (portfolio.get_cash(con, book), portfolio.get_positions(con, book)) == expected


def test_fifo_matching_exposes_lots_and_records_same_day_trade(con, book):
    _margin_account(con, book, engine="account")
    _record_fill(con, book, 1, "XYZ", "buy", 10, 10, SESSIONS[1])
    _record_fill(con, book, 2, "XYZ", "buy", 10, 11, SESSIONS[2])
    _record_fill(con, book, 3, "XYZ", "sell", 15, 12, SESSIONS[2])
    assert con.execute(
        "SELECT session_date,open_order_id,close_order_id FROM sim_day_trades"
    ).fetchall() == [(SESSIONS[2], 2, 3)]
    assert con.execute(
        "SELECT open_order_id,qty FROM sim_position_lots"
    ).fetchall() == [(2, 5.0)]

    ledger.add_lot(con, book, "ABC", SESSIONS[1], 10, 2, 20)
    matched = ledger.match_lots(con, book, "ABC", 1)
    assert matched == (ledger.MatchedLot(10, SESSIONS[1], 1, 20),)


def test_stock_settlement_transfers_lots_with_position(con, book):
    _margin_account(con, book, engine="account")
    _record_fill(con, book, 1, "OLD", "buy", 10, 20, SESSIONS[1])
    settle.apply_settlement_event(con, book, "OLD", "stock", 10, 0, "NEW", 2)
    assert portfolio.get_positions(con, book) == {
        "NEW": {"qty": 20.0, "avg_cost": 10.0},
    }
    positions = dict(con.execute(
        "SELECT ticker,qty FROM sim_positions WHERE portfolio_id=? AND abs(qty)>=1e-9",
        [book],
    ).fetchall())
    lots = dict(con.execute(
        "SELECT instrument_id,SUM(qty) FROM sim_position_lots "
        "WHERE portfolio_id=? GROUP BY instrument_id HAVING abs(SUM(qty))>=1e-9",
        [book],
    ).fetchall())
    assert lots == positions
