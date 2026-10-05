"""Multiple external strategies share prices, never balances or execution state."""
from datetime import date, datetime, timezone

import pytest

from engine import paper_accounts as accounts
from sim import league, portfolio
from tests.conftest import insert_bars

NOW = datetime(2026, 10, 2, 21, tzinfo=timezone.utc)
SIGNAL = date(2026, 10, 2)
FILL = date(2026, 10, 5)


def _spec(name="a", capital=10000, **changes):
    return {"schema_version": 1, "strategy_ref": f"strategy-{name}", "spec_sha256": "a" * 64,
            "registration_sha256": "b" * 64, "instrument_kind": "stock", "capital_usd": capital,
            "account_id": name, "max_position_fraction": 0.5, "max_gross_fraction": 1.0,
            "min_trade_usd": 1.0, **changes}


def _intent(account="a", *, quantity=5, side="buy", **changes):
    return {"schema_version": 1, "intent_id": f"request-{account}-{side}", "account_id": account,
            "spec_sha256": "a" * 64, "registration_sha256": "b" * 64,
            "instrument_kind": "stock", "ticker": "SAME", "side": side, "quantity": quantity,
            "signal_date": SIGNAL.isoformat(), "created_at": NOW.isoformat(),
            "source_sha256": "c" * 64, **changes}


def test_three_tiers_hold_same_stock_with_independent_cash_fills_and_equity(con):
    insert_bars(con, "SAME", [SIGNAL], open_=100, close=100)
    tiers = {"small": (10000, 10), "medium": (50000, 20), "large": (100000, 30)}
    for account, (capital, quantity) in tiers.items():
        result = accounts.create_account(con, _spec(account, capital), now=NOW)
        assert not result["replayed"]
        assert not con.execute("SELECT active FROM portfolios WHERE id=?", [account]).fetchone()[0]
        request = _intent(account, quantity=quantity)
        first = accounts.submit_intent(con, request, now=NOW)
        assert accounts.submit_intent(con, request, now=NOW) == {**first, "replayed": True}
    insert_bars(con, "SAME", [FILL], open_=100, close=102)
    assert league.fill_pending(con, FILL)["filled"] == 3
    for account, (capital, quantity) in tiers.items():
        position = portfolio.get_positions(con, account)["SAME"]
        assert position["qty"] == quantity
        cash = portfolio.get_cash(con, account)
        fills = con.execute("SELECT qty,fill_px FROM sim_fills WHERE portfolio_id=?", [account]).fetchall()
        assert len(fills) == 1 and fills[0][0] == quantity
        assert cash == pytest.approx(capital - quantity * fills[0][1])
        equity = portfolio.mark_to_market(con, account, FILL)
        assert equity["equity"] == pytest.approx(cash + quantity * 102)
    balances = con.execute("SELECT id,cash FROM portfolios ORDER BY id").fetchall()
    portfolio.rebuild_state(con)
    assert con.execute("SELECT id,cash FROM portfolios ORDER BY id").fetchall() == balances
    accounts.create_account(con, _spec("small", 10000), now=NOW)
    assert con.execute("SELECT id,cash FROM portfolios ORDER BY id").fetchall() == balances


def test_twenty_five_accounts_cannot_sell_or_spend_each_others_assets(con):
    insert_bars(con, "SAME", [SIGNAL], open_=100, close=100)
    for index in range(25):
        accounts.create_account(con, _spec(f"account-{index}"), now=NOW)
    con.execute("INSERT INTO sim_positions VALUES ('account-0','SAME',50,100)")
    con.execute("UPDATE portfolios SET cash=5000 WHERE id='account-0'")
    with pytest.raises(accounts.AccountRefused, match="holdings"):
        accounts.submit_intent(con, _intent("account-1", side="sell"), now=NOW)
    with pytest.raises(accounts.AccountRefused, match="constraints"):
        accounts.submit_intent(con, _intent("account-1", quantity=51), now=NOW)
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone()[0] == 0
    assert con.execute("SELECT SUM(cash) FROM portfolios").fetchone()[0] == 245000
    assert portfolio.get_positions(con, "account-0")["SAME"]["qty"] == 50
    assert not portfolio.get_positions(con, "account-1")


@pytest.mark.parametrize("changes", [
    {"schema_version": True}, {"instrument_kind": "option"},
    {"instrument_kind": "future"}, {"capital_usd": 750},
    {"max_position_fraction": 2}, {"min_trade_usd": float("nan")},
])
def test_infeasible_or_unsupported_account_is_refused_before_mutation(con, changes):
    with pytest.raises(accounts.AccountRefused):
        accounts.create_account(con, _spec(**changes), now=NOW)
    assert con.execute("SELECT COUNT(*) FROM portfolios").fetchone()[0] == 0


@pytest.mark.parametrize("changes", [
    {"schema_version": True}, {"instrument_kind": "option"},
    {"spec_sha256": "d" * 64}, {"quantity": float("inf")},
    {"created_at": "2026-10-05T14:00:00+00:00"}, {"created_at": "2026-10-02T19:00:00+00:00"},
])
def test_invalid_intake_never_creates_an_order_or_activates(con, changes):
    insert_bars(con, "SAME", [SIGNAL], open_=100, close=100)
    accounts.create_account(con, _spec(), now=NOW)
    with pytest.raises((accounts.AccountRefused, ValueError)):
        accounts.submit_intent(con, _intent(**changes), now=NOW)
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone()[0] == 0
    assert con.execute("SELECT active,cash FROM portfolios WHERE id='a'").fetchone() == (False, 10000)


def test_late_replay_is_idempotent_but_new_late_request_cannot_retroactively_fill(con):
    insert_bars(con, "SAME", [SIGNAL], open_=100, close=100)
    accounts.create_account(con, _spec(), now=NOW)
    receipt = accounts.submit_intent(con, _intent(), now=NOW)
    late = datetime(2026, 10, 5, 14, tzinfo=timezone.utc)
    assert accounts.submit_intent(con, _intent(), now=late) == {**receipt, "replayed": True}
    with pytest.raises(accounts.AccountRefused, match="late"):
        accounts.submit_intent(con, _intent(intent_id="new-request"), now=late)
    with pytest.raises(accounts.AccountRefused, match="different evidence"):
        accounts.submit_intent(con, _intent(quantity=6), now=NOW)


def test_existing_account_cannot_be_refunded_or_rebound(con):
    accounts.create_account(con, _spec(), now=NOW)
    con.execute("UPDATE portfolios SET cash=123 WHERE id='a'")
    with pytest.raises(accounts.AccountRefused, match="different specification"):
        accounts.create_account(con, _spec(capital=50000), now=NOW)
    assert portfolio.get_cash(con, "a") == 123


def test_pure_intent_validation_uses_exchange_early_close():
    now = datetime(2026, 11, 27, 18, 15, tzinfo=timezone.utc)
    intent = _intent(signal_date="2026-11-27", created_at=now.isoformat())
    assert accounts.validate_intent(intent, _spec(), now)[0] == date(2026, 11, 27)


def test_replayed_receipt_must_still_match_its_order_and_spec(con):
    insert_bars(con, "SAME", [SIGNAL], open_=100, close=100)
    spec, intent = _spec(), _intent()
    accounts.create_account(con, spec, now=NOW)
    accounts.submit_intent(con, intent, now=NOW)
    con.execute("UPDATE sim_orders SET portfolio_id='different-account'")
    with pytest.raises(accounts.AccountRefused, match="engine order"):
        accounts.submit_intent(con, intent, now=NOW)
    con.execute("UPDATE portfolios SET initial_cash=50000 WHERE id='a'")
    with pytest.raises(accounts.AccountRefused, match="differs"):
        accounts.create_account(con, spec, now=NOW)


def test_bootstrap_intake_does_not_poison_nightly_completion(con, tmp_path):
    insert_bars(con, "SAME", [SIGNAL], open_=100, close=100)
    for account in ("a", "b", "c"):
        accounts.create_account(con, _spec(account), now=NOW)
        accounts.submit_intent(con, _intent(account), now=NOW)
    assert con.execute("SELECT COUNT(*) FROM sim_equity").fetchone()[0] == 0
    league.step(con, SIGNAL, tmp_path, False, False, True)
    assert con.execute("SELECT COUNT(*) FROM sim_equity WHERE date=?", [SIGNAL]).fetchone()[0] == 3
    insert_bars(con, "SAME", [FILL], open_=100, close=102)
    league.step(con, FILL, tmp_path, False, False, True)
    assert con.execute("SELECT portfolio_id,qty FROM sim_fills ORDER BY portfolio_id").fetchall() == [
        ("a", 5), ("b", 5), ("c", 5),
    ]
    assert con.execute("SELECT COUNT(*) FROM sim_equity WHERE date=?", [FILL]).fetchone()[0] == 3


def test_initialized_intake_waits_for_all_books_then_preserves_completed_checkpoint(con, tmp_path):
    previous = date(2026, 10, 1)
    insert_bars(con, "SAME", [previous, SIGNAL], open_=100, close=100)
    accounts.create_account(con, _spec("existing"), now=NOW)
    con.execute("UPDATE portfolios SET active=TRUE WHERE id='existing'")
    portfolio.mark_to_market(con, "existing", previous)
    accounts.create_account(con, _spec("new"), now=NOW)
    with pytest.raises(accounts.AccountRefused, match="nightly accounting"):
        accounts.submit_intent(con, _intent("new"), now=NOW)
    assert con.execute("SELECT COUNT(*) FROM sim_equity WHERE date=?", [SIGNAL]).fetchone()[0] == 0
    league.step(con, SIGNAL, tmp_path, False, False, True)
    accounts.submit_intent(con, _intent("new"), now=NOW)
    assert con.execute("SELECT portfolio_id FROM sim_equity WHERE date=? ORDER BY 1",
                       [SIGNAL]).fetchall() == [("existing",), ("new",)]
