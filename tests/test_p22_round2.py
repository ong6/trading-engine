"""Round-2 regressions exercise production routes, nightly and the late CLI."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import duckdb
import pytest

from engine.accounts import api, cli
from engine.lib import db
from server import accounts_routes as routes
from server import db as server_db
from sim import league
from sim.schema import set_portfolio_account
from tests.test_account_entrypoints_e2e import (
    DAY,
    PRIOR,
    RECEIVED,
    _daily_store,
    _intent,
    _main_store,
    _minute_store,
    _short_store,
    _spec,
)
from tests.test_accounts_settle import _historical_fill


class Harness:
    def __init__(self, tmp_path, monkeypatch):
        self.root = tmp_path
        self.market = tmp_path / 'market.duckdb'
        self.daily = tmp_path / 'daily.duckdb'
        self.minute = tmp_path / 'minute.duckdb'
        self.short = tmp_path / 'short.duckdb'
        for path, make in ((self.market, _main_store), (self.daily, _daily_store),
                           (self.minute, _minute_store), (self.short, _short_store)):
            make(path)
        for key, path in (('TRADING_ENGINE_DB', self.market),
                          ('TRADING_ENGINE_FREE_SOURCES_DB', self.daily),
                          ('TRADING_ENGINE_MASSIVE_MINUTE_DB', self.minute),
                          ('TRADING_ENGINE_SHORT_DATA_DB', self.short)):
            monkeypatch.setenv(key, str(path))
        monkeypatch.setattr(db.settings, 'DEFAULT_DB', self.market)
        monkeypatch.setattr(server_db, 'DEFAULT_DB', self.market)
        token = tmp_path / 'token'
        api.generate_token(path=token)
        monkeypatch.setenv(api.TOKEN_ENV, str(token))
        self.auth = f'Bearer {api.read_token(path=token)}'
        self.now = RECEIVED
        harness = self

        class Clock:
            @classmethod
            def now(cls, _tz):
                return harness.now

        monkeypatch.setattr(routes, 'datetime', Clock)

    @contextmanager
    def con(self, path=None):
        connection = duckdb.connect(str(path or self.market))
        try:
            yield connection
        finally:
            connection.close()

    def create(self, name='acct-a', **kwargs):
        spec = {**_spec(name), 'max_position_fraction': 1.5,
                'max_gross_fraction': 1.5, **kwargs}
        return routes.create_account(spec, self.auth)

    def order(self, name, ticker, side, qty, kind='moo', account='acct-a', parent=None):
        intent = {**_intent(name, ticker, side, kind, contingent_on=parent),
                  'quantity': qty, 'account_id': account,
                  'created_at': self.now.isoformat()}
        return routes.submit_order(account, intent, self.auth)

    def history(self, ticker, side, qty, price, account='acct-a'):
        with self.con() as con:
            order_id = con.execute('SELECT COALESCE(MAX(order_id),0)+100 FROM sim_fills').fetchone()[0]
            _historical_fill(con, account, ticker, side, qty, price, PRIOR, order_id)
            con.execute('UPDATE portfolios SET active=TRUE WHERE id=?', [account])
            set_portfolio_account(con, account, status='active')

    def night(self, day=DAY, rerun=False):
        return league.run(str(self.market), self.root / 'reports', day.isoformat(), False, rerun)

    def scalar(self, sql):
        with self.con() as con:
            return con.execute(sql).fetchone()[0]


@pytest.fixture
def h(tmp_path, monkeypatch):
    return Harness(tmp_path, monkeypatch)


def test_independent_accounts_can_each_use_authorized_gross(h):
    for account, ticker in [('acct-a', 'LONG'), ('acct-b', 'RETIRE')]:
        h.create(account)
        h.order(account, ticker, 'buy', 600, account=account)
    assert h.night() == 0
    assert h.scalar('SELECT COUNT(*) FROM sim_fills') == 2


@pytest.mark.parametrize('future_close', [100, 600])
def test_moo_capacity_does_not_read_an_existing_holding_future_close(h, future_close):
    h.create()
    h.history('LONG', 'buy', 100, 100)
    h.order('buy', 'RETIRE', 'buy', 300)
    with h.con(h.daily) as con:
        con.execute("UPDATE free_daily_bars SET c=? WHERE ticker='LONG' AND date=?",
                    [future_close, DAY])
    assert h.night() == 0
    assert h.scalar("SELECT COUNT(*) FROM sim_fills WHERE ticker='RETIRE'") == 1


def test_api_marks_massive_short_from_selected_source(h):
    h.create()
    h.history('SHORT', 'short', 100, 10)
    with h.con(h.daily) as con:
        con.execute("UPDATE free_daily_bars SET c=10 WHERE ticker='SHORT'")
    assert h.night() == 0
    position = routes.get_positions('acct-a', h.auth)[0]
    account = routes.get_account('acct-a', h.auth)
    assert position['mark'] == 10
    assert position['market_value'] == -1000
    assert account['positions_market_value'] == -1000
    assert account['gross_market_value'] == 1000


def test_nightly_maintenance_carries_fill_when_all_source_marks_are_missing(h):
    h.create()
    # A 1-dollar short owes at least 5 dollars/share maintenance.
    h.history('SHORT', 'short', 11_000, 1)
    with h.con(h.daily) as con:
        con.execute("DELETE FROM free_daily_bars WHERE ticker='SHORT'")
    assert h.night() == 0
    assert h.scalar("SELECT COUNT(*) FROM account_events WHERE kind='margin_call'") == 1
    position = routes.get_positions('acct-a', h.auth)[0]
    assert position['mark'] == 1
    assert position['stale'] is True
    assert routes.get_account('acct-a', h.auth)['margin_excess'] < 0


def test_contingent_child_never_exceeds_requested_quantity(h):
    h.create()
    h.order('open', 'LONG', 'buy', 100)
    h.order('close', 'LONG', 'sell', 50, 'moc', parent='open')
    assert h.night() == 0
    assert h.scalar("SELECT qty FROM sim_fills WHERE side='sell'") == 50
    assert h.scalar("SELECT qty FROM sim_positions WHERE ticker='LONG'") == 50


def test_reconciliation_tolerates_sub_half_cent_but_rejects_cent(h):
    h.create()
    h.order('open', 'LONG', 'buy', 1)
    assert h.night() == 0
    with h.con() as con:
        con.execute("UPDATE portfolios SET cash=cash+0.004 WHERE id='acct-a'")
    assert cli.main(['verify', 'acct-a']) == 0
    assert h.scalar("SELECT pa_status FROM portfolio_accounts_v WHERE portfolio_id='acct-a'") == 'active'
    with h.con() as con:
        con.execute("UPDATE portfolios SET cash=cash+0.006 WHERE id='acct-a'")
    cli.main(['verify', 'acct-a'])
    assert h.scalar("SELECT pa_status FROM portfolio_accounts_v WHERE portfolio_id='acct-a'") == 'halted'


def test_retiring_short_keeps_financing_until_moc(h):
    h.create()
    h.history('SHORT', 'short', 100, 100)
    h.now = datetime(2026, 10, 6, 21, tzinfo=timezone.utc)
    assert routes.retire_account('acct-a', h.auth)['status'] == 'retiring'
    with h.con(h.daily) as con:
        con.execute("INSERT INTO free_daily_bars SELECT ?,ticker,o,h,l,c,volume,vwap,source,"
                    "TIMESTAMP '2026-10-07 21:00:00','current' FROM free_daily_bars "
                    "WHERE ticker='SHORT' AND date=?", [DAY, PRIOR])
    assert h.night() == 0
    assert h.scalar("SELECT COUNT(*) FROM sim_cash_events WHERE kind='borrow_fee'") == 1
    assert h.scalar("SELECT pa_status FROM portfolio_accounts_v WHERE portfolio_id='acct-a'") == 'retired'
