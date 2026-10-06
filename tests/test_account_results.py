"""Deterministic account-result projection tests."""
import json
from datetime import date, datetime, timezone

import pytest

from engine.accounts import results, service
from tests.conftest import insert_bars

NOW = datetime(2026, 10, 2, 21, tzinfo=timezone.utc)


def _spec():
    return {
        "schema_version": 2, "strategy_ref": "strategy-a", "strategy_version": "v1",
        "spec_sha256": "a" * 64, "artifact_sha256": "b" * 64,
        "registration_sha256": "c" * 64, "instrument_kinds": ["stock"],
        "capital_usd": 10_000, "account_id": "acct-a", "account_type": "margin",
        "max_position_fraction": 1.0, "max_gross_fraction": 1.0, "min_trade_usd": 1.0,
        "allow_short": False, "price_source": "prices", "benchmark": "SPY",
        "day_trades_per_week_expected": 3, "day_trade_rule": "pdt_25k_legacy",
    }


def test_result_payload_and_sha_are_deterministic(con):
    first, second = date(2026, 10, 2), date(2026, 10, 5)
    insert_bars(con, "SPY", [first, second], open_=[100, 102], close=[100, 102])
    service.create(con, _spec(), now=NOW)
    con.execute("INSERT INTO sim_equity VALUES ('acct-a',?,10000,10000,0)", [first])
    con.execute("INSERT INTO sim_equity VALUES ('acct-a',?,10100,10100,0)", [second])
    con.execute("INSERT INTO sim_fills VALUES (1,'acct-a','XYZ','buy',10,?,100,101,100,100)",
                [first])
    con.execute("INSERT INTO sim_fills VALUES (2,'acct-a','XYZ','sell',10,?,103,102,100,100)",
                [second])
    con.execute(
        "INSERT INTO sim_fill_fees VALUES "
        "(1,'ibkr_pro_tiered_v1',.35,.015,.002,.000259,.00003,0,0,0,0,.37),"
        "(2,'ibkr_pro_tiered_v1',.35,.016,.002,.000259,.00003,.021,0,0,0,.39)"
    )
    con.execute(
        "INSERT INTO sim_fill_details "
        "(order_id,fill_ts,fill_kind,price_source,bar_ref,reference_px,multiplier,late_settled) "
        "VALUES (1,?,'open_auction','prices','first',100,1,FALSE),"
        "(2,?,'close_auction','prices','second',103,1,TRUE)",
        [NOW, NOW],
    )
    con.execute(
        "INSERT INTO sim_cash_events VALUES ('acct-a',?,1,'borrow_fee',-.25,'XYZ',NULL,NULL,?)",
        [second, NOW],
    )
    first_result = results.build(con, "acct-a")
    second_result = results.build(con, "acct-a")
    assert first_result == second_result
    assert json.dumps(first_result, sort_keys=True, separators=(",", ":")) == json.dumps(
        second_result, sort_keys=True, separators=(",", ":")
    )
    assert first_result["total_return"] == pytest.approx(0.01)
    assert first_result["fills"] == {"count": 2, "notional": 2030.0}
    assert first_result["costs_paid"]["total_usd"] == 0.76
    assert first_result["costs_paid"]["borrow"] == 0.25
    assert first_result["trade_stats"]["n"] == 1
    assert first_result["trade_stats"]["mean_net_bp"] == pytest.approx(
        (10.0 - 0.76) / 1010.0 * 10_000
    )
    assert first_result["late_settled_fills"] == 1
    assert len(first_result["sha256"]) == 64


def test_empty_account_result_is_stable_and_contains_all_money_signals(con):
    service.create(con, _spec(), now=NOW)
    payload = results.account_results(con, "acct-a")
    assert payload["as_of"] is None
    assert payload["equity_curve"] == []
    assert payload["total_return"] is None
    assert payload["halts"] == payload["alerts"] == payload["margin_calls"] == 0
    assert payload["reconciliation_status"] is None


def test_drawdown_is_seeded_with_initial_cash(con):
    service.create(con, _spec(), now=NOW)
    con.execute("INSERT INTO sim_equity VALUES ('acct-a',DATE '2026-10-02',8000,8000,0)")
    payload = results.build(con, "acct-a")
    assert payload["max_drawdown"] == pytest.approx(-0.20)
    assert payload["daily_loss_worst"] == pytest.approx(-0.20)
