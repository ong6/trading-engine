"""Round-3 accounting regressions through API, nightly and recovery CLI."""
from datetime import date, datetime, timezone

import pytest

from engine.accounts import cli, service
from server import accounts_routes as routes
from sim import settle as delist
from tests.test_p22_round2 import DAY, PRIOR, RECEIVED, Harness
from tools import migrate_cost_profiles


@pytest.fixture
def h(tmp_path, monkeypatch):
    return Harness(tmp_path, monkeypatch)


def test_late_recovery_keeps_cash_delisting(h):
    h.create()
    h.history('SHORT', 'buy', 100, 100)
    assert h.night() == 0  # Missing close creates an unresolved stale mark.
    assert delist.main(['--db', str(h.market), '--ticker', 'SHORT', '--kind', 'cash',
                        '--price', '100', '--effective', DAY.isoformat(),
                        '--source', 'fixture cash consideration', '--apply']) == 0
    before = h.scalar("SELECT cash FROM portfolios WHERE id='acct-a'")
    assert cli.main(['settle', '--late']) == 0
    assert h.scalar("SELECT cash FROM portfolios WHERE id='acct-a'") == before
    assert routes.get_positions('acct-a', h.auth) == []
    assert h.scalar("SELECT COUNT(*) FROM account_reconciliations WHERE status='mismatch'") == 0


def test_late_recovery_verification_failure_rolls_back_and_exits_nonzero(h, monkeypatch):
    h.create()
    h.order('open', 'LONG', 'buy', 100)
    assert h.night() == 0
    before = h.scalar("SELECT cash FROM portfolios WHERE id='acct-a'")
    original = service.verify

    def fail_reconstruction(*args, **kwargs):
        if not kwargs.get('manage_transaction', True):
            return {'status': 'mismatch'}
        return original(*args, **kwargs)

    monkeypatch.setattr(service, 'verify', fail_reconstruction)
    assert cli.main(['settle', '--late', '--date', DAY.isoformat()]) != 0
    assert h.scalar("SELECT cash FROM portfolios WHERE id='acct-a'") == before
    assert h.scalar("SELECT COUNT(*) FROM account_events WHERE kind='settlement_error'") > 0


@pytest.mark.parametrize('future_close', [100, 600])
def test_borrow_at_open_cannot_use_future_close(h, future_close):
    h.create()
    h.history('SHORT', 'short', 100, 100)
    with h.con(h.daily) as con:
        con.execute('UPDATE free_daily_bars SET volume=1000000')
    order = h.order('open', 'LONG', 'buy', 649.735)
    with h.con(h.daily) as con:
        con.execute("INSERT INTO free_daily_bars VALUES "
                    "(?,'SHORT',100,600,100,?,100000,100,'fixture',?,'later')",
                    [DAY, future_close, datetime(2026, 10, 7, 21)])
    assert h.night() == 0
    assert h.scalar(f"SELECT status FROM sim_orders WHERE id={order['order_id']}") == 'filled'
    assert h.scalar("SELECT -SUM(amount) FROM sim_cash_events WHERE kind='borrow_fee'") == pytest.approx(
        100 * 100 * .0025 / 360)


def test_flat_sessions_advance_interest_checkpoint(h):
    h.now = datetime(2026, 10, 5, 13, 27, tzinfo=timezone.utc)
    h.session = date(2026, 10, 5)
    h.create()
    with h.con(h.daily) as con:
        con.execute("UPDATE free_daily_bars SET o=100,h=100,l=100,c=100")
        for day in (8, 9):
            con.execute("INSERT INTO free_daily_bars SELECT ?,ticker,o,h,l,c,volume,vwap,source,"
                        "TIMESTAMP '2026-10-05 12:00:00','later' FROM free_daily_bars "
                        "WHERE date=?", [date(2026, 10, day), PRIOR])
    for day, side in ((5, 'buy'), (6, 'sell'), (7, None), (8, 'buy'), (9, None)):
        h.now = datetime(2026, 10, day, 13, 27, tzinfo=timezone.utc)
        h.session = date(2026, 10, day)
        if side:
            h.order(f'{side}-{day}', 'LONG', side, 731)
        assert h.night(h.session) == 0
    debit = h.scalar("SELECT -cash FROM sim_equity WHERE portfolio_id='acct-a' "
                     "AND date=DATE '2026-10-08'")
    assert h.scalar("SELECT -SUM(amount) FROM sim_cash_events WHERE kind='margin_interest' "
                    "AND event_date=DATE '2026-10-09'") == pytest.approx(debit * .0538 / 360)


def _split(h, ticker):
    with h.con() as con:
        con.execute("INSERT INTO corporate_actions VALUES (?,?,'split',2,'fixture',?)",
                    [ticker, DAY, RECEIVED])


def test_results_split_round_trip_uses_adjusted_lots(h):
    h.create()
    h.history('LONG', 'buy', 100, 100)
    h.now = datetime(2026, 10, 6, 21, tzinfo=timezone.utc)
    h.order('close', 'LONG', 'sell', 100, 'moc')
    _split(h, 'LONG')
    with h.con(h.daily) as con:
        con.execute("UPDATE free_daily_bars SET o=50,h=50,l=50,c=50 WHERE ticker='LONG' AND date=?", [DAY])
    assert h.night() == 0
    payload = routes.get_results('acct-a', h.auth)
    cash = h.scalar("SELECT cash FROM portfolios WHERE id='acct-a'")
    assert payload['trade_stats']['n'] == 1
    assert payload['trade_stats']['mean_net_bp'] == pytest.approx((cash - 50_000) / 10_000 * 10_000)


def test_identical_api_retry_after_split_keeps_original_receipt(h):
    h.create()
    h.history('SHORT', 'buy', 100, 100)
    h.now = datetime(2026, 10, 6, 21, tzinfo=timezone.utc)
    receipt = h.order('close', 'SHORT', 'sell', 100, 'moc')
    _split(h, 'SHORT')
    assert h.night() == 0
    assert h.scalar('SELECT qty FROM sim_orders') == 200
    assert h.order('close', 'SHORT', 'sell', 100, 'moc') == receipt


def test_stale_holding_does_not_block_unrelated_affordable_open(h):
    h.create()
    h.history('SHORT', 'buy', 100, 100)
    with h.con(h.daily) as con:
        con.execute("DELETE FROM free_daily_bars WHERE ticker='SHORT' AND date>DATE '2026-09-30'")
    assert h.order('open', 'LONG', 'buy', 100)['state'] == 'queued'
    position = routes.get_positions('acct-a', h.auth)[0]
    assert position['stale'] is True
    assert position['mark'] == 100


def test_migration_cli_preserves_existing_routes_and_uses_deployed_revision(h):
    with h.con() as con:
        con.execute("INSERT INTO portfolios (id,name,strategy,config,created,active,cash,initial_cash) "
                    "VALUES ('p15_ai_ranked','Example','none','{}',?,TRUE,10000,10000)", [PRIOR])
    assert migrate_cost_profiles.main(['--db', str(h.market), '--d0', '2026-10-19', '--apply']) == 0
    assert h.scalar("SELECT pa_engine FROM portfolio_accounts_v WHERE portfolio_id='p15_ai_ranked'") == 'league'
    assert h.scalar('SELECT registration_revision FROM sim_book_breaks') == 14


def test_migration_revision_is_read_from_registration(h):
    h.create()
    assert migrate_cost_profiles.main(['--db', str(h.market), '--d0', '2026-10-19', '--apply']) == 0
    assert h.scalar('SELECT registration_revision FROM sim_book_breaks') == 14


def test_p15_pending_order_keeps_legacy_fill_with_commission(h):
    from sim import league
    from tests.conftest import insert_bars

    with h.con() as con:
        con.execute("INSERT INTO portfolios (id,name,strategy,config,created,active,cash,initial_cash) "
                    "VALUES ('p15_ai_ranked','Example','none','{}',?,TRUE,10000,10000)", [PRIOR])
        insert_bars(con, 'XYZ', [PRIOR, DAY], open_=100, close=100, volume=1_000_000)
        con.execute("INSERT INTO sim_orders VALUES (1,'p15_ai_ranked','XYZ','buy',1,?,'pending',NULL)",
                    [PRIOR])
        assert migrate_cost_profiles.migrate(con, DAY)['routing_changes'] == []
        assert league.fill_pending(con, DAY)['filled'] == 1
        assert con.execute('SELECT total_usd FROM sim_fill_fees').fetchone()[0] > 0
        cash, notional, fee = con.execute(
            'SELECT p.cash,f.qty*f.fill_px,ff.total_usd FROM portfolios p '
            'JOIN sim_fills f ON f.portfolio_id=p.id JOIN sim_fill_fees ff USING(order_id)',
        ).fetchone()
        assert cash == pytest.approx(10_000 - notional - fee)
