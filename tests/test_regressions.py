"""Regression tests for the 2026-09-02 simulator audit (BUILDLOG 2026-09-02).
Each test is the minimal shape of a bug that was confirmed against the store."""
from datetime import date, datetime, timezone

import pytest

from server import risk
from server.main import _ticket_signal_date
from sim import calendar, fills, league, portfolio
from sim.schema import INITIAL_CASH
from tests.conftest import insert_bars

D1, D2, D3, D4 = date(2024, 6, 3), date(2024, 6, 4), date(2024, 6, 5), date(2024, 6, 6)


def _book(con, pf_id="b"):
    con.execute("INSERT INTO portfolios (id, name, strategy, created, active, cash) "
                "VALUES (?, ?, 'x', ?, TRUE, ?)", [pf_id, pf_id, D1, INITIAL_CASH])
    return pf_id


def _fill(con, pf, tk, side, qty, px, d, oid):
    con.execute("INSERT INTO sim_orders (id, portfolio_id, ticker, side, qty, "
                "signal_date, status) VALUES (?, ?, ?, ?, ?, ?, 'filled')",
                [oid, pf, tk, side, qty, d, ])
    con.execute("INSERT INTO sim_fills (order_id, portfolio_id, ticker, side, qty, "
                "fill_date, open_px, fill_px, slippage_bps, cost_bps) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 10, 10)",
                [oid, pf, tk, side, qty, d, px, px])
    portfolio.apply_fill(con, {"portfolio_id": pf, "ticker": tk, "side": side,
                               "qty": qty, "fill_px": px})


def _corp_actions(con):
    con.execute("CREATE TABLE IF NOT EXISTS corporate_actions (ticker VARCHAR, "
                "ex_date DATE, kind VARCHAR, value DOUBLE, source VARCHAR, "
                "fetched_at TIMESTAMP)")


# 1. dividends -----------------------------------------------------------------
def test_dividend_published_day_after_ex_date_is_still_credited(con):
    pf = _book(con)
    _corp_actions(con)
    _fill(con, pf, "XYZ", "buy", 100, 50.0, D1, 1)
    # Ex-date D2. On the D2 step the row is not there yet (yfinance lag).
    assert portfolio.credit_dividends(con, D2) == {"credited": 0, "amount": 0.0}
    con.execute("INSERT INTO corporate_actions VALUES ('XYZ', ?, 'dividend', 0.40, "
                "'yf', now())", [D2])
    out = portfolio.credit_dividends(con, D3)
    assert out == {"credited": 1, "amount": pytest.approx(40.0)}
    assert portfolio.get_cash(con, pf) == pytest.approx(INITIAL_CASH - 5000 + 40)
    row = con.execute("SELECT ex_date, qty, dps FROM sim_dividends").fetchone()
    assert row == (D2, 100.0, 0.40)          # stamped with the TRUE ex-date
    # Exactly once.
    assert portfolio.credit_dividends(con, D4) == {"credited": 0, "amount": 0.0}


def test_late_dividend_uses_position_as_of_ex_date(con):
    pf = _book(con)
    _corp_actions(con)
    _fill(con, pf, "XYZ", "buy", 100, 50.0, D1, 1)
    _fill(con, pf, "XYZ", "sell", 60, 50.0, D3, 2)   # sold AFTER ex-date D2
    con.execute("INSERT INTO corporate_actions VALUES ('XYZ', ?, 'dividend', 1.0, "
                "'yf', now())", [D2])
    out = portfolio.credit_dividends(con, D4)
    assert out["amount"] == pytest.approx(100.0)     # entitled on 100, not 40


def test_name_bought_after_ex_date_gets_nothing(con):
    pf = _book(con)
    _corp_actions(con)
    _fill(con, pf, "XYZ", "buy", 100, 50.0, D3, 1)
    con.execute("INSERT INTO corporate_actions VALUES ('XYZ', ?, 'dividend', 1.0, "
                "'yf', now())", [D2])
    assert portfolio.credit_dividends(con, D4)["credited"] == 0


def test_rebuild_state_replays_late_credit_at_ex_date(con):
    pf = _book(con)
    _corp_actions(con)
    _fill(con, pf, "XYZ", "buy", 100, 50.0, D1, 1)
    con.execute("INSERT INTO corporate_actions VALUES ('XYZ', ?, 'dividend', 0.5, "
                "'yf', now())", [D2])
    portfolio.credit_dividends(con, D3)
    cash_live = portfolio.get_cash(con, pf)
    portfolio.rebuild_state(con)
    assert portfolio.get_cash(con, pf) == pytest.approx(cash_live)


# 2. cadence at the latest bar -----------------------------------------------
def test_month_signal_fires_when_month_ends_on_weekend(con):
    insert_bars(con, "SPY", [date(2026, 10, 29), date(2026, 10, 30)])
    assert calendar.is_month_signal(con, date(2026, 10, 30))
    assert not calendar.is_month_signal(con, date(2026, 10, 29))


def test_week_signal_fires_on_thursday_before_holiday_friday(con):
    insert_bars(con, "SPY", [date(2026, 12, 23), date(2026, 12, 24)])
    assert calendar.is_week_signal(con, date(2026, 12, 24))
    assert not calendar.is_week_signal(con, date(2026, 12, 23))


def test_month_signal_does_not_fire_midmonth_latest_bar(con):
    insert_bars(con, "SPY", [date(2026, 9, 1)])
    assert not calendar.is_month_signal(con, date(2026, 9, 1))
    assert not calendar.is_week_signal(con, date(2026, 9, 1))


# 3 & 7. untradeable bars ------------------------------------------------------
def test_zero_open_bar_is_not_a_fill(con):
    insert_bars(con, "ACAAW", [D1], open_=0.0, close=0.60)
    r = fills.attempt_fill(con, "ACAAW", "buy", 1000, date(2024, 5, 31), D1)
    assert r.status == "pending"


def test_apply_fill_refuses_zero_price(con):
    pf = _book(con)
    assert portfolio.apply_fill(con, {"portfolio_id": pf, "ticker": "X", "side": "buy",
                                      "qty": 1_000_000, "fill_px": 0.0}) == 0.0
    assert portfolio.get_cash(con, pf) == INITIAL_CASH
    assert con.execute("SELECT COUNT(*) FROM sim_positions").fetchone()[0] == 0


def test_zero_volume_phantom_bar_does_not_fill(con):
    insert_bars(con, "EA", [date(2024, 5, 30), date(2024, 5, 31)], open_=209.7,
                close=209.7, volume=5_000_000)
    insert_bars(con, "EA", [D1], open_=209.7, close=209.7, volume=0)
    r = fills.attempt_fill(con, "EA", "sell", 5, date(2024, 5, 31), D1)
    assert r.status == "pending"
    insert_bars(con, "EA", [D2], open_=209.7, close=209.7, volume=1000)
    assert fills.attempt_fill(con, "EA", "sell", 5, date(2024, 5, 31), D2).status == "filled"


# 4. same-day ticket must not kill the step ------------------------------------
def test_fill_pending_skips_orders_signalled_today(con):
    pf = _book(con)
    insert_bars(con, "DELL", [D1, D2], open_=100.0, close=100.0)
    con.execute("INSERT INTO sim_orders (id, portfolio_id, ticker, side, qty, "
                "signal_date, status) VALUES (1, ?, 'DELL', 'buy', 9, ?, 'pending')",
                [pf, D2])
    counts = league.fill_pending(con, D2)     # would have raised AssertionError
    assert counts == {"filled": 0, "rejected": 0, "pending": 0}
    assert con.execute("SELECT status FROM sim_orders").fetchone()[0] == "pending"


# 6. --rerun and discretionary tickets ----------------------------------------
def test_rerun_cleanup_keeps_ticket_orders(con):
    pf = _book(con, "discretionary")
    con.execute("INSERT INTO sim_orders (id, portfolio_id, ticker, side, qty, "
                "signal_date, status) VALUES (1, ?, 'DELL', 'buy', 9, ?, 'pending'), "
                "(2, ?, 'AAPL', 'buy', 1, ?, 'pending')", [pf, D1, pf, D1])
    con.execute("INSERT INTO disc_tickets (id, ticker, side, qty, status, order_id, "
                "created_at) VALUES (1, 'DELL', 'buy', 9, 'submitted', 1, now())")
    league.rerun_cleanup(con, D1)
    assert con.execute("SELECT id FROM sim_orders").fetchall() == [(1,)]


def test_step_refuses_historical_rerun(con, tmp_path):
    _book(con)
    con.execute("INSERT INTO sim_equity (portfolio_id, date, equity, cash) VALUES "
                "('b', ?, 1, 1), ('b', ?, 1, 1)", [D1, D2])
    assert league.step(con, D1, tmp_path, rerun=True, verbose=False) == 1


# 5. risk gates anchored to the market ----------------------------------------
def _risk_con(con):
    from datetime import timedelta
    days = [date(2023, 1, 2) + timedelta(days=i) for i in range(280)]
    days = [d for d in days if d.weekday() < 5][:200]
    insert_bars(con, "SPY", days, close=[400.0 + i for i in range(200)])
    insert_bars(con, "AAA", days[-3:], close=100.0)
    return con


def test_absurd_entry_ref_no_longer_sizes_a_25x_position(con):
    _risk_con(con)
    t = dict(ticker="AAA", side="buy", qty=9750, entry_ref=1000.0, stop=999.99,
             target=1100.0, playbook="experiment", acknowledge_earnings=True)
    gates = risk.evaluate_gates(con, t)
    st = {g["name"]: g["status"] for g in gates}
    assert st["entry_anchored"] == "fail"
    assert st["notional_cap"] == "fail"
    assert st["stop_present"] == "fail"          # stop 999.99 > close 100
    assert not risk.is_allowed(gates, t)[0]


def test_stop_above_live_close_is_breached(con):
    _risk_con(con)
    t = dict(ticker="AAA", side="buy", qty=10, entry_ref=105.0, stop=101.0,
             target=115.0, playbook="experiment", acknowledge_earnings=True)
    gates = risk.evaluate_gates(con, t)
    assert {g["name"]: g["status"] for g in gates}["stop_present"] == "fail"


def test_risk_per_share_uses_worse_of_entry_and_close(con):
    _risk_con(con)
    # entry typed 95 with close 100: r/share is 100-90 = 10, not 5.
    t = dict(ticker="AAA", side="buy", qty=40, entry_ref=95.0, stop=90.0,
             target=120.0, playbook="vcp", acknowledge_earnings=True)
    gates = risk.evaluate_gates(con, t)
    sizing = next(g for g in gates if g["name"] == "sizing_1pct")
    assert sizing["status"] == "fail"            # 40 × $10 = $400 > $390
    assert "max 39" in sizing["detail"]


# 4b. discretionary look-ahead through the server -----------------------------
def test_ticket_signal_date_rolls_forward_during_next_session():
    as_of = date(2026, 9, 1)
    pre = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)    # 08:00 ET, pre-market
    mid = datetime(2026, 9, 2, 15, 0, tzinfo=timezone.utc)    # 11:00 ET, session open
    same = datetime(2026, 9, 1, 23, 0, tzinfo=timezone.utc)   # after tonight's collect
    assert _ticket_signal_date(as_of, pre) == as_of
    assert _ticket_signal_date(as_of, mid) == date(2026, 9, 2)
    assert _ticket_signal_date(as_of, same) == as_of
