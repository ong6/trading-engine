"""Regression tests for the 2026-09-02 simulator audit (BUILDLOG 2026-09-02).
Each test is the minimal shape of a bug that was confirmed against the store."""
from datetime import date, datetime, timedelta, timezone

import pytest

from server import risk, tickets
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


def test_init_portfolios_respects_retired_config_flag(con):
    league.init_portfolios(con, D1)
    assert con.execute(
        "SELECT active FROM portfolios WHERE id = 'news_gated_momo'"
    ).fetchone() == (False,)
    assert con.execute(
        "SELECT active FROM portfolios WHERE id = 'xs_momentum_12_1'"
    ).fetchone() == (True,)


def test_league_run_closes_connection_when_step_fails(monkeypatch, tmp_path):
    class Result:
        @staticmethod
        def fetchone():
            return (1,)

    class Connection:
        closed = False

        @staticmethod
        def execute(_sql):
            return Result()

        def close(self):
            self.closed = True

    connection = Connection()
    monkeypatch.setattr(league.db, "connect", lambda *_args, **_kwargs: connection)
    monkeypatch.setattr(league.db, "init_schema", lambda _con: None)
    monkeypatch.setattr(league.db, "init_actions_schema", lambda _con: None)
    monkeypatch.setattr(league, "init_sim_schema", lambda _con: None)
    monkeypatch.setattr(league, "resolve_date", lambda *_args: D1)
    monkeypatch.setattr(
        league,
        "step",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("injected step failure")
        ),
    )

    with pytest.raises(RuntimeError, match="injected step failure"):
        league.run("unused", tmp_path, None, False, False)
    assert connection.closed is True


def test_league_skip_if_done_restores_reports_without_rewriting_ledger(con, tmp_path):
    _book(con)
    insert_bars(con, "SPY", [D1])
    con.execute(
        "INSERT INTO sim_equity (portfolio_id, date, equity, cash) VALUES (?, ?, ?, ?)",
        ["b", D1, INITIAL_CASH, INITIAL_CASH],
    )
    ledger_tables = (
        "portfolios",
        "sim_orders",
        "sim_fills",
        "sim_fill_costs",
        "sim_execution_attempts",
        "sim_positions",
        "sim_equity",
        "sim_dividends",
    )
    before = {
        table: con.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608
        for table in ledger_tables
    }

    assert league.step(con, D1, tmp_path, False, skip_if_done=True) == 0
    assert {
        table: con.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608
        for table in ledger_tables
    } == before
    markdown = (tmp_path / "reports" / "league.md").read_text()
    assert "# Paper League" in markdown
    assert "b" in markdown
    assert (tmp_path / "reports" / "league.csv").read_text() == (
        "portfolio_id,date,equity\nb,2024-06-03,39000.0\n"
    )


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


def test_fill_pending_scales_simultaneous_buys_pro_rata(con):
    pf = _book(con)
    con.execute("UPDATE portfolios SET cash = 100 WHERE id = ?", [pf])
    hist = [D1 - timedelta(days=i) for i in range(30, 0, -1)]
    for ticker in ("AAA", "ZZZ"):
        insert_bars(con, ticker, hist + [D2], open_=100.0, close=100.0,
                    volume=1_000_000)
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(1, ?, 'ZZZ', 'buy', 1, ?, 'pending', NULL), "
        "(2, ?, 'AAA', 'buy', 1, ?, 'pending', NULL)",
        [pf, D1, pf, D1],
    )
    counts = league.fill_pending(con, D2)
    fills_ = dict(con.execute(
        "SELECT ticker, qty FROM sim_fills ORDER BY ticker").fetchall())
    assert counts == {"filled": 2, "rejected": 0, "pending": 0}
    assert fills_["AAA"] == pytest.approx(fills_["ZZZ"])
    assert fills_["AAA"] == pytest.approx(100 / (2 * 100.1), rel=1e-9)
    assert 0 <= portfolio.get_cash(con, pf) < 1e-6


@pytest.mark.parametrize(
    ("second_result", "expected_counts", "expected_order"),
    [
        (
            fills.FillResult(
                status="rejected", reject_reason="scaled_order_rejected",
                open_px=100.0,
            ),
            {"filled": 0, "rejected": 1, "pending": 0},
            ("rejected", "scaled_order_rejected"),
        ),
        (
            fills.FillResult(status="pending"),
            {"filled": 0, "rejected": 0, "pending": 1},
            ("pending", None),
        ),
    ],
)
def test_cash_scaled_buy_handles_nonfill_when_repriced(
        con, monkeypatch, second_result, expected_counts, expected_order):
    pf = _book(con)
    con.execute("UPDATE portfolios SET cash = 50 WHERE id = ?", [pf])
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(1, ?, 'AAA', 'buy', 1, ?, 'pending', NULL)", [pf, D1])
    first_result = fills.FillResult(
        status="filled", open_px=100.0, fill_px=100.1,
        slippage_bps=10.0, cost_bps=10.0,
        median_dollar_vol=1_000_000.0, participation=0.0001,
        impact_bps=0.0, fee_bps=0.0, execution_profile="baseline_v1",
    )
    attempts = iter((first_result, second_result))
    monkeypatch.setattr(league.fills, "attempt_fill", lambda *args: next(attempts))

    counts = league.fill_pending(con, D2)

    assert counts == expected_counts
    assert con.execute(
        "SELECT status, reject_reason FROM sim_orders WHERE id = 1"
    ).fetchone() == expected_order
    assert con.execute("SELECT COUNT(*) FROM sim_fills").fetchone() == (0,)
    outcome, reason, raw_notional = con.execute(
        "SELECT outcome, reject_reason, raw_notional "
        "FROM sim_execution_attempts WHERE order_id = 1 AND attempt_date = ?",
        [D2],
    ).fetchone()
    assert (outcome, reason) == (second_result.status, second_result.reject_reason)
    expected_raw = 50.0 / first_result.fill_px * (1.0 - 1e-12) * 100.0
    assert raw_notional == (None if second_result.open_px is None else
                            pytest.approx(expected_raw))


def test_cash_dust_rejection_is_recorded_as_rejected_attempt(con):
    pf = _book(con)
    con.execute("UPDATE portfolios SET cash = 0.50 WHERE id = ?", [pf])
    hist = [D1 - timedelta(days=i) for i in range(30, 0, -1)]
    insert_bars(con, "AAA", hist + [D2], open_=100.0, close=100.0,
                volume=1_000_000)
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(1, ?, 'AAA', 'buy', 1, ?, 'pending', NULL)", [pf, D1])

    counts = league.fill_pending(con, D2)

    assert counts == {"filled": 0, "rejected": 1, "pending": 0}
    assert con.execute(
        "SELECT outcome, reject_reason FROM sim_execution_attempts "
        "WHERE order_id = 1 AND attempt_date = ?", [D2]).fetchone() == (
            "rejected", "insufficient_cash")
    assert con.execute("SELECT COUNT(*) FROM sim_fills").fetchone() == (0,)


def test_empty_position_sell_is_recorded_as_rejected_attempt(con):
    pf = _book(con)
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(1, ?, 'AAA', 'sell', 1, ?, 'pending', NULL)", [pf, D1])

    counts = league.fill_pending(con, D2)

    assert counts == {"filled": 0, "rejected": 1, "pending": 0}
    assert con.execute(
        "SELECT outcome, reject_reason FROM sim_execution_attempts "
        "WHERE order_id = 1 AND attempt_date = ?", [D2]).fetchone() == (
            "rejected", "no_position_to_sell")


def test_oversized_sell_is_costed_and_filled_at_held_quantity(con):
    pf = _book(con)
    insert_bars(con, "AAA", [D1, D2], open_=100.0, close=100.0,
                volume=100_000)
    portfolio.apply_fill(con, {"portfolio_id": pf, "ticker": "AAA",
                               "side": "buy", "qty": 10, "fill_px": 100})
    con.execute(
        "UPDATE portfolios SET execution_profile = 'participation_stress_v1' "
        "WHERE id = ?", [pf])
    con.execute(
        "INSERT INTO sim_orders (id, portfolio_id, ticker, side, qty, signal_date, "
        "status) VALUES (1, ?, 'AAA', 'sell', 1000, ?, 'pending')", [pf, D1])
    counts = league.fill_pending(con, D2)
    assert counts["filled"] == 1
    qty, participation = con.execute(
        "SELECT f.qty, c.participation FROM sim_fills f "
        "JOIN sim_fill_costs c USING (order_id) WHERE f.order_id = 1").fetchone()
    assert qty == pytest.approx(10.0)
    assert participation == pytest.approx(10 * 100 / (100 * 100_000))


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
    con.execute(
        "CREATE TABLE universe "
        "(ticker VARCHAR PRIMARY KEY, active BOOLEAN, liquid BOOLEAN)"
    )
    con.execute(
        "INSERT INTO universe VALUES ('SPY', TRUE, TRUE), ('AAA', TRUE, TRUE)"
    )
    days = [date(2023, 1, 2) + timedelta(days=i) for i in range(280)]
    days = [d for d in days if d.weekday() < 5][:200]
    insert_bars(con, "SPY", days, close=[400.0 + i for i in range(200)])
    insert_bars(
        con, "AAA", days[-3:], open_=100.0, high=101.0, low=99.0, close=100.0
    )
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
    assert tickets.signal_date(as_of, pre) == as_of
    assert tickets.signal_date(as_of, mid) == date(2026, 9, 2)
    assert tickets.signal_date(as_of, same) == as_of
