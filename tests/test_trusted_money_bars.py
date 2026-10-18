"""Fills, carried marks and stale exposure agree on trusted OHLCV."""
from datetime import datetime, timezone

import pytest

from engine.lib.data_quality import trusted_bar, trusted_bar_sql
from server import exposure_monitor
from sim import bar_sources, fills, league, p15_books, p15_fills, portfolio, valuation
from tests.conftest import SESSIONS, insert_bars
from tests.test_p15_books import _activate

INVALID = [
    (10, 9, 8, 8.5, 100), (10, 11, 10.5, 10, 100),
    (10, 11, 9, 0, 100), (0, 11, 9, 10, 100),
    (10, 11, 9, 10, 0), (10, 11, 9, 10, -1),
    (float('nan'), 11, 9, 10, 100), (10, float('inf'), 9, 10, 100),
    (10, 11, float('-inf'), 10, 100), (10, 11, 9, None, 100),
]


@pytest.mark.parametrize('bar', INVALID + [(10, 10, 10, 10, 100), (10, 11, 9, 10, 100)])
def test_sql_and_python_trusted_rule_agree(con, bar):
    con.execute('INSERT INTO prices(ticker,date,open,high,low,close,volume) VALUES (\'AAA\',?,?,?,?,?,?)',
                [SESSIONS[1], *bar])
    actual = con.execute(f'SELECT COALESCE({trusted_bar_sql()},FALSE) FROM prices').fetchone()[0]
    assert actual == trusted_bar(bar)


@pytest.mark.parametrize('bar', INVALID)
@pytest.mark.parametrize('side', ['buy', 'sell'])
def test_legacy_and_p15_wait_without_money_and_carry_date(con, book, bar, side):
    signal, day = SESSIONS[:2]
    insert_bars(con, 'AAA', [signal], open_=10, close=10)
    insert_bars(con, 'SPY', SESSIONS[:5])
    con.execute('INSERT INTO prices(ticker,date,open,high,low,close,volume) VALUES (\'AAA\',?,?,?,?,?,?)', [day, *bar])
    con.execute('INSERT INTO sim_positions VALUES (?,\'AAA\',10,10)', [book])
    con.execute('INSERT INTO sim_orders VALUES (1,?,\'AAA\',?,1,?,\'pending\',NULL)', [book, side, signal])
    cash, positions = portfolio.get_cash(con, book), portfolio.get_positions(con, book)
    result = league.fill_pending(con, day)
    assert result == {'filled': 0, 'rejected': 0, 'pending': 1}
    assert con.execute('SELECT outcome,reject_reason FROM sim_execution_attempts').fetchone() == ('pending', 'untrusted_bar')
    if side == 'buy':
        assert p15_fills.attempt_limit_on_open(con, 'AAA', side, 1, signal, day, 11).status == 'pending'
    assert portfolio.get_cash(con, book) == cash
    assert portfolio.get_positions(con, book) == positions
    assert con.execute('SELECT COUNT(*) FROM sim_fills').fetchone() == (0,)
    assert portfolio.close_on(con, 'AAA', day) == (10, True)
    assert portfolio.close_observation(con, 'AAA', day) == (signal, 10)
    mark = portfolio.mark_to_market(con, book, day)
    assert mark['carried'] == ['AAA'] and mark['equity'] == cash + 100
    projected = exposure_monitor.status(con, day)
    assert projected['positions'][0]['last_traded'] == signal
    assert fills.attempt_fill(con, 'AAA', side, 1, signal, SESSIONS[3]).reject_reason == 'no_bar'


@pytest.mark.parametrize('side', ['buy', 'sell', 'short', 'cover'])
@pytest.mark.parametrize('source', ['prices', 'massive_daily'])
@pytest.mark.parametrize('bar', INVALID)
def test_v2_all_sides_sources_refuse_invalid_daily_bar(con, side, source, bar):
    signal, day = SESSIONS[:2]
    if source == 'prices':
        insert_bars(con, 'AAA', [signal], open_=10, close=10)
        con.execute('INSERT INTO prices(ticker,date,open,high,low,close,volume) VALUES (\'AAA\',?,?,?,?,?,?)', [day, *bar])
    else:
        con.execute('CREATE TABLE free_daily_bars(ticker VARCHAR,date DATE,o DOUBLE,h DOUBLE,l DOUBLE,c DOUBLE,volume DOUBLE,vwap DOUBLE,fetched_at TIMESTAMP,source_sha256 VARCHAR)')
        con.execute("INSERT INTO free_daily_bars VALUES ('AAA',?,10,11,9,10,100,NULL,NULL,'a')", [signal])
        con.execute("INSERT INTO free_daily_bars VALUES ('AAA',?,?,?,?,?,?,NULL,NULL,'b')", [day, *bar])
    assert bar_sources.daily_bar(con, 'AAA', day, source=source) is None
    assert bar_sources.latest_close_observation(con, 'AAA', day, source=source) == (signal, 10)
    result = fills.attempt_next_open_fill(con, 'AAA', side, 1, signal, day, price_source=source)
    assert result.status == 'pending' and result.reject_reason == 'untrusted_bar'
    observed = valuation.mark(con, 'test', 'AAA', day, price_source=source)
    assert observed.price == 10 and observed.stale
    assert observed.observed_at.date() == signal
    for kind, hour in [('moo', 12), ('moc', 15)]:
        result = fills.attempt_auction_fill(con, 'AAA', side, 1, day,
                 datetime.combine(day, datetime.min.time()).replace(hour=hour, tzinfo=timezone.utc),
                 kind, price_source=source)
        assert result.status == 'pending'


@pytest.mark.parametrize('bar', INVALID)
@pytest.mark.parametrize('side,role', [('buy', 'spy_reinvest'), ('sell', 'spy_fund'), ('sell', 'stop')])
def test_p15_spy_and_sells_cannot_bypass_trusted_bar(con, bar, side, role):
    signal, day = SESSIONS[:2]
    ticker = 'AAA' if role == 'stop' else 'SPY'
    insert_bars(con, ticker, [signal])
    _activate(con, signal)
    book = p15_books.BOOK_IDS[0]
    if side == 'sell':
        con.execute('INSERT INTO sim_positions VALUES (?,?,1,100)', [book, ticker])
    p15_books._add_intent(con, decision_id=None, portfolio_id=book, ticker=ticker,
                         side=side, qty=1, signal_date=signal, role=role, priority=1,
                         signal_close=100, entry_atr=None, limit_px=None,
                         created_at=datetime(2024, 6, 4))
    con.execute('INSERT INTO prices(ticker,date,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?)', [ticker, day, *bar])
    before = portfolio.get_cash(con, book), portfolio.get_positions(con, book)
    assert p15_books.process_pending(con, day) == {'filled': 0, 'rejected': 0, 'pending': 1}
    assert con.execute('SELECT status,reason FROM p15_order_intents').fetchone() == ('pending', 'untrusted_bar')
    assert (portfolio.get_cash(con, book), portfolio.get_positions(con, book)) == before
    assert con.execute('SELECT COUNT(*) FROM sim_fills').fetchone() == (0,)


@pytest.mark.parametrize('bar', INVALID)
@pytest.mark.parametrize('source', ['intraday_prices', 'massive_minute'])
def test_minute_invalid_geometry_cannot_fill_or_mark(con, bar, source):
    day = SESSIONS[1]
    stamp = datetime(2024, 6, 4, 14, 1)
    if source == 'intraday_prices':
        con.execute('CREATE TABLE intraday_prices(ticker VARCHAR,ts TIMESTAMP,open DOUBLE,high DOUBLE,low DOUBLE,close DOUBLE,volume DOUBLE)')
        table = 'intraday_prices'
    else:
        con.execute('CREATE TABLE massive_minute_bars(ticker VARCHAR,ts_utc TIMESTAMP,o DOUBLE,h DOUBLE,l DOUBLE,c DOUBLE,v DOUBLE)')
        table = 'massive_minute_bars'
    con.execute(f'INSERT INTO {table} VALUES (\'AAA\',?,?,?,?,?,?)', [stamp, *bar])
    assert bar_sources.minute_bars(con, 'AAA', day, source=source) == []
    for side in ('buy', 'sell', 'short', 'cover'):
        received = stamp.replace(minute=0, tzinfo=timezone.utc)
        assert fills.attempt_intraday_market_fill(con, 'AAA', side, 1, day, received, price_source=source).status == 'pending'
        assert fills.attempt_intraday_limit_fill(con, 'AAA', side, 1, day, received, 10, price_source=source).status == 'pending'


def test_p15_waiting_partial_bar_can_finish_with_first_attempt_retained(con):
    signal, day = SESSIONS[:2]
    insert_bars(con, 'AAA', [signal])
    _activate(con, signal)
    book = p15_books.BOOK_IDS[0]
    p15_books._add_intent(con, decision_id=None, portfolio_id=book, ticker='AAA',
                         side='buy', qty=1, signal_date=signal, role='entry', priority=1,
                         signal_close=100, entry_atr=2, limit_px=103, created_at=datetime(2024, 6, 4))
    con.execute('INSERT INTO prices(ticker,date,open,high,low,close,volume) VALUES (\'AAA\',?,100,NULL,NULL,NULL,1000000)', [day])
    assert p15_books.process_pending(con, day)['pending'] == 1
    first = con.execute('SELECT * FROM p15_limit_attempts').fetchall()
    con.execute("UPDATE prices SET high=101,low=99,close=100 WHERE ticker='AAA' AND date=?", [day])
    assert p15_books.process_pending(con, day)['filled'] == 1
    assert con.execute('SELECT * FROM p15_limit_attempts').fetchall() == first
    assert con.execute('SELECT COUNT(*) FROM sim_fills').fetchone() == (1,)
