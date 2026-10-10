"""Round 6: complete accounting folds and risk at processing time."""
from datetime import datetime, timedelta, timezone

import pytest

from engine.accounts import cli, service
from engine.paper_accounts import AccountRefused
from sim import ledger
from tests.test_p22_round2 import DAY, RECEIVED, Harness
from tests.test_p22_round5 import add_day


@pytest.fixture
def h(tmp_path, monkeypatch):
    return Harness(tmp_path, monkeypatch)


def test_pending_pre_split_order_fills_in_original_session_units(h):
    h.create()
    receipt = h.order('open', 'LONG', 'buy', 10)
    with h.con(h.daily) as con:
        bar = con.execute("SELECT * FROM free_daily_bars WHERE ticker='LONG' AND date=?", [DAY]).fetchone()
        con.execute("DELETE FROM free_daily_bars WHERE ticker='LONG' AND date=?", [DAY])
    assert h.night() == 0
    tomorrow = DAY + timedelta(days=1)
    add_day(h, tomorrow, price=50)
    with h.con() as con:
        con.execute("INSERT INTO corporate_actions VALUES ('LONG',?,'split',2,'fixture',?)", [tomorrow, RECEIVED])
    assert h.night(tomorrow) == 0
    assert h.scalar(f"SELECT qty FROM sim_orders WHERE id={receipt['order_id']}") == 10
    with h.con(h.daily) as con:
        con.execute('INSERT INTO free_daily_bars VALUES (?,?,?,?,?,?,?,?,?,?,?)', bar)
    assert cli.main(['settle', '--late', '--date', tomorrow.isoformat()]) == 0
    assert h.scalar('SELECT qty FROM sim_fills') == 10
    assert h.scalar("SELECT qty FROM sim_positions WHERE ticker='LONG'") == 20
    assert cli.main(['verify', 'acct-a']) == 0


def test_cash_identity_includes_account_and_effective_date(h):
    h.create()
    with h.con() as con:
        for day in (DAY, DAY + timedelta(days=1)):
            ledger.apply_cash_event(con, dict(portfolio_id='acct-a', event_date=day,
                                             kind='adjustment', amount=1))
        events = [event for event in ledger.events(con, ['acct-a']) if event.kind == 'cash']
        assert len({ledger.event_identity(event) for event in events}) == 2


def test_backdated_resume_cannot_skip_later_loss_checks(h):
    h.create(capital_usd=10000)
    h.history('LONG', 'buy', 90, 100)
    with h.con(h.daily) as con:
        con.execute("UPDATE free_daily_bars SET c=50 WHERE ticker='LONG' AND date=?", [DAY])
    assert h.night() == 0
    with h.con() as con:
        with pytest.raises(AccountRefused, match='past'):
            service.resume(con, 'acct-a', resumed_by='owner', now=RECEIVED.replace(hour=22))
    assert h.scalar("SELECT pa_status FROM portfolio_accounts_v WHERE portfolio_id='acct-a'") == 'halted'


@pytest.mark.parametrize('entry', ['nightly', 'late', 'verify'])
def test_any_fold_exception_rolls_back_then_halts(h, monkeypatch, entry):
    h.create()
    h.order('open', 'LONG', 'buy', 10)
    assert h.night() == 0
    with h.con() as con:
        before = ledger.state(con, 'acct-a')
        equity = con.execute('SELECT * FROM sim_equity').fetchall()

    def broken(*args, **kwargs):
        raise RuntimeError('injected fold failure')

    monkeypatch.setattr(ledger, 'apply_event', broken)
    if entry == 'nightly':
        code = h.night(DAY + timedelta(days=1))
    elif entry == 'late':
        code = cli.main(['settle', '--late', '--date', DAY.isoformat()])
    else:
        code = cli.main(['verify', 'acct-a'])
    assert code != 0
    with h.con() as con:
        assert ledger.state(con, 'acct-a') == before
        assert con.execute('SELECT * FROM sim_equity').fetchall() == equity
    assert h.scalar("SELECT pa_status FROM portfolio_accounts_v WHERE portfolio_id='acct-a'") == 'halted'
    assert h.scalar("SELECT COUNT(*) FROM account_reconciliations WHERE status='mismatch'") == 1
    assert h.scalar("SELECT halted_at FROM account_state") > datetime.combine(DAY, datetime.min.time())


def test_list_cli_accepts_list_payload(h):
    h.create()
    assert cli.main(['list']) == 0
