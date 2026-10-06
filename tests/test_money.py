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


def _spec(account_id: str, *, gross=1.0):
    return {
        "schema_version": 2, "strategy_ref": f"strategy-{account_id}",
        "strategy_version": "v1", "spec_sha256": "a" * 64,
        "artifact_sha256": "b" * 64, "registration_sha256": "c" * 64,
        "instrument_kinds": ["stock"], "capital_usd": 10_000,
        "account_id": account_id, "account_type": "margin",
        "max_position_fraction": gross, "max_gross_fraction": gross,
        "min_trade_usd": 1.0, "allow_short": True, "price_source": "prices",
        "benchmark": "SPY", "day_trades_per_week_expected": 3,
        "day_trade_rule": "pdt_25k_legacy",
    }


def _account(con, account_id: str, *, gross=1.0):
    service.create(con, _spec(account_id, gross=gross), now=NOW)
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
        "SELECT resumed_by,peak_equity FROM account_state WHERE portfolio_id='acct-a'"
    ).fetchone() == ("owner", 10_000.0)


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
