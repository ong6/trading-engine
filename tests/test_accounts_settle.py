"""Account session settlement across fills, fees, controls and late bars."""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from engine.accounts.settle import settle_session
from sim import costs, ledger, shorts
from sim.schema import next_order_id, set_portfolio_account
from tests.conftest import insert_bars

DAY = date(2026, 10, 12)
PRIOR = date(2026, 10, 9)
NEW_YORK = ZoneInfo("America/New_York")
SETTLED_AT = datetime(2026, 10, 13, 8, tzinfo=timezone.utc)


def _account(
    con, account_id, *, capital=50_000, rule="pdt_25k_legacy", allow_short=True,
    account_type="margin",
):
    con.execute(
        "INSERT INTO portfolios "
        "(id,name,strategy,config,created,active,cash,initial_cash,execution_profile) "
        "VALUES (?,?, 'none','{}',?,TRUE,?,?, 'baseline_v1')",
        [account_id, account_id, PRIOR, capital, capital],
    )
    set_portfolio_account(
        con,
        account_id,
        engine="account",
        cost_profile="ibkr_pro_tiered_v1",
        account_type=account_type,
        visibility="private",
        status="active",
        price_source="prices",
        day_trade_rule=rule,
        allow_short=allow_short,
        updated_at=datetime(2026, 10, 9, 20),
    )


def _order(
    con,
    account_id,
    ticker,
    side,
    qty,
    order_type,
    received,
    *,
    signal_date=DAY,
    limit_px=None,
    contingent_on=None,
    instrument_kind="stock",
    parent_order_id=None,
):
    order_id = next_order_id(con)
    con.execute(
        "INSERT INTO sim_orders VALUES (?,?,?,?,?,?,'pending',NULL)",
        [order_id, account_id, ticker, side, qty, signal_date],
    )
    con.execute(
        "INSERT INTO sim_order_details "
        "(order_id,instrument_id,instrument_kind,order_type,side,tif,limit_px,"
        "session_date,received_at,parent_order_id,contingent_on,state,state_at) "
        "VALUES (?,?,?,?,?,'day',?,?,?,?,?,'queued',?)",
        [order_id, ticker, instrument_kind, order_type, side, limit_px, signal_date,
         received, parent_order_id, contingent_on, received],
    )
    return order_id


def _daily(con, ticker, *, open_=100, close=100, mdv=100_000_000):
    history = [date(2026, 10, value) for value in (5, 6, 7, 8, 9)]
    insert_bars(con, ticker, history, open_=100, close=100, volume=mdv / 100)
    insert_bars(con, ticker, [DAY], open_=open_, close=close, volume=mdv / 100)
    con.execute(
        "UPDATE prices SET fetched_at='2026-10-12 21:00:00' WHERE ticker=?",
        [ticker],
    )


def _settle(con, day=DAY, **kwargs):
    kwargs.setdefault("settled_at", SETTLED_AT)
    return settle_session(con, day, **kwargs)


def _minute_table(con):
    con.execute(
        "CREATE TABLE IF NOT EXISTS intraday_prices (ticker VARCHAR,ts TIMESTAMP,"
        "interval VARCHAR,open DOUBLE,high DOUBLE,low DOUBLE,close DOUBLE,volume BIGINT,"
        "source VARCHAR,as_of DATE,PRIMARY KEY(ticker,ts,interval))"
    )


def test_every_fill_kind_charges_fee_and_cash(con):
    _account(con, "moo")
    _account(con, "moc")
    _account(con, "market")
    _account(con, "limit")
    for ticker in ("AAA", "BBB", "CCC", "DDD"):
        _daily(con, ticker)
    _minute_table(con)
    con.executemany(
        "INSERT INTO intraday_prices VALUES "
        "(?,'2026-10-12 14:18:00','1m',100,101,98,100,1000,'fixture',?)",
        [("CCC", DAY), ("DDD", DAY)],
    )
    moo = _order(con, "moo", "AAA", "buy", 2.5, "moo",
                 datetime(2026, 10, 12, 9, 27, tzinfo=NEW_YORK))
    ledger.apply_fill(con, {
        "order_id": 90, "portfolio_id": "moc", "ticker": "BBB", "side": "buy",
        "qty": 2.5, "fill_px": 100, "fill_date": PRIOR,
    })
    moc = _order(con, "moc", "BBB", "sell", 2.5, "moc",
                 datetime(2026, 10, 12, 15, 49, tzinfo=NEW_YORK))
    market = _order(con, "market", "CCC", "buy", 2.5, "market",
                    datetime(2026, 10, 12, 10, 17, tzinfo=NEW_YORK))
    limit = _order(con, "limit", "DDD", "buy", 2.5, "limit",
                   datetime(2026, 10, 12, 10, 17, tzinfo=NEW_YORK), limit_px=99)
    cash_before = {
        account: con.execute("SELECT cash FROM portfolios WHERE id=?", [account]).fetchone()[0]
        for account in ("moo", "moc", "market", "limit")
    }

    result = _settle(con)

    assert result["filled"] == 4
    assert con.execute(
        "SELECT order_id,fill_kind FROM sim_fill_details ORDER BY order_id"
    ).fetchall() == [
        (moo, "open_auction"), (moc, "close_auction"),
        (market, "intraday_bar"), (limit, "limit_touch"),
    ]
    fees = dict(con.execute(
        "SELECT order_id,total_usd FROM sim_fill_fees ORDER BY order_id"
    ).fetchall())
    assert all(fees[order_id] > 0 for order_id in (moo, moc, market, limit))
    assert con.execute("SELECT cash FROM portfolios WHERE id='moo'").fetchone()[0] == (
        pytest.approx(cash_before["moo"] - 2.5 * con.execute(
            "SELECT fill_px FROM sim_fills WHERE order_id=?", [moo]
        ).fetchone()[0] - fees[moo])
    )


def test_aggregate_liquidity_includes_league_fill_and_receipt_order(con):
    _account(con, "acct-a")
    _account(con, "acct-b")
    _daily(con, "XYZ", mdv=100_000)
    con.execute(
        "INSERT INTO sim_fills VALUES (900,'league','XYZ','buy',4,?,100,100,0,0)",
        [DAY],
    )
    first = _order(con, "acct-a", "XYZ", "buy", 3, "moo",
                   datetime(2026, 10, 12, 9, 27, 1, tzinfo=NEW_YORK))
    second = _order(con, "acct-b", "XYZ", "buy", 4, "moo",
                    datetime(2026, 10, 12, 9, 27, 2, tzinfo=NEW_YORK))

    result = _settle(con)

    assert result["filled"] == 1
    assert result["rejected"] == 1
    assert con.execute("SELECT status FROM sim_orders WHERE id=?", [first]).fetchone() == (
        "filled",
    )
    assert con.execute(
        "SELECT status,reject_reason FROM sim_orders WHERE id=?", [second]
    ).fetchone() == ("rejected", "illiquid_aggregate")


def test_aggregate_liquidity_combines_buy_with_cover_direction(con):
    _account(con, "acct-a")
    _daily(con, "XYZ", mdv=100_000)
    con.execute(
        "INSERT INTO sim_fills VALUES (900,'league','XYZ','buy',4,?,100,100,0,0)",
        [DAY],
    )
    ledger.apply_fill(con, {
        "order_id": 90, "portfolio_id": "acct-a", "ticker": "XYZ", "side": "short",
        "qty": 7, "fill_px": 100, "fill_date": PRIOR,
    })
    cover = _order(
        con, "acct-a", "XYZ", "cover", 7, "moc",
        datetime(2026, 10, 12, 15, 49, tzinfo=NEW_YORK),
    )
    _settle(con)
    assert con.execute(
        "SELECT status,reject_reason FROM sim_orders WHERE id=?", [cover]
    ).fetchone() == ("rejected", "illiquid_aggregate")


def test_contingent_moc_uses_exact_fractional_moo_quantity(con):
    _account(con, "acct-a")
    _daily(con, "XYZ", open_=100, close=105)
    moo = _order(con, "acct-a", "XYZ", "buy", 7.25, "moo",
                 datetime(2026, 10, 12, 9, 27, tzinfo=NEW_YORK))
    moc = _order(con, "acct-a", "XYZ", "sell", 999, "moc",
                 datetime(2026, 10, 12, 9, 27, 1, tzinfo=NEW_YORK),
                 contingent_on=moo)

    result = _settle(con)

    assert result["filled"] == 2
    assert con.execute(
        "SELECT order_id,qty FROM sim_fills ORDER BY order_id"
    ).fetchall() == [(moo, 7.25), (moc, 7.25)]
    assert con.execute(
        "SELECT qty FROM sim_positions WHERE portfolio_id='acct-a' AND ticker='XYZ'"
    ).fetchone() == (0.0,)


def test_contingent_child_keeps_its_received_at_position(con):
    _account(con, "acct-a", capital=10_000)
    _daily(con, "XYZ")
    parent = _order(
        con, "acct-a", "XYZ", "buy", 60, "moo",
        datetime(2026, 10, 12, 9, 27, tzinfo=NEW_YORK),
    )
    child = _order(
        con, "acct-a", "XYZ", "sell", 999, "moc",
        datetime(2026, 10, 12, 9, 27, 1, tzinfo=NEW_YORK),
        contingent_on=parent,
    )
    later = _order(
        con, "acct-a", "XYZ", "buy", 60, "moo",
        datetime(2026, 10, 12, 9, 27, 2, tzinfo=NEW_YORK),
    )
    result = _settle(con)
    assert result["filled"] == 3
    assert con.execute(
        "SELECT id,status FROM sim_orders WHERE id IN (?,?,?) ORDER BY id",
        [parent, child, later],
    ).fetchall() == [(parent, "filled"), (child, "filled"), (later, "filled")]


def test_contingent_moc_does_nothing_when_moo_is_refused(con):
    _account(con, "acct-a")
    _daily(con, "XYZ")
    moo = _order(con, "acct-a", "XYZ", "buy", 7.25, "moo",
                 datetime(2026, 10, 12, 9, 28, 1, tzinfo=NEW_YORK))
    moc = _order(con, "acct-a", "XYZ", "sell", 7.25, "moc",
                 datetime(2026, 10, 12, 9, 28, 2, tzinfo=NEW_YORK),
                 contingent_on=moo)

    _settle(con)

    assert con.execute("SELECT COUNT(*) FROM sim_fills").fetchone() == (0,)
    assert con.execute(
        "SELECT id,reject_reason FROM sim_orders ORDER BY id"
    ).fetchall() == [(moo, "cutoff"), (moc, "contingent_not_filled")]


@pytest.mark.parametrize(
    ("kind", "parent"), [("option", None), ("stock", 123)],
)
def test_unsupported_instrument_and_multileg_structure_are_refused(con, kind, parent):
    _account(con, "acct-a")
    _daily(con, "XYZ")
    order_id = _order(
        con, "acct-a", "XYZ", "buy", 1, "moo",
        datetime(2026, 10, 12, 9, 27, tzinfo=NEW_YORK),
        instrument_kind=kind, parent_order_id=parent,
    )
    _settle(con)
    assert con.execute(
        "SELECT reject_reason FROM sim_orders WHERE id=?", [order_id]
    ).fetchone() == ("instrument_not_executable",)


def test_short_in_threshold_name_is_refused_without_fill(con):
    _account(con, "acct-a", allow_short=True)
    _daily(con, "XYZ", open_=10, close=10, mdv=10_000_000)
    con.execute("CREATE TABLE universe (ticker VARCHAR,liquid BOOLEAN)")
    con.execute("INSERT INTO universe VALUES ('XYZ',TRUE)")
    con.execute(
        "CREATE TABLE regsho_threshold "
        "(ticker VARCHAR,session_date DATE,publication_date DATE)"
    )
    con.execute(
        "CREATE TABLE finra_short_interest "
        "(ticker VARCHAR,settlement_date DATE,days_to_cover DOUBLE,publication_date DATE)"
    )
    con.execute("INSERT INTO regsho_threshold VALUES ('XYZ',?,?)", [DAY, DAY])
    order_id = _order(con, "acct-a", "XYZ", "short", 10, "moo",
                      datetime(2026, 10, 12, 9, 27, tzinfo=NEW_YORK))
    _settle(con, short_con=con)
    assert con.execute(
        "SELECT status,reject_reason FROM sim_orders WHERE id=?", [order_id]
    ).fetchone() == ("rejected", "no_locate")
    assert con.execute("SELECT COUNT(*) FROM sim_fills").fetchone() == (0,)


def test_missing_short_data_rejects_short_but_other_order_and_mark_complete(con):
    _account(con, "short", allow_short=True)
    _account(con, "other")
    _daily(con, "XYZ", open_=10, close=10, mdv=10_000_000)
    short_order = _order(
        con, "short", "XYZ", "short", 10, "moo",
        datetime(2026, 10, 12, 9, 27, tzinfo=NEW_YORK),
    )
    other_order = _order(
        con, "other", "XYZ", "buy", 10, "moo",
        datetime(2026, 10, 12, 9, 27, 1, tzinfo=NEW_YORK),
    )
    con.execute("UPDATE sim_order_details SET state_reason='bar_missing'")
    con.execute(
        "CREATE TABLE account_events (id BIGINT PRIMARY KEY,portfolio_id VARCHAR,"
        "kind VARCHAR,payload VARCHAR,created_at TIMESTAMP)"
    )
    result = _settle(con, late=True)
    assert result["filled"] == result["rejected"] == 1
    assert con.execute(
        "SELECT status,reject_reason FROM sim_orders WHERE id=?", [short_order]
    ).fetchone() == ("rejected", "locate_unavailable")
    assert con.execute(
        "SELECT kind FROM account_events WHERE portfolio_id='short'"
    ).fetchone() == ("locate_unavailable",)
    assert con.execute(
        "SELECT status FROM sim_orders WHERE id=?", [other_order]
    ).fetchone() == ("filled",)
    assert con.execute(
        "SELECT equity FROM sim_equity WHERE portfolio_id='other' AND date=?", [DAY]
    ).fetchone() is not None


def test_stale_locate_is_recorded_for_results(con):
    _account(con, "acct-a", allow_short=True)
    _daily(con, "XYZ", open_=10, close=10, mdv=10_000_000)
    con.execute("CREATE TABLE universe (ticker VARCHAR,liquid BOOLEAN)")
    con.execute("INSERT INTO universe VALUES ('XYZ',TRUE)")
    con.execute(
        "CREATE TABLE regsho_threshold "
        "(ticker VARCHAR,session_date DATE,publication_date DATE)"
    )
    con.execute(
        "CREATE TABLE finra_short_interest "
        "(ticker VARCHAR,settlement_date DATE,days_to_cover DOUBLE,publication_date DATE)"
    )
    con.execute(
        "INSERT INTO finra_short_interest VALUES "
        "('XYZ','2026-09-01',1,'2026-09-01')"
    )
    con.execute(
        "CREATE TABLE account_events (id BIGINT PRIMARY KEY,portfolio_id VARCHAR,"
        "kind VARCHAR,payload VARCHAR,created_at TIMESTAMP)"
    )
    _order(con, "acct-a", "XYZ", "short", 10, "moo",
           datetime(2026, 10, 12, 9, 27, tzinfo=NEW_YORK))
    result = _settle(con, short_con=con)
    assert result["filled"] == 1
    assert con.execute(
        "SELECT kind FROM account_events WHERE portfolio_id='acct-a'"
    ).fetchone() == ("locate_data_stale",)


def test_threshold_buy_in_covers_next_open_with_penalty(con):
    _account(con, "acct-a", allow_short=True)
    _daily(con, "XYZ")
    next_day = date(2026, 10, 13)
    insert_bars(con, "XYZ", [next_day], open_=100, close=100, volume=1_000_000)
    con.execute(
        "UPDATE prices SET fetched_at='2026-10-13 21:00:00' "
        "WHERE ticker='XYZ' AND date=?",
        [next_day],
    )
    ledger.apply_fill(con, {
        "order_id": 90, "portfolio_id": "acct-a", "ticker": "XYZ", "side": "short",
        "qty": 2.5, "fill_px": 100, "fill_date": date(2026, 10, 5),
    })
    con.execute(
        "CREATE TABLE regsho_threshold "
        "(ticker VARCHAR,session_date DATE,publication_date DATE)"
    )
    con.executemany(
        "INSERT INTO regsho_threshold VALUES ('XYZ',?,?)",
        [(date(2026, 10, value), date(2026, 10, value))
         for value in (6, 7, 8, 9, 12)],
    )
    order_id, = shorts.queue_buy_ins(con, con, DAY)

    result = _settle(
        con, next_day,
        settled_at=datetime(2026, 10, 14, 8, tzinfo=timezone.utc),
    )

    assert result["filled"] == 1
    fill_px = con.execute(
        "SELECT fill_px FROM sim_fills WHERE order_id=?", [order_id]
    ).fetchone()[0]
    assert fill_px == pytest.approx(100 * (1 + 60 / 10_000))
    assert con.execute(
        "SELECT kind,amount,ref_order_id FROM sim_cash_events"
    ).fetchone() == ("buy_in_penalty", 0.0, order_id)
    assert con.execute(
        "SELECT qty FROM sim_positions WHERE portfolio_id='acct-a' AND ticker='XYZ'"
    ).fetchone() == (0.0,)


def test_r10_settings_diverge_on_fourth_moo_moc_day_trade(con):
    _account(con, "legacy", capital=10_000, rule="pdt_25k_legacy")
    _account(con, "current", capital=10_000, rule="intraday_margin_2026")
    _daily(con, "XYZ")
    for account in ("legacy", "current"):
        con.executemany(
            "INSERT INTO sim_day_trades VALUES (?,?,'OLD',?,?)",
            [
                (account, date(2026, 10, 7), 1, 11),
                (account, date(2026, 10, 8), 2, 12),
                (account, date(2026, 10, 9), 3, 13),
            ],
        )
    legacy_open = _order(
        con, "legacy", "XYZ", "buy", 1, "moo",
        datetime(2026, 10, 12, 9, 27, tzinfo=NEW_YORK),
    )
    legacy = _order(
        con, "legacy", "XYZ", "sell", 99, "moc",
        datetime(2026, 10, 12, 9, 27, 1, tzinfo=NEW_YORK),
        contingent_on=legacy_open,
    )
    current_open = _order(
        con, "current", "XYZ", "buy", 1, "moo",
        datetime(2026, 10, 12, 9, 27, 2, tzinfo=NEW_YORK),
    )
    current = _order(
        con, "current", "XYZ", "sell", 99, "moc",
        datetime(2026, 10, 12, 9, 27, 3, tzinfo=NEW_YORK),
        contingent_on=current_open,
    )

    _settle(con)

    assert con.execute(
        "SELECT status,reject_reason FROM sim_orders WHERE id=?", [legacy]
    ).fetchone() == ("rejected", "pdt_limit")
    assert con.execute(
        "SELECT status,reject_reason FROM sim_orders WHERE id=?", [current]
    ).fetchone() == ("filled", None)


def test_late_settle_fills_only_missing_bar_account_and_restates_its_equity(con):
    _account(con, "late")
    _account(con, "untouched")
    insert_bars(con, "XYZ", [PRIOR], open_=100, close=100, volume=1_000_000)
    order_id = _order(con, "late", "XYZ", "buy", 1.5, "moo",
                      datetime(2026, 10, 12, 9, 27, tzinfo=NEW_YORK))
    con.executemany(
        "INSERT INTO sim_equity VALUES (?,?,?,?,?)",
        [("late", DAY, 1, 1, 0), ("untouched", DAY, 12345, 12345, 0)],
    )
    first = _settle(con)
    assert first["pending"] == 1
    insert_bars(con, "XYZ", [DAY], open_=100, close=101, volume=1_000_000)
    con.execute(
        "UPDATE prices SET fetched_at='2026-10-13 07:00:00' "
        "WHERE ticker='XYZ' AND date=?",
        [DAY],
    )

    late = settle_session(
        con, DAY, late=True,
        settled_at=datetime(2026, 10, 13, 7, 45, tzinfo=ZoneInfo("UTC")),
    )

    assert late["late_settled"] == 1
    assert late["affected_accounts"] == ["late"]
    assert con.execute(
        "SELECT late_settled FROM sim_fill_details WHERE order_id=?", [order_id]
    ).fetchone() == (True,)
    assert con.execute(
        "SELECT equity FROM sim_equity WHERE portfolio_id='late' AND date=?", [DAY]
    ).fetchone()[0] != 1
    assert con.execute(
        "SELECT equity FROM sim_equity WHERE portfolio_id='untouched' AND date=?", [DAY]
    ).fetchone() == (12345.0,)


def test_late_moo_unblocks_and_fills_its_contingent_moc(con):
    _account(con, "late")
    insert_bars(con, "XYZ", [PRIOR], open_=100, close=100, volume=1_000_000)
    moo = _order(con, "late", "XYZ", "buy", 2.25, "moo",
                 datetime(2026, 10, 12, 9, 27, tzinfo=NEW_YORK))
    moc = _order(con, "late", "XYZ", "sell", 999, "moc",
                 datetime(2026, 10, 12, 9, 27, 1, tzinfo=NEW_YORK),
                 contingent_on=moo)
    first = _settle(con)
    assert first["pending"] == 2
    assert con.execute(
        "SELECT state_reason FROM sim_order_details WHERE order_id=?", [moc]
    ).fetchone() == ("bar_missing",)
    insert_bars(con, "XYZ", [DAY], open_=100, close=101, volume=1_000_000)
    con.execute(
        "UPDATE prices SET fetched_at='2026-10-13 07:00:00' "
        "WHERE ticker='XYZ' AND date=?",
        [DAY],
    )
    result = settle_session(
        con, DAY, late=True,
        settled_at=datetime(2026, 10, 13, 7, 45, tzinfo=timezone.utc),
    )
    assert result["filled"] == 2
    assert con.execute(
        "SELECT order_id,qty FROM sim_fills ORDER BY order_id"
    ).fetchall() == [(moo, 2.25), (moc, 2.25)]


def test_intraday_capture_outage_stays_pending_for_late_retries(con):
    _account(con, "late")
    _daily(con, "XYZ")
    _minute_table(con)
    order_id = _order(
        con, "late", "XYZ", "buy", 1, "market",
        datetime(2026, 10, 12, 10, 17, tzinfo=NEW_YORK),
    )
    first = _settle(con)
    assert first["pending"] == 1
    assert con.execute(
        "SELECT status FROM sim_orders WHERE id=?", [order_id]
    ).fetchone() == ("pending",)
    final = settle_session(
        con, DAY, late=True,
        settled_at=datetime(2026, 10, 15, 20, tzinfo=timezone.utc),
    )
    assert final["rejected"] == 1
    assert con.execute(
        "SELECT status,reject_reason FROM sim_orders WHERE id=?", [order_id]
    ).fetchone() == ("rejected", "no_bar")


def test_cash_clamp_charges_fee_for_applied_fractional_quantity(con):
    _account(con, "cash", capital=100, account_type="cash_legacy")
    _daily(con, "XYZ", open_=100, close=100)
    order_id = _order(
        con, "cash", "XYZ", "buy", 2, "moo",
        datetime(2026, 10, 12, 9, 27, tzinfo=NEW_YORK),
    )
    _settle(con)
    qty, price = con.execute(
        "SELECT qty,fill_px FROM sim_fills WHERE order_id=?", [order_id]
    ).fetchone()
    stored = con.execute(
        "SELECT total_usd FROM sim_fill_fees WHERE order_id=?", [order_id]
    ).fetchone()[0]
    expected = costs.charge(
        "ibkr_pro_tiered_v1", side="buy", qty=qty, price=price,
        fill_kind="open_auction", instrument={"kind": "stock", "multiplier": 1},
        session_date=DAY,
    )
    assert qty < 1
    assert stored == expected.total_usd


def test_fill_and_state_transition_roll_back_together(con, monkeypatch):
    _account(con, "acct-a")
    _daily(con, "XYZ")
    order_id = _order(
        con, "acct-a", "XYZ", "buy", 1, "moo",
        datetime(2026, 10, 12, 9, 27, tzinfo=NEW_YORK),
    )
    before = con.execute(
        "SELECT cash FROM portfolios WHERE id='acct-a'"
    ).fetchone()[0]
    from engine.accounts import settle as module

    original = module._state

    def fail_after_persist(*args, **kwargs):
        if args[2] == "filled":
            raise RuntimeError("planted transition failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "_state", fail_after_persist)
    with pytest.raises(RuntimeError, match="planted"):
        _settle(con)
    assert con.execute("SELECT COUNT(*) FROM sim_fills").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM sim_fill_fees").fetchone() == (0,)
    assert con.execute(
        "SELECT cash FROM portfolios WHERE id='acct-a'"
    ).fetchone() == (before,)
    assert con.execute("SELECT status FROM sim_orders WHERE id=?", [order_id]).fetchone() == (
        "pending",
    )
