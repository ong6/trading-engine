"""Round 6: complete accounting folds and risk at processing time."""
import os
import random
from datetime import date, datetime, timedelta, timezone

import pytest

from engine.accounts import cli, service
from engine.paper_accounts import AccountRefused
from sim import ledger
from sim import settle as delist
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


@pytest.mark.parametrize('entry', ['nightly', 'late', 'verify', 'results', 'api_results'])
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
    elif entry in {'verify', 'results'}:
        code = cli.main([entry, 'acct-a'])
    else:
        from fastapi import HTTPException

        from server import accounts_routes as routes

        with pytest.raises(HTTPException) as failure:
            routes.get_results('acct-a', h.auth)
        code = failure.value.status_code
        assert code == 409
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


def test_api_resume_rejects_past_effective_time(h):
    from fastapi import HTTPException

    from server import accounts_routes as routes

    h.create()
    routes.halt_account('acct-a', {}, h.auth)
    with pytest.raises(HTTPException, match='effective at receipt'):
        routes.resume_account('acct-a', {'by': 'owner', 'effective_at': '2026-10-01T22:00:00Z'}, h.auth)
    assert h.scalar('SELECT COUNT(*) FROM account_events WHERE kind=\'resumed\'') == 0


DAYS = tuple(date.fromisoformat(day) for day in
             ('2026-09-30', '2026-10-01', '2026-10-02', '2026-10-05',
              '2026-10-06', '2026-10-07', '2026-10-08'))
# CI uses a fixed subset. The acceptance run sets P22_PROPERTY_SEEDS=200.
SEEDS = tuple(range(int(os.environ.get('P22_PROPERTY_SEEDS', '8'))))


class RiskOracle:
    """Risk decisions at receipt, independent of the engine's risk implementation."""
    def __init__(self):
        self.status, self.anchor_day = 'active', None

    def check(self, h):
        with h.con() as con:
            curve = con.execute('SELECT date,equity FROM sim_equity ORDER BY date').fetchall()
            if self.status == 'active' and curve:
                anchor = next((value for day, value in curve if day == self.anchor_day), 50000)
                later = [value for day, value in curve if self.anchor_day is None or day > self.anchor_day]
                peak = max([anchor, *later])
                previous = later[-2] if len(later) > 1 else anchor
                if curve[-1][1] <= peak * .8 or curve[-1][1] <= previous * .95:
                    self.status = 'halted'
            assert con.execute('SELECT pa_status FROM portfolio_accounts_v').fetchone()[0] == self.status
            for (stamp,) in con.execute("SELECT created_at FROM account_events WHERE kind LIKE 'halt_%'").fetchall():
                assert stamp.hour == 22  # processing clock, never the historical close


def _delivery(root, monkeypatch, seed, delayed):
    from engine.accounts import late, settle
    from server import accounts_routes as routes
    from tests.conftest import insert_bars

    root.mkdir()
    h = Harness(root, monkeypatch)
    rng = random.Random(seed)
    ratio = rng.choice((.5, .25, 2., 3.))
    qty, dividend = rng.randint(520, 560), rng.uniform(.1, 2)
    split_arrival = rng.choice((2, 3)) if delayed else 1
    fill_arrival = rng.choice((0, 2, 3)) if delayed else 0
    dividend_arrival = rng.choice((3, 4)) if delayed else 2
    delist_arrival = rng.choice((3, 4)) if delayed else 3
    recovery_start = rng.choice(DAYS[2:])
    loss = random.Random(seed + 10000).choice((.99, .93, .65))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return h.now if tz else h.now.replace(tzinfo=None)

    for module in (settle, late, cli, delist):
        monkeypatch.setattr(module, 'datetime', Clock)
    with h.con(h.daily) as con:
        con.execute('DELETE FROM free_daily_bars')
        for day in (date(2026, 9, 29), *DAYS):
            for ticker in ('LONG', 'SHORT', 'RETIRE'):
                price = 100 if day <= DAYS[0] or ticker == 'SHORT' else 100 / ratio
                if day == DAYS[-1] and ticker != 'SHORT':
                    price *= loss
                con.execute('INSERT INTO free_daily_bars VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                            [day, ticker, price, price, price, price, 1_000_000, price,
                             'fixture', datetime(2026, 9, 29), f'{day}-{ticker}'])
        missing = con.execute("SELECT * FROM free_daily_bars WHERE ticker='LONG' AND date=?", [DAYS[0]]).fetchone()
        if fill_arrival:
            con.execute("DELETE FROM free_daily_bars WHERE ticker='LONG' AND date=?", [DAYS[0]])
    with h.con() as con:
        con.execute('DELETE FROM prices')
    h.now = datetime(2026, 9, 30, 13, 27, tzinfo=timezone.utc)
    h.create()
    risk = RiskOracle()
    for index, day in enumerate(DAYS):
        h.session = day
        h.now = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=13, minutes=27)
        if index == 0:
            h.order('open-long', 'LONG', 'buy', qty)
            h.order('close-long', 'LONG', 'sell', 5, 'moc', parent='open-long')
            h.order('open-filled', 'RETIRE', 'buy', 10)
            h.order('open-dead', 'SHORT', 'buy', 3)
        h.now = h.now.replace(hour=22, minute=0)
        if index == fill_arrival and fill_arrival:
            with h.con(h.daily) as con:
                con.execute('INSERT INTO free_daily_bars VALUES (?,?,?,?,?,?,?,?,?,?,?)', missing)
        with h.con() as con:
            insert_bars(con, 'SPY', [day], open_=100, close=100, volume=1_000_000)
            if index == split_arrival:
                for ticker in ('LONG', 'RETIRE'):
                    con.execute("INSERT INTO corporate_actions VALUES (?,?,'split',?,'fixture',?)",
                                [ticker, DAYS[1], ratio, h.now])
            if index == dividend_arrival:
                con.execute("INSERT INTO corporate_actions VALUES ('LONG',?,'dividend',?,'fixture',?)",
                            [DAYS[2], dividend, h.now])
            retained_fills = con.execute('SELECT * FROM sim_fills ORDER BY order_id').fetchall()
        assert h.night(day) == 0
        risk.check(h)
        with h.con() as con:
            assert all(row in con.execute('SELECT * FROM sim_fills').fetchall() for row in retained_fills)
        if index == delist_arrival:
            assert delist.main(['--db', str(h.market), '--ticker', 'SHORT', '--kind', 'cash',
                               '--price', '80', '--effective', DAYS[3].isoformat(),
                               '--source', 'fixture cash consideration', '--apply']) == 0
            risk.check(h)
        if index == 4:
            routes.halt_account('acct-a', {}, h.auth)
            risk.status = 'halted'
        if index == 5:
            routes.resume_account('acct-a', {'by': 'owner'}, h.auth)
            risk.status, risk.anchor_day = 'active', day
        risk.check(h)
    h.now += timedelta(days=1)
    assert cli.main(['settle', '--late', '--date', recovery_start.isoformat()]) == 0
    risk.check(h)
    if seed % 4 == 0:
        with h.con() as con:
            before = ledger.state(con, 'acct-a')
        with monkeypatch.context() as injected:
            def broken(*args, **kwargs):
                raise RuntimeError('generated replay failure')
            injected.setattr(ledger, 'apply_event', broken)
            assert cli.main(['settle', '--late']) != 0
        risk.status = 'halted'
        risk.check(h)
        with h.con() as con:
            assert ledger.state(con, 'acct-a') == before
    assert cli.main(['verify', 'acct-a']) == 0
    with h.con() as con:
        state = ledger.state(con, 'acct-a')
        curve = con.execute('SELECT date,equity,cash,n_positions FROM sim_equity ORDER BY date').fetchall()
        financing = con.execute("SELECT -SUM(amount) FROM sim_cash_events WHERE kind='margin_interest'").fetchone()[0]
        assert financing > 0
        ids = [ledger.event_identity(event) for event in ledger.events(con, ['acct-a'])]
        assert len(ids) == len(set(ids))
        return state, curve


@pytest.mark.parametrize('seed', SEEDS)
def test_generated_delivery_matches_on_time_accounting(tmp_path, monkeypatch, seed):
    with monkeypatch.context() as patch:
        clean = _delivery(tmp_path / 'clean', patch, seed, False)
    with monkeypatch.context() as patch:
        late = _delivery(tmp_path / 'late', patch, seed, True)
    assert ledger.states_match(clean[0], late[0])
    assert clean[1] == late[1]
