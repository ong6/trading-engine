"""Transactional lifecycle tests for the paper-account service."""
import sys
from datetime import date, datetime, timezone
from types import ModuleType

import pytest

from engine import paper_accounts
from engine.accounts import cli, service
from sim import schema as sim_schema

NOW = datetime(2026, 10, 5, 13, 27, tzinfo=timezone.utc)


def _spec(account_id="acct-a"):
    return {
        "schema_version": 2, "strategy_ref": "strategy-a", "strategy_version": "v1",
        "spec_sha256": "a" * 64, "artifact_sha256": "b" * 64,
        "registration_sha256": "c" * 64, "instrument_kinds": ["stock"],
        "capital_usd": 10_000, "account_id": account_id, "account_type": "margin",
        "max_position_fraction": 1.0, "max_gross_fraction": 1.0, "min_trade_usd": 1.0,
        "allow_short": True, "price_source": "prices", "benchmark": "SPY",
        "day_trades_per_week_expected": 3, "day_trade_rule": "pdt_25k_legacy",
    }


def _active_account(con, account_id="acct-a"):
    service.create(con, _spec(account_id), now=NOW)
    con.execute("UPDATE portfolios SET active=TRUE WHERE id=?", [account_id])
    sim_schema.set_portfolio_account(con, account_id, status="active", updated_at=NOW)


def test_cancel_requires_queued_order_before_auction(con):
    _active_account(con)
    con.execute("INSERT INTO sim_orders VALUES (1,'acct-a','XYZ','buy',1,DATE '2026-10-05',"
                "'pending',NULL)")
    con.execute("INSERT INTO sim_order_details "
                "(order_id,instrument_id,instrument_kind,order_type,side,tif,session_date,"
                "received_at,state,state_at) VALUES "
                "(1,'XYZ','stock','moo','buy','day',DATE '2026-10-05',?,'queued',?)",
                [NOW, NOW])
    result = service.cancel(con, "acct-a", 1, now=NOW)
    assert result["state"] == "cancelled"
    assert service.cancel(con, "acct-a", 1, now=NOW)["replayed"] is True


def test_halted_account_keeps_positions_and_manual_halt_is_idempotent(con):
    _active_account(con)
    con.execute("INSERT INTO sim_positions VALUES ('acct-a','XYZ',4,100)")
    assert service.halt(con, "acct-a", note="operator", now=NOW)["replayed"] is False
    assert service.halt(con, "acct-a", note="operator", now=NOW)["replayed"] is True
    assert con.execute("SELECT qty FROM sim_positions").fetchone()[0] == 4
    assert con.execute("SELECT COUNT(*) FROM account_events").fetchone()[0] == 1


def test_retire_queues_moc_closes_and_deactivates(con):
    _active_account(con)
    con.execute("INSERT INTO sim_positions VALUES ('acct-a','LONG',4,100)")
    con.execute("INSERT INTO sim_positions VALUES ('acct-a','SHORT',-2,100)")
    con.execute("INSERT INTO sim_orders VALUES (99,'acct-a','NEW','buy',1,DATE '2026-10-05',"
                "'pending',NULL)")
    con.execute("INSERT INTO sim_order_details "
                "(order_id,instrument_id,instrument_kind,order_type,side,tif,session_date,"
                "received_at,state,state_at) VALUES "
                "(99,'NEW','stock','moo','buy','day',DATE '2026-10-05',?,'queued',?)",
                [NOW, NOW])
    result = service.retire(con, "acct-a", now=NOW)
    assert len(result["queued_order_ids"]) == 2
    assert con.execute("SELECT active FROM portfolios WHERE id='acct-a'").fetchone()[0] is False
    assert sim_schema.portfolio_account(con, "acct-a")["status"] == "retired"
    assert con.execute(
        "SELECT o.ticker,o.side,o.qty,d.order_type FROM sim_orders o JOIN sim_order_details d "
        "ON o.id=d.order_id WHERE o.status='pending' ORDER BY o.ticker"
    ).fetchall() == [("LONG", "sell", 4, "moc"), ("SHORT", "cover", 2, "moc")]
    assert con.execute("SELECT status,reject_reason FROM sim_orders WHERE id=99").fetchone() == (
        "cancelled", "retired",
    )


def test_watch_replacement_is_bounded_and_sorted(con):
    _active_account(con)
    assert service.replace_watch(con, "acct-a", ["xyz", "ABC", "XYZ"], now=NOW) == {
        "account_id": "acct-a", "tickers": ["ABC", "XYZ"],
    }
    with pytest.raises(paper_accounts.AccountRefused, match="500"):
        service.replace_watch(con, "acct-a", [f"X{index}" for index in range(501)], now=NOW)


def test_account_list_only_reveals_private_when_requested(con):
    service.create(con, _spec(), now=NOW)
    assert service.account_list(con) == []
    assert service.account_list(con, include_private=True) == [{
        "id": "acct-a", "status": "inactive", "tier": 10_000,
        "engine": "account", "visibility": "private",
    }]


def test_cancel_after_window_opens_is_refused(con):
    _active_account(con)
    con.execute("INSERT INTO sim_orders VALUES (1,'acct-a','XYZ','buy',1,DATE '2026-10-05',"
                "'pending',NULL)")
    con.execute("INSERT INTO sim_order_details "
                "(order_id,instrument_id,instrument_kind,order_type,side,tif,session_date,"
                "received_at,state,state_at) VALUES "
                "(1,'XYZ','stock','moo','buy','day',DATE '2026-10-05',?,'queued',?)",
                [NOW, NOW])
    opened = datetime(2026, 10, 5, 13, 30, tzinfo=timezone.utc)
    with pytest.raises(paper_accounts.AccountRefused, match="window"):
        service.cancel(con, "acct-a", 1, now=opened)


@pytest.mark.parametrize(("order_type", "received_at", "allowed_at", "refused_at"), [
    ("market", datetime(2026, 10, 5, 14, 17, tzinfo=timezone.utc),
     datetime(2026, 10, 5, 14, 18, tzinfo=timezone.utc),
     datetime(2026, 10, 5, 14, 18, 1, tzinfo=timezone.utc)),
    ("limit", datetime(2026, 10, 5, 13, 0, tzinfo=timezone.utc),
     datetime(2026, 10, 5, 13, 30, tzinfo=timezone.utc),
     datetime(2026, 10, 5, 13, 30, 1, tzinfo=timezone.utc)),
    ("moc", datetime(2026, 11, 27, 17, 0, tzinfo=timezone.utc),
     datetime(2026, 11, 27, 17, 50, tzinfo=timezone.utc),
     datetime(2026, 11, 27, 17, 50, 1, tzinfo=timezone.utc)),
])
def test_cancel_uses_each_order_receipt_window(
    con, order_type, received_at, allowed_at, refused_at,
):
    _active_account(con)
    session = date(2026, 11, 27) if order_type == "moc" else date(2026, 10, 5)
    for order_id in (1, 2):
        con.execute("INSERT INTO sim_orders VALUES (?,?,'XYZ','buy',1,?,'pending',NULL)",
                    [order_id, "acct-a", session])
        con.execute(
            "INSERT INTO sim_order_details "
            "(order_id,instrument_id,instrument_kind,order_type,side,tif,session_date,"
            "received_at,state,state_at) VALUES (?,'XYZ','stock',?,'buy','day',?,?,"
            "'queued',?)", [order_id, order_type, session, received_at, received_at],
        )
    assert service.cancel(con, "acct-a", 1, now=allowed_at)["state"] == "cancelled"
    with pytest.raises(paper_accounts.AccountRefused, match="window"):
        service.cancel(con, "acct-a", 2, now=refused_at)


def test_reconciliation_replay_cannot_change_evidence(con):
    _active_account(con)
    body = {"session_date": date(2026, 10, 2).isoformat(), "expected_sha256": "d" * 64,
            "observed_sha256": "d" * 64, "status": "ok", "detail": "matched"}
    assert service.reconcile(con, "acct-a", body, now=NOW)["replayed"] is False
    assert service.reconcile(con, "acct-a", body, now=NOW)["replayed"] is True
    with pytest.raises(paper_accounts.AccountRefused, match="different evidence"):
        service.reconcile(con, "acct-a", {**body, "detail": "changed"}, now=NOW)


def test_verify_rebuilds_without_mutating_the_account(con):
    _active_account(con)
    assert service.verify(con, "acct-a")["status"] == "ok"
    con.execute("UPDATE portfolios SET cash=9999 WHERE id='acct-a'")
    assert service.verify(con, "acct-a")["status"] == "mismatch"
    assert con.execute("SELECT cash FROM portfolios WHERE id='acct-a'").fetchone()[0] == 9999


def test_settle_cli_wiring_lazily_calls_l1(monkeypatch, con):
    stub = ModuleType("engine.accounts.settle")
    calls = []
    stub.settle_session = lambda connection, session_date, *, late: (
        calls.append((connection, session_date, late)) or {"settled": 2}
    )
    monkeypatch.setitem(sys.modules, "engine.accounts.settle", stub)
    session_date = date(2026, 10, 5)
    assert cli._settle(con, session_date=session_date, late=True) == {"settled": 2}
    assert calls == [(con, session_date, True)]
