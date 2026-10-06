"""Account money-layer limits, halts, and alerts."""
from datetime import date, datetime, timezone

import pytest

from engine.accounts import service
from engine.money import alerts, halts
from engine.money.allocation import AllocationRefused, require_total_capacity
from sim import schema as sim_schema
from tests.conftest import insert_bars

NOW = datetime(2026, 10, 5, 13, 27, tzinfo=timezone.utc)
SESSION = date(2026, 10, 2)


def _spec(account_id: str, *, gross=1.0, price_source="prices"):
    return {
        "schema_version": 2, "strategy_ref": f"strategy-{account_id}",
        "strategy_version": "v1", "spec_sha256": "a" * 64,
        "artifact_sha256": "b" * 64, "registration_sha256": "c" * 64,
        "instrument_kinds": ["stock"], "capital_usd": 10_000,
        "account_id": account_id, "account_type": "margin",
        "max_position_fraction": gross, "max_gross_fraction": gross,
        "min_trade_usd": 1.0, "allow_short": True, "price_source": price_source,
        "benchmark": "SPY", "day_trades_per_week_expected": 3,
        "day_trade_rule": "pdt_25k_legacy",
    }


def _account(con, account_id: str, *, gross=1.0, price_source="prices"):
    service.create(con, _spec(account_id, gross=gross, price_source=price_source), now=NOW)
    con.execute("UPDATE portfolios SET active=TRUE WHERE id=?", [account_id])
    sim_schema.set_portfolio_account(
        con, account_id, status="active", updated_at=NOW,
    )


def _pending(con, account_id: str, order_id: int):
    con.execute(
        "INSERT INTO sim_orders VALUES (?,?,'XYZ','buy',1,?,'pending',NULL)",
        [order_id, account_id, SESSION],
    )
    con.execute(
        "INSERT INTO sim_order_details "
        "(order_id,instrument_id,instrument_kind,order_type,side,tif,session_date,"
        "received_at,state,state_at) VALUES (?,'XYZ','stock','moo','buy','day',?,?,"
        "'queued',?)", [order_id, SESSION, NOW, NOW],
    )


@pytest.mark.parametrize(("equity", "reason"), [
    (8_000.0, "halt_drawdown"),
    (9_500.0, "halt_daily_loss"),
])
def test_loss_halt_is_structured_once_and_cancels_queued_orders(con, equity, reason):
    _account(con, "acct-a")
    _pending(con, "acct-a", 101)
    con.execute("INSERT INTO sim_equity VALUES ('acct-a',?, ?, ?, 0)",
                [SESSION, equity, equity])
    assert halts.check(con, "acct-a", SESSION, now=NOW) == reason
    assert halts.check(con, "acct-a", SESSION, now=NOW) is None
    assert sim_schema.portfolio_account(con, "acct-a")["status"] == "halted"
    assert con.execute("SELECT status,reject_reason FROM sim_orders").fetchone() == (
        "cancelled", reason,
    )
    assert con.execute("SELECT kind FROM account_events").fetchall() == [(reason,)]


def test_reconciliation_mismatch_halts_and_resume_records_actor(con):
    _account(con, "acct-a")
    mismatch = {
        "session_date": SESSION.isoformat(), "expected_sha256": "d" * 64,
        "observed_sha256": "e" * 64, "status": "mismatch", "detail": "fee differs",
    }
    receipt = service.reconcile(con, "acct-a", mismatch, now=NOW)
    assert receipt["status"] == "mismatch"
    assert con.execute("SELECT kind FROM account_events").fetchall() == [
        ("halt_reconciliation",),
    ]
    resumed = service.resume(con, "acct-a", resumed_by="owner", note="checked", now=NOW)
    assert resumed["status"] == "active"
    assert con.execute(
        "SELECT resumed_by,peak_equity,drawdown_anchor_equity FROM account_state "
        "WHERE portfolio_id='acct-a'"
    ).fetchone() == ("owner", 10_000.0, None)


def test_resolved_reconciliation_does_not_rehalt_after_resume(con):
    _account(con, "acct-a")
    con.execute("INSERT INTO sim_equity VALUES ('acct-a',DATE '2026-10-02',10000,10000,0)")
    mismatch = {"session_date": "2026-10-02", "expected_sha256": "d" * 64,
                "observed_sha256": "e" * 64, "status": "mismatch", "detail": "old"}
    service.reconcile(con, "acct-a", mismatch, now=NOW)
    service.resume(con, "acct-a", resumed_by="owner", now=NOW)
    resolved_at = datetime(2026, 10, 6, 20, tzinfo=timezone.utc)
    service.reconcile(
        con, "acct-a",
        {**mismatch, "session_date": "2026-10-06", "observed_sha256": "d" * 64,
         "status": "ok", "detail": "matched"},
        now=resolved_at,
    )
    con.execute("INSERT INTO sim_equity VALUES ('acct-a',DATE '2026-10-06',10000,10000,0)")
    assert halts.check(con, "acct-a", date(2026, 10, 6), now=resolved_at) is None
    assert con.execute("SELECT COUNT(*) FROM account_events WHERE kind='halt_reconciliation'") \
        .fetchone()[0] == 1


def test_resume_rearms_drawdown_from_resume_equity(con):
    _account(con, "acct-a")
    con.execute("INSERT INTO sim_equity VALUES ('acct-a',DATE '2026-10-02',8000,8000,0)")
    assert halts.check(con, "acct-a", date(2026, 10, 2), now=NOW) == "halt_drawdown"
    service.resume(con, "acct-a", resumed_by="owner", now=NOW)
    con.execute("INSERT INTO sim_equity VALUES ('acct-a',DATE '2026-10-05',6500,6500,0)")
    con.execute("INSERT INTO sim_equity VALUES ('acct-a',DATE '2026-10-06',6400,6400,0)")
    later = datetime(2026, 10, 6, 20, tzinfo=timezone.utc)
    assert halts.check(con, "acct-a", date(2026, 10, 6), now=later) == "halt_drawdown"
    assert con.execute(
        "SELECT peak_equity,drawdown_anchor_equity FROM account_state WHERE portfolio_id='acct-a'"
    ).fetchone() == (10_000.0, 8_000.0)


def test_reconciliation_resume_keeps_all_time_drawdown_armed(con):
    _account(con, "acct-a")
    con.execute("INSERT INTO sim_equity VALUES ('acct-a',DATE '2026-10-02',8550,8550,0)")
    mismatch = {"session_date": "2026-10-02", "expected_sha256": "d" * 64,
                "observed_sha256": "e" * 64, "status": "mismatch", "detail": "old"}
    service.reconcile(con, "acct-a", mismatch, now=NOW)
    service.resume(con, "acct-a", resumed_by="owner", now=NOW)
    assert con.execute(
        "SELECT drawdown_anchor_equity FROM account_state WHERE portfolio_id='acct-a'"
    ).fetchone()[0] is None
    con.execute("INSERT INTO sim_equity VALUES ('acct-a',DATE '2026-10-06',7950,7950,0)")
    later = datetime(2026, 10, 6, 20, tzinfo=timezone.utc)
    assert halts.check(con, "acct-a", date(2026, 10, 6), now=later) == "halt_drawdown"


def test_total_account_exposure_cap_refuses_increment(con):
    insert_bars(con, "XYZ", [SESSION], open_=100, close=100)
    _account(con, "acct-a", gross=1.5)
    _account(con, "acct-b", gross=1.5)
    con.execute("INSERT INTO sim_positions VALUES ('acct-a','XYZ',150,100)")
    with pytest.raises(AllocationRefused, match="total_exposure_cap"):
        require_total_capacity(con, "acct-b", 5_001, SESSION)
    require_total_capacity(con, "acct-b", 5_000, SESSION)


def test_three_accounts_create_one_concentration_alert_each(con):
    dates = [date(2026, 7, 10), SESSION]
    insert_bars(con, "XYZ", dates, open_=100, close=100, volume=1_000_000)
    for account_id in ("acct-a", "acct-b", "acct-c"):
        _account(con, account_id)
        con.execute("INSERT INTO sim_positions VALUES (?, 'XYZ', 1, 100)", [account_id])
    created = alerts.concentration(con, SESSION, now=NOW)
    assert len(created) == 3
    assert alerts.concentration(con, SESSION, now=NOW) == []
    assert con.execute(
        "SELECT portfolio_id,kind FROM account_events ORDER BY portfolio_id"
    ).fetchall() == [("acct-a", "alert"), ("acct-b", "alert"), ("acct-c", "alert")]


def test_allocation_and_alerts_honor_massive_source_without_prices(con):
    con.execute("CREATE TABLE free_daily_bars (ticker VARCHAR,date DATE,c DOUBLE,"
                "volume DOUBLE,vwap DOUBLE)")
    con.execute("INSERT INTO free_daily_bars VALUES ('ONLY',?,100,1000000,100)", [SESSION])
    for account_id in ("acct-a", "acct-b", "acct-c"):
        _account(con, account_id, price_source="massive_daily")
        con.execute("INSERT INTO sim_positions VALUES (?, 'ONLY', 1, 100)", [account_id])
    require_total_capacity(con, "acct-a", 100, SESSION)
    assert len(alerts.concentration(con, SESSION, now=NOW)) == 3


def test_manual_halt_does_not_activate_never_traded_account(con):
    service.create(con, _spec("acct-a"), now=NOW)
    assert service.halt(con, "acct-a", now=NOW)["status"] == "halted"
    assert con.execute("SELECT active FROM portfolios WHERE id='acct-a'").fetchone()[0] is False
