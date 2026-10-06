"""P22 L3 routing, replay, fee, phase-order, and public-report contracts."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from server import league_read_models
from sim import fills, league, p15_books, p16_book_mechanics
from sim.schema import set_portfolio_account
from tests.conftest import SESSIONS, insert_bars
from tests.read_model_helpers import liquid_universe


def _portfolio(con, portfolio_id: str, created: date, *, cash: float = 10_000.0):
    con.execute(
        "INSERT INTO portfolios "
        "(id,name,strategy,config,created,active,cash,initial_cash,execution_profile) "
        "VALUES (?,?, 'none','{}',?,TRUE,?,?, 'baseline_v1')",
        [portfolio_id, portfolio_id, created, cash, cash],
    )


def test_every_l3_order_allocator_uses_a_non_reusing_sequence(con):
    first = league.next_order_id(con)
    con.execute(
        "INSERT INTO sim_orders VALUES (?, 'x','XYZ','buy',1,?,'pending',NULL)",
        [first, SESSIONS[0]],
    )
    con.execute("DELETE FROM sim_orders WHERE id=?", [first])
    second = p15_books._next_order_id(con)
    con.execute(
        "INSERT INTO sim_orders VALUES (?, 'x','XYZ','buy',1,?,'pending',NULL)",
        [second, SESSIONS[0]],
    )
    con.execute("DELETE FROM sim_orders WHERE id=?", [second])
    third = p16_book_mechanics.next_sim_order_id(con)

    assert first < second < third


def test_rerun_preserves_every_externally_referenced_order(con):
    _portfolio(con, "book", SESSIONS[0])
    con.executemany(
        "INSERT INTO sim_orders VALUES (?, 'book','XYZ','buy',1,?,'pending',NULL)",
        [(order_id, SESSIONS[0]) for order_id in range(1, 7)],
    )
    con.execute(
        "CREATE TABLE daily_opportunity_order_attribution (order_id BIGINT)"
    )
    con.execute("CREATE TABLE p15_order_intents (sim_order_id BIGINT)")
    con.execute("CREATE TABLE p16_order_intents (sim_order_id BIGINT)")
    con.execute("INSERT INTO daily_opportunity_order_attribution VALUES (1)")
    con.execute(
        "INSERT INTO paper_account_intakes "
        "(intent_id,account_id,order_id,payload,sha256,received_at) "
        "VALUES ('intent-2','book',2,'{}',repeat('a',64),now())"
    )
    con.execute("INSERT INTO p15_order_intents VALUES (3)")
    con.execute("INSERT INTO p16_order_intents VALUES (4)")
    con.execute(
        "INSERT INTO sim_order_details "
        "(order_id,instrument_id,instrument_kind,order_type,side,tif,session_date,"
        "received_at,state) VALUES (5,'XYZ','stock','next_open','buy','day',?,?,'queued')",
        [SESSIONS[1], datetime(2026, 10, 6, 20)],
    )

    league.rerun_cleanup(con, SESSIONS[0])

    assert con.execute("SELECT id FROM sim_orders ORDER BY id").fetchall() == [
        (1,), (2,), (3,), (4,), (5,)
    ]


def test_rerun_requeues_account_detail_when_its_fill_is_removed(con):
    _portfolio(con, "account-book", SESSIONS[0])
    set_portfolio_account(con, "account-book", engine="account")
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(1,'account-book','XYZ','buy',1,?,'filled',NULL)", [SESSIONS[0]]
    )
    con.execute(
        "INSERT INTO sim_order_details "
        "(order_id,instrument_id,instrument_kind,order_type,side,tif,session_date,"
        "received_at,state,state_at) VALUES "
        "(1,'XYZ','stock','moo','buy','day',?,?, 'filled',now())",
        [SESSIONS[1], datetime(2026, 10, 6, 20)],
    )
    con.execute(
        "INSERT INTO sim_fills VALUES "
        "(1,'account-book','XYZ','buy',1,?,100,100,0,0)", [SESSIONS[1]]
    )

    league.rerun_cleanup(con, SESSIONS[1])

    assert con.execute("SELECT status FROM sim_orders WHERE id=1").fetchone() == (
        "pending",
    )
    assert con.execute("SELECT state FROM sim_order_details WHERE order_id=1").fetchone() == (
        "queued",
    )
    assert con.execute("SELECT COUNT(*) FROM sim_fills WHERE order_id=1").fetchone() == (0,)


def test_league_fills_and_generates_only_league_engine_books(con, monkeypatch):
    signal_date, fill_date = SESSIONS[29:31]
    insert_bars(
        con, "XYZ", SESSIONS[:31], open_=100, close=100, high=101, low=99
    )
    for portfolio_id in ("league-book", "account-book"):
        _portfolio(con, portfolio_id, signal_date)
    set_portfolio_account(con, "account-book", engine="account")
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(1,'league-book','XYZ','buy',1,?,'pending',NULL),"
        "(2,'account-book','XYZ','buy',1,?,'pending',NULL)",
        [signal_date, signal_date],
    )

    assert league.fill_pending(con, fill_date)["filled"] == 1
    assert con.execute(
        "SELECT id,status FROM sim_orders ORDER BY id"
    ).fetchall() == [(1, "filled"), (2, "pending")]

    generated = []
    monkeypatch.setattr(league, "get_strategy", lambda _name: type(
        "Strategy", (), {"generate_orders": lambda *_args: generated.append(True) or []}
    )())
    league.generate_all(con, fill_date)
    assert generated == [True]


def test_phase_order_calls_optional_account_hooks_between_legacy_phases(
    con, tmp_path, monkeypatch,
):
    _portfolio(con, "book", SESSIONS[0])
    observed = []
    monkeypatch.setattr(
        league.portfolio, "credit_dividends", lambda *_args: observed.append("a0") or {}
    )
    monkeypatch.setattr(league, "accrue_accounts", lambda *_args: observed.append("a0b"))
    monkeypatch.setattr(
        league, "fill_pending", lambda *_args: observed.append("a") or {
            "filled": 0, "rejected": 0, "pending": 0,
        }
    )
    monkeypatch.setattr(league, "settle_accounts", lambda *_args: observed.append("a2"))
    monkeypatch.setattr(
        league, "mtm_all", lambda *_args, **_kwargs: observed.append("b") or {
            "carried": {},
        }
    )
    monkeypatch.setattr(
        league, "check_account_halts", lambda *_args: observed.append("b2")
    )
    monkeypatch.setattr(
        league, "generate_all", lambda *_args: observed.append("c") or 0
    )
    monkeypatch.setattr(
        league, "write_reports", lambda *_args: observed.append("d") or tmp_path
    )

    assert league.step(
        con, SESSIONS[1], tmp_path, rerun=False, verbose=False
    ) == 0
    assert observed == ["a0", "a0b", "a", "a2", "b", "b2", "c", "d"]


def test_present_optional_module_with_missing_hook_fails_loudly(monkeypatch):
    monkeypatch.setattr(league.importlib, "import_module", lambda _name: object())

    with pytest.raises(AttributeError):
        league._optional_phase("engine.accounts.settle", "settle_session", None, SESSIONS[0])


def test_integrated_phase_hooks_use_l1_and_l2_entry_points(monkeypatch):
    observed = []

    def call(module_name, function_name, _con, _day, **kwargs):
        observed.append((module_name, function_name, kwargs))
        return function_name

    monkeypatch.setattr(league, "_optional_phase", call)

    assert league.accrue_accounts(None, SESSIONS[0]) == {
        "borrow": "accrue_borrow", "interest": "accrue_interest",
    }
    assert league.settle_accounts(None, SESSIONS[0]) == "settle_session"
    assert league.check_account_halts(None, SESSIONS[0]) == {
        "halts": "check_all", "alerts": "concentration",
    }
    assert observed == [
        ("sim.shorts", "accrue_borrow", {}),
        ("sim.margin", "accrue_interest", {}),
        ("engine.accounts.settle", "settle_session", {"manage_transactions": False}),
        ("engine.money.halts", "check_all", {}),
        ("engine.money.alerts", "concentration", {}),
    ]


def test_private_book_never_reaches_public_files_or_read_models(con, tmp_path):
    prior, current = SESSIONS[:2]
    liquid_universe(con, ("SPY",))
    insert_bars(con, "SPY", [prior, current], open_=100, close=[100, 101])
    for portfolio_id in ("public-book", "private-book"):
        _portfolio(con, portfolio_id, prior, cash=100)
        con.executemany(
            "INSERT INTO sim_equity VALUES (?,?,?,?,0)",
            [(portfolio_id, prior, 100.0, 100.0),
             (portfolio_id, current, 110.0, 110.0)],
        )
    set_portfolio_account(con, "private-book", visibility="private")
    con.execute(
        "INSERT INTO sim_book_breaks VALUES "
        "('public-book',?,'cost_profile','baseline_v1','ibkr_pro_tiered_v1',"
        "13,'test',now())",
        [current],
    )

    league.write_reports(con, current, tmp_path)
    markdown = (tmp_path / "reports" / "league.md").read_text()
    csv = (tmp_path / "reports" / "league.csv").read_text()
    payload = league_read_models.league(con)

    assert "Since break" in markdown and "Fees paid" in markdown
    assert "commissions from the recorded cost-profile break" in markdown
    assert "private-book" not in markdown and "private-book" not in csv
    assert [row["id"] for row in payload["rows"]] == ["public-book"]
    assert league_read_models.equity(con, "private-book") is None


def test_future_break_is_not_disclosed_in_pre_break_report(con, tmp_path):
    prior, d0 = SESSIONS[:2]
    insert_bars(con, "SPY", [prior], open_=100, close=100)
    _portfolio(con, "public-book", prior, cash=100)
    con.execute("INSERT INTO sim_equity VALUES ('public-book',?,100,100,0)", [prior])
    con.execute(
        "INSERT INTO sim_book_breaks VALUES "
        "('public-book',?,'cost_profile','baseline_v1','ibkr_pro_tiered_v1',"
        "13,'test',now())",
        [d0],
    )

    league.write_reports(con, prior, tmp_path)

    markdown = (tmp_path / "reports" / "league.md").read_text()
    assert "Commission break" not in markdown
    assert "Since break" not in markdown


def test_post_break_p15_fill_charges_fee_and_debits_cash(con):
    signal_date, fill_date = SESSIONS[:2]
    portfolio_id = p15_books.BOOK_IDS[0]
    p15_books.init_schema(con)
    _portfolio(con, portfolio_id, signal_date, cash=9_000.0)
    con.execute(
        "INSERT INTO sim_positions VALUES (?, 'XYZ', 10, 90)", [portfolio_id]
    )
    set_portfolio_account(
        con, portfolio_id, engine="p15", cost_profile="ibkr_pro_tiered_v1"
    )
    con.execute(
        "INSERT INTO sim_book_breaks VALUES "
        "(?,?,'cost_profile','baseline_v1','ibkr_pro_tiered_v1',13,'test',now())",
        [portfolio_id, fill_date],
    )
    result = fills.FillResult(
        status="filled",
        open_px=100.0,
        fill_px=100.0,
        slippage_bps=0.0,
        cost_bps=0.0,
        execution_profile="baseline_v1",
        median_dollar_vol=1_000_000.0,
        participation=0.001,
        impact_bps=0.0,
        fee_bps=0.0,
    )
    intent = (
        1, portfolio_id, "XYZ", "sell", 10.0, signal_date, "time_exit",
        0, 100.0, None, None,
    )

    assert p15_books._terminal_order(con, intent, fill_date, result) == "filled"
    fee = con.execute("SELECT total_usd FROM sim_fill_fees").fetchone()[0]
    cash = con.execute(
        "SELECT cash FROM portfolios WHERE id=?", [portfolio_id]
    ).fetchone()[0]
    assert fee > 0
    assert cash == pytest.approx(9_000.0 + 1_000.0 - fee)


def test_post_break_p15_spy_sizing_reserves_estimated_fee(con, monkeypatch):
    signal_date, fill_date = SESSIONS[:2]
    portfolio_id = p15_books.BOOK_IDS[0]
    p15_books.init_schema(con)
    _portfolio(con, portfolio_id, signal_date, cash=1_000.0)
    set_portfolio_account(
        con, portfolio_id, engine="p15", cost_profile="ibkr_pro_tiered_v1"
    )
    con.execute(
        "INSERT INTO sim_book_breaks VALUES "
        "(?,?,'cost_profile','baseline_v1','ibkr_pro_tiered_v1',13,'test',now())",
        [portfolio_id, fill_date],
    )
    result = fills.FillResult(
        status="filled",
        open_px=100.0,
        fill_px=100.0,
        slippage_bps=0.0,
        cost_bps=0.0,
        execution_profile="baseline_v1",
        median_dollar_vol=1_000_000.0,
        participation=0.001,
        impact_bps=0.0,
        fee_bps=0.0,
    )
    monkeypatch.setattr(p15_books.fills, "attempt_fill", lambda *_args: result)
    intent = (
        1, portfolio_id, "SPY", "buy", 1.0, signal_date, "spy_reinvest",
        99, 100.0, None, None,
    )

    assert p15_books._terminal_order(con, intent, fill_date, result) == "filled"
    qty, fee = con.execute(
        "SELECT f.qty,ff.total_usd FROM sim_fills f "
        "JOIN sim_fill_fees ff USING (order_id)"
    ).fetchone()
    cash = con.execute(
        "SELECT cash FROM portfolios WHERE id=?", [portfolio_id]
    ).fetchone()[0]
    assert qty == 9.0
    assert cash == pytest.approx(1_000.0 - qty * 100.0 - fee)
    assert cash >= 0
