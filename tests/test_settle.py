"""sim/settle.py — settling a dead position at owner-supplied terms."""
from datetime import date, datetime

import pytest

from engine.lib.util import table_exists
from sim import league, portfolio, settle
from sim.schema import INITIAL_CASH
from tests.conftest import insert_bars

D1, D2, D3, D4, D5 = (date(2024, 6, 3), date(2024, 6, 4), date(2024, 6, 5),
                      date(2024, 6, 6), date(2024, 6, 7))
SRC = "https://example.com/deal-close-press-release"


def _book(con, pf_id="b"):
    con.execute("INSERT INTO portfolios (id, name, strategy, created, active, cash) "
                "VALUES (?, ?, 'x', ?, TRUE, ?)", [pf_id, pf_id, D1, INITIAL_CASH])
    return pf_id


def _fill(con, pf, tk, side, qty, px, d, oid):
    con.execute("INSERT INTO sim_orders (id, portfolio_id, ticker, side, qty, "
                "signal_date, status) VALUES (?, ?, ?, ?, ?, ?, 'filled')",
                [oid, pf, tk, side, qty, d])
    con.execute("INSERT INTO sim_fills (order_id, portfolio_id, ticker, side, qty, "
                "fill_date, open_px, fill_px, slippage_bps, cost_bps) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 10, 10)",
                [oid, pf, tk, side, qty, d, px, px])
    portfolio.apply_fill(con, {"portfolio_id": pf, "ticker": tk, "side": side,
                               "qty": qty, "fill_px": px})


def _pending(con, pf, tk, side, qty, d, oid):
    con.execute("INSERT INTO sim_orders (id, portfolio_id, ticker, side, qty, "
                "signal_date, status) VALUES (?, ?, ?, ?, ?, ?, 'pending')",
                [oid, pf, tk, side, qty, d])


def _dead_name(con, tk="EA", last=D2):
    """Real bars through `last`, then two zero-volume phantom bars (yfinance style)."""
    insert_bars(con, tk, [D1, last], open_=200.0, close=209.7, volume=5_000_000)
    insert_bars(con, tk, [D3, D4], open_=209.7, close=209.7, volume=0)


def _terms(**kw):
    base = dict(ticker="EA", kind="cash", price=209.70, effective=D3, source=SRC)
    base.update(kw)
    return settle.Terms(**base)


def _state(con, pf):
    return portfolio.get_cash(con, pf), portfolio.get_positions(con, pf)


# cash --------------------------------------------------------------------------
def test_cash_settle_credits_and_zeroes(con):
    pf = _book(con)
    _dead_name(con)
    _fill(con, pf, "EA", "buy", 10, 200.0, D1, 1)
    cash0 = portfolio.get_cash(con, pf)

    plans = settle.settle(con, _terms(), apply=False)          # dry run
    assert plans[0].cash_after == pytest.approx(cash0 + 2097.0)
    assert portfolio.get_cash(con, pf) == cash0                 # nothing written
    assert not table_exists(con, "sim_settlements")

    settle.settle(con, _terms(), apply=True)
    cash, pos = _state(con, pf)
    assert cash == pytest.approx(cash0 + 10 * 209.70)
    assert "EA" not in pos
    row = con.execute("SELECT portfolio_id, ticker, kind, qty, price, effective, source "
                      "FROM sim_settlements").fetchone()
    assert row == (pf, "EA", "cash", 10.0, 209.70, D3, SRC)


def test_settles_every_active_holder_not_inactive_or_nonholder(con):
    a, b, c = _book(con, "a"), _book(con, "b"), _book(con, "c")
    con.execute("UPDATE portfolios SET active = FALSE WHERE id = 'c'")
    _dead_name(con)
    _fill(con, a, "EA", "buy", 10, 200.0, D1, 1)
    _fill(con, c, "EA", "buy", 5, 200.0, D1, 2)
    plans = settle.settle(con, _terms(), apply=True)
    assert [p.portfolio_id for p in plans] == ["a"]
    assert portfolio.get_positions(con, c)["EA"]["qty"] == 5
    assert portfolio.get_cash(con, b) == INITIAL_CASH


def test_worthless_zeroes_without_cash(con):
    pf = _book(con)
    _dead_name(con, "FBRX")
    _fill(con, pf, "FBRX", "buy", 100, 200.0, D1, 1)
    cash0 = portfolio.get_cash(con, pf)
    settle.settle(con, _terms(ticker="FBRX", kind="worthless", price=0.0), apply=True)
    assert portfolio.get_cash(con, pf) == cash0
    assert "FBRX" not in portfolio.get_positions(con, pf)


def test_apply_cancels_matching_pending_orders_and_audits(con):
    pf = _book(con)
    other = _book(con, "other")
    _dead_name(con)
    _fill(con, pf, "EA", "buy", 10, 200.0, D1, 1)
    _pending(con, pf, "EA", "sell", 10, D2, 2)
    _pending(con, pf, "SPY", "buy", 1, D2, 3)
    _pending(con, other, "EA", "buy", 1, D2, 4)

    plans = settle.settle(
        con, _terms(), apply=True, now=datetime(2024, 6, 8, 12, 0, 0))

    assert plans[0].pending_order_ids == [2]
    assert con.execute(
        "SELECT id, status, reject_reason FROM sim_orders ORDER BY id"
    ).fetchall() == [
        (1, "filled", None),
        (2, "cancelled", "cancelled by settlement effective 2024-06-05"),
        (3, "pending", None),
        (4, "pending", None),
    ]
    action, payload = con.execute(
        "SELECT action, payload FROM audit_log ORDER BY ts DESC LIMIT 1"
    ).fetchone()
    assert action == "settlement_applied"
    assert '"cancelled_order_ids": [2]' in payload


def test_apply_keeps_linked_discretionary_ticket_consistent(con):
    pf = _book(con)
    _dead_name(con)
    _fill(con, pf, "EA", "buy", 10, 200.0, D1, 1)
    _pending(con, pf, "EA", "sell", 10, D2, 2)
    con.execute(
        "INSERT INTO disc_tickets (id, ticker, side, qty, status, order_id, created_at) "
        "VALUES (1, 'EA', 'sell', 10, 'submitted', 2, ?)",
        [datetime(2024, 6, 4, 12, 0, 0)],
    )

    settle.settle(con, _terms(), apply=True)

    assert con.execute("SELECT status FROM disc_tickets WHERE id = 1").fetchone()[0] == (
        "cancelled"
    )


def test_dry_run_reports_pending_orders_without_mutating(con):
    pf = _book(con)
    _dead_name(con)
    _fill(con, pf, "EA", "buy", 10, 200.0, D1, 1)
    _pending(con, pf, "EA", "sell", 10, D2, 2)

    plans = settle.settle(con, _terms(), apply=False)

    assert plans[0].pending_order_ids == [2]
    assert "pending order(s) 2: would cancel" in settle._render(
        _terms(), plans, applied=False)
    assert con.execute("SELECT status FROM sim_orders WHERE id = 2").fetchone()[0] == "pending"


def test_reconcile_cancels_only_orders_present_by_settlement_booking(con):
    pf = _book(con)
    _dead_name(con)
    _fill(con, pf, "EA", "buy", 10, 200.0, D1, 1)
    booked = datetime(2024, 6, 5, 12, 0, 0)
    settle.settle(con, _terms(), apply=True, now=booked)
    _pending(con, pf, "EA", "sell", 10, D2, 2)
    _pending(con, pf, "EA", "buy", 10, D4, 3)
    _pending(con, pf, "EA", "buy", 10, D3, 4)
    con.execute(
        "INSERT INTO disc_tickets (id, ticker, side, qty, status, order_id, created_at) "
        "VALUES (1, 'EA', 'sell', 10, 'submitted', 2, ?)",
        [datetime(2024, 6, 4, 12, 0, 0)],
    )

    plans = settle.reconcile_settled_pending_orders(con, apply=False)
    assert [p.order_id for p in plans] == [2]
    assert con.execute("SELECT status FROM sim_orders WHERE id = 2").fetchone()[0] == "pending"

    applied = settle.reconcile_settled_pending_orders(
        con, apply=True, now=datetime(2024, 6, 8, 12, 0, 0))
    assert [p.order_id for p in applied] == [2]
    assert con.execute(
        "SELECT id, status, reject_reason FROM sim_orders WHERE id IN (2, 3, 4) ORDER BY id"
    ).fetchall() == [
        (2, "cancelled", "cancelled by booked settlement effective 2024-06-05"),
        (3, "pending", None),
        (4, "pending", None),
    ]
    action, payload = con.execute(
        "SELECT action, payload FROM audit_log ORDER BY ts DESC LIMIT 1"
    ).fetchone()
    assert action == "settlement_pending_orders_reconciled"
    assert '"order_ids": [2]' in payload
    assert con.execute("SELECT status FROM disc_tickets WHERE id = 1").fetchone()[0] == (
        "cancelled"
    )


def test_rebuild_does_not_cancel_order_created_after_settlement(con):
    pf = _book(con)
    _dead_name(con)
    _fill(con, pf, "EA", "buy", 10, 200.0, D1, 1)
    settle.settle(con, _terms(), apply=True,
                  now=datetime(2024, 6, 5, 12, 0, 0))
    _pending(con, pf, "EA", "buy", 1, D4, 2)

    portfolio.rebuild_state(con)

    assert con.execute("SELECT status FROM sim_orders WHERE id = 2").fetchone()[0] == "pending"


# rebuild -----------------------------------------------------------------------
def test_rebuild_state_reproduces_settlement(con):
    pf = _book(con)
    _dead_name(con)
    insert_bars(con, "SPY", [D1, D2, D3, D4, D5])
    _fill(con, pf, "EA", "buy", 10, 200.0, D1, 1)
    _fill(con, pf, "SPY", "buy", 20, 100.0, D2, 2)
    settle.settle(con, _terms(), apply=True)
    _fill(con, pf, "SPY", "buy", 5, 100.0, D4, 3)     # a fill after the settlement
    live = _state(con, pf)
    portfolio.rebuild_state(con)
    assert _state(con, pf) == live
    assert live[0] == pytest.approx(INITIAL_CASH - 2000 - 2000 + 2097 - 500)


def test_rerun_cleanup_and_rebuild_keep_settlement(con, capsys):
    pf = _book(con)
    _dead_name(con)
    insert_bars(con, "SPY", [D1, D2, D3, D4, D5])
    _fill(con, pf, "EA", "buy", 10, 200.0, D1, 1)
    settle.settle(con, _terms(), apply=True)
    con.execute("INSERT INTO sim_equity (portfolio_id, date, equity, cash) "
                "VALUES (?, ?, 1, 1)", [pf, D3])
    live = _state(con, pf)
    league.rerun_cleanup(con, D3)                     # d == effective
    assert _state(con, pf) == live
    assert con.execute("SELECT COUNT(*) FROM sim_settlements").fetchone()[0] == 1
    assert "WARN" not in capsys.readouterr().out


def test_settled_name_leaves_stale_marks_table(con):
    pf = _book(con)
    _dead_name(con)
    insert_bars(con, "SPY", [D1, D2, D3, D4, D5])
    _fill(con, pf, "EA", "buy", 10, 200.0, D1, 1)
    stale_sql = ("SELECT p.ticker FROM sim_positions p JOIN prices pr ON pr.ticker = p.ticker "
                 "WHERE p.qty > 0 GROUP BY p.ticker "
                 "HAVING MAX(pr.date) FILTER (WHERE pr.volume > 0) < ?")
    assert con.execute(stale_sql, [D5]).fetchall() == [("EA",)]
    settle.settle(con, _terms(), apply=True)
    assert con.execute(stale_sql, [D5]).fetchall() == []
    # and the live report: EA is gone from the stale section
    portfolio.mark_to_market(con, pf, D5)
    md = league.write_reports(con, D5, __import__("pathlib").Path(
        __import__("tempfile").mkdtemp())).read_text()
    assert "Stale marks" not in md


def test_league_stale_marks_exclude_inactive_books(con, monkeypatch):
    active = _book(con, "active")
    inactive = _book(con, "inactive")
    con.execute("UPDATE portfolios SET active = FALSE WHERE id = ?", [inactive])
    _dead_name(con)
    _fill(con, active, "EA", "buy", 10, 200.0, D1, 1)
    _fill(con, inactive, "EA", "buy", 5, 200.0, D1, 2)
    portfolio.mark_to_market(con, active, D5)

    settle.settle(con, _terms(portfolios=(active,)), apply=True)
    atomic_paths = []
    real_atomic_write = league.resources.write_text_atomic

    def recording_atomic_write(path, text):
        atomic_paths.append(path)
        real_atomic_write(path, text)

    monkeypatch.setattr(league.resources, "write_text_atomic", recording_atomic_write)
    data_dir = __import__("pathlib").Path(__import__("tempfile").mkdtemp())
    md_path = league.write_reports(con, D5, data_dir)
    md = md_path.read_text()

    assert "Stale marks" not in md
    assert atomic_paths == [md_path, data_dir / "reports" / "league.csv"]


def test_equity_history_before_effective_untouched(con):
    pf = _book(con)
    _dead_name(con)
    _fill(con, pf, "EA", "buy", 10, 200.0, D1, 1)
    portfolio.mark_to_market(con, pf, D2)
    before = con.execute("SELECT * FROM sim_equity ORDER BY date").fetchall()
    settle.settle(con, _terms(), apply=True)
    assert con.execute("SELECT * FROM sim_equity ORDER BY date").fetchall() == before
    assert con.execute("SELECT COUNT(*) FROM prices WHERE ticker = 'EA'").fetchone()[0] == 4


# refusals ----------------------------------------------------------------------
def test_refuses_live_ticker(con):
    pf = _book(con)
    insert_bars(con, "EA", [D1, D2, D3, D4], close=209.7, volume=1_000)   # still trading
    _fill(con, pf, "EA", "buy", 10, 200.0, D1, 1)
    with pytest.raises(settle.SettlementRefused, match="traded on/after"):
        settle.settle(con, _terms(effective=D3), apply=True)
    assert portfolio.get_positions(con, pf)["EA"]["qty"] == 10
    assert not table_exists(con, "sim_settlements")


def test_refuses_without_source(con):
    pf = _book(con)
    _dead_name(con)
    _fill(con, pf, "EA", "buy", 10, 200.0, D1, 1)
    for src in ("", "   "):
        with pytest.raises(settle.SettlementRefused, match="--source is required"):
            settle.settle(con, _terms(source=src), apply=True)


def test_refuses_bad_shapes(con):
    pf = _book(con)
    _dead_name(con)
    _fill(con, pf, "EA", "buy", 10, 200.0, D1, 1)
    with pytest.raises(settle.SettlementRefused):
        settle.settle(con, _terms(kind="cash", price=0.0))
    with pytest.raises(settle.SettlementRefused):
        settle.settle(con, _terms(kind="worthless", price=1.0))
    with pytest.raises(settle.SettlementRefused, match="no real bar"):
        settle.settle(con, _terms(kind="stock", price=0.0, into_ticker="NOPX", ratio=0.5))
    with pytest.raises(settle.SettlementRefused, match="no active book"):
        settle.settle(con, _terms(ticker="TALK"))


# stock -------------------------------------------------------------------------
def test_stock_conversion_produces_acquirer_position(con):
    pf = _book(con)
    _dead_name(con, "TALK")
    insert_bars(con, "ACQ", [D1, D2, D3, D4, D5], close=50.0)
    _fill(con, pf, "TALK", "buy", 10, 200.0, D1, 1)
    cash0 = portfolio.get_cash(con, pf)
    settle.settle(con, _terms(ticker="TALK", kind="stock", price=0.0,
                              into_ticker="ACQ", ratio=4.0), apply=True)
    cash, pos = _state(con, pf)
    assert cash == cash0                                  # pure swap, no cash leg
    assert "TALK" not in pos
    assert pos["ACQ"]["qty"] == pytest.approx(40.0)
    assert pos["ACQ"]["avg_cost"] == pytest.approx(50.0)  # 200 / 4: basis carried
    live = _state(con, pf)
    portfolio.rebuild_state(con)
    assert _state(con, pf) == live


def test_stock_conversion_merges_into_existing_acquirer_lot(con):
    pf = _book(con)
    _dead_name(con, "TALK")
    insert_bars(con, "ACQ", [D1, D2, D3, D4, D5], close=50.0)
    _fill(con, pf, "TALK", "buy", 10, 200.0, D1, 1)
    _fill(con, pf, "ACQ", "buy", 40, 60.0, D1, 2)
    settle.settle(con, _terms(ticker="TALK", kind="stock", price=1.0,   # $1/sh cash leg
                              into_ticker="ACQ", ratio=4.0), apply=True)
    pos = portfolio.get_positions(con, pf)
    assert pos["ACQ"]["qty"] == pytest.approx(80.0)
    assert pos["ACQ"]["avg_cost"] == pytest.approx((40 * 60 + 40 * 50) / 80)
    assert portfolio.get_cash(con, pf) == pytest.approx(INITIAL_CASH - 2000 - 2400 + 10)


# CLI ---------------------------------------------------------------------------
def test_cli_dry_run_is_read_only_and_apply_writes(tmp_path, capsys):
    import duckdb

    from sim.schema import init_sim_schema
    from tests.conftest import PRICES_DDL
    path = str(tmp_path / "t.duckdb")
    c = duckdb.connect(path)
    c.execute(PRICES_DDL)
    init_sim_schema(c)
    pf = _book(c)
    _dead_name(c)
    _fill(c, pf, "EA", "buy", 10, 200.0, D1, 1)
    c.close()
    argv = ["--db", path, "--ticker", "EA", "--kind", "cash", "--price", "209.70",
            "--effective", D3.isoformat(), "--source", SRC]
    assert settle.main(argv) == 0
    assert "DRY RUN" in capsys.readouterr().out
    c = duckdb.connect(path, read_only=True)
    assert not table_exists(c, "sim_settlements")
    c.close()
    assert settle.main(argv + ["--apply"]) == 0
    assert "APPLIED" in capsys.readouterr().out
    c = duckdb.connect(path, read_only=True)
    assert c.execute("SELECT qty FROM sim_settlements").fetchone()[0] == 10.0
    assert c.execute("SELECT cash FROM portfolios").fetchone()[0] == pytest.approx(
        INITIAL_CASH - 2000 + 2097)
    c.close()
    assert settle.main(argv + ["--apply"]) == 2           # nothing left to settle
    assert "REFUSED" in capsys.readouterr().out
