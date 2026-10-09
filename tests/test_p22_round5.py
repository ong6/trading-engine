"""Historical delivery must equal chronological processing at real entry points."""
import random
from datetime import date, datetime, timedelta, timezone

import pytest

from engine.accounts import cli, service
from server import accounts_routes as routes
from sim import league, ledger
from sim import settle as delist
from tests.test_p22_round2 import DAY, RECEIVED, Harness

NEXT = DAY + timedelta(days=1)


@pytest.fixture
def h(tmp_path, monkeypatch):
    return Harness(tmp_path, monkeypatch)


def add_day(h, day, ticker='LONG', price=100):
    with h.con(h.daily) as con:
        con.execute('INSERT INTO free_daily_bars VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    [day, ticker, price, price, price, price, 100000, price,
                     'fixture', datetime.combine(day, datetime.min.time()), 'round5'])


def test_recovery_from_loss_date_replays_later_resume(h):
    h.create(capital_usd=10000)
    h.history('LONG', 'buy', 90, 100)
    with h.con(h.daily) as con:
        con.execute("UPDATE free_daily_bars SET c=50 WHERE ticker='LONG' AND date=?", [DAY])
    assert h.night() == 0
    add_day(h, NEXT, price=95)
    assert h.night(NEXT) == 0
    with h.con() as con:
        service.resume(con, 'acct-a', resumed_by='owner',
                       now=datetime.now(timezone.utc))
    anchor = h.scalar('SELECT drawdown_anchor_equity FROM account_state')
    assert anchor == 9550
    assert cli.main(['settle', '--late', '--date', DAY.isoformat()]) == 0
    assert h.scalar("SELECT pa_status FROM portfolio_accounts_v WHERE portfolio_id='acct-a'") == 'active'
    assert h.scalar('SELECT prior_close_equity FROM account_state') == anchor


def test_delayed_split_precedes_already_filled_sell(h):
    h.create()
    h.history('LONG', 'buy', 10, 100)
    assert h.night() == 0
    add_day(h, NEXT, price=50)
    h.session, h.now = NEXT, RECEIVED + timedelta(days=1)
    h.order('close', 'LONG', 'sell', 5)
    assert h.night(NEXT) == 0
    with h.con() as con:
        con.execute("INSERT INTO corporate_actions VALUES ('LONG',?,'split',2,'fixture',?)",
                    [DAY, RECEIVED + timedelta(days=1)])
    assert league.run(str(h.market), h.root / 'reports', NEXT.isoformat(), False, False,
                      skip_if_done=True) == 0
    assert h.scalar("SELECT qty FROM sim_positions WHERE ticker='LONG'") == 15
    assert cli.main(['verify', 'acct-a']) == 0
    assert h.scalar("SELECT pa_status FROM portfolio_accounts_v WHERE portfolio_id='acct-a'") == 'active'


@pytest.mark.parametrize('mutation', [
    'UPDATE sim_equity SET equity=equity+100',
    'UPDATE sim_equity SET cash=cash+100',
    'UPDATE sim_position_lots SET qty=qty+1',
    'UPDATE portfolios SET cash=cash+100',
])
def test_nightly_retry_preserves_corruption_and_halts(h, mutation):
    h.create()
    h.order('open', 'LONG', 'buy', 10)
    assert h.night() == 0
    with h.con() as con:
        con.execute(mutation)
        before = con.execute('SELECT * FROM sim_equity').fetchall()
    assert league.run(str(h.market), h.root / 'reports', DAY.isoformat(), False, False,
                      skip_if_done=True) != 0
    with h.con() as con:
        assert con.execute('SELECT * FROM sim_equity').fetchall() == before
    assert h.scalar("SELECT pa_status FROM portfolio_accounts_v WHERE portfolio_id='acct-a'") == 'halted'
    assert h.scalar("SELECT COUNT(*) FROM account_reconciliations WHERE status='mismatch'") == 1


def test_discount_cash_delisting_on_checkpoint_date(h):
    h.create()
    h.history('SHORT', 'buy', 10, 100)
    assert h.night() == 0
    assert delist.main(['--db', str(h.market), '--ticker', 'SHORT', '--kind', 'cash',
                        '--price', '80', '--effective', DAY.isoformat(),
                        '--source', 'fixture cash consideration', '--apply']) == 0
    assert cli.main(['settle', '--late', '--date', DAY.isoformat()]) == 0
    assert h.scalar("SELECT cash FROM portfolios WHERE id='acct-a'") == 49800
    assert h.scalar('SELECT equity FROM sim_equity WHERE date=DATE \'2026-10-07\'') == 49800
    assert cli.main(['verify', 'acct-a']) == 0
    assert h.scalar("SELECT COUNT(*) FROM account_reconciliations WHERE status='mismatch'") == 0


def test_late_split_replays_prior_cash_delisting(h):
    h.create()
    h.history('SHORT', 'buy', 10, 100)
    assert h.night() == 0
    assert delist.main(['--db', str(h.market), '--ticker', 'SHORT', '--kind', 'cash',
                        '--price', '80', '--effective', NEXT.isoformat(),
                        '--source', 'fixture cash consideration', '--apply']) == 0
    with h.con() as con:
        con.execute("INSERT INTO corporate_actions VALUES ('SHORT',?,'split',2,'fixture',?)",
                    [DAY, RECEIVED])
    assert cli.main(['settle', '--late']) == 0
    assert h.scalar("SELECT cash FROM portfolios WHERE id='acct-a'") == 50600
    assert cli.main(['verify', 'acct-a']) == 0


def test_fifo_overnight_close_is_not_a_day_trade(h):
    h.create()
    h.history('LONG', 'buy', 10, 100)
    h.order('open', 'LONG', 'buy', 1)
    h.order('close', 'LONG', 'sell', 1, 'moc')
    assert h.night() == 0
    assert h.scalar('SELECT COUNT(*) FROM sim_day_trades') == 0
    assert routes.get_results('acct-a', h.auth)['day_trades_trailing_5'] == 0


def test_interest_uses_debit_before_opening_dividend(h):
    h.create()
    h.history('LONG', 'buy', 600, 100)
    with h.con() as con:
        con.execute("INSERT INTO corporate_actions VALUES ('LONG',?,'dividend',20,'fixture',?)",
                    [DAY, RECEIVED])
    assert h.night() == 0
    assert h.scalar("SELECT -SUM(amount) FROM sim_cash_events WHERE kind='margin_interest'") == pytest.approx(
        10000 * .0538 / 360)


def test_verify_cli_mismatch_is_nonzero(h):
    h.create()
    h.order('open', 'LONG', 'buy', 1)
    assert h.night() == 0
    with h.con() as con:
        con.execute('UPDATE sim_equity SET equity=equity+100')
    assert cli.main(['verify', 'acct-a']) != 0


def test_failed_replay_rolls_back_events_and_preserves_mismatch(h, monkeypatch):
    h.create()
    h.history('LONG', 'buy', 10, 100)
    assert h.night() == 0
    with h.con() as con:
        before = ledger.state(con, 'acct-a')
        equity = con.execute('SELECT * FROM sim_equity').fetchall()
        con.execute("INSERT INTO corporate_actions VALUES ('LONG',?,'split',2,'fixture',?)",
                    [DAY, RECEIVED])
    verify = service.verify

    def mismatch(*args, **kwargs):
        result = verify(*args, **kwargs)
        if not kwargs.get('manage_transaction', True):
            result['status'] = 'mismatch'
        return result

    monkeypatch.setattr(service, 'verify', mismatch)
    assert cli.main(['settle', '--late', '--date', DAY.isoformat()]) != 0
    with h.con() as con:
        assert ledger.state(con, 'acct-a') == before
        assert con.execute('SELECT * FROM sim_equity').fetchall() == equity
        assert con.execute("SELECT COUNT(*) FROM account_events WHERE kind='split'").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM account_events WHERE kind='verification_mismatch'").fetchone()[0] >= 1
    assert h.scalar("SELECT pa_status FROM portfolio_accounts_v WHERE portfolio_id='acct-a'") == 'halted'


PROPERTY_SEEDS = tuple(range(12))
PROPERTY_DAYS = tuple(date.fromisoformat(day) for day in
                      ('2026-09-30', '2026-10-01', '2026-10-02', '2026-10-05',
                       '2026-10-06', '2026-10-07', '2026-10-08'))


def _interleaving(root, monkeypatch, seed, delayed):
    root.mkdir()
    h = Harness(root, monkeypatch)
    rng = random.Random(seed)
    qty, ratio, dps, consideration = rng.randint(10, 20), rng.choice((2, 3)), rng.randint(1, 4), rng.randint(70, 100)
    arrivals = dict(split=rng.choice((1, 3)), dividend=rng.choice((2, 4)),
                    delist=rng.choice((3, 5)), halt=rng.choice((4, 6)), resume=6,
                    fill=rng.choice((0, 1)))
    if not delayed:
        arrivals = dict(split=1, dividend=2, delist=3, halt=4, resume=5, fill=0)
    with h.con(h.daily) as con:
        con.execute('DELETE FROM free_daily_bars')
        for prior_day in (23, 24, 25, 28, 29):
            for ticker in ('LONG', 'SHORT'):
                con.execute('INSERT INTO free_daily_bars VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    [date(2026, 9, prior_day), ticker, 100, 100, 100, 100, 1_000_000, 100,
                     'fixture', datetime(2026, 9, 30), 'prior'])
        for index, day in enumerate(PROPERTY_DAYS):
            for ticker in ('LONG', 'SHORT'):
                price = 100 / ratio if ticker == 'LONG' and index else 100
                con.execute('INSERT INTO free_daily_bars VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    [day, ticker, price, price, price, price, 1_000_000, price,
                     'fixture', datetime(2026, 9, 30), f'{index}-{ticker}'])
        captured = con.execute("SELECT * FROM free_daily_bars WHERE ticker='LONG' AND date=?",
                               [PROPERTY_DAYS[0]]).fetchone()
        if arrivals['fill']:
            con.execute("DELETE FROM free_daily_bars WHERE ticker='LONG' AND date=?", [PROPERTY_DAYS[0]])
    with h.con() as con:
        con.execute('DELETE FROM prices')
    h.now = datetime(2026, 9, 30, 13, 27, tzinfo=timezone.utc)
    h.create()
    for index, day in enumerate(PROPERTY_DAYS):
        h.session = day
        h.now = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=13, minutes=27)
        if index == 0:
            h.order('open-long', 'LONG', 'buy', qty)
            h.order('open-dead', 'SHORT', 'buy', 3)
        if index == 2:
            h.order('sell-long', 'LONG', 'sell', 3)
        if arrivals['fill'] == index == 1:
            with h.con(h.daily) as con:
                con.execute('INSERT INTO free_daily_bars VALUES (?,?,?,?,?,?,?,?,?,?,?)', captured)
            assert cli.main(['settle', '--late']) == 0
        for kind, effective_index, value in (('split', 1, ratio), ('dividend', 2, dps)):
            if arrivals[kind] == index:
                with h.con() as con:
                    con.execute("INSERT INTO corporate_actions VALUES ('LONG',?,?,?,'fixture',?)",
                                [PROPERTY_DAYS[effective_index], kind, value, h.now])
        with h.con() as con:
            from tests.conftest import insert_bars

            insert_bars(con, 'SPY', [day], open_=100, close=100, volume=1_000_000)
        assert league.run(str(h.market), h.root / 'reports', day.isoformat(), False, False,
                          skip_if_done=True) == 0
        if arrivals['delist'] == index:
            assert delist.main(['--db', str(h.market), '--ticker', 'SHORT', '--kind', 'cash',
                '--price', str(consideration), '--effective', PROPERTY_DAYS[3].isoformat(),
                '--source', 'fixture cash consideration', '--apply']) == 0
        # Risk requests carry their effective clocks even when delivered later.
        for kind, effective_index in (('halt', 4), ('resume', 5)):
            if arrivals[kind] == index:
                at = datetime.combine(PROPERTY_DAYS[effective_index], datetime.min.time(),
                                      tzinfo=timezone.utc) + timedelta(hours=22)
                with h.con() as con:
                    if kind == 'halt':
                        service.halt(con, 'acct-a', now=at)
                    else:
                        service.resume(con, 'acct-a', resumed_by='owner', now=at)
    assert cli.main(['settle', '--late', '--date', PROPERTY_DAYS[0].isoformat()]) == 0
    assert cli.main(['verify', 'acct-a']) == 0
    with h.con() as con:
        actual = ledger.state(con, 'acct-a')
        assert ledger.states_match(ledger.projected_state(con, 'acct-a'), actual)
        equity = con.execute('SELECT date,equity,cash,n_positions FROM sim_equity ORDER BY date').fetchall()
        risk = con.execute('SELECT prior_close_equity,halted_at,halt_reason,resumed_at,drawdown_anchor_equity '
                           'FROM account_state').fetchone()
        day_trades = con.execute('SELECT * FROM sim_day_trades ORDER BY close_order_id').fetchall()
    return actual, equity, risk, day_trades


@pytest.mark.parametrize('seed', PROPERTY_SEEDS)
def test_randomized_effective_time_delivery_matches_chronological(tmp_path, monkeypatch, seed):
    with monkeypatch.context() as patch:
        clean = _interleaving(tmp_path / 'clean', patch, seed, False)
    with monkeypatch.context() as patch:
        delivered = _interleaving(tmp_path / 'delivered', patch, seed, True)
    assert ledger.states_match(clean[0], delivered[0])
    assert clean[1:] == delivered[1:]
